from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
                str(ROOT / "backend" / "src"), str(ROOT / "scripts")]

from evaluate_stage10 import can_select_default, evaluate_provider  # noqa: E402
from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.image_store import LocalImageStore  # noqa: E402
from kroika_backend.vision_providers import (  # noqa: E402
    GeminiProvider, HTTPResult, QwenProvider,
)
from kroika_contracts.ports import AIProviderError, ProviderErrorCode  # noqa: E402


def example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def dataset_png() -> bytes:
    return (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()


def provider_request(image_ref: str) -> dict:
    request = example("example-ai-request.json")
    request["image_refs"] = [image_ref]
    return request


def configured_provider(cls, tmp_path: Path, transport, *, attempts: int = 2):
    store = LocalImageStore(tmp_path / "images")
    asset = store.save_base64(base64.b64encode(dataset_png()).decode(), "image/png")
    provider = cls(
        image_store=store,
        api_key="server-only-secret",
        base_url="https://example.invalid/v1",
        model="vision-test",
        timeout_seconds=3,
        max_attempts=attempts,
        transport=transport,
        retry_pause=lambda _: asyncio.sleep(0),
    )
    return provider, provider_request(asset.image_ref)


def configured_openrouter_qwen(tmp_path: Path, transport):
    store = LocalImageStore(tmp_path / "images")
    asset = store.save_base64(base64.b64encode(dataset_png()).decode(), "image/png")
    provider = QwenProvider(
        image_store=store,
        api_key="server-only-secret",
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen3.8-27b:free",
        timeout_seconds=3,
        max_attempts=2,
        transport=transport,
        retry_pause=lambda _: asyncio.sleep(0),
    )
    return provider, provider_request(asset.image_ref)


def test_qwen_payload_uses_official_multimodal_shape_and_leaks_no_project_data(tmp_path: Path):
    captured = []

    async def transport(url, headers, payload, timeout):
        captured.append((url, headers, payload, timeout))
        return HTTPResult(200, {
            "choices": [{"message": {"content": json.dumps(example("example-ai-response.json"))}}]
        })

    provider, request = configured_provider(QwenProvider, tmp_path, transport)
    result = asyncio.run(provider.analyze_style(request))
    assert result["garment_category"] == "dress"
    url, headers, payload, timeout = captured[0]
    assert url == "https://example.invalid/v1/chat/completions"
    assert headers["Authorization"] == "Bearer server-only-secret"
    assert timeout == 3
    assert payload["messages"][1]["content"][1]["type"] == "image_url"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    serialized = json.dumps(payload, ensure_ascii=False)
    assert request["project_id"] not in serialized
    assert request["request_id"] not in serialized
    assert "body_measurements" not in serialized
    assert "data:image/png;base64," in serialized


def test_openrouter_qwen_requires_structured_output_and_disables_reasoning(tmp_path: Path):
    captured = []

    async def transport(url, headers, payload, timeout):
        captured.append(payload)
        return HTTPResult(200, {
            "choices": [{"message": {"content": json.dumps(example("example-ai-response.json"))}}]
        })

    provider, request = configured_openrouter_qwen(tmp_path, transport)
    result = asyncio.run(provider.analyze_style(request))

    assert result["status"] == "needs_confirmation"
    assert captured[0]["provider"] == {"require_parameters": True}
    assert captured[0]["reasoning"] == {"enabled": False}


def test_gemini_payload_uses_inline_image_and_structured_output(tmp_path: Path):
    captured = []

    async def transport(url, headers, payload, timeout):
        captured.append((url, headers, payload, timeout))
        return HTTPResult(200, {"steps": [{
            "type": "model_output",
            "content": [{"type": "text", "text": json.dumps(example("example-ai-response.json"))}],
        }]})

    provider, request = configured_provider(GeminiProvider, tmp_path, transport)
    asyncio.run(provider.analyze_style(request))
    url, headers, payload, _ = captured[0]
    assert url == "https://example.invalid/v1/interactions"
    assert headers["x-goog-api-key"] == "server-only-secret"
    assert payload["input"][1]["type"] == "image"
    assert payload["input"][1]["mime_type"] == "image/png"
    assert payload["response_format"]["mime_type"] == "application/json"
    assert payload["response_format"]["schema"]["additionalProperties"] is False
    assert payload["store"] is False
    assert "мерки" in payload["system_instruction"]
    assert request["project_id"] not in json.dumps(payload)


def test_retry_is_bounded_and_invalid_model_output_is_rejected(tmp_path: Path):
    calls = 0

    async def overloaded(url, headers, payload, timeout):
        nonlocal calls
        calls += 1
        return HTTPResult(429, {})

    provider, request = configured_provider(QwenProvider, tmp_path, overloaded, attempts=2)
    with pytest.raises(AIProviderError) as failure:
        asyncio.run(provider.analyze_style(request))
    assert failure.value.code is ProviderErrorCode.RATE_LIMIT
    assert calls == 2

    async def invalid(url, headers, payload, timeout):
        return HTTPResult(200, {"choices": [{"message": {"content": '{"status":"ok"}'}}]})

    provider, request = configured_provider(QwenProvider, tmp_path / "invalid", invalid)
    with pytest.raises(AIProviderError) as failure:
        asyncio.run(provider.analyze_style(request))
    assert failure.value.code is ProviderErrorCode.INVALID_SCHEMA


def test_qwen_reports_insufficient_openrouter_credit_without_retry(tmp_path: Path):
    calls = 0

    async def payment_required(url, headers, payload, timeout):
        nonlocal calls
        calls += 1
        return HTTPResult(402, {"error": {"message": "Insufficient credits"}})

    provider, request = configured_openrouter_qwen(tmp_path, payment_required)
    with pytest.raises(AIProviderError) as failure:
        asyncio.run(provider.analyze_style(request))

    assert failure.value.code is ProviderErrorCode.PAYMENT_REQUIRED
    assert failure.value.retryable is False
    assert calls == 1


def test_api_preserves_payment_required_status(tmp_path: Path):
    class PaymentRequiredProvider:
        provider_id = "qwen"

        async def analyze_style(self, request):
            raise AIProviderError(
                ProviderErrorCode.PAYMENT_REQUIRED,
                "На ключе сервиса анализа недостаточно средств.",
                False,
            )

    settings = Settings(
        database_path=tmp_path / "payment.db",
        image_storage_path=tmp_path / "images",
        ai_provider="qwen",
        log_level="CRITICAL",
    )
    with TestClient(
        create_app(settings, ai_provider=PaymentRequiredProvider()),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/garments/analyze-image?provider=qwen",
            json=example("example-ai-request.json"),
        )

    assert response.status_code == 402
    assert response.json()["code"] == "PAYMENT_REQUIRED"


def test_image_store_rejects_false_types_oversize_and_unknown_refs(tmp_path: Path):
    store = LocalImageStore(tmp_path, max_image_bytes=64)
    with pytest.raises(AIProviderError) as failure:
        store.save_base64(base64.b64encode(b"not a png").decode(), "image/png")
    assert failure.value.code is ProviderErrorCode.INVALID_IMAGE
    with pytest.raises(AIProviderError):
        store.save_base64(base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 100).decode(), "image/png")
    with pytest.raises(AIProviderError):
        store.resolve("../../secret")


def test_image_store_applies_orientation_and_removes_private_metadata(tmp_path: Path):
    raw = BytesIO()
    exif = Image.Exif()
    exif[0x010E] = "private-client-location"
    exif[0x0112] = 6
    Image.new("RGB", (3, 2), "red").save(raw, format="JPEG", exif=exif)

    asset = LocalImageStore(tmp_path).save_base64(
        base64.b64encode(raw.getvalue()).decode(), "image/jpeg"
    )
    assert b"private-client-location" not in asset.data
    with Image.open(BytesIO(asset.data)) as stored:
        assert stored.size == (2, 3)
        assert not stored.getexif()


def test_api_lists_choices_uploads_safely_and_keeps_mock_fallback(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        ai_provider="qwen",
        log_level="CRITICAL",
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        providers = client.get("/api/v1/ai/providers")
        assert providers.status_code == 200
        indexed = {item["provider_id"]: item for item in providers.json()["items"]}
        assert indexed["mock"]["configured"] is True
        assert indexed["qwen"]["configured"] is False

        upload = client.post("/api/v1/images", json={
            "file_name": "dress.png",
            "media_type": "image/png",
            "data_base64": base64.b64encode(dataset_png()).decode(),
        })
        assert upload.status_code == 201, upload.text
        assert upload.json()["image_ref"].startswith("img_")

        request = provider_request(upload.json()["image_ref"])
        unavailable = client.post("/api/v1/garments/analyze-image?provider=qwen", json=request)
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "PROVIDER_UNAVAILABLE"
        fallback = client.post("/api/v1/garments/analyze-image?provider=mock", json=request)
        assert fallback.status_code == 200
        assert fallback.json()["status"] == "needs_confirmation"


def test_annotated_seed_has_50_owned_images_and_evaluator_stays_fail_closed(tmp_path: Path):
    manifest = json.loads(
        (ROOT / "evaluation/stage10/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["case_count"] == len(manifest["cases"]) == 50
    assert all(case["license"] == "CC0-1.0" for case in manifest["cases"])
    assert all((ROOT / "evaluation/stage10" / case["image"]).is_file()
               for case in manifest["cases"])
    results = tmp_path / "qwen"
    results.mkdir()
    (results / "synthetic-01.json").write_text(json.dumps({
        "analysis": example("example-ai-response.json"),
        "latency_ms": 125,
        "cost_usd": 0.01,
    }), encoding="utf-8")
    score = evaluate_provider(manifest, results)
    assert score["completed_cases"] == 1
    assert score["schema_valid_rate"] == score["semantic_valid_rate"] == 1
    assert can_select_default(manifest, {"qwen": score, "gemini": deepcopy(score)}) is False


def test_stage10_configuration_rejects_unsafe_or_unknown_values(tmp_path: Path):
    with pytest.raises(ValueError, match="mock, qwen или gemini"):
        Settings(database_path=tmp_path / "db", ai_provider="other").validate()
    with pytest.raises(ValueError, match="https"):
        Settings(database_path=tmp_path / "db", qwen_base_url="http://example.test").validate()


def test_stage10_runtime_contract_and_current_only_ci_are_wired(tmp_path: Path):
    launcher = (ROOT / "scripts/start_local.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    current_stage = max(
        int(path.stem.removeprefix("verify_stage"))
        for path in (ROOT / "scripts").glob("verify_stage*.py")
    )
    assert '"requirements-stage10.txt"' in launcher
    assert "requirements-stage10.txt" in dockerfile
    assert f"python scripts/verify_stage{current_stage}.py" in workflow
    assert "verify_all.py" not in workflow

    spec, base_uri = read_from_filename(str(ROOT / "schemas/openapi.v1.yaml"))
    validate(spec, base_uri=base_uri)
    documented = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    app = create_app(Settings(
        database_path=tmp_path / "contract.db",
        image_storage_path=tmp_path / "images-contract",
        log_level="CRITICAL",
    ))
    runtime = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert runtime == documented

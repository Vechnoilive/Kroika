from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.image_store import LocalImageStore  # noqa: E402
from kroika_backend.vision_providers import (  # noqa: E402
    GeminiProvider,
    HTTPResult,
    QwenProvider,
)
from tests.wiring import assert_current_only_workflow  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _png() -> bytes:
    return (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()


def _provider(provider_class, tmp_path: Path, transport):
    return provider_class(
        image_store=LocalImageStore(tmp_path / "images"),
        api_key="server-only-secret",
        base_url="https://example.invalid/v1",
        model="vision-test",
        timeout_seconds=3,
        max_attempts=1,
        transport=transport,
        retry_pause=lambda _: asyncio.sleep(0),
    )


def test_user_image_views_reach_ai_without_local_identifiers(tmp_path: Path) -> None:
    captured: list[dict] = []

    async def transport(url, headers, payload, timeout):
        captured.append(payload)
        return HTTPResult(200, {
            "choices": [{"message": {
                "content": json.dumps(_example("example-ai-response.json")),
            }}],
        })

    provider = _provider(QwenProvider, tmp_path, transport)
    encoded = base64.b64encode(_png()).decode("ascii")
    first = provider.image_store.save_base64(encoded, "image/png")
    second = provider.image_store.save_base64(encoded, "image/png")
    request = _example("example-ai-request.json")
    request["image_refs"] = [first.image_ref, second.image_ref]
    request["image_views"] = ["front", "detail"]

    asyncio.run(provider.analyze_style(request))

    instruction = captured[0]["messages"][1]["content"][0]["text"]
    assert '"image_number":1,"view":"front"' in instruction
    assert '"image_number":2,"view":"detail"' in instruction
    assert request["project_id"] not in instruction
    assert first.image_ref not in instruction
    assert second.image_ref not in instruction


def test_provider_checks_are_text_only_for_qwen_and_gemini(tmp_path: Path) -> None:
    qwen_payloads: list[dict] = []
    gemini_payloads: list[dict] = []

    async def qwen_transport(url, headers, payload, timeout):
        qwen_payloads.append(payload)
        return HTTPResult(200, {"choices": [{"message": {"content": "OK"}}]})

    async def gemini_transport(url, headers, payload, timeout):
        gemini_payloads.append(payload)
        return HTTPResult(200, {"steps": [{
            "type": "model_output", "content": [{"type": "text", "text": "OK"}],
        }]})

    asyncio.run(_provider(QwenProvider, tmp_path / "qwen", qwen_transport).check_connection())
    asyncio.run(_provider(GeminiProvider, tmp_path / "gemini", gemini_transport).check_connection())

    qwen_serialized = json.dumps(qwen_payloads[0])
    gemini_serialized = json.dumps(gemini_payloads[0])
    assert "image_url" not in qwen_serialized
    assert "response_format" not in qwen_payloads[0]
    assert qwen_payloads[0]["max_tokens"] == 8
    assert '"type": "image"' not in gemini_serialized
    assert gemini_payloads[0]["store"] is False
    assert gemini_payloads[0]["generation_config"]["max_output_tokens"] == 8


def test_provider_check_endpoint_and_view_count_validation(tmp_path: Path) -> None:
    class CheckableProvider:
        provider_id = "qwen"
        model = "qwen-test"
        checked = 0

        async def check_connection(self) -> None:
            self.checked += 1

        async def analyze_style(self, request):
            return _example("example-ai-response.json")

    provider = CheckableProvider()
    settings = Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        ai_provider="qwen",
        enabled_ai_providers=("mock", "qwen"),
        log_level="CRITICAL",
    )
    with TestClient(create_app(settings, ai_provider=provider), raise_server_exceptions=False) as api:
        checked = api.post("/api/v1/ai/providers/qwen/check")
        assert checked.status_code == 200, checked.text
        assert checked.json() == {
            "provider_id": "qwen",
            "model": "qwen-test",
            "status": "ready",
            "latency_ms": checked.json()["latency_ms"],
            "message_ru": "Соединение и ключ работают. Изображения не отправлялись.",
        }
        assert provider.checked == 1

        request = _example("example-ai-request.json")
        request["image_views"] = ["front", "back"]
        rejected = api.post("/api/v1/garments/analyze-image?provider=qwen", json=request)
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "IMAGE_VIEW_COUNT_MISMATCH"
        assert rejected.json()["issues"][0]["json_pointer"] == "/image_views"


def test_stage23_contract_and_current_only_gate_are_wired(tmp_path: Path) -> None:
    requirements = (ROOT / "requirements-stage23.txt").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    verify_all = (ROOT / "scripts" / "verify_all.py").read_text(encoding="utf-8")
    assert "-r requirements-stage22.txt" in requirements
    assert 'ROOT / "requirements-stage23.txt"' in launcher
    assert '"requirements-stage23.txt"' in launcher
    assert_current_only_workflow(ROOT, workflow)
    assert "verify_stage23.py" in verify_all

    spec, base_uri = read_from_filename(str(ROOT / "schemas/openapi.v1.yaml"))
    validate(spec, base_uri=base_uri)
    assert "/api/v1/ai/providers/{provider_id}/check" in spec["paths"]

    documented = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    app = create_app(Settings(
        database_path=tmp_path / "contract.db",
        image_storage_path=tmp_path / "contract-images",
        log_level="CRITICAL",
    ))
    runtime = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert runtime == documented

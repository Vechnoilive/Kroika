from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
import sys

import httpx2 as httpx
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine/src"), str(ROOT / "backend/src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.image_store import LocalImageStore  # noqa: E402
from kroika_backend.logging_config import JsonFormatter, request_id_context  # noqa: E402
from kroika_backend.vision_providers import (  # noqa: E402
    GeminiProvider, HTTPResult, _retry_after, httpx_json_transport,
)
from kroika_contracts.ports import AIProviderError, ProviderErrorCode  # noqa: E402


def example(name: str) -> dict:
    return json.loads((ROOT / "examples/v1" / name).read_text())


def provider(tmp_path: Path, transport):
    store = LocalImageStore(tmp_path / "images")
    asset = store.save_base64(base64.b64encode(
        (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
    ).decode(), "image/png")
    request = example("example-ai-request.json")
    request["image_refs"] = [asset.image_ref]
    return GeminiProvider(
        api_mode="interactions",
        image_store=store, api_key="secret-key", base_url="https://example.invalid/v1beta",
        model="gemini-3.5-flash", timeout_seconds=600, max_attempts=3,
        transport=transport, retry_pause=lambda _: asyncio.sleep(0),
    ), request


def completed_response() -> dict:
    return {"status": "completed", "steps": [{
        "type": "model_output", "content": [{
            "type": "text", "text": json.dumps(example("example-ai-response.json")),
        }],
    }]}


@pytest.mark.parametrize("seconds", [0, 1, 300, 600, 1800])
def test_response_timeout_supports_long_or_unlimited_wait(monkeypatch, seconds):
    monkeypatch.setenv("KROIKA_AI_TIMEOUT_SECONDS", str(seconds))
    settings = Settings.from_env()
    settings.validate()
    assert settings.ai_timeout_seconds == seconds


@pytest.mark.parametrize("seconds", [-1, 0.5, 1801, float("nan"), float("inf")])
def test_invalid_timeout_does_not_reach_transport(tmp_path, seconds):
    with pytest.raises(ValueError, match="KROIKA_AI_TIMEOUT_SECONDS"):
        Settings(database_path=tmp_path / "db", ai_timeout_seconds=seconds).validate()


@pytest.mark.parametrize("timeout", [0, 3, 600])
def test_http_transport_separates_connection_and_response_timeouts(monkeypatch, timeout):
    captured = []

    def handler(request):
        captured.append(request.extensions["timeout"])
        return httpx.Response(503, json={"error": {"code": "service_unavailable"}},
                              headers={"Retry-After": "15"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    result = asyncio.run(httpx_json_transport("https://example.invalid", {}, {}, timeout))
    assert captured == [{
        "connect": min(timeout, 30) if timeout else 30,
        "read": timeout or None,
        "write": min(timeout, 60) if timeout else 60,
        "pool": 30,
    }]
    assert result.status_code == 503
    assert result.retry_after_seconds == 15


@pytest.mark.parametrize("exception, code", [
    (httpx.ReadTimeout, ProviderErrorCode.TIMEOUT),
    (httpx.ConnectError, ProviderErrorCode.PROVIDER_UNAVAILABLE),
])
def test_network_failure_preserves_safe_type_without_echoing_exception(monkeypatch, exception, code):
    def handler(request):
        raise exception("secret-key and private image", request=request)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    with pytest.raises(AIProviderError) as failure:
        asyncio.run(httpx_json_transport("https://example.invalid", {}, {}, 600))
    assert failure.value.code is code
    assert failure.value.retryable
    assert isinstance(failure.value.__cause__, exception)
    assert "secret-key" not in failure.value.message_ru


def test_gemini_recovers_after_overload_and_honors_server_retry_delay(tmp_path):
    captured = []
    pauses = []

    async def transport(url, headers, payload, timeout):
        captured.append((payload, timeout))
        if len(captured) == 1:
            return HTTPResult(503, {"error": {"code": "service_unavailable"}}, 15)
        if len(captured) == 2:
            return HTTPResult(429, {"error": {
                "status": "RESOURCE_EXHAUSTED", "details": [{
                    "@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "20s",
                }],
            }})
        return HTTPResult(200, completed_response())

    async def pause(delay):
        pauses.append(delay)

    adapter, request = provider(tmp_path, transport)
    adapter.retry_pause = pause
    result = asyncio.run(adapter.analyze_style(request))
    assert result["garment_category"] == "dress"
    assert len(captured) == 3
    assert pauses == [15, 20]
    assert all(timeout == 600 for _, timeout in captured)
    assert captured[0][0]["generation_config"] == {"thinking_level": "low", "max_output_tokens": 16384}
    assert captured[0][0]["store"] is False


def test_gemini_overload_backoff_is_bounded_and_longer_than_one_second(tmp_path):
    calls, pauses = [], []

    async def transport(*args):
        calls.append(args)
        return HTTPResult(503, {"error": {"code": "service_unavailable"}})

    async def pause(delay):
        pauses.append(delay)

    adapter, request = provider(tmp_path, transport)
    adapter.retry_pause = pause
    with pytest.raises(AIProviderError, match="HTTP 503"):
        asyncio.run(adapter.analyze_style(request))
    assert len(calls) == 3
    assert 5 <= pauses[0] <= 5.25
    assert 10 <= pauses[1] <= 10.25


@pytest.mark.parametrize("status, body, code, message", [
    (404, {"code": "model_not_found"}, ProviderErrorCode.PROVIDER_UNAVAILABLE, "имя модели"),
    (400, {"code": "failed_precondition"}, ProviderErrorCode.PROVIDER_UNAVAILABLE, "оплаты"),
    (400, {"details": [{"reason": "API_KEY_INVALID"}]}, ProviderErrorCode.AUTH, "Ключ"),
    (429, {"code": "quota_exceeded"}, ProviderErrorCode.RATE_LIMIT, "квоту"),
    (402, {"code": "payment_required"}, ProviderErrorCode.PAYMENT_REQUIRED, "средств"),
    (200, {"code": "safety"}, ProviderErrorCode.INVALID_IMAGE, "фильтрами"),
])
def test_permanent_errors_are_explained_without_repeating_request(tmp_path, status, body, code, message):
    calls = []

    async def transport(*args):
        calls.append(args)
        return HTTPResult(status, {"status": "failed", "error": {
            **body, "message": "secret-key private image base64",
        }})

    adapter, request = provider(tmp_path, transport)
    with pytest.raises(AIProviderError) as failure:
        asyncio.run(adapter.analyze_style(request))
    assert failure.value.code is code
    assert not failure.value.retryable
    assert message in failure.value.message_ru
    assert "secret-key" not in failure.value.message_ru
    assert len(calls) == 1


@pytest.mark.parametrize("status", ["incomplete", "cancelled", "requires_action", "queued", "failed"])
def test_unfinished_interaction_cannot_pass_analysis_or_connection_check(tmp_path, status):
    async def transport(*args):
        return HTTPResult(200, {**completed_response(), "status": status})

    adapter, request = provider(tmp_path, transport)
    for operation in (adapter.analyze_style(request), adapter.check_connection()):
        with pytest.raises(AIProviderError) as failure:
            asyncio.run(operation)
        assert failure.value.code is ProviderErrorCode.INVALID_SCHEMA


@pytest.mark.parametrize("value, expected", [
    ("12", 12), ("12.5s", 12.5), ("99999", 60), ("nan", None),
    ("inf", None), ("-3", None), ("garbage", None), (None, None),
])
def test_untrusted_retry_delay_is_bounded(value, expected):
    assert _retry_after(value) == expected


def test_ai_logs_identify_upstream_failure_and_match_ui_request_id(tmp_path, caplog):
    async def transport(*args):
        return HTTPResult(503, {"error": {
            "code": "service_unavailable", "message": "secret-key private prompt",
        }})

    adapter, _ = provider(tmp_path, transport)
    settings = Settings(database_path=tmp_path / "db", image_storage_path=tmp_path / "images",
                        ai_provider="gemini", enabled_ai_providers=("mock", "gemini"))
    app = create_app(settings, ai_provider=adapter)
    app.state.logger.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/ai/providers/gemini/check")
        assert response.status_code == 503
        logs = [json.loads(JsonFormatter().format(record)) for record in caplog.records
                if record.getMessage() == "ai_provider_attempt_failed"]
        assert len(logs) == 3
        assert {log["request_id"] for log in logs} == {response.json()["request_id"]}
        assert all(log["upstream_status"] == 503 for log in logs)
        assert all(log["upstream_code"] == "SERVICE_UNAVAILABLE" for log in logs)
        assert "secret-key" not in json.dumps(logs)
        assert "private prompt" not in json.dumps(logs)
        assert request_id_context.get() is None
    finally:
        app.state.logger.removeHandler(caplog.handler)


def test_formatter_drops_raw_provider_fields():
    record = logging.LogRecord("kroika.backend", logging.WARNING, __file__, 1,
                               "ai_provider_attempt_failed", (), None)
    record.upstream_status = 503
    record.api_key = "secret-key"
    record.upstream_message = "private prompt"
    record.body = "private image"
    formatted = JsonFormatter().format(record)
    assert json.loads(formatted)["upstream_status"] == 503
    assert "secret-key" not in formatted
    assert "private" not in formatted

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "backend/src"),
                str(ROOT / "pattern-engine/src"), str(ROOT / "scripts")]

import check_gemini  # noqa: E402
from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.image_store import LocalImageStore  # noqa: E402
from kroika_backend.vision_providers import GeminiProvider, HTTPResult  # noqa: E402
from kroika_contracts.ports import AIProviderError, ProviderErrorCode  # noqa: E402


def example(name):
    return json.loads((ROOT / "examples/v1" / name).read_text())


def content_response():
    text = json.dumps(example("example-ai-response.json"))
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"thought": True, "text": "private thought must not become the analysis"},
        {"text": text[:50]}, {"text": text[50:]},
    ]}}]}


def adapter(tmp_path, model="gemini-3.8-flash", mode="generate_content", transport=None,
            thinking_level="auto"):
    kwargs = {"transport": transport} if transport else {}
    return GeminiProvider(
        image_store=LocalImageStore(tmp_path / "images"),
        api_key="server-secret", base_url="https://example.invalid/v1beta",
        model=model, api_mode=mode, thinking_level=thinking_level,
        timeout_seconds=600, max_attempts=1, **kwargs,
    )


@pytest.mark.parametrize("mode", ["generate_content", "interactions"])
@pytest.mark.parametrize("model, expected", [
    ("gemini-3.8-flash", "low"), ("gemini-3.7-flash", "low"),
    ("gemini-3.6-flash", "minimal"), ("gemini-3.5-flash", "minimal"),
    ("gemini-3.5-flash-lite", "minimal"), ("gemini-3.1-pro-preview", "low"),
])
def test_probe_uses_only_supported_thinking_level(tmp_path, mode, model, expected):
    payload = adapter(tmp_path, model, mode)._probe_payload()
    if mode == "interactions":
        assert payload["generation_config"] == {"thinking_level": expected}
        assert payload["store"] is False
        assert "image" not in json.dumps(payload)
    else:
        assert payload["generationConfig"] == {"thinkingConfig": {"thinkingLevel": expected}}
        assert "inlineData" not in json.dumps(payload)


def test_legacy_flash_uses_budget_in_generate_content(tmp_path):
    provider = adapter(tmp_path, "gemini-2.5-flash")
    assert provider._probe_payload()["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert provider._payload([], "instruction")["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 1024}


@pytest.mark.parametrize("mode", ["generate_content", "interactions"])
@pytest.mark.parametrize("model, level, expected", [
    ("gemini-3.6-flash", "auto", "minimal"),
    ("models/gemini-3.5-flash", "auto", "minimal"),
    ("gemini-3.6-flash", "minimal", "minimal"),
    ("gemini-3.6-flash", "low", "low"),
    ("gemini-3.8-flash", "auto", "low"),
    ("gemini-3.8-flash", "low", "low"),
    ("vision-test", "auto", "low"),
])
def test_analysis_uses_selected_supported_thinking_level(tmp_path, mode, model, level, expected):
    provider = adapter(tmp_path, model, mode, thinking_level=level)
    payload = provider._payload([], "instruction")
    if mode == "interactions":
        config = payload["generation_config"]
        assert config["thinking_level"] == expected
        assert config["max_output_tokens"] == 16384
    else:
        config = payload["generationConfig"]
        assert config["thinkingConfig"] == {"thinkingLevel": expected}
        assert config["maxOutputTokens"] == 16384
    if model.removeprefix("models/") in {"gemini-3.5-flash", "gemini-3.6-flash"}:
        assert provider._thinking_level(probe=True) == "minimal"


@pytest.mark.parametrize("model, level", [
    ("gemini-3.6-flash", "off"), ("gemini-3.8-flash", "minimal"),
    ("gemini-3.1-pro-preview", "minimal"), ("gemini-2.5-flash", "minimal"),
])
def test_invalid_thinking_configuration_fails_before_request(tmp_path, model, level):
    with pytest.raises(ValueError, match="GEMINI_THINKING_LEVEL"):
        Settings(database_path=tmp_path / "db", gemini_model=model,
                 gemini_thinking_level=level).validate()
    with pytest.raises(ValueError, match="GEMINI_THINKING_LEVEL"):
        adapter(tmp_path, model, thinking_level=level)


def test_generate_content_analyzes_front_and_back_with_strict_local_validation(tmp_path):
    captured = []

    async def transport(url, headers, payload, timeout):
        captured.append((url, headers, payload, timeout))
        return HTTPResult(200, content_response())

    provider = adapter(tmp_path, model="gemini-3.6-flash", transport=transport)
    image = base64.b64encode((ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()).decode()
    first = provider.image_store.save_base64(image, "image/png")
    back_image = base64.b64encode((ROOT / "evaluation/stage10/images/synthetic-02.png").read_bytes()).decode()
    second = provider.image_store.save_base64(back_image, "image/png")
    request = example("example-ai-request.json")
    request.update(image_refs=[first.image_ref, second.image_ref], image_views=["front", "back"])
    settings = Settings(database_path=tmp_path / "db", image_storage_path=tmp_path / "images",
                        ai_provider="gemini", enabled_ai_providers=("mock", "gemini"), log_level="CRITICAL")
    with TestClient(create_app(settings, ai_provider=provider)) as client:
        response = client.post("/api/v1/garments/analyze-image?provider=gemini", json=request)
    assert response.status_code == 200, response.text
    assert response.json() == example("example-ai-response.json")
    url, headers, payload, timeout = captured[0]
    assert url == "https://example.invalid/v1beta/models/gemini-3.6-flash:generateContent"
    assert headers["x-goog-api-key"] == "server-secret"
    assert timeout == 600
    parts = payload["contents"][0]["parts"]
    assert len(parts) == 3
    for part, reference in zip(parts[1:], request["image_refs"], strict=True):
        stored_data = provider.image_store.resolve(reference).data
        assert part["inlineData"] == {
            "data": base64.b64encode(stored_data).decode(), "mimeType": "image/png",
        }
    assert '"image_number":2,"view":"back"' in parts[0]["text"]
    assert payload["generationConfig"] == {
        "responseMimeType": "application/json", "maxOutputTokens": 16384,
        "thinkingConfig": {"thinkingLevel": "minimal"},
    }
    serialized = json.dumps(payload)
    for private_value in (request["project_id"], request["request_id"], first.image_ref, second.image_ref):
        assert private_value not in serialized
    assert "store" not in payload
    assert "temperature" not in payload["generationConfig"]


@pytest.mark.parametrize("finish, code", [
    ("MAX_TOKENS", ProviderErrorCode.INVALID_SCHEMA),
    ("OTHER", ProviderErrorCode.INVALID_SCHEMA), (None, ProviderErrorCode.INVALID_SCHEMA),
    ("SAFETY", ProviderErrorCode.INVALID_IMAGE), ("RECITATION", ProviderErrorCode.INVALID_IMAGE),
])
def test_unfinished_or_blocked_candidate_cannot_pass_with_valid_json(tmp_path, finish, code):
    result = content_response()
    result["candidates"][0]["finishReason"] = finish
    with pytest.raises(AIProviderError) as failure:
        adapter(tmp_path)._extract_text(result)
    assert failure.value.code is code


def test_blocked_prompt_is_reported_before_missing_candidates(tmp_path):
    with pytest.raises(AIProviderError) as failure:
        adapter(tmp_path)._extract_text({"promptFeedback": {"blockReason": "SAFETY"}})
    assert failure.value.code is ProviderErrorCode.INVALID_IMAGE


def test_generate_content_connection_and_invalid_analysis_are_distinct(tmp_path):
    async def transport(url, headers, payload, timeout):
        return HTTPResult(200, {"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": "OK"}],
        }}]})

    provider = adapter(tmp_path, transport=transport)
    asyncio.run(provider.check_connection())
    image = provider.image_store.save_base64(base64.b64encode(
        (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
    ).decode(), "image/png")
    request = example("example-ai-request.json")
    request["image_refs"] = [image.image_ref]
    with pytest.raises(AIProviderError) as failure:
        asyncio.run(provider.analyze_style(request))
    assert failure.value.code is ProviderErrorCode.INVALID_SCHEMA


@pytest.mark.parametrize("mode, tokens", [("bad", 16384), ("generate_content", 8), ("interactions", 65537)])
def test_invalid_api_settings_fail_before_request(tmp_path, mode, tokens):
    with pytest.raises(ValueError):
        Settings(database_path=tmp_path / "db", gemini_api_mode=mode,
                 gemini_max_output_tokens=tokens).validate()


def test_selected_api_mode_and_output_budget_reach_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_MODE", " interactions ")
    monkeypatch.setenv("GEMINI_MODEL", " models/gemini-3.5-flash ")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", " MINIMAL ")
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "32768")
    settings = Settings.from_env()
    settings.validate()
    assert settings.gemini_api_mode == "interactions"
    assert settings.gemini_max_output_tokens == 32768
    selected = create_app(settings).state.provider_registry.providers["gemini"]
    assert selected.thinking_level == "minimal"
    assert selected._payload([], "instruction")["generation_config"]["thinking_level"] == "minimal"
    default = Settings(database_path=tmp_path / "db", image_storage_path=tmp_path / "images")
    selected = create_app(default).state.provider_registry.providers["gemini"]
    assert selected.api_mode == "generate_content"
    assert selected.max_output_tokens == 16384
    assert selected.model == "gemini-3.6-flash"
    assert selected.thinking_level == "auto"
    assert selected._content_config(probe=False)["thinkingConfig"] == {"thinkingLevel": "minimal"}


def test_blank_thinking_level_uses_auto(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "  ")
    assert Settings.from_env().gemini_thinking_level == "auto"


def test_diagnostic_compares_models_without_keys_in_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "server-secret")
    captures = []

    class Probe:
        def __init__(self, **kwargs):
            captures.append(kwargs)
            self.mode = kwargs["api_mode"]

        async def check_connection(self):
            if self.mode == "interactions":
                raise AIProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE, "HTTP 503", True)

    monkeypatch.setattr(check_gemini, "GeminiProvider", Probe)
    assert asyncio.run(check_gemini.check_models(["gemini-3.8-flash"],
                                                ["generate_content", "interactions"])) == 0
    output = capsys.readouterr().out
    assert "generate_content" in output and "interactions" in output and "HTTP 503" in output
    assert "server-secret" not in output
    assert all(item["max_attempts"] == 1 for item in captures)

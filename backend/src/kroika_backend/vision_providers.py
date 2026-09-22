"""Qwen, Gemini and mock adapters behind one privacy-preserving contract."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib.parse import urlparse

import httpx2 as httpx

from kroika_contracts.contract_io import ContractValidationError, validate_document
from kroika_contracts.ports import AIProvider, AIProviderError, ProviderErrorCode
from kroika_contracts.semantic import SemanticContractError, validate_ai_analysis

from .config import Settings
from .image_store import ImageAsset, LocalImageStore
from .mock_provider import MockVisionProvider
from .vision_prompt import COMMON_SYSTEM_PROMPT, analysis_instruction, provider_analysis_schema


MAX_RESPONSE_CHARACTERS = 256_000
MAX_EXTERNAL_IMAGE_BYTES = 14 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class HTTPResult:
    status_code: int
    payload: dict[str, Any]


class JSONTransport(Protocol):
    async def __call__(
        self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> HTTPResult: ...


async def httpx_json_transport(
    url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
) -> HTTPResult:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise AIProviderError(
            ProviderErrorCode.TIMEOUT,
            "Сервис анализа не успел ответить. Попробуйте ещё раз или выберите демо-режим.",
            True,
        ) from exc
    except httpx.HTTPError as exc:
        raise AIProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            "Сервис анализа временно недоступен. Фото сохранено локально.",
            True,
        ) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return HTTPResult(response.status_code, body if isinstance(body, dict) else {})


def _provider_error(status_code: int) -> AIProviderError:
    if status_code in {401, 403}:
        return AIProviderError(
            ProviderErrorCode.AUTH,
            "Ключ сервиса анализа не принят. Проверьте настройки на сервере.",
            False,
        )
    if status_code == 402:
        return AIProviderError(
            ProviderErrorCode.PAYMENT_REQUIRED,
            "На ключе сервиса анализа недостаточно средств. Пополните баланс или выберите бесплатную модель.",
            False,
        )
    if status_code == 429:
        return AIProviderError(
            ProviderErrorCode.RATE_LIMIT,
            "Сервис анализа перегружен. Попробуйте чуть позже или выберите демо-режим.",
            True,
        )
    return AIProviderError(
        ProviderErrorCode.PROVIDER_UNAVAILABLE,
        "Сервис анализа временно недоступен. Фото сохранено локально.",
        status_code >= 500,
    )


def _strict_json(text: str) -> dict[str, Any]:
    if not text or len(text) > MAX_RESPONSE_CHARACTERS:
        raise ValueError("empty or oversized response")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite constant: {value}")

    parsed = json.loads(text, parse_constant=reject_constant)
    if not isinstance(parsed, dict):
        raise ValueError("response is not an object")
    return parsed


class ExternalVisionProvider:
    provider_id: str

    def __init__(
        self,
        *,
        image_store: LocalImageStore,
        api_key: str | None,
        base_url: str | None,
        model: str,
        timeout_seconds: float,
        max_attempts: int,
        transport: JSONTransport = httpx_json_transport,
        retry_pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.image_store = image_store
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else None
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.transport = transport
        self.retry_pause = retry_pause

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    async def analyze_style(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise AIProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                f"{self.provider_id.capitalize()} ещё не настроен. Выберите демо-режим.",
                False,
            )
        images = [self.image_store.resolve(reference) for reference in request["image_refs"]]
        if sum(len(image.data) for image in images) > MAX_EXTERNAL_IMAGE_BYTES:
            raise AIProviderError(
                ProviderErrorCode.INVALID_IMAGE,
                "Общий размер изображений слишком велик. Уменьшите файлы или отправьте меньше видов.",
                False,
            )
        instruction = analysis_instruction(
            list(request["supported_garment_categories"]),
            {key: list(values) for key, values in request["supported_features"].items()},
        )
        response = await self._send_with_retry(images, instruction)
        try:
            document = _strict_json(self._extract_text(response))
            validate_document("ai-style-analysis", document)
            validate_ai_analysis(document)
        except (KeyError, IndexError, TypeError, ValueError, ContractValidationError,
                SemanticContractError) as exc:
            raise AIProviderError(
                ProviderErrorCode.INVALID_SCHEMA,
                "Сервис вернул неполный разбор. Результат не принят — попробуйте ещё раз.",
                False,
            ) from exc
        return document

    async def _send_with_retry(self, images: list[ImageAsset], instruction: str) -> dict[str, Any]:
        last_error: AIProviderError | None = None
        for attempt in range(self.max_attempts):
            try:
                result = await self.transport(
                    self._url(), self._headers(), self._payload(images, instruction),
                    self.timeout_seconds,
                )
                if result.status_code < 400:
                    return result.payload
                error = _provider_error(result.status_code)
            except AIProviderError as exc:
                error = exc
            last_error = error
            if not error.retryable or attempt + 1 >= self.max_attempts:
                raise error
            await self.retry_pause(0.1 * (2 ** attempt))
        assert last_error is not None
        raise last_error

    def _url(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _payload(self, images: list[ImageAsset], instruction: str) -> dict[str, Any]:
        raise NotImplementedError

    def _extract_text(self, response: dict[str, Any]) -> str:
        raise NotImplementedError


class QwenProvider(ExternalVisionProvider):
    provider_id = "qwen"

    def _url(self) -> str:
        assert self.base_url is not None
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, images: list[ImageAsset], instruction: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
        content.extend({
            "type": "image_url",
            "image_url": {
                "url": f"data:{image.media_type};base64,{base64.b64encode(image.data).decode('ascii')}"
            },
        } for image in images)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": COMMON_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "kroika_style_analysis",
                    "strict": True,
                    "schema": provider_analysis_schema(),
                },
            },
            "temperature": 0.1,
            "stream": False,
        }
        hostname = urlparse(self.base_url).hostname if self.base_url else None
        if hostname == "openrouter.ai" or (hostname and hostname.endswith(".openrouter.ai")):
            # Structured output and free Qwen endpoints can otherwise be routed to
            # a backend that ignores response_format or emits reasoning around JSON.
            payload["provider"] = {"require_parameters": True}
            payload["reasoning"] = {"enabled": False}
        return payload

    def _extract_text(self, response: dict[str, Any]) -> str:
        return response["choices"][0]["message"]["content"]


class GeminiProvider(ExternalVisionProvider):
    provider_id = "gemini"

    def _url(self) -> str:
        assert self.base_url is not None
        return f"{self.base_url}/interactions"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": str(self.api_key), "Content-Type": "application/json"}

    def _payload(self, images: list[ImageAsset], instruction: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
        content.extend({
            "type": "image",
            "data": base64.b64encode(image.data).decode("ascii"),
            "mime_type": image.media_type,
        } for image in images)
        return {
            "model": self.model,
            "system_instruction": COMMON_SYSTEM_PROMPT,
            "input": content,
            "store": False,
            "generation_config": {"temperature": 0.1},
            "response_format": {
                "type": "text", "mime_type": "application/json",
                "schema": provider_analysis_schema(),
            },
        }

    def _extract_text(self, response: dict[str, Any]) -> str:
        for step in reversed(response["steps"]):
            if step.get("type") != "model_output":
                continue
            texts = [part["text"] for part in step["content"] if part.get("type") == "text"]
            if texts:
                return "".join(texts)
        raise TypeError("missing model output text")


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    default_provider: str
    providers: Mapping[str, AIProvider]
    enabled_for_users: tuple[str, ...] = ("mock", "qwen")

    def get(self, provider_id: str | None = None) -> AIProvider:
        selected = provider_id or self.default_provider
        if provider_id is not None and selected not in self.enabled_for_users:
            raise AIProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                "Выбранный сервис анализа отключён в настройках приложения.",
                False,
            )
        provider = self.providers.get(selected)
        if provider is None:
            raise AIProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                "Выбранный сервис анализа недоступен. Выберите другой.",
                False,
            )
        return provider

    def statuses(self) -> list[dict[str, Any]]:
        names = {"mock": "Демо-режим", "qwen": "Qwen", "gemini": "Gemini"}
        result = []
        for provider_id in ("mock", "qwen", "gemini"):
            provider = self.providers[provider_id]
            if isinstance(provider, ExternalVisionProvider):
                external = True
                configured = provider.configured
            else:
                external = False
                configured = True
            result.append({
                "provider_id": provider_id,
                "name": names[provider_id],
                "model": getattr(provider, "model", "offline fixture"),
                "configured": configured,
                "is_default": provider_id == self.default_provider,
                "enabled_for_users": provider_id in self.enabled_for_users,
                "sends_images_external": external,
                "message_ru": (
                    "Работает без интернета и не отправляет фото."
                    if provider_id == "mock" else
                    "Готов к анализу; фото уйдёт только после подтверждения."
                    if configured else
                    "Нужны серверный API-ключ и адрес региона."
                ),
            })
        return result


def build_provider_registry(settings: Settings, image_store: LocalImageStore) -> ProviderRegistry:
    return ProviderRegistry(settings.ai_provider, {
        "mock": MockVisionProvider(),
        "qwen": QwenProvider(
            image_store=image_store,
            timeout_seconds=settings.ai_timeout_seconds,
            max_attempts=settings.ai_max_attempts,
            api_key=settings.qwen_api_key, base_url=settings.qwen_base_url,
            model=settings.qwen_model,
        ),
        "gemini": GeminiProvider(
            image_store=image_store,
            timeout_seconds=settings.ai_timeout_seconds,
            max_attempts=settings.ai_max_attempts,
            api_key=settings.gemini_api_key, base_url=settings.gemini_base_url,
            model=settings.gemini_model,
        ),
    }, settings.enabled_ai_providers)

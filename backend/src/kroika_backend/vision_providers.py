"""Qwen, Gemini and mock adapters behind one privacy-preserving contract."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import math
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import perf_counter
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib.parse import urlparse

import httpx2 as httpx

from kroika_contracts.contract_io import ContractValidationError, validate_document
from kroika_contracts.ports import AIProvider, AIProviderError, ProviderErrorCode
from kroika_contracts.semantic import SemanticContractError, validate_ai_analysis

from .config import Settings
from .image_store import ImageAsset, LocalImageStore
from .logging_config import request_id_context
from .mock_provider import MockVisionProvider
from .vision_prompt import COMMON_SYSTEM_PROMPT, analysis_instruction, provider_analysis_schema


MAX_RESPONSE_CHARACTERS = 256_000
MAX_EXTERNAL_IMAGE_BYTES = 14 * 1024 * 1024
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_JITTER_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 60.0
logger = logging.getLogger("kroika.backend")
UPSTREAM_ERROR_STATUSES = {
    "INVALID_ARGUMENT": 400, "FAILED_PRECONDITION": 400,
    "UNAUTHENTICATED": 401, "PERMISSION_DENIED": 403, "NOT_FOUND": 404,
    "RESOURCE_EXHAUSTED": 429, "INTERNAL": 500, "UNAVAILABLE": 503,
    "DEADLINE_EXCEEDED": 504, "API_KEY_INVALID": 401,
    "API_KEY_SERVICE_BLOCKED": 403, "API_KEY_EXPIRED": 401,
    "INVALID_REQUEST": 400, "PARAMETER_UNKNOWN": 400, "AUTHENTICATION": 401,
    "PAYMENT_REQUIRED": 402, "MODEL_NOT_FOUND": 404,
    "RATE_LIMIT_EXCEEDED": 429, "QUOTA_EXCEEDED": 429, "TOO_MANY_REQUESTS": 429,
    "API_ERROR": 500, "SERVICE_UNAVAILABLE": 503,
    "SAFETY": 422, "RECITATION": 422, "LANGUAGE": 422,
    "PROHIBITED_CONTENT": 422, "SPII": 422, "BLOCKLIST": 422,
    "CONTENT_BLOCKED": 422,
}


@dataclass(frozen=True, slots=True)
class HTTPResult:
    status_code: int
    payload: dict[str, Any]
    retry_after_seconds: float | None = None


def _retry_after(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        delay = float(value.removesuffix("s"))
    except ValueError:
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if not math.isfinite(delay) or delay < 0:
        return None
    return min(delay, MAX_RETRY_DELAY_SECONDS)


def _upstream_code(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            reason = detail.get("reason") if isinstance(detail, dict) else None
            if isinstance(reason, str) and reason in UPSTREAM_ERROR_STATUSES:
                return reason
    for field in ("status", "code"):
        value = error.get(field)
        if isinstance(value, str):
            code = value.rsplit("/", 1)[-1].upper()
            if code in UPSTREAM_ERROR_STATUSES:
                return code
    return None


def _payload_retry_delay(payload: dict[str, Any]) -> float | None:
    error = payload.get("error")
    details = error.get("details") if isinstance(error, dict) else None
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict) and detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                return _retry_after(detail.get("retryDelay"))
    return None


class JSONTransport(Protocol):
    async def __call__(
        self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> HTTPResult: ...


async def httpx_json_transport(
    url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
) -> HTTPResult:
    try:
        limits = httpx.Timeout(
            connect=min(timeout, 30.0) if timeout else 30.0,
            read=timeout or None,
            write=min(timeout, 60.0) if timeout else 60.0,
            pool=30.0,
        )
        async with httpx.AsyncClient(timeout=limits) as client:
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
            "Не удалось соединиться с API анализа. Проверьте сеть, DNS и доступность адреса API. "
            "Фото сохранено локально.",
            True,
        ) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return HTTPResult(
        response.status_code, body if isinstance(body, dict) else {},
        _retry_after(response.headers.get("Retry-After")),
    )


def _provider_error(status_code: int, payload: dict[str, Any] | None = None) -> AIProviderError:
    code = _upstream_code(payload or {})
    if code in {"API_KEY_INVALID", "API_KEY_EXPIRED"}:
        status_code = 401
    if status_code in {408, 504}:
        return AIProviderError(
            ProviderErrorCode.TIMEOUT,
            "Сервис анализа не успел ответить. Попробуйте ещё раз или выберите демо-режим.",
            True,
        )
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
            "API анализа ограничил запросы (HTTP 429). Проверьте квоту и лимиты ключа; "
            "повторите позже.",
            code != "QUOTA_EXCEEDED",
        )
    if status_code == 404:
        return AIProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            "API не нашёл модель или endpoint (HTTP 404). Проверьте имя модели и адрес API.",
            False,
        )
    if status_code == 400 and code == "FAILED_PRECONDITION":
        return AIProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            "API отклонил запрос из-за условий доступа (HTTP 400 FAILED_PRECONDITION). "
            "Проверьте доступность сервиса в регионе и настройки оплаты проекта.",
            False,
        )
    if code in {"SAFETY", "RECITATION", "LANGUAGE", "PROHIBITED_CONTENT", "SPII", "BLOCKLIST", "CONTENT_BLOCKED"}:
        return AIProviderError(
            ProviderErrorCode.INVALID_IMAGE,
            "Сервис заблокировал разбор изображения своими фильтрами. "
            "Попробуйте другой снимок изделия или эскиз.",
            False,
        )
    if 300 <= status_code < 500:
        return AIProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            f"Сервис отклонил запрос (HTTP {status_code}). "
            "Проверьте API-ключ, адрес API и имя модели в настройках.",
            False,
        )
    return AIProviderError(
        ProviderErrorCode.PROVIDER_UNAVAILABLE,
        f"API анализа вернул HTTP {status_code}: временный сбой или перегрузка сервиса. "
        "Фото сохранено локально; повторите анализ позже.",
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
    retry_base_delay_seconds = RETRY_BASE_DELAY_SECONDS

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
        normalized_api_key = api_key.strip() if api_key else ""
        normalized_base_url = base_url.strip() if base_url else ""
        self.image_store = image_store
        self.api_key = normalized_api_key or None
        self.base_url = normalized_base_url.rstrip("/") or None
        self.model = model.strip()
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
            list(request.get("image_views", [])),
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

    async def check_connection(self) -> None:
        """Send a tiny text-only request only after the user explicitly asks for it."""
        if not self.configured:
            raise AIProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                f"{self.provider_id.capitalize()} ещё не настроен. Проверьте ключ и адрес сервиса.",
                False,
            )
        response = await self._request_with_retry(self._probe_payload())
        try:
            text = self._extract_text(response).strip()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIProviderError(
                ProviderErrorCode.INVALID_SCHEMA,
                "Сервис доступен, но вернул неожиданный ответ на проверочный запрос.",
                False,
            ) from exc
        if not text:
            raise AIProviderError(
                ProviderErrorCode.INVALID_SCHEMA,
                "Сервис доступен, но вернул пустой ответ на проверочный запрос.",
                False,
            )

    async def _send_with_retry(self, images: list[ImageAsset], instruction: str) -> dict[str, Any]:
        return await self._request_with_retry(self._payload(images, instruction))

    async def _request_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: AIProviderError | None = None
        for attempt in range(self.max_attempts):
            started = perf_counter()
            upstream_status: int | None = None
            upstream_code: str | None = None
            server_delay: float | None = None
            try:
                result = await self.transport(
                    self._url(), self._headers(), payload,
                    self.timeout_seconds,
                )
                upstream_status = result.status_code
                upstream_code = _upstream_code(result.payload)
                server_delay = result.retry_after_seconds
                if server_delay is None:
                    server_delay = _payload_retry_delay(result.payload)
                successful_http = 200 <= result.status_code < 300
                failed_response = (
                    result.payload.get("status") == "failed"
                    or isinstance(result.payload.get("error"), dict)
                )
                if successful_http and not failed_response:
                    return result.payload
                error_status = (
                    UPSTREAM_ERROR_STATUSES.get(upstream_code or "", 422)
                    if successful_http else result.status_code
                )
                if successful_http and upstream_code is None:
                    error = AIProviderError(
                        ProviderErrorCode.INVALID_SCHEMA,
                        "Сервис не завершил разбор и вернул ошибку вместо результата. "
                        "Ответ не принят — попробуйте другой снимок или повторите позже.",
                        False,
                    )
                else:
                    error = _provider_error(error_status, result.payload)
            except AIProviderError as exc:
                error = exc
            last_error = error
            will_retry = error.retryable and attempt + 1 < self.max_attempts
            delay = max(server_delay or 0.0, (
                self.retry_base_delay_seconds * (2 ** attempt)
                + random.uniform(0.0, RETRY_MAX_JITTER_SECONDS)
            )) if will_retry else 0.0
            delay = min(delay, MAX_RETRY_DELAY_SECONDS)
            logger.warning("ai_provider_attempt_failed", extra={
                "request_id": request_id_context.get(),
                "provider_id": self.provider_id,
                "attempt": attempt + 1, "max_attempts": self.max_attempts,
                "upstream_status": upstream_status, "upstream_code": upstream_code,
                "error_code": error.code.value, "retryable": error.retryable,
                "error_type": type(error.__cause__).__name__ if error.__cause__ else None,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "retry_delay_seconds": round(delay, 2),
                "timeout_seconds": self.timeout_seconds,
            })
            if not will_retry:
                raise error
            await self.retry_pause(delay)
        assert last_error is not None
        raise last_error

    def _url(self) -> str:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _payload(self, images: list[ImageAsset], instruction: str) -> dict[str, Any]:
        raise NotImplementedError

    def _probe_payload(self) -> dict[str, Any]:
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

    def _probe_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Ответь только словом OK."}],
            "max_tokens": 8,
            "temperature": 0,
            "stream": False,
        }
        hostname = urlparse(self.base_url).hostname if self.base_url else None
        if hostname == "openrouter.ai" or (hostname and hostname.endswith(".openrouter.ai")):
            payload["reasoning"] = {"enabled": False}
        return payload


class GeminiProvider(ExternalVisionProvider):
    provider_id = "gemini"
    retry_base_delay_seconds = 5.0

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
            "generation_config": {"thinking_level": "low"},
            # Gemini 3.x is tuned for its default temperature. Forcing a low
            # value can degrade or loop structured responses, so leave it unset.
            "response_format": {
                # The canonical contract is already included once in the instruction.
                # Repeating that large, deeply nested schema here makes Gemini compile
                # it as Structured Output and can end in upstream 503/timeout errors.
                # JSON mode keeps the response machine-readable; the strict contract
                # and semantic checks in analyze_style remain the trust boundary.
                "type": "text", "mime_type": "application/json",
            },
        }

    def _extract_text(self, response: dict[str, Any]) -> str:
        if response.get("status") in {
            "incomplete", "budget_exceeded", "cancelled", "in_progress", "queued", "requires_action",
        }:
            raise AIProviderError(
                ProviderErrorCode.INVALID_SCHEMA,
                "Gemini не завершил разбор. Неполный ответ не принят — повторите анализ.",
                False,
            )
        for step in reversed(response["steps"]):
            if step.get("type") != "model_output":
                continue
            texts = [part["text"] for part in step["content"] if part.get("type") == "text"]
            if texts:
                return "".join(texts)
        raise TypeError("missing model output text")

    def _probe_payload(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": "Ответь только словом OK.",
            "store": False,
            # Gemini 3.x counts hidden thought tokens against max_output_tokens.
            # A tiny hard limit can therefore end the request before model_output
            # is emitted. Minimal thinking keeps this health check cheap without
            # risking an empty, status=incomplete response.
            "generation_config": {"thinking_level": "minimal"},
        }


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

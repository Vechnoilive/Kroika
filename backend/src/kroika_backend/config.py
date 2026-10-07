"""Environment-only configuration with safe local defaults."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
from urllib.parse import urlparse


GEMINI_MINIMAL_MODELS = frozenset({
    "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite", "gemini-3-flash-preview",
})


def validate_gemini_thinking(model: str, level: str) -> None:
    if level not in {"auto", "minimal", "low"}:
        raise ValueError("GEMINI_THINKING_LEVEL должен быть auto, minimal или low")
    if level == "minimal" and model.removeprefix("models/") not in GEMINI_MINIMAL_MODELS:
        raise ValueError(
            "GEMINI_THINKING_LEVEL=minimal не поддерживается выбранной моделью; "
            "используйте auto или low"
        )


def _string(name: str, default: str) -> str:
    raw = os.getenv(name)
    normalized = raw.strip() if raw is not None else ""
    return normalized or default


def _optional_string(name: str) -> str | None:
    raw = os.getenv(name)
    normalized = raw.strip() if raw is not None else ""
    return normalized or None


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} должен быть true или false")


def _integer(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть числом") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    image_storage_path: Path = Path("data/images")
    log_level: str = "INFO"
    ai_provider: str = "mock"
    enabled_ai_providers: tuple[str, ...] = ("mock", "qwen")
    qwen_api_key: str | None = None
    qwen_base_url: str | None = None
    qwen_model: str = "qwen3-vl-plus"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.6-flash"
    gemini_api_mode: str = "generate_content"
    gemini_thinking_level: str = "auto"
    gemini_max_output_tokens: int = 16384
    ai_timeout_seconds: float = 300.0
    ai_max_attempts: int = 3
    max_image_bytes: int = 10 * 1024 * 1024
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    debug: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            item.strip() for item in os.getenv(
                "KROIKA_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",") if item.strip()
        )
        enabled_ai_providers = tuple(
            item.strip().lower() for item in os.getenv(
                "KROIKA_ENABLED_AI_PROVIDERS", "mock,qwen"
            ).split(",") if item.strip()
        )
        return cls(
            database_path=Path(os.getenv("KROIKA_DATABASE_PATH", "data/kroika.db")),
            image_storage_path=Path(os.getenv("KROIKA_IMAGE_STORAGE_PATH", "data/images")),
            log_level=_string("KROIKA_LOG_LEVEL", "INFO").upper(),
            ai_provider=_string("KROIKA_AI_PROVIDER", "mock").lower(),
            enabled_ai_providers=enabled_ai_providers,
            qwen_api_key=_optional_string("QWEN_API_KEY"),
            qwen_base_url=_optional_string("QWEN_BASE_URL"),
            qwen_model=_string("QWEN_MODEL", "qwen3-vl-plus"),
            gemini_api_key=_optional_string("GEMINI_API_KEY"),
            gemini_base_url=_string(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
            ),
            gemini_model=_string("GEMINI_MODEL", "gemini-3.6-flash"),
            gemini_api_mode=_string("GEMINI_API_MODE", "generate_content").lower(),
            gemini_thinking_level=_string("GEMINI_THINKING_LEVEL", "auto").lower(),
            gemini_max_output_tokens=_integer("GEMINI_MAX_OUTPUT_TOKENS", 16384),
            ai_timeout_seconds=_float("KROIKA_AI_TIMEOUT_SECONDS", 300.0),
            ai_max_attempts=_integer("KROIKA_AI_MAX_ATTEMPTS", 3),
            max_image_bytes=_integer("KROIKA_MAX_IMAGE_BYTES", 10 * 1024 * 1024),
            cors_origins=origins,
            debug=_boolean("KROIKA_DEBUG", False),
        )

    def validate(self) -> None:
        if self.ai_provider not in {"mock", "qwen", "gemini"}:
            raise ValueError("KROIKA_AI_PROVIDER должен быть mock, qwen или gemini")
        if not self.enabled_ai_providers:
            raise ValueError("KROIKA_ENABLED_AI_PROVIDERS не должен быть пустым")
        if len(set(self.enabled_ai_providers)) != len(self.enabled_ai_providers):
            raise ValueError("KROIKA_ENABLED_AI_PROVIDERS содержит повторяющиеся значения")
        if any(item not in {"mock", "qwen", "gemini"} for item in self.enabled_ai_providers):
            raise ValueError(
                "KROIKA_ENABLED_AI_PROVIDERS может содержать только mock, qwen и gemini"
            )
        if "mock" not in self.enabled_ai_providers:
            raise ValueError("Демо-режим mock должен оставаться доступным как безопасный fallback")
        if self.ai_provider not in self.enabled_ai_providers:
            raise ValueError(
                "KROIKA_AI_PROVIDER должен входить в KROIKA_ENABLED_AI_PROVIDERS"
            )
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("KROIKA_LOG_LEVEL содержит неподдерживаемое значение")
        if self.gemini_api_mode not in {"generate_content", "interactions"}:
            raise ValueError("GEMINI_API_MODE должен быть generate_content или interactions")
        validate_gemini_thinking(self.gemini_model, self.gemini_thinking_level)
        if not 1024 <= self.gemini_max_output_tokens <= 65536:
            raise ValueError("GEMINI_MAX_OUTPUT_TOKENS должен быть от 1024 до 65536")
        if not 1 <= self.ai_max_attempts <= 3:
            raise ValueError("KROIKA_AI_MAX_ATTEMPTS должен быть от 1 до 3")
        if not math.isfinite(self.ai_timeout_seconds) or not (
            self.ai_timeout_seconds == 0 or 1 <= self.ai_timeout_seconds <= 1800
        ):
            raise ValueError(
                "KROIKA_AI_TIMEOUT_SECONDS должен быть от 1 до 1800; "
                "0 отключает ограничение ожидания ответа"
            )
        if not 1024 <= self.max_image_bytes <= 20 * 1024 * 1024:
            raise ValueError("KROIKA_MAX_IMAGE_BYTES должен быть от 1024 до 20971520")
        for name, value in (
            ("QWEN_BASE_URL", self.qwen_base_url),
            ("GEMINI_BASE_URL", self.gemini_base_url),
        ):
            if value is not None and urlparse(value).scheme != "https":
                raise ValueError(f"{name} должен использовать https")

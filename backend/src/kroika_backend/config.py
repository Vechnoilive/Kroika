"""Environment-only configuration with safe local defaults."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


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
    qwen_api_key: str | None = None
    qwen_base_url: str | None = None
    qwen_model: str = "qwen3-vl-plus"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.8-flash"
    ai_timeout_seconds: float = 45.0
    ai_max_attempts: int = 2
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
        return cls(
            database_path=Path(os.getenv("KROIKA_DATABASE_PATH", "data/kroika.db")),
            image_storage_path=Path(os.getenv("KROIKA_IMAGE_STORAGE_PATH", "data/images")),
            log_level=os.getenv("KROIKA_LOG_LEVEL", "INFO").upper(),
            ai_provider=os.getenv("KROIKA_AI_PROVIDER", "mock").lower(),
            qwen_api_key=os.getenv("QWEN_API_KEY") or None,
            qwen_base_url=os.getenv("QWEN_BASE_URL") or None,
            qwen_model=os.getenv("QWEN_MODEL", "qwen3-vl-plus"),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
            ),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            ai_timeout_seconds=_float("KROIKA_AI_TIMEOUT_SECONDS", 45.0),
            ai_max_attempts=_integer("KROIKA_AI_MAX_ATTEMPTS", 2),
            max_image_bytes=_integer("KROIKA_MAX_IMAGE_BYTES", 10 * 1024 * 1024),
            cors_origins=origins,
            debug=_boolean("KROIKA_DEBUG", False),
        )

    def validate(self) -> None:
        if self.ai_provider not in {"mock", "qwen", "gemini"}:
            raise ValueError("KROIKA_AI_PROVIDER должен быть mock, qwen или gemini")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("KROIKA_LOG_LEVEL содержит неподдерживаемое значение")
        if not 1 <= self.ai_max_attempts <= 3:
            raise ValueError("KROIKA_AI_MAX_ATTEMPTS должен быть от 1 до 3")
        if not 1 <= self.ai_timeout_seconds <= 180:
            raise ValueError("KROIKA_AI_TIMEOUT_SECONDS должен быть от 1 до 180")
        if not 1024 <= self.max_image_bytes <= 20 * 1024 * 1024:
            raise ValueError("KROIKA_MAX_IMAGE_BYTES должен быть от 1024 до 20971520")
        for name, value in (
            ("QWEN_BASE_URL", self.qwen_base_url),
            ("GEMINI_BASE_URL", self.gemini_base_url),
        ):
            if value is not None and urlparse(value).scheme != "https":
                raise ValueError(f"{name} должен использовать https")

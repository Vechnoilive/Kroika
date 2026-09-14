"""Environment-only configuration with safe local defaults."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


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


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    log_level: str = "INFO"
    ai_provider: str = "mock"
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
            log_level=os.getenv("KROIKA_LOG_LEVEL", "INFO").upper(),
            ai_provider=os.getenv("KROIKA_AI_PROVIDER", "mock").lower(),
            cors_origins=origins,
            debug=_boolean("KROIKA_DEBUG", False),
        )

    def validate(self) -> None:
        if self.ai_provider != "mock":
            raise ValueError(
                "На этапе 4 доступен только KROIKA_AI_PROVIDER=mock; Qwen появится на этапе 10."
            )
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("KROIKA_LOG_LEVEL содержит неподдерживаемое значение")

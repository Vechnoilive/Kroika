"""Structured metadata-only logging."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any


request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    _allowed = (
        "request_id", "method", "route", "status_code", "duration_ms",
        "provider_id", "attempt", "max_attempts", "upstream_status", "upstream_code",
        "error_code", "error_type", "retryable", "retry_delay_seconds", "timeout_seconds",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for name in self._allowed:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if "request_id" not in payload and request_id_context.get() is not None:
            payload["request_id"] = request_id_context.get()
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("kroika.backend")
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger

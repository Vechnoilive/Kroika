"""Dependency-free boundaries for AI adapters and the pattern engine."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable

JsonObject = dict[str, Any]


class ProviderErrorCode(StrEnum):
    TIMEOUT = 'timeout'
    AUTH = 'auth'
    RATE_LIMIT = 'rate_limit'
    INVALID_SCHEMA = 'invalid_schema'
    PROVIDER_UNAVAILABLE = 'provider_unavailable'


class AIProviderError(RuntimeError):
    def __init__(self, code: ProviderErrorCode, message_ru: str, retryable: bool):
        self.code = code
        self.message_ru = message_ru
        self.retryable = retryable
        super().__init__(message_ru)


@runtime_checkable
class AIProvider(Protocol):
    """An adapter may inspect images, but receives no body measurements."""

    provider_id: str

    async def analyze_style(self, request: Mapping[str, Any]) -> JsonObject:
        """Return an object matching ai-style-analysis.schema.json."""
        ...


class PatternEngineError(RuntimeError):
    """Engine failures are explicit; callers must not turn them into success."""


@runtime_checkable
class PatternEngine(Protocol):
    """Pure boundary: confirmed structured inputs in, canonical geometry out."""

    engine_id: str
    engine_version: str

    def generate(self, request: Mapping[str, Any]) -> JsonObject:
        """Return an object matching pattern-engine-result.schema.json."""
        ...

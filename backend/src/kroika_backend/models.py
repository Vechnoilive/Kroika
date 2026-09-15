"""Small HTTP-only models; domain documents stay governed by JSON Schema."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(HealthResponse):
    database: Literal["ok"]
    ai_provider: str
    pattern_engine: str


class ImageUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1, max_length=120)
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    data_base64: str = Field(min_length=4, max_length=28_000_000)


class ImageUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_ref: str
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(ge=1)


class AIProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: Literal["mock", "qwen", "gemini"]
    name: str
    model: str
    configured: bool
    is_default: bool
    sends_images_external: bool
    message_ru: str


class AIProviderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: Literal["mock", "qwen", "gemini"]
    items: list[AIProviderStatus]


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    revision: int = Field(ge=1)
    status: str
    updated_at: str


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectSummary]


class MeasurementProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    name: str
    status: Literal["draft", "ready"]
    revision: int = Field(ge=1)
    updated_at: str


class MeasurementProfileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MeasurementProfileSummary]


class MeasurementProfileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    updated_at: str
    profile: dict[str, Any]

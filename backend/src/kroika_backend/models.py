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

"""Small HTTP-only models; domain documents stay governed by JSON Schema."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    enabled_for_users: bool
    sends_images_external: bool
    message_ru: str


class AIProviderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: Literal["mock", "qwen", "gemini"]
    items: list[AIProviderStatus]


class AIProviderCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: Literal["mock", "qwen", "gemini"]
    model: str
    status: Literal["ready"] = "ready"
    latency_ms: int = Field(ge=0)
    message_ru: str


class GarmentAcceptanceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_type: Literal[
        "dress", "sundress", "skirt", "top", "blouse", "shirt", "vest", "jacket",
        "trousers", "shorts",
    ]
    name_ru: str
    scope_ru: str
    formula_status: Literal["implemented"]
    reference_status: Literal["automated_passed"]
    invariant_status: Literal["automated_passed"]
    paper_status: Literal["pending", "passed"]
    expert_status: Literal["pending", "passed"]
    toile_status: Literal["pending", "passed"]
    production_allowed: bool


class GarmentCatalogueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GarmentAcceptanceStatus]


class BlockedGarmentRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_type: Literal[
        "dress", "sundress", "skirt", "top", "blouse", "shirt", "vest", "jacket",
        "trousers", "shorts",
    ]
    missing_gates: list[Literal["paper", "expert", "toile"]]


class ReleaseStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal[15]
    status: Literal["ready", "blocked"]
    production_ready: bool
    policy: str
    ready_garments: list[str]
    blocked_garments: list[BlockedGarmentRelease]


class PhysicalValidationCreate(BaseModel):
    """One append-only observation for an exact generated pattern."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    gate: Literal["paper", "expert", "toile"]
    outcome: Literal["passed", "failed"] | None = None
    reviewer_name: str = Field(min_length=2, max_length=120)
    notes: str = Field(default="", max_length=2000)
    printer_name: str | None = Field(default=None, min_length=2, max_length=120)
    square_width_mm: float | None = Field(default=None, gt=0, le=100)
    square_height_mm: float | None = Field(default=None, gt=0, le=100)
    control_line_mm: float | None = Field(default=None, gt=0, le=400)
    figure_label: str | None = Field(default=None, min_length=2, max_length=120)
    evidence_image_refs: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_gate_fields(self) -> "PhysicalValidationCreate":
        if self.gate == "paper":
            if self.outcome is not None:
                raise ValueError("Результат печати вычисляется по измерениям.")
            if not self.printer_name or any(value is None for value in (
                self.square_width_mm, self.square_height_mm, self.control_line_mm,
            )):
                raise ValueError(
                    "Для проверки печати укажите принтер, обе стороны квадрата и линию 200 мм."
                )
        elif self.outcome is None:
            raise ValueError("Для экспертной проверки и макета выберите результат.")
        if self.gate == "toile" and not self.figure_label:
            raise ValueError("Для макета укажите фигуру или профиль мерок.")
        if self.outcome == "failed" and not self.notes.strip():
            raise ValueError("Для неудачной проверки опишите замечания.")
        return self


class PhysicalValidationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    project_id: str
    generation_id: str
    gate: Literal["paper", "expert", "toile"]
    outcome: Literal["passed", "failed"]
    reviewer_name: str
    notes: str
    printer_name: str | None
    square_width_mm: float | None
    square_height_mm: float | None
    control_line_mm: float | None
    figure_label: str | None
    evidence_image_refs: list[str]
    created_at: str


class PhysicalGateStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: Literal["paper", "expert", "toile"]
    status: Literal["pending", "passed", "failed"]
    latest_record_id: str | None
    checked_at: str | None
    passed_observations: int = Field(ge=0)
    required_observations: int = Field(ge=1)


class PhysicalValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    generation_id: str
    gates: list[PhysicalGateStatus]
    production_allowed: bool
    policy: str
    records: list[PhysicalValidationRecord]


class PrintPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_id: str
    page_format: Literal["A4"]
    scale: float = Field(ge=1.0, le=1.0)
    pattern_sheet_count: int = Field(ge=1)
    total_pdf_pages: int = Field(ge=2)
    columns: int = Field(ge=1)
    rows: int = Field(ge=1)
    overlap_mm: float = Field(ge=0)
    control_square_mm: float = Field(gt=0)
    production_allowed: bool


class GenerationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_id: str
    created_at: str
    status: Literal["succeeded", "rejected"]
    validation_status: Literal["passed", "warnings", "failed"]
    engine_version: str
    method_version: str
    piece_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    blocking_issue_count: int = Field(ge=0)
    comparable: bool
    is_current: bool


class GenerationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    items: list[GenerationSummary]


class MeasurementChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str
    label_ru: str
    kind: Literal["added", "removed", "changed"]
    before: float | None
    after: float | None
    delta: float | None
    unit: Literal["mm", "deg"]


class StyleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    section: str
    label_ru: str
    kind: Literal["added", "removed", "changed"]
    before: Any
    after: Any
    delta: float | None
    unit: str | None


class ComparedPiece(BaseModel):
    model_config = ConfigDict(extra="forbid")

    piece_id: str
    name_ru: str
    cut_quantity: int = Field(ge=1)
    cut_on_fold: bool


class PieceGeometryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    piece_id: str
    name_ru: str
    area_delta_mm2: float | None
    width_delta_mm: float | None
    height_delta_mm: float | None
    perimeter_delta_mm: float | None
    segment_count_delta: int
    cut_quantity_before: int = Field(ge=1)
    cut_quantity_after: int = Field(ge=1)


class PatternComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    piece_count_before: int = Field(ge=0)
    piece_count_after: int = Field(ge=0)
    sheet_count_before: int | None = Field(default=None, ge=1)
    sheet_count_after: int | None = Field(default=None, ge=1)
    added_pieces: list[ComparedPiece]
    removed_pieces: list[ComparedPiece]
    changed_pieces: list[PieceGeometryChange]
    added_seam_pair_ids: list[str]
    removed_seam_pair_ids: list[str]


class ComparedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["blocking_error", "warning"]
    message_ru: str
    piece_id: str | None


class ValidationComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_before: Literal["passed", "warnings", "failed"]
    status_after: Literal["passed", "warnings", "failed"]
    added_issues: list[ComparedIssue]
    removed_issues: list[ComparedIssue]


class ComparisonTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measurement_changes: int = Field(ge=0)
    style_changes: int = Field(ge=0)
    added_pieces: int = Field(ge=0)
    removed_pieces: int = Field(ge=0)
    changed_pieces: int = Field(ge=0)
    validation_changes: int = Field(ge=0)


class GenerationComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    base: GenerationSummary
    target: GenerationSummary
    measurements: list[MeasurementChange]
    style: list[StyleChange]
    pattern: PatternComparison
    validation: ValidationComparison
    totals: ComparisonTotals
    no_changes: bool


class ManualPointEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    piece_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    segment_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    handle: Literal["end", "control_1", "control_2"]
    x_mm: float = Field(ge=-1_000_000, le=1_000_000)
    y_mm: float = Field(ge=-1_000_000, le=1_000_000)


class ManualPatternEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str = Field(default="", max_length=500)
    edits: list[ManualPointEdit] = Field(min_length=1, max_length=100)


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


class ProjectHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    status: str
    updated_at: str
    change_summary: str
    is_current: bool


class ProjectHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectHistoryEntry]


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

"""FastAPI composition root for the stage-18 modeling-aware workflow."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from kroika_contracts.contract_io import validate_document
from kroika_contracts.measurements import catalogue, measurement_issues
from kroika_contracts.ports import AIProvider, PatternEngine
from kroika_contracts.semantic import (
    validate_ai_analysis,
    validate_engine_request,
    validate_validation_report,
)
from kroika_pattern_engine import (
    GeometryPatternEngine,
    PDFRenderError,
    render_pattern_pdf,
    render_pattern_svg,
    SVG_PREVIEW_LAYERS,
    garment_catalogue,
    release_gate,
)

from .config import Settings
from .errors import AppError, install_exception_handlers
from .logging_config import configure_logging
from .image_store import LocalImageStore
from .models import (
    AIProviderListResponse,
    GarmentCatalogueResponse,
    HealthResponse,
    ImageUploadRequest,
    ImageUploadResponse,
    MeasurementProfileListResponse,
    MeasurementProfileRecord,
    MeasurementProfileSummary,
    ProjectListResponse,
    ProjectHistoryResponse,
    ProjectSummary,
    ReadinessResponse,
    ReleaseStatusResponse,
)
from .repository import SQLiteRepository
from .vision_providers import ProviderRegistry, build_provider_registry

APP_VERSION = "0.20.0"


def _project_or_404(repository: SQLiteRepository, project_id: str) -> dict[str, Any]:
    project = repository.get_project(project_id)
    if project is None:
        raise AppError(404, "PROJECT_NOT_FOUND", "Проект не найден.")
    return project


def _generation_or_404(repository: SQLiteRepository, generation_id: str) -> dict[str, Any]:
    result = repository.get_generation(generation_id)
    if result is None:
        raise AppError(404, "GENERATION_NOT_FOUND", "Результат построения не найден.")
    return result


def create_app(
    settings: Settings | None = None,
    repository: SQLiteRepository | None = None,
    ai_provider: AIProvider | None = None,
    pattern_engine: PatternEngine | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    repository = repository or SQLiteRepository(settings.database_path)
    repository.initialize()
    image_store = LocalImageStore(settings.image_storage_path, settings.max_image_bytes)
    provider_registry = build_provider_registry(settings, image_store)
    if ai_provider is not None:
        overridden = dict(provider_registry.providers)
        overridden[ai_provider.provider_id] = ai_provider
        provider_registry = ProviderRegistry(
            ai_provider.provider_id, overridden, provider_registry.enabled_for_users
        )
    active_provider = provider_registry.get()
    pattern_engine = pattern_engine or GeometryPatternEngine()
    logger = configure_logging(settings.log_level)

    app = FastAPI(
        title="Kroika API",
        version=APP_VERSION,
        description="Kroika: локальные проекты, управляемый vision-анализ и диагностическая печать.",
        debug=settings.debug,
    )
    app.state.settings = settings
    app.state.repository = repository
    app.state.image_store = image_store
    app.state.ai_provider = active_provider
    app.state.provider_registry = provider_registry
    app.state.pattern_engine = pattern_engine
    app.state.logger = logger
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "If-Match", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "Content-Disposition",
            "X-Kroika-Sheet-Count",
            "X-Kroika-Export-Mode",
            "X-Kroika-Production-Ready",
        ],
    )
    install_exception_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        route = request.scope.get("route")
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "route": getattr(route, "path", "unmatched"),
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    def health_live() -> HealthResponse:
        return HealthResponse(service="kroika-backend", version=APP_VERSION)

    @app.get("/health/ready", response_model=ReadinessResponse, tags=["health"])
    def health_ready() -> ReadinessResponse:
        if not repository.health():
            raise AppError(503, "DATABASE_UNAVAILABLE", "Локальное хранилище недоступно.")
        return ReadinessResponse(
            service="kroika-backend",
            version=APP_VERSION,
            database="ok",
            ai_provider=active_provider.provider_id,
            pattern_engine=f"{pattern_engine.engine_id}:{pattern_engine.engine_version}",
        )

    @app.get("/api/v1/projects", response_model=ProjectListResponse, tags=["projects"])
    def list_projects() -> ProjectListResponse:
        items = [ProjectSummary(
            project_id=item["project_id"], name=item["name"], revision=item["revision"],
            status=item["status"], updated_at=item["updated_at"],
        ) for item in repository.list_projects()]
        return ProjectListResponse(items=items)

    @app.post("/api/v1/projects", status_code=201, tags=["projects"])
    def create_project(project: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return repository.create_project(project)

    @app.get("/api/v1/projects/{project_id}", tags=["projects"])
    def get_project(project_id: UUID) -> dict[str, Any]:
        return _project_or_404(repository, str(project_id))

    @app.delete("/api/v1/projects/{project_id}", status_code=204, tags=["privacy"])
    def delete_project(project_id: UUID) -> Response:
        _project_or_404(repository, str(project_id))
        image_refs = repository.project_image_refs(str(project_id))
        if not repository.delete_project(str(project_id)):
            raise AppError(404, "PROJECT_NOT_FOUND", "Проект не найден.")
        for image_ref in image_refs:
            if not repository.image_ref_in_use(image_ref):
                image_store.delete(image_ref)
        return Response(status_code=204)

    @app.put("/api/v1/projects/{project_id}", tags=["projects"])
    def replace_project(
        project_id: UUID,
        project: dict[str, Any] = Body(...),
        if_match: int = Header(..., alias="If-Match", ge=1),
    ) -> dict[str, Any]:
        return repository.replace_project(str(project_id), if_match, project)

    @app.get(
        "/api/v1/projects/{project_id}/history",
        response_model=ProjectHistoryResponse,
        tags=["projects"],
    )
    def get_project_history(project_id: UUID) -> dict[str, Any]:
        _project_or_404(repository, str(project_id))
        return {"items": repository.list_project_history(str(project_id))}

    @app.post("/api/v1/projects/{project_id}/history/{revision}/restore", tags=["projects"])
    def restore_project_revision(
        project_id: UUID,
        revision: int,
        if_match: int = Header(..., alias="If-Match", ge=1),
    ) -> dict[str, Any]:
        return repository.restore_project_revision(str(project_id), revision, if_match)

    @app.get("/api/v1/measurements/catalog", tags=["measurements"])
    def get_measurement_catalog(
        garment_type: Literal[
            "dress", "sundress", "skirt", "top", "blouse", "shirt", "vest",
            "jacket", "trousers", "shorts", "jumpsuit",
        ] = "dress",
        sleeve_type: Literal["sleeveless", "short", "long"] = "sleeveless",
    ) -> dict[str, Any]:
        return catalogue(garment_type, sleeve_type)

    @app.post("/api/v1/measurements/validate", tags=["measurements"])
    def validate_measurements(
        profile: dict[str, Any] = Body(...),
        garment_type: Literal[
            "dress", "sundress", "skirt", "top", "blouse", "shirt", "vest", "jacket",
            "trousers", "shorts",
        ] = "dress",
        sleeve_type: Literal["sleeveless", "short", "long"] = "sleeveless",
    ) -> dict[str, Any]:
        validate_document("body-measurements", profile)
        issues = measurement_issues(profile, garment_type, sleeve_type)
        required = [
            item for item in catalogue(garment_type, sleeve_type)["measurements"] if item["required"]
        ]
        values = profile.get("values", {})
        angles = profile.get("angles_deg", {})
        completed = sum(
            1 for item in required
            if item["id"] in (angles if item["kind"] == "angle" else values)
        )
        return {
            "status": "invalid" if any(item.severity == "blocking_error" for item in issues)
            else "ready" if completed == len(required) else "incomplete",
            "required_count": len(required),
            "completed_count": completed,
            "issues": [{
                "code": item.code,
                "severity": item.severity,
                "json_pointer": item.json_pointer,
                "message_ru": item.message_ru,
            } for item in issues],
        }

    @app.get(
        "/api/v1/measurement-profiles",
        response_model=MeasurementProfileListResponse,
        tags=["measurements"],
    )
    def list_measurement_profiles() -> MeasurementProfileListResponse:
        return MeasurementProfileListResponse(items=[
            MeasurementProfileSummary(**item) for item in repository.list_measurement_profiles()
        ])

    @app.post(
        "/api/v1/measurement-profiles", status_code=201,
        response_model=MeasurementProfileRecord, tags=["measurements"],
    )
    def create_measurement_profile(profile: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return repository.create_measurement_profile(profile)

    @app.get(
        "/api/v1/measurement-profiles/{profile_id}",
        response_model=MeasurementProfileRecord, tags=["measurements"],
    )
    def get_measurement_profile(profile_id: UUID) -> dict[str, Any]:
        record = repository.get_measurement_profile(str(profile_id))
        if record is None:
            raise AppError(404, "MEASUREMENT_PROFILE_NOT_FOUND", "Профиль мерок не найден.")
        return record

    @app.delete(
        "/api/v1/measurement-profiles/{profile_id}", status_code=204, tags=["privacy"]
    )
    def delete_measurement_profile(profile_id: UUID) -> Response:
        if not repository.delete_measurement_profile(str(profile_id)):
            raise AppError(
                404, "MEASUREMENT_PROFILE_NOT_FOUND", "Профиль мерок не найден."
            )
        return Response(status_code=204)

    @app.put(
        "/api/v1/measurement-profiles/{profile_id}",
        response_model=MeasurementProfileRecord, tags=["measurements"],
    )
    def replace_measurement_profile(
        profile_id: UUID,
        profile: dict[str, Any] = Body(...),
        if_match: int = Header(..., alias="If-Match", ge=1),
    ) -> dict[str, Any]:
        return repository.replace_measurement_profile(str(profile_id), if_match, profile)

    @app.get(
        "/api/v1/ai/providers", response_model=AIProviderListResponse, tags=["garments"]
    )
    def list_ai_providers() -> dict[str, Any]:
        return {
            "default_provider": provider_registry.default_provider,
            "items": provider_registry.statuses(),
        }

    @app.get(
        "/api/v1/garments/catalog",
        response_model=GarmentCatalogueResponse,
        tags=["garments"],
    )
    def list_garment_catalogue() -> dict[str, Any]:
        return {"items": garment_catalogue()}

    @app.get(
        "/api/v1/release/status",
        response_model=ReleaseStatusResponse,
        tags=["release"],
    )
    def get_release_status() -> dict[str, Any]:
        return release_gate()

    @app.post(
        "/api/v1/images", status_code=201,
        response_model=ImageUploadResponse, tags=["garments"],
    )
    def upload_image(request_document: ImageUploadRequest) -> dict[str, Any]:
        asset = image_store.save_base64(
            request_document.data_base64, request_document.media_type
        )
        return {
            "image_ref": asset.image_ref,
            "media_type": asset.media_type,
            "size_bytes": len(asset.data),
        }

    @app.delete("/api/v1/images/{image_ref}", status_code=204, tags=["privacy"])
    def delete_image(image_ref: str) -> Response:
        if repository.image_ref_in_use(image_ref):
            raise AppError(
                409,
                "IMAGE_IN_USE",
                "Изображение используется в проекте. Сначала удалите проект.",
            )
        if not image_store.delete(image_ref):
            raise AppError(404, "IMAGE_NOT_FOUND", "Изображение не найдено.")
        return Response(status_code=204)

    @app.post("/api/v1/garments/analyze-image", tags=["garments"])
    async def analyze_image(
        request_document: dict[str, Any] = Body(...),
        provider: Literal["mock", "qwen", "gemini"] | None = None,
    ) -> dict[str, Any]:
        validate_document("ai-analysis-request", request_document)
        selected_provider = provider_registry.get(provider)
        result = await selected_provider.analyze_style(request_document)
        validate_ai_analysis(result)
        return result

    @app.post("/api/v1/patterns/generate", tags=["patterns"])
    def generate_pattern(request_document: dict[str, Any] = Body(...)) -> dict[str, Any]:
        validate_engine_request(request_document)
        _project_or_404(repository, request_document["project_id"])
        existing = repository.get_generation_by_hash(
            request_document["project_id"],
            request_document["input_hash"],
            pattern_engine.engine_version,
        )
        if existing is not None:
            return repository.activate_generation(existing)
        result = pattern_engine.generate(request_document)
        validate_document("pattern-engine-result", result)
        validate_validation_report(result["validation_report"])
        binding_fields = ("request_id", "project_id", "input_hash", "pattern_method")
        if any(result[field] != request_document[field] for field in binding_fields):
            raise AppError(
                500, "ENGINE_RESULT_MISMATCH",
                "Движок вернул несогласованный результат. Проект не был изменён.",
            )
        return repository.record_generation(result)

    @app.get("/api/v1/patterns/{generation_id}/validation", tags=["patterns"])
    def get_validation(generation_id: UUID) -> dict[str, Any]:
        return _generation_or_404(repository, str(generation_id))["validation_report"]

    @app.get("/api/v1/patterns/{generation_id}/preview.svg", tags=["patterns"])
    def get_preview(
        generation_id: UUID,
        layers: str | None = Query(
            default=None,
            description="Слои через запятую: cutting,seam,internal,fold,grain,notches,labels,dimensions",
        ),
    ) -> Response:
        result = _generation_or_404(repository, str(generation_id))
        if result["pattern"] is None:
            raise AppError(
                409, "PATTERN_NOT_AVAILABLE",
                "Для отклонённого построения предпросмотр недоступен.",
            )
        selected_layers = None
        if layers is not None:
            selected_layers = {item.strip() for item in layers.split(",") if item.strip()}
            unknown = selected_layers - SVG_PREVIEW_LAYERS
            if unknown:
                raise AppError(
                    422, "SVG_LAYER_UNKNOWN",
                    f"Неизвестные слои: {', '.join(sorted(unknown))}.",
                )
        svg = render_pattern_svg(result["pattern"], selected_layers)
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    f'inline; filename="kroika-{generation_id}-preview.svg"'
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/patterns/{generation_id}/export/print.svg", tags=["patterns"])
    def export_print_svg(generation_id: UUID) -> Response:
        result = _generation_or_404(repository, str(generation_id))
        if result["pattern"] is None or not result["validation_report"]["diagnostic_export_allowed"]:
            raise AppError(
                409,
                "DIAGNOSTIC_EXPORT_BLOCKED",
                "Диагностический экспорт недоступен для отклонённого построения.",
            )
        svg = render_pattern_svg(result["pattern"])
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="kroika-{generation_id}-print.svg"',
                "X-Content-Type-Options": "nosniff",
                "X-Kroika-Export-Mode": "diagnostic",
                "X-Kroika-Production-Ready": "false",
            },
        )

    @app.post("/api/v1/patterns/{generation_id}/export/a4-pdf", tags=["patterns"])
    def export_pdf(generation_id: UUID) -> Response:
        result = _generation_or_404(repository, str(generation_id))
        if result["pattern"] is None or not result["validation_report"]["diagnostic_export_allowed"]:
            raise AppError(
                409,
                "DIAGNOSTIC_EXPORT_BLOCKED",
                "Диагностическая печать недоступна для отклонённого построения.",
            )
        try:
            rendered = render_pattern_pdf(result["pattern"])
        except PDFRenderError as error:
            raise AppError(409, "PDF_EXPORT_INVALID", str(error)) from error
        return Response(
            content=rendered.content,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="kroika-{generation_id}-a4.pdf"',
                "X-Content-Type-Options": "nosniff",
                "X-Kroika-Sheet-Count": str(rendered.tile_count),
                "X-Kroika-Export-Mode": "diagnostic",
                "X-Kroika-Production-Ready": "false",
            },
        )

    @app.get("/api/v1/patterns/{generation_id}/export/project-json", tags=["patterns"])
    def export_project(generation_id: UUID) -> JSONResponse:
        result = _generation_or_404(repository, str(generation_id))
        project = _project_or_404(repository, result["project_id"])
        return JSONResponse(
            project,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    f'attachment; filename="kroika-{project["project_id"]}.json"'
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app

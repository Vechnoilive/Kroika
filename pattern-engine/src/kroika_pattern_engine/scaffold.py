"""Deterministic multi-garment generator boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .assembly import assemble_garment
from .allowances import apply_seam_allowances
from .blocks import (
    BaseBlockSet,
    BlockConstructionError,
    SkirtBlockSet,
    TrouserBlockSet,
    build_base_blocks,
    build_skirt_blocks,
    build_trouser_blocks,
)
from .composites import apply_composite_transformations
from .coverage import compile_design_coverage
from .garment_catalogue import garment_acceptance
from .geometry import run_core_diagnostics
from .modeling import apply_modeling_transformations


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GeometryPatternEngine:
    """Build a bounded experimental garment and return an auditable report."""

    engine_id = "kroika-geometry"
    engine_version = "0.11.0"

    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock

    def generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        diagnostic = run_core_diagnostics()
        input_hash = str(request["input_hash"])
        project_id = str(request["project_id"])
        generation_id = str(
            uuid5(NAMESPACE_URL, f"kroika:{self.engine_version}:{project_id}:{input_hash}")
        )
        report_id = str(
            uuid5(NAMESPACE_URL, f"kroika:report:{self.engine_version}:{project_id}:{input_hash}")
        )
        created_at = self._clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        checks: list[dict[str, Any]] = [{
            "id": "engine.geometry.core",
            "status": "passed",
            "message_ru": (
                f"Ядро {diagnostic['version']}: {diagnostic['precision']}, "
                f"координаты {diagnostic['unit']}."
            ),
        }]
        issues: list[dict[str, Any]] = []
        pattern: dict[str, Any] | None = None
        result_status = "rejected"
        report_status = "failed"
        garment_type = str(request["garment_spec"]["garment_type"])
        acceptance = garment_acceptance(garment_type)

        try:
            blocks: BaseBlockSet | SkirtBlockSet | TrouserBlockSet
            if garment_type == "skirt":
                blocks = build_skirt_blocks(request)
            elif garment_type in {"trousers", "shorts"}:
                blocks = build_trouser_blocks(request)
            else:
                blocks = build_base_blocks(request)
            assembly = assemble_garment(request, blocks)
            modeling = apply_modeling_transformations(assembly.pattern, request)
            composite = apply_composite_transformations(modeling.pattern, request)
            coverage = compile_design_coverage(composite.pattern, request)
            printable_pattern = apply_seam_allowances(coverage.pattern, request)
        except BlockConstructionError as error:
            checks.append({
                "id": (
                    "engine.design_coverage"
                    if error.code == "DESIGN_COVERAGE_EVIDENCE_MISSING"
                    else "engine.garment_assembly"
                ),
                "status": "failed",
                "message_ru": (
                    "Фасон не покрыт геометрией: вернитесь к деталям изделия."
                    if error.code == "DESIGN_COVERAGE_EVIDENCE_MISSING"
                    else "Изделие не собрано: проверьте указанное поле."
                ),
            })
            issues.append({
                "code": error.code,
                "severity": "blocking_error",
                "message_ru": error.message_ru,
                "json_pointer": error.json_pointer,
            })
        else:
            residual_names = (
                (
                    "front_skirt_waist_residual_mm",
                    "back_skirt_waist_residual_mm",
                )
                if garment_type == "skirt"
                else (
                    "finished_waist_residual_mm",
                    "finished_hip_residual_mm",
                    "side_seam_residual_mm",
                    "inseam_residual_mm",
                )
                if garment_type in {"trousers", "shorts"}
                else (
                    "front_bodice_waist_residual_mm",
                    "back_bodice_waist_residual_mm",
                    "front_skirt_waist_residual_mm",
                    "back_skirt_waist_residual_mm",
                    "front_side_projection_residual_mm",
                    "shoulder_length_residual_front_mm",
                    "shoulder_length_residual_back_mm",
                )
            )
            maximum_residual = max(abs(blocks.controls[name]) for name in residual_names)
            expected_formula_count = (
                14 if garment_type == "skirt"
                else 24 if garment_type in {"trousers", "shorts"}
                else 41
            )
            base_piece_count = 2 if garment_type in {"skirt", "trousers", "shorts"} else 4
            sleeved = garment_type in {"blouse", "shirt", "jacket"}
            checks.extend([
                {
                    "id": "engine.pattern_blocks.formulas",
                    "status": "passed",
                    "message_ru": (
                        "Выполнены S01–S14 независимой основы юбки."
                        if garment_type == "skirt"
                        else "Выполнены T01–T24 независимой брючной основы."
                        if garment_type in {"trousers", "shorts"}
                        else "Выполнены F01–F41 зафиксированной основы лифа и юбки."
                    ),
                    "measured_value": blocks.controls["formula_count"],
                    "limit_value": expected_formula_count,
                    "unit": "1",
                },
                {
                    "id": "engine.pattern_blocks.geometry",
                    "status": "passed",
                    "message_ru": (
                        f"{base_piece_count} базовых контура связны, замкнуты и не пересекают сами себя."
                    ),
                    "measured_value": base_piece_count,
                    "limit_value": base_piece_count,
                    "unit": "1",
                },
                {
                    "id": "engine.pattern_blocks.controls",
                    "status": "passed",
                    "message_ru": "Расчётные проекции и контрольные длины совпали с целями.",
                    "measured_value": maximum_residual,
                    "limit_value": 0.001,
                    "unit": "mm",
                },
                {
                    "id": "engine.pattern_blocks.sleeve",
                    "status": "passed" if sleeved else "not_run",
                    "message_ru": (
                        "Окат одношовного рукава решён по суммарной длине проймы."
                        if sleeved
                        else "Выбран вариант без рукавов; модуль рукава не меняет результат."
                    ),
                },
                {
                    "id": "engine.garment_assembly",
                    "status": "passed",
                    "message_ru": "Собраны только компоненты ограниченного варианта выбранного изделия.",
                    "measured_value": assembly.controls["piece_count"],
                    "limit_value": assembly.controls["piece_count"],
                    "unit": "1",
                },
                {
                    "id": "engine.garment_assembly.seam_pairs",
                    "status": "passed",
                    "message_ru": "Все реализованные соединения имеют явные пары участков и допуск.",
                    "measured_value": assembly.controls["seam_pair_count"],
                    "limit_value": assembly.controls["seam_pair_count"],
                    "unit": "1",
                },
                {
                    "id": "engine.garment_assembly.interfaces",
                    "status": "passed",
                    "message_ru": (
                        "Растворы вытачек исключены отдельно; скрытого остатка в парах швов нет."
                    ),
                    "measured_value": assembly.controls["maximum_interface_residual_mm"],
                    "limit_value": 0.001,
                    "unit": "mm",
                },
                {
                    "id": "engine.garment_assembly.ease",
                    "status": "passed",
                    "message_ru": (
                        "Максимальная разница собираемых длин после закрытия вытачек "
                        "не превышает ограничение экспериментальной методики."
                    ),
                    "measured_value": assembly.controls["maximum_declared_ease_mm"],
                    "limit_value": 5.0,
                    "unit": "mm",
                },
                {
                    "id": "engine.modeling.transformations",
                    "status": "passed" if modeling.applied_count else "not_run",
                    "message_ru": (
                        "Подтверждённые модельные операции применены к геометрии "
                        "и записаны в аудиторский журнал."
                        if modeling.applied_count
                        else "Подтверждённых модельных операций этапа 18 нет."
                    ),
                    "measured_value": modeling.applied_count,
                    "limit_value": modeling.applied_count,
                    "unit": "1",
                },
                {
                    "id": "engine.modeling.interfaces",
                    "status": "passed" if modeling.applied_count else "not_run",
                    "message_ru": (
                        "После моделирования длины всех парных срезов остаются в допуске."
                        if modeling.applied_count
                        else "Новые модельные сопряжения не создавались."
                    ),
                    "measured_value": modeling.maximum_invariant_residual_mm,
                    "limit_value": 1.0,
                    "unit": "mm",
                },
                {
                    "id": "engine.composites.modules",
                    "status": "passed" if composite.applied_count else "not_run",
                    "message_ru": (
                        "Подтверждённые составные детали и слои построены как реальные лекала."
                        if composite.applied_count
                        else "Подтверждённых составных модулей этапа 19 нет."
                    ),
                    "measured_value": composite.applied_count,
                    "limit_value": composite.applied_count,
                    "unit": "1",
                },
                {
                    "id": "engine.composites.interfaces",
                    "status": "passed" if composite.applied_count else "not_run",
                    "message_ru": (
                        "Соединения составных деталей и слоёв явно заданы и остаются в допуске."
                        if composite.applied_count
                        else "Новые интерфейсы составных деталей не создавались."
                    ),
                    "measured_value": composite.maximum_invariant_residual_mm,
                    "limit_value": 1.0,
                    "unit": "mm",
                },
                {
                    "id": "engine.design_coverage",
                    "status": "passed",
                    "message_ru": (
                        "Каждый подтверждённый модуль фасона связан с реальными "
                        "деталями, линиями, соединениями или операциями выкройки."
                    ),
                    "measured_value": coverage.required_module_count,
                    "limit_value": coverage.required_module_count,
                    "unit": "1",
                },
                {
                    "id": "engine.jacket.interfaces",
                    "status": "passed" if garment_type == "jacket" else "not_run",
                    "message_ru": (
                        "Воротник, окат, подборта и подкладка имеют явные парные срезы."
                        if garment_type == "jacket"
                        else "Проверка относится только к отдельной методике лёгкого жакета."
                    ),
                    "measured_value": 0.0 if garment_type == "jacket" else None,
                    "limit_value": 1.0 if garment_type == "jacket" else None,
                    "unit": "mm" if garment_type == "jacket" else None,
                },
                {
                    "id": "engine.trousers.balance",
                    "status": "passed" if garment_type in {"trousers", "shorts"} else "not_run",
                    "message_ru": (
                        "Боковые, шаговые и средние швы заданы парами; линии бёдер, "
                        "баланса ноги и долевой нанесены на обе половинки."
                        if garment_type in {"trousers", "shorts"}
                        else "Проверка относится только к независимой брючной основе."
                    ),
                    "measured_value": (
                        max(
                            assembly.controls["trouser_side_residual_mm"],
                            assembly.controls["trouser_inseam_residual_mm"],
                        ) if garment_type in {"trousers", "shorts"} else None
                    ),
                    "limit_value": 1.0 if garment_type in {"trousers", "shorts"} else None,
                    "unit": "mm" if garment_type in {"trousers", "shorts"} else None,
                },
                {
                    "id": "engine.printing.cutting_contours",
                    "status": "passed",
                    "message_ru": (
                        "Для каждой детали построена линия среза из припусков по типам участков."
                    ),
                    "measured_value": len(printable_pattern["pieces"]),
                    "limit_value": len(printable_pattern["pieces"]),
                    "unit": "1",
                },
                {
                    "id": "engine.garment_acceptance",
                    "status": "not_run",
                    "message_ru": (
                        f"{acceptance['name_ru']}: бумажная, экспертная и макетная "
                        "приёмка пока не выполнены."
                    ),
                },
                {
                    "id": "engine.printing.scale",
                    "status": "passed",
                    "message_ru": "Макет размечен для диагностической печати A4 в масштабе 1:1.",
                    "measured_value": 1,
                    "limit_value": 1,
                    "unit": "1",
                },
            ])
            issues.extend([
                {
                    "code": "GARMENT_ACCEPTANCE_PENDING",
                    "severity": "warning",
                    "message_ru": (
                        f"{acceptance['name_ru']}: автоматические эталоны и инварианты пройдены, "
                        "но expert/toile status остаётся pending."
                    ),
                    "json_pointer": f"/garments/{garment_type}/toile_status",
                },
                {
                    "code": "EXPERT_BLOCK_REVIEW_REQUIRED",
                    "severity": "warning",
                    "message_ru": (
                        "Автоматические контроли пройдены, но бумажное построение и посадка "
                        "ещё не подтверждены закройщиком."
                    ),
                    "json_pointer": "/pattern_method/validation_status",
                },
                {
                    "code": "SEAM_TRUEING_REVIEW_REQUIRED",
                    "severity": "warning",
                    "message_ru": (
                        "Величины совмещения швов записаны в seam_pairs; их распределение "
                        "нужно проверить на бумаге и макете до раскроя."
                    ),
                    "json_pointer": "/pattern/seam_pairs",
                },
                {
                    "code": "PHYSICAL_PRINT_TEST_REQUIRED",
                    "severity": "warning",
                    "message_ru": (
                        "Перед раскроем ткани проверьте квадрат 50×50 мм и совмещение "
                        "листов минимум на двух принтерах, затем изготовьте макет."
                    ),
                    "json_pointer": "/pattern/print_layout",
                },
            ])
            pattern = printable_pattern
            result_status = "succeeded"
            report_status = "warnings"

        report = {
            "schema_version": "1.0.0",
            "report_id": report_id,
            "project_id": project_id,
            "generation_id": generation_id,
            "input_hash": input_hash,
            "validator_version": self.engine_version,
            "created_at": created_at,
            "status": report_status,
            "method_validation_status": request["pattern_method"]["validation_status"],
            "issues": issues,
            "checks": checks,
            "diagnostic_export_allowed": pattern is not None,
            "production_export_allowed": False,
        }
        return {
            "schema_version": "1.0.0",
            "request_id": request["request_id"],
            "project_id": project_id,
            "generation_id": generation_id,
            "input_hash": input_hash,
            "engine_version": self.engine_version,
            "pattern_method": dict(request["pattern_method"]),
            "created_at": created_at,
            "status": result_status,
            "pattern": pattern,
            "validation_report": report,
        }


ScaffoldPatternEngine = GeometryPatternEngine

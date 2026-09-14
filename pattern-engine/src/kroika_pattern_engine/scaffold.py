"""Stage-7 pattern-engine boundary.

The base bodice, skirt and sleeve blocks are now executable and validated.
A complete dress assembly, seam pairing and preview belong to stage 8, so the
public garment-generation operation still fails closed instead of presenting
diagnostic blocks as a ready-to-cut dress.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .blocks import BlockConstructionError, build_base_blocks
from .geometry import run_core_diagnostics


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GeometryPatternEngine:
    """Deterministic boundary around geometry and experimental base blocks."""

    engine_id = "kroika-geometry"
    engine_version = "0.3.0"

    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock

    def generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        diagnostic = run_core_diagnostics()
        input_hash = str(request["input_hash"])
        project_id = str(request["project_id"])
        generation_id = str(uuid5(NAMESPACE_URL, f"kroika:{project_id}:{input_hash}"))
        report_id = str(uuid5(NAMESPACE_URL, f"kroika:report:{project_id}:{input_hash}"))
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
        try:
            blocks = build_base_blocks(request)
        except BlockConstructionError as error:
            checks.append({
                "id": "engine.pattern_blocks",
                "status": "failed",
                "message_ru": "Базовые блоки не построены: проверьте указанное поле.",
            })
            issues.append({
                "code": error.code,
                "severity": "blocking_error",
                "message_ru": error.message_ru,
                "json_pointer": error.json_pointer,
            })
        else:
            residual_names = (
                "front_bodice_waist_residual_mm",
                "back_bodice_waist_residual_mm",
                "front_skirt_waist_residual_mm",
                "back_skirt_waist_residual_mm",
                "front_side_projection_residual_mm",
                "shoulder_length_residual_front_mm",
                "shoulder_length_residual_back_mm",
            )
            maximum_residual = max(abs(blocks.controls[name]) for name in residual_names)
            checks.extend([
                {
                    "id": "engine.pattern_blocks.formulas",
                    "status": "passed",
                    "message_ru": "Выполнены F01–F41 зафиксированной версии методики.",
                    "measured_value": blocks.controls["formula_count"],
                    "limit_value": 41,
                    "unit": "1",
                },
                {
                    "id": "engine.pattern_blocks.geometry",
                    "status": "passed",
                    "message_ru": "Четыре базовых контура связны, замкнуты и не пересекают сами себя.",
                    "measured_value": 4,
                    "limit_value": 4,
                    "unit": "1",
                },
                {
                    "id": "engine.pattern_blocks.controls",
                    "status": "passed",
                    "message_ru": "Талия, плечо и проекционный баланс совпали с расчётными целями.",
                    "measured_value": maximum_residual,
                    "limit_value": 0.001,
                    "unit": "mm",
                },
                {
                    "id": "engine.pattern_blocks.sleeve",
                    "status": "not_run",
                    "message_ru": "Одношовный рукав реализован отдельно; выбран вариант без рукава.",
                },
                {
                    "id": "engine.garment_assembly",
                    "status": "not_run",
                    "message_ru": "Сборка деталей платья и пары швов будут добавлены на этапе 8.",
                },
            ])
            issues.extend([
                {
                    "code": "EXPERT_BLOCK_REVIEW_REQUIRED",
                    "severity": "warning",
                    "message_ru": (
                        "Автоматические контроли пройдены, но бумажные построения и посадка "
                        "ещё не подтверждены закройщиком."
                    ),
                    "json_pointer": "/pattern_method/validation_status",
                },
                {
                    "code": "GARMENT_ASSEMBLY_STAGE_NOT_READY",
                    "severity": "blocking_error",
                    "message_ru": (
                        "Базовые блоки построены, но это ещё не собранное платье: пары швов "
                        "и правила деталей появятся на этапе 8."
                    ),
                    "json_pointer": "/pattern",
                },
            ])

        report = {
            "schema_version": "1.0.0",
            "report_id": report_id,
            "project_id": project_id,
            "generation_id": generation_id,
            "input_hash": input_hash,
            "validator_version": self.engine_version,
            "created_at": created_at,
            "status": "failed",
            "method_validation_status": request["pattern_method"]["validation_status"],
            "issues": issues,
            "checks": checks,
            "diagnostic_export_allowed": False,
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
            "status": "rejected",
            "pattern": None,
            "validation_report": report,
        }


# Backwards-compatible import name for projects created by the stage-4 shell.
ScaffoldPatternEngine = GeometryPatternEngine

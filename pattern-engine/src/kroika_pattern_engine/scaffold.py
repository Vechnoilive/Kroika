"""Stage-4 engine scaffold.

The geometry core starts at stage 6. Until then the engine must fail closed:
it returns a valid diagnostic report and never invents pattern geometry.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScaffoldPatternEngine:
    """Deterministic, dependency-free implementation of the engine port."""

    engine_id = "kroika-scaffold"
    engine_version = "0.1.0"

    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock

    def generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        input_hash = str(request["input_hash"])
        project_id = str(request["project_id"])
        generation_id = str(uuid5(NAMESPACE_URL, f"kroika:{project_id}:{input_hash}"))
        report_id = str(uuid5(NAMESPACE_URL, f"kroika:report:{project_id}:{input_hash}"))
        created_at = self._clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

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
            "issues": [{
                "code": "GEOMETRY_STAGE_NOT_READY",
                "severity": "blocking_error",
                "message_ru": (
                    "Каркас работает, но построение геометрии появится на этапе 6. "
                    "Производственная выкройка не создана."
                ),
                "json_pointer": "/pattern",
            }],
            "checks": [{
                "id": "engine.geometry",
                "status": "not_run",
                "message_ru": "Геометрические проверки не запускались до реализации этапа 6.",
            }],
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

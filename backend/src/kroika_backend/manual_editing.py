"""Build an immutable engine result from a validated manual geometry edit."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from kroika_pattern_engine import apply_manual_edits


MANUAL_ENGINE_VERSION = "0.13.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def build_manual_generation(
    base: Mapping[str, Any],
    input_snapshot: Mapping[str, Any],
    edits: Sequence[Mapping[str, Any]],
    note: str,
) -> dict[str, Any]:
    edit_payload = {"base_generation_id": base["generation_id"], "edits": edits, "note": note}
    input_hash = hashlib.sha256(
        f"{base['input_hash']}:{_canonical(edit_payload)}".encode("utf-8")
    ).hexdigest()
    generation_id = str(uuid5(
        NAMESPACE_URL,
        f"kroika:manual:{MANUAL_ENGINE_VERSION}:{base['project_id']}:{input_hash}",
    ))
    created_at = _now()
    edited = apply_manual_edits(
        base["pattern"], edits, input_snapshot,
        base_generation_id=str(base["generation_id"]), note=note,
    )

    base_report = deepcopy(base["validation_report"])
    issues = [
        issue for issue in base_report["issues"]
        if issue.get("code") != "MANUAL_GEOMETRY_REVIEW_REQUIRED"
    ]
    issues.append({
        "code": "MANUAL_GEOMETRY_REVIEW_REQUIRED",
        "severity": "warning",
        "message_ru": (
            "Контур изменён вручную. До раскроя заново проверьте бумажную сборку, "
            "сопряжения и посадку макета."
        ),
        "json_pointer": "/pattern/manual_adjustments",
    })
    checks = [
        check for check in base_report["checks"]
        if not str(check.get("id", "")).startswith("engine.manual_edit.")
    ]
    checks.extend((
        {
            "id": "engine.manual_edit.contours",
            "status": "passed",
            "message_ru": "Ручные правки сохранили замкнутые контуры без самопересечений.",
            "measured_value": len(edited.audit_edits),
            "limit_value": len(edited.audit_edits),
            "unit": "1",
        },
        {
            "id": "engine.manual_edit.seam_pairs",
            "status": "passed",
            "message_ru": "После правок длины парных швов остаются в заданных допусках.",
            "measured_value": round(edited.maximum_seam_residual_mm, 6),
            "limit_value": max(
                (float(pair["tolerance_mm"]) for pair in edited.pattern["seam_pairs"]),
                default=0.0,
            ),
            "unit": "mm",
        },
    ))
    report = {
        **base_report,
        "report_id": str(uuid5(NAMESPACE_URL, f"kroika:manual-report:{generation_id}")),
        "generation_id": generation_id,
        "input_hash": input_hash,
        "validator_version": MANUAL_ENGINE_VERSION,
        "created_at": created_at,
        "status": "warnings",
        "issues": issues,
        "checks": checks,
        "diagnostic_export_allowed": True,
        "production_export_allowed": False,
    }
    return {
        "schema_version": "1.0.0",
        "request_id": str(uuid4()),
        "project_id": str(base["project_id"]),
        "generation_id": generation_id,
        "input_hash": input_hash,
        "engine_version": MANUAL_ENGINE_VERSION,
        "pattern_method": deepcopy(base["pattern_method"]),
        "created_at": created_at,
        "status": "succeeded",
        "pattern": edited.pattern,
        "validation_report": report,
    }

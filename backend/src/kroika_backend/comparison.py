"""Deterministic, human-readable comparison of two immutable generations."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from kroika_contracts.hashing import canonical_generation_payload
from kroika_contracts.measurements import BY_ID
from kroika_pattern_engine import PDFRenderError, inspect_pattern_print_plan
from kroika_pattern_engine.geometry import contour_from_data


_MISSING = object()
_SECTION_LABELS = {
    "pattern_method": "Методика",
    "garment_spec": "Фасон",
    "fit_settings": "Прибавки и припуски",
    "fabric_properties": "Ткань",
}
_FIELD_LABELS = {
    "id": "Модуль",
    "version": "Версия",
    "garment_type": "Тип изделия",
    "symmetry": "Симметрия",
    "bodice_fit": "Посадка лифа",
    "shaping": "Формообразование",
    "type": "Тип",
    "variant": "Вариант",
    "front_depth_mm": "Глубина выреза спереди",
    "back_depth_mm": "Глубина выреза сзади",
    "length_mm": "Длина",
    "length_from_waist_mm": "Длина от талии",
    "hem_expansion_each_side_mm": "Расширение низа с каждой стороны",
    "length_below_waist_mm": "Длина ниже талии",
    "location": "Расположение",
    "count": "Количество",
    "module_id": "Конструктивный модуль",
    "wearing_ease_mm": "Прибавка на свободу",
    "design_ease_mm": "Модельная прибавка",
    "front_share": "Доля переда",
    "back_share": "Доля спинки",
    "seam_allowance_mode": "Режим припусков",
    "seam_allowances_mm": "Припуск",
    "normal": "Обычный шов",
    "neckline": "Горловина",
    "armhole": "Пройма",
    "zipper": "Молния",
    "hem": "Низ изделия",
    "sleeve_hem": "Низ рукава",
    "fold": "Сгиб",
    "bust": "По груди",
    "waist": "По талии",
    "hips": "По бёдрам",
    "upper_arm": "По плечу",
    "intended_use": "Назначение ткани",
    "structure": "Структура ткани",
    "warp": "Растяжимость по долевой",
    "weft": "Растяжимость по поперечной",
    "weight": "Плотность",
    "drape": "Драпируемость",
    "stability": "Стабильность",
    "directional_nap": "Направленный ворс",
    "prewashed": "Декатирована",
    "included": "Включено",
    "construction": "Конструкция",
    "role": "Роль слоя",
    "coverage": "Покрытие слоя",
    "opacity": "Прозрачность",
}


def _rounded(value: float) -> float:
    return round(float(value), 3)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _stable_list_key(item: Mapping[str, Any], index: int) -> str:
    for key in ("source_element_id", "source_layer_id", "module_id", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return str(index + 1)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        flattened: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(value[key], child))
        return flattened
    if isinstance(value, list):
        if all(isinstance(item, Mapping) for item in value):
            flattened = {}
            for index, item in enumerate(value):
                child = f"{prefix}.{_stable_list_key(item, index)}"
                flattened.update(_flatten(item, child))
            return flattened
        return {prefix: _canonical_json(value)}
    return {prefix: value}


def _change_kind(before: Any, after: Any) -> str:
    if before is _MISSING:
        return "added"
    if after is _MISSING:
        return "removed"
    return "changed"


def _unit_for_path(path: str) -> str | None:
    final = path.rsplit(".", 1)[-1]
    if final.endswith("_mm") or ".seam_allowances_mm." in path:
        return "mm"
    if "stretch_percent" in path:
        return "%"
    return None


def _label_for_path(path: str) -> str:
    parts = path.split(".")
    final = parts[-1]
    label = _FIELD_LABELS.get(final)
    if label is not None:
        parent = _FIELD_LABELS.get(parts[-2]) if len(parts) > 1 else None
        if parent and final in {"bust", "waist", "hips", "upper_arm", "normal", "neckline", "armhole", "zipper", "hem", "sleeve_hem", "fold"}:
            return f"{parent}: {label.lower()}"
        return label
    return final.replace("_", " ").capitalize()


def _value_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    first = _flatten(before)
    second = _flatten(after)
    changes: list[dict[str, Any]] = []
    for path in sorted(first.keys() | second.keys()):
        old = first.get(path, _MISSING)
        new = second.get(path, _MISSING)
        if old == new:
            continue
        old_value = None if old is _MISSING else old
        new_value = None if new is _MISSING else new
        delta = None
        if (
            isinstance(old_value, (int, float))
            and not isinstance(old_value, bool)
            and isinstance(new_value, (int, float))
            and not isinstance(new_value, bool)
        ):
            delta = _rounded(float(new_value) - float(old_value))
        section_id = path.split(".", 1)[0]
        changes.append({
            "path": path,
            "section": _SECTION_LABELS.get(section_id, "Фасон"),
            "label_ru": _label_for_path(path),
            "kind": _change_kind(old, new),
            "before": old_value,
            "after": new_value,
            "delta": delta,
            "unit": _unit_for_path(path),
        })
    return changes


def _measurement_changes(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, Any]]:
    first = dict(before.get("values", {}))
    second = dict(after.get("values", {}))
    first.update(before.get("angles_deg", {}))
    second.update(after.get("angles_deg", {}))
    changes: list[dict[str, Any]] = []
    for field_id in sorted(first.keys() | second.keys()):
        old = first.get(field_id, _MISSING)
        new = second.get(field_id, _MISSING)
        if old == new:
            continue
        definition = BY_ID.get(field_id)
        old_value = None if old is _MISSING else float(old)
        new_value = None if new is _MISSING else float(new)
        changes.append({
            "field_id": field_id,
            "label_ru": definition.label_ru if definition else field_id,
            "kind": _change_kind(old, new),
            "before": old_value,
            "after": new_value,
            "delta": (
                _rounded(new_value - old_value)
                if old_value is not None and new_value is not None
                else None
            ),
            "unit": definition.unit if definition else "mm",
        })
    return changes


def _piece_metrics(piece: Mapping[str, Any]) -> dict[str, Any]:
    contour_data = piece.get("cutting_contour") or piece.get("seam_contour")
    if not isinstance(contour_data, Mapping):
        return {
            "area_mm2": None,
            "width_mm": None,
            "height_mm": None,
            "perimeter_mm": None,
            "segment_count": 0,
            "fingerprint": None,
        }
    contour = contour_from_data(contour_data)
    bounds = contour.bounding_box
    return {
        "area_mm2": _rounded(contour.area_mm2),
        "width_mm": _rounded(bounds.width_mm),
        "height_mm": _rounded(bounds.height_mm),
        "perimeter_mm": _rounded(contour.length_mm),
        "segment_count": len(contour.segments),
        "fingerprint": hashlib.sha256(_canonical_json(contour_data).encode()).hexdigest(),
    }


def _piece_summary(piece: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "piece_id": str(piece["id"]),
        "name_ru": str(piece.get("name_ru") or piece["id"]),
        "cut_quantity": int(piece.get("cut_quantity", 1)),
        "cut_on_fold": bool(piece.get("cut_on_fold", False)),
    }


def _pattern_comparison(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> dict[str, Any]:
    first_pieces = {
        str(piece["id"]): piece for piece in (before or {}).get("pieces", [])
    }
    second_pieces = {
        str(piece["id"]): piece for piece in (after or {}).get("pieces", [])
    }
    added = [_piece_summary(second_pieces[key]) for key in sorted(second_pieces.keys() - first_pieces.keys())]
    removed = [_piece_summary(first_pieces[key]) for key in sorted(first_pieces.keys() - second_pieces.keys())]
    changed: list[dict[str, Any]] = []
    for piece_id in sorted(first_pieces.keys() & second_pieces.keys()):
        old_piece = first_pieces[piece_id]
        new_piece = second_pieces[piece_id]
        old = _piece_metrics(old_piece)
        new = _piece_metrics(new_piece)
        metadata_changed = any(
            old_piece.get(field) != new_piece.get(field)
            for field in ("name_ru", "cut_quantity", "cut_on_fold", "mirrored_pair")
        )
        if old["fingerprint"] == new["fingerprint"] and not metadata_changed:
            continue

        def difference(field: str) -> float | None:
            if old[field] is None or new[field] is None:
                return None
            return _rounded(float(new[field]) - float(old[field]))

        changed.append({
            "piece_id": piece_id,
            "name_ru": str(new_piece.get("name_ru") or old_piece.get("name_ru") or piece_id),
            "area_delta_mm2": difference("area_mm2"),
            "width_delta_mm": difference("width_mm"),
            "height_delta_mm": difference("height_mm"),
            "perimeter_delta_mm": difference("perimeter_mm"),
            "segment_count_delta": int(new["segment_count"] - old["segment_count"]),
            "cut_quantity_before": int(old_piece.get("cut_quantity", 1)),
            "cut_quantity_after": int(new_piece.get("cut_quantity", 1)),
        })

    first_seams = {str(item["id"]) for item in (before or {}).get("seam_pairs", [])}
    second_seams = {str(item["id"]) for item in (after or {}).get("seam_pairs", [])}

    def sheets(pattern: Mapping[str, Any] | None) -> int | None:
        if pattern is None:
            return None
        try:
            return inspect_pattern_print_plan(pattern).pattern_sheet_count
        except PDFRenderError:
            return None

    return {
        "piece_count_before": len(first_pieces),
        "piece_count_after": len(second_pieces),
        "sheet_count_before": sheets(before),
        "sheet_count_after": sheets(after),
        "added_pieces": added,
        "removed_pieces": removed,
        "changed_pieces": changed,
        "added_seam_pair_ids": sorted(second_seams - first_seams),
        "removed_seam_pair_ids": sorted(first_seams - second_seams),
    }


def _issue_key(issue: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(issue.get(key) or "") for key in (
        "code", "severity", "json_pointer", "piece_id", "formula_id", "message_ru",
        "measured_value", "limit_value", "unit",
    ))


def _issue_summary(issue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": str(issue.get("code") or "UNKNOWN"),
        "severity": str(issue.get("severity") or "warning"),
        "message_ru": str(issue.get("message_ru") or "Без описания"),
        "piece_id": issue.get("piece_id"),
    }


def generation_summary(
    result: Mapping[str, Any], *, comparable: bool, current_generation_id: str | None
) -> dict[str, Any]:
    issues = result["validation_report"].get("issues", [])
    pattern = result.get("pattern")
    return {
        "generation_id": result["generation_id"],
        "created_at": result["created_at"],
        "status": result["status"],
        "validation_status": result["validation_report"]["status"],
        "engine_version": result["engine_version"],
        "method_version": result["pattern_method"]["version"],
        "piece_count": len(pattern.get("pieces", [])) if pattern else 0,
        "issue_count": len(issues),
        "blocking_issue_count": sum(
            issue.get("severity") == "blocking_error" for issue in issues
        ),
        "comparable": comparable,
        "is_current": result["generation_id"] == current_generation_id,
    }


def compare_generations(
    base: Mapping[str, Any],
    target: Mapping[str, Any],
    base_snapshot: Mapping[str, Any],
    target_snapshot: Mapping[str, Any],
    *,
    current_generation_id: str | None,
) -> dict[str, Any]:
    """Compare inputs, pattern topology/geometry, and validation messages."""

    first = canonical_generation_payload(base_snapshot)
    second = canonical_generation_payload(target_snapshot)
    measurements = _measurement_changes(
        first["body_measurements"], second["body_measurements"]
    )
    first_style = {
        key: first[key]
        for key in ("pattern_method", "garment_spec", "fit_settings", "fabric_properties")
    }
    second_style = {
        key: second[key]
        for key in ("pattern_method", "garment_spec", "fit_settings", "fabric_properties")
    }
    style = _value_changes(first_style, second_style)
    pattern = _pattern_comparison(base.get("pattern"), target.get("pattern"))
    base_issues = {_issue_key(issue): issue for issue in base["validation_report"].get("issues", [])}
    target_issues = {
        _issue_key(issue): issue for issue in target["validation_report"].get("issues", [])
    }
    validation = {
        "status_before": base["validation_report"]["status"],
        "status_after": target["validation_report"]["status"],
        "added_issues": [
            _issue_summary(target_issues[key])
            for key in sorted(target_issues.keys() - base_issues.keys())
        ],
        "removed_issues": [
            _issue_summary(base_issues[key])
            for key in sorted(base_issues.keys() - target_issues.keys())
        ],
    }
    totals = {
        "measurement_changes": len(measurements),
        "style_changes": len(style),
        "added_pieces": len(pattern["added_pieces"]),
        "removed_pieces": len(pattern["removed_pieces"]),
        "changed_pieces": len(pattern["changed_pieces"]),
        "validation_changes": (
            len(validation["added_issues"])
            + len(validation["removed_issues"])
            + int(validation["status_before"] != validation["status_after"])
        ),
    }
    return {
        "project_id": base["project_id"],
        "base": generation_summary(
            base, comparable=True, current_generation_id=current_generation_id
        ),
        "target": generation_summary(
            target, comparable=True, current_generation_id=current_generation_id
        ),
        "measurements": measurements,
        "style": style,
        "pattern": pattern,
        "validation": validation,
        "totals": totals,
        "no_changes": all(value == 0 for value in totals.values()),
    }

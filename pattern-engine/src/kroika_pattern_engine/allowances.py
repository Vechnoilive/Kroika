"""Stage-9 seam allowance assignment and fail-closed cutting contours."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from .blocks import BlockConstructionError
from .geometry import (
    GeometryError,
    contour_from_data,
    contour_to_data,
    offset_contour_by_segment,
    validate_simple_contour,
)


EDGE_TYPES = ("normal", "neckline", "armhole", "zipper", "hem", "sleeve_hem", "fold")
PRINT_LAYOUT_SPEC = {
    "page_format": "A4",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "margin_mm": 10,
    "overlap_mm": 10,
    "scale": 1,
    "control_square_mm": 50,
}


def edge_type_for_segment(piece: Mapping[str, Any], segment_id: str) -> str:
    """Classify a stable drafting segment into its sewing edge category."""

    if "sleeve_hem" in segment_id:
        return "sleeve_hem"
    if "neckline" in segment_id:
        return "neckline"
    if "armhole" in segment_id:
        return "armhole"
    if "_hem" in segment_id:
        return "hem"
    if segment_id.endswith("_center"):
        return "fold" if piece["cut_on_fold"] else "zipper"
    return "normal"


def _allowances(request: Mapping[str, Any]) -> dict[str, float]:
    fit = request.get("fit_settings")
    if not isinstance(fit, Mapping) or fit.get("seam_allowance_mode") != "by_edge":
        raise BlockConstructionError(
            "SEAM_ALLOWANCE_MODE_REQUIRED",
            "Для печати выберите припуски по типам срезов.",
            "/fit_settings/seam_allowance_mode",
        )
    values = fit.get("seam_allowances_mm")
    if not isinstance(values, Mapping) or set(values) != set(EDGE_TYPES):
        raise BlockConstructionError(
            "SEAM_ALLOWANCES_INCOMPLETE",
            "Для печати нужны все семь значений припусков.",
            "/fit_settings/seam_allowances_mm",
        )
    result: dict[str, float] = {}
    for edge_type in EDGE_TYPES:
        value = values[edge_type]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BlockConstructionError(
                "SEAM_ALLOWANCE_INVALID",
                "Каждый припуск должен быть конечным неотрицательным числом.",
                f"/fit_settings/seam_allowances_mm/{edge_type}",
            )
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise BlockConstructionError(
                "SEAM_ALLOWANCE_INVALID",
                "Каждый припуск должен быть конечным неотрицательным числом.",
                f"/fit_settings/seam_allowances_mm/{edge_type}",
            )
        result[edge_type] = numeric
    if result["fold"] != 0.0:
        raise BlockConstructionError(
            "FOLD_ALLOWANCE_MUST_BE_ZERO",
            "По линии сгиба припуск должен быть равен 0 мм.",
            "/fit_settings/seam_allowances_mm/fold",
        )
    return result


def apply_seam_allowances(
    pattern: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    """Return canonical pattern data with audited cutting contours and print spec."""

    allowance_values = _allowances(request)
    result = deepcopy(dict(pattern))
    for piece in result["pieces"]:
        seam = contour_from_data(piece["seam_contour"])
        edge_allowances: list[dict[str, Any]] = []
        distances: dict[str, float] = {}
        for segment in seam.segments:
            edge_type = edge_type_for_segment(piece, segment.id)
            allowance = allowance_values[edge_type]
            distances[segment.id] = allowance
            edge_allowances.append({
                "segment_id": segment.id,
                "edge_type": edge_type,
                "allowance_mm": allowance,
            })
        try:
            cutting = offset_contour_by_segment(
                seam,
                distances,
                join="miter",
                miter_limit=3.0,
                curve_flatness_mm=0.05,
            ).contour
            validate_simple_contour(cutting, flatness_mm=0.05)
        except GeometryError as error:
            raise BlockConstructionError(
                "CUTTING_CONTOUR_INVALID",
                f"Не удалось построить безопасную линию среза для детали «{piece['name_ru']}».",
                f"/pattern/pieces/{piece['id']}/cutting_contour",
            ) from error
        piece["cutting_contour"] = contour_to_data(cutting)
        piece["edge_allowances"] = edge_allowances
        for annotation in piece["annotations"]:
            annotation["text_ru"] = annotation["text_ru"].replace(
                "; без припусков.", "; припуски по типам срезов."
            )
    result["print_layout"] = dict(PRINT_LAYOUT_SPEC)
    return result

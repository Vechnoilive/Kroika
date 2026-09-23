"""Bounded, auditable modeling transformations introduced at stage 18."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
from typing import Any, Mapping

from .blocks import BlockConstructionError
from .geometry import (
    AffineTransform,
    ArcSegment,
    Contour,
    LineSegment,
    Point,
    contour_from_data,
    contour_to_data,
    validate_simple_contour,
)


STAGE18_MODULES = frozenset({
    "adjustable_straight_waistband_v1",
    "center_pleat_v1",
    "waist_gather_allowance_v1",
    "circular_hem_flounce_v1",
    "straight_belt_v1",
})
MODULE_ORDER = {
    "center_pleat_v1": 10,
    "waist_gather_allowance_v1": 10,
    "adjustable_straight_waistband_v1": 20,
    "circular_hem_flounce_v1": 30,
    "straight_belt_v1": 40,
}


@dataclass(frozen=True, slots=True)
class ModelingResult:
    pattern: dict[str, Any]
    applied_count: int
    added_piece_count: int
    maximum_invariant_residual_mm: float


def pleat_allowance_mm(variant: str, depth_mm: float, count: int = 1) -> float:
    """Return added cut width: knife=2d, box/inverted=4d for every pleat."""

    depth = _bounded(depth_mm, 5.0, 80.0, "MODEL_PLEAT_DEPTH_OUTSIDE_DOMAIN")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError("Количество складок должно быть целым числом от 1 до 8.")
    factors = {"knife": 2.0, "box": 4.0, "inverted": 4.0}
    try:
        factor = factors[variant]
    except KeyError as error:
        raise ValueError("Поддержаны односторонняя, бантовая и встречная складки.") from error
    return factor * depth * count


def gathered_cut_length_mm(finished_length_mm: float, added_fullness_mm: float) -> float:
    """Added-width form of L_cut = L_finished + A_gather."""

    finished = _bounded(
        finished_length_mm, 40.0, 3000.0, "MODEL_GATHER_FINISHED_LENGTH_OUTSIDE_DOMAIN"
    )
    addition = _bounded(
        added_fullness_mm, 20.0, 600.0, "MODEL_GATHER_ALLOWANCE_OUTSIDE_DOMAIN"
    )
    return finished + addition


def flounce_radii_mm(
    seam_length_mm: float, depth_mm: float, sweep_angle_rad: float = math.pi,
) -> tuple[float, float]:
    """Compute an annular-sector flounce where r*theta equals the joining seam."""

    seam = _bounded(seam_length_mm, 40.0, 3000.0, "MODEL_FLOUNCE_SEAM_OUTSIDE_DOMAIN")
    depth = _bounded(depth_mm, 30.0, 400.0, "MODEL_FLOUNCE_DEPTH_OUTSIDE_DOMAIN")
    if not math.isfinite(sweep_angle_rad) or not math.pi / 2 <= sweep_angle_rad <= 1.5 * math.pi:
        raise ValueError("Угол сектора волана должен быть от 90° до 270°.")
    inner = seam / sweep_angle_rad
    return inner, inner + depth


def yoke_split_depths_mm(total_length_mm: float, yoke_depth_mm: float) -> tuple[float, float]:
    """Reference formula for a straight horizontal yoke split."""

    total = _bounded(total_length_mm, 200.0, 1500.0, "MODEL_YOKE_LENGTH_OUTSIDE_DOMAIN")
    depth = _bounded(yoke_depth_mm, 40.0, 300.0, "MODEL_YOKE_DEPTH_OUTSIDE_DOMAIN")
    if depth >= total - 80.0:
        raise ValueError("Под кокеткой должно остаться минимум 80 мм основной детали.")
    return depth, total - depth


def equal_panel_boundaries_mm(total_width_mm: float, panel_count: int) -> tuple[float, ...]:
    """Reference formula x_i = i*W/n for equal vertical panels."""

    total = _bounded(total_width_mm, 80.0, 2000.0, "MODEL_PANEL_WIDTH_OUTSIDE_DOMAIN")
    if isinstance(panel_count, bool) or not isinstance(panel_count, int) or not 2 <= panel_count <= 8:
        raise ValueError("Количество панелей должно быть целым числом от 2 до 8.")
    return tuple(total * index / panel_count for index in range(1, panel_count))


def transferred_dart_intake_mm(source_intake_mm: float, transfer_share: float = 1.0) -> tuple[float, float]:
    """Reference invariant: source intake equals transferred plus retained intake."""

    intake = _bounded(source_intake_mm, 1.0, 100.0, "MODEL_DART_INTAKE_OUTSIDE_DOMAIN")
    if not math.isfinite(transfer_share) or not 0.0 <= transfer_share <= 1.0:
        raise ValueError("Доля переноса вытачки должна находиться от 0 до 1.")
    transferred = intake * transfer_share
    return transferred, intake - transferred


def adjusted_hem_width_mm(base_half_width_mm: float, adjustment_each_side_mm: float) -> float:
    """Reference formula W_hem = W_base + delta; delta may be negative."""

    base = _bounded(base_half_width_mm, 40.0, 1000.0, "MODEL_HEM_BASE_OUTSIDE_DOMAIN")
    if not math.isfinite(adjustment_each_side_mm) or not -100.0 <= adjustment_each_side_mm <= 250.0:
        raise ValueError("Изменение низа должно быть от −100 до 250 мм на сторону.")
    result = base + adjustment_each_side_mm
    if result < 30.0:
        raise ValueError("После заужения половина низа должна быть не уже 30 мм.")
    return result


def apply_modeling_transformations(
    pattern: Mapping[str, Any], request: Mapping[str, Any],
) -> ModelingResult:
    """Compile supported design-intent modules into actual pattern geometry."""

    result = deepcopy(dict(pattern))
    original_piece_count = len(result["pieces"])
    operations: list[dict[str, Any]] = []
    occupied_targets: set[str] = set()
    intent = request.get("garment_spec", {}).get("design_intent")
    elements = intent.get("elements", []) if isinstance(intent, Mapping) else []
    active_elements = sorted(
        (
            element for element in elements
            if element.get("included") is not False
            and element.get("support_status") == "supported"
            and element.get("module_id") in STAGE18_MODULES
        ),
        key=lambda element: (
            MODULE_ORDER[str(element["module_id"])], str(element["source_element_id"])
        ),
    )

    for element in active_elements:
        module_id = element.get("module_id")
        source_id = str(element["source_element_id"])
        dimensions = element.get("dimensions_mm") or {}
        if module_id in {"center_pleat_v1", "waist_gather_allowance_v1"}:
            target_id = "front_skirt"
            if target_id in occupied_targets:
                raise _model_error(
                    "MODEL_TARGET_CONFLICT",
                    "На одной детали нельзя одновременно размещать две добавки ширины по центру.",
                    source_id,
                )
            occupied_targets.add(target_id)
            if module_id == "center_pleat_v1":
                depth = _required_dimension(dimensions, "depth", source_id)
                allowance = pleat_allowance_mm(str(element["variant"]), depth, 1)
                marker_kind = "pleat"
                formula_id = "M18-P01"
            else:
                allowance = _required_dimension(dimensions, "width", source_id)
                piece = _piece(result, target_id, source_id)
                waist_length = _segment_length(piece, "front_skirt_waist")
                gathered_cut_length_mm(waist_length, allowance)
                marker_kind = "gather"
                formula_id = "M18-G01"
            marker_length = dimensions.get("length")
            _extend_center(
                result, target_id, allowance, marker_kind, marker_length, source_id,
                str(element.get("variant", "standard")),
            )
            operations.append(_operation(
                source_id, marker_kind, module_id, formula_id, [target_id],
                {"added_width": allowance, "marker_length": float(marker_length or 0.0)},
            ))
        elif module_id == "circular_hem_flounce_v1":
            depth = _required_dimension(dimensions, "depth", source_id)
            added_ids, residual = _add_hem_flounces(result, depth, source_id)
            operations.append(_operation(
                source_id, "flounce", module_id, "M18-F01", added_ids,
                {"depth": depth}, residual,
            ))
        elif module_id == "adjustable_straight_waistband_v1":
            width = _required_dimension(dimensions, "width", source_id)
            target_ids = _resize_waistbands(result, width, source_id)
            operations.append(_operation(
                source_id, "waistband", module_id, "M18-B01", target_ids,
                {"finished_width": width},
            ))
        elif module_id == "straight_belt_v1":
            width = _required_dimension(dimensions, "width", source_id)
            length = _required_dimension(dimensions, "length", source_id)
            piece_id = _add_belt(result, width, length, source_id)
            operations.append(_operation(
                source_id, "belt", module_id, "M18-B02", [piece_id],
                {"finished_width": width, "finished_length": length},
            ))

    garment_spec = request.get("garment_spec", {})
    skirt = garment_spec.get("parameters", {}).get("skirt")
    has_skirt_geometry = all(_has_piece(result, piece_id) for piece_id in (
        "front_skirt", "back_skirt",
    ))
    if (garment_spec.get("garment_type") in {"dress", "sundress", "skirt"}
            and isinstance(skirt, Mapping) and has_skirt_geometry):
        adjustment = float(skirt.get("hem_expansion_each_side_mm", 0.0))
        if adjustment != 0.0:
            # Geometry is created by the base-block builder; this entry makes the formula auditable.
            _bounded(
                adjustment, -100.0, 250.0, "MODEL_HEM_ADJUSTMENT_OUTSIDE_DOMAIN"
            )
            operations.append(_operation(
                "parameter_skirt_hem", "hem_adjustment", "bounded_hem_adjustment_v1",
                "M18-H01", ["front_skirt", "back_skirt"],
                {"adjustment_each_side": adjustment},
            ))

    maximum_residual = _pair_residual(result)
    if operations and maximum_residual > 1.0:
        raise BlockConstructionError(
            "MODEL_INTERFACE_RESIDUAL_EXCEEDED",
            "После моделирования длины парных срезов вышли за допуск 1 мм.",
            "/pattern/seam_pairs",
        )
    result["modeling_operations"] = operations
    return ModelingResult(
        result,
        len(operations),
        len(result["pieces"]) - original_piece_count,
        maximum_residual,
    )


def _extend_center(
    pattern: dict[str, Any], piece_id: str, allowance_mm: float, marker_kind: str,
    marker_length_mm: object, source_id: str, variant: str,
) -> None:
    piece = _piece(pattern, piece_id, source_id)
    contour = contour_from_data(piece["seam_contour"])
    center = contour.segments[0]
    if not isinstance(center, LineSegment) or not center.id.endswith("_center"):
        raise _model_error(
            "MODEL_CENTER_EDGE_REQUIRED",
            "Для добавки ширины нужна прямая центральная линия детали.",
            source_id,
        )
    allowance = _bounded(allowance_mm, 10.0, 600.0, "MODEL_ALLOWANCE_OUTSIDE_DOMAIN")
    shift = AffineTransform.translation(allowance, 0.0)
    translated = [segment.transformed(shift) for segment in contour.segments]
    old_center = translated[0]
    hem_connector_id = f"{source_id}_center_extension_hem"
    waist_connector_id = f"{source_id}_center_extension_waist"
    new_contour = Contour((
        LineSegment(center.start, center.end, center.id),
        LineSegment(center.end, old_center.end, hem_connector_id),
        *translated[1:],
        LineSegment(old_center.start, center.start, waist_connector_id),
    ), id=contour.id)
    validate_simple_contour(new_contour)
    piece["seam_contour"] = contour_to_data(new_contour)
    piece["internal_paths"] = [
        contour_to_data(contour_from_data(path).transformed(shift))
        for path in piece["internal_paths"]
    ]
    total_length = center.length_mm
    if marker_length_mm is None:
        marker_length = min(total_length * 0.45, 300.0)
    else:
        marker_length = _bounded(
            marker_length_mm, 30.0, total_length - 20.0, "MODEL_MARKER_LENGTH_OUTSIDE_DOMAIN"
        )
    if marker_kind == "pleat":
        factor = 2 if variant == "knife" else 4
        for index in range(1, factor + 1):
            x = allowance * index / factor
            path_id = f"{source_id}_fold_{index}"
            path = Contour((LineSegment(
                Point(x, center.start.y_mm), Point(x, center.start.y_mm - marker_length),
                f"{path_id}_line",
            ),), closed=False, id=path_id)
            piece["internal_paths"].append(contour_to_data(path))
    else:
        y = center.start.y_mm - min(marker_length, 20.0)
        path_id = f"{source_id}_gather_line"
        path = Contour((LineSegment(
            Point(0.0, y), Point(allowance, y), f"{path_id}_segment",
        ),), closed=False, id=path_id)
        piece["internal_paths"].append(contour_to_data(path))
    piece["grainline"] = {
        "start": [piece["grainline"]["start"][0] + allowance, piece["grainline"]["start"][1]],
        "end": [piece["grainline"]["end"][0] + allowance, piece["grainline"]["end"][1]],
    }
    for annotation in piece["annotations"]:
        annotation["position"][0] += allowance
    piece["annotations"].append({
        "id": f"{source_id}_modeling_note",
        "text_ru": (
            f"Модельная {'складка' if marker_kind == 'pleat' else 'сборка'}: "
            f"добавлено {allowance:.1f} мм; контрольные линии обязательны."
        ),
        "position": [allowance / 2.0, center.start.y_mm - marker_length / 2.0],
    })
    for pair in pattern["seam_pairs"]:
        for side in ("first", "second"):
            if pair[f"{side}_piece_id"] == piece_id and "front_skirt_waist" in pair[f"{side}_segment_ids"]:
                pair[f"{side}_segment_ids"].append(waist_connector_id)
                pair[f"{side}_length_reduction_mm"] = round(
                    float(pair[f"{side}_length_reduction_mm"]) + allowance, 6
                )


def _add_hem_flounces(
    pattern: dict[str, Any], depth_mm: float, source_id: str,
) -> tuple[list[str], float]:
    targets = [piece_id for piece_id in ("front_skirt", "back_skirt") if _has_piece(pattern, piece_id)]
    if len(targets) != 2:
        raise _model_error(
            "MODEL_FLOUNCE_TARGET_REQUIRED",
            "Круговой волан этапа 18 поддержан только для переда и спинки юбки.",
            source_id,
        )
    added: list[str] = []
    for target_id in targets:
        target = _piece(pattern, target_id, source_id)
        contour = contour_from_data(target["seam_contour"])
        hem_id_map = {
            segment.id: f"{segment.id.removesuffix('_hem')}_flounce_join"
            for segment in contour.segments if segment.id.endswith("_hem")
        }
        renamed_contour = Contour(tuple(
            replace(segment, id=hem_id_map[segment.id])
            if segment.id in hem_id_map else segment
            for segment in contour.segments
        ), id=contour.id)
        hem_segments = [
            segment for segment in renamed_contour.segments
            if segment.id in hem_id_map.values()
        ]
        if not hem_segments:
            raise _model_error(
                "MODEL_HEM_EDGE_REQUIRED", "Для волана не найдена линия низа.", source_id
            )
        validate_simple_contour(renamed_contour)
        target["seam_contour"] = contour_to_data(renamed_contour)
        for notch in target["notches"]:
            notch["segment_id"] = hem_id_map.get(notch["segment_id"], notch["segment_id"])
        hem_length = sum(segment.length_mm for segment in hem_segments)
        inner, outer = flounce_radii_mm(hem_length, depth_mm)
        piece_id = f"{target_id}_flounce"
        flounce = Contour((
            ArcSegment.circular(Point(0.0, 0.0), inner, 0.0, math.pi, f"{piece_id}_inner_join"),
            LineSegment(Point(-inner, 0.0), Point(-outer, 0.0), f"{piece_id}_side_left"),
            ArcSegment.circular(Point(0.0, 0.0), outer, math.pi, -math.pi, f"{piece_id}_outer_hem"),
            LineSegment(Point(outer, 0.0), Point(inner, 0.0), f"{piece_id}_side_right"),
        ), id=f"{piece_id}_seam")
        validate_simple_contour(flounce)
        pattern["pieces"].append({
            "id": piece_id,
            "name_ru": f"Волан · {'перед' if target_id == 'front_skirt' else 'спинка'}",
            "cut_quantity": 1,
            "cut_on_fold": False,
            "mirrored_pair": False,
            "seam_contour": contour_to_data(flounce),
            "cutting_contour": None,
            "internal_paths": [],
            "grainline": {"start": [-inner * 0.5, 8.0], "end": [inner * 0.5, 8.0]},
            "notches": [],
            "annotations": [{
                "id": f"{piece_id}_formula",
                "text_ru": f"Полукруговой волан: r={inner:.1f} мм, глубина={depth_mm:.1f} мм.",
                "position": [0.0, outer * 0.55],
            }],
        })
        pattern["seam_pairs"].append({
            "id": f"{target_id}_flounce_join",
            "first_piece_id": target_id,
            "first_segment_ids": [segment.id for segment in hem_segments],
            "second_piece_id": piece_id,
            "second_segment_ids": [f"{piece_id}_inner_join"],
            "first_length_reduction_mm": 0.0,
            "second_length_reduction_mm": 0.0,
            "allowed_ease_mm": 0.0,
            "tolerance_mm": 1.0,
        })
        added.append(piece_id)
    front_id, back_id = added
    for suffix in ("left", "right"):
        pattern["seam_pairs"].append({
            "id": f"flounce_side_{suffix}_join",
            "first_piece_id": front_id,
            "first_segment_ids": [f"{front_id}_side_{suffix}"],
            "second_piece_id": back_id,
            "second_segment_ids": [f"{back_id}_side_{suffix}"],
            "first_length_reduction_mm": 0.0,
            "second_length_reduction_mm": 0.0,
            "allowed_ease_mm": 0.0,
            "tolerance_mm": 1.0,
        })
    return added, abs(_segment_length(_piece(pattern, added[0], source_id), f"{added[0]}_side_left") - depth_mm)


def _resize_waistbands(pattern: dict[str, Any], height_mm: float, source_id: str) -> list[str]:
    height = _bounded(height_mm, 25.0, 100.0, "MODEL_WAISTBAND_WIDTH_OUTSIDE_DOMAIN")
    targets = [piece for piece in pattern["pieces"] if "waistband" in piece["id"]]
    if not targets:
        raise _model_error(
            "MODEL_WAISTBAND_TARGET_REQUIRED", "В комплекте не найдена деталь пояса.", source_id
        )
    for piece in targets:
        contour = contour_from_data(piece["seam_contour"])
        box = contour.bounding_box
        ids = [segment.id for segment in contour.segments]
        if len(ids) != 4:
            raise _model_error(
                "MODEL_WAISTBAND_RECTANGLE_REQUIRED",
                "Регулируемый пояс должен быть прямоугольной деталью.",
                source_id,
            )
        p0 = Point(box.min_x_mm, box.min_y_mm)
        p1 = Point(box.max_x_mm, box.min_y_mm)
        p2 = Point(box.max_x_mm, box.min_y_mm + height)
        p3 = Point(box.min_x_mm, box.min_y_mm + height)
        resized = Contour((
            LineSegment(p0, p1, ids[0]), LineSegment(p1, p2, ids[1]),
            LineSegment(p2, p3, ids[2]), LineSegment(p3, p0, ids[3]),
        ), id=contour.id)
        validate_simple_contour(resized)
        piece["seam_contour"] = contour_to_data(resized)
        piece["grainline"] = {
            "start": [box.min_x_mm + box.width_mm * 0.25, box.min_y_mm + min(8.0, height * 0.25)],
            "end": [box.min_x_mm + box.width_mm * 0.75, box.min_y_mm + min(8.0, height * 0.25)],
        }
    return [piece["id"] for piece in targets]


def _add_belt(pattern: dict[str, Any], width_mm: float, length_mm: float, source_id: str) -> str:
    width = _bounded(width_mm, 15.0, 150.0, "MODEL_BELT_WIDTH_OUTSIDE_DOMAIN")
    length = _bounded(length_mm, 300.0, 2500.0, "MODEL_BELT_LENGTH_OUTSIDE_DOMAIN")
    piece_id = f"{source_id}_belt"
    if _has_piece(pattern, piece_id):
        raise _model_error("MODEL_PIECE_ID_DUPLICATE", "Деталь ремня уже существует.", source_id)
    contour = Contour((
        LineSegment(Point(0.0, 0.0), Point(length, 0.0), f"{piece_id}_lower"),
        LineSegment(Point(length, 0.0), Point(length, width), f"{piece_id}_side"),
        LineSegment(Point(length, width), Point(0.0, width), f"{piece_id}_upper"),
        LineSegment(Point(0.0, width), Point(0.0, 0.0), f"{piece_id}_center"),
    ), id=f"{piece_id}_seam")
    validate_simple_contour(contour)
    pattern["pieces"].append({
        "id": piece_id, "name_ru": "Отдельный прямой ремень", "cut_quantity": 1,
        "cut_on_fold": False, "mirrored_pair": False,
        "seam_contour": contour_to_data(contour), "cutting_contour": None,
        "internal_paths": [],
        "grainline": {"start": [length * 0.2, width / 2.0], "end": [length * 0.8, width / 2.0]},
        "notches": [],
        "annotations": [{
            "id": f"{piece_id}_formula", "text_ru": f"Ремень {length:.1f}×{width:.1f} мм.",
            "position": [length / 2.0, width / 2.0],
        }],
    })
    return piece_id


def _operation(
    source_id: str, kind: str, module_id: str, formula_id: str,
    target_piece_ids: list[str], parameters_mm: dict[str, float], residual: float = 0.0,
) -> dict[str, Any]:
    return {
        "operation_id": f"model_{source_id}_{kind}",
        "source_element_id": source_id,
        "kind": kind,
        "module_id": module_id,
        "formula_id": formula_id,
        "target_piece_ids": target_piece_ids,
        "parameters_mm": {key: round(float(value), 6) for key, value in parameters_mm.items()},
        "invariant_residual_mm": round(float(residual), 9),
    }


def _pair_residual(pattern: Mapping[str, Any]) -> float:
    pieces = {piece["id"]: piece for piece in pattern["pieces"]}
    residuals: list[float] = []
    for pair in pattern["seam_pairs"]:
        first = sum(
            _segment_length(pieces[pair["first_piece_id"]], segment_id)
            for segment_id in pair["first_segment_ids"]
        ) - float(pair["first_length_reduction_mm"])
        second = sum(
            _segment_length(pieces[pair["second_piece_id"]], segment_id)
            for segment_id in pair["second_segment_ids"]
        ) - float(pair["second_length_reduction_mm"])
        residuals.append(abs(abs(first - second) - float(pair["allowed_ease_mm"])))
    return max(residuals, default=0.0)


def _piece(pattern: Mapping[str, Any], piece_id: str, source_id: str) -> dict[str, Any]:
    try:
        return next(piece for piece in pattern["pieces"] if piece["id"] == piece_id)
    except StopIteration as error:
        raise _model_error(
            "MODEL_TARGET_PIECE_MISSING", f"Не найдена целевая деталь «{piece_id}».", source_id
        ) from error


def _has_piece(pattern: Mapping[str, Any], piece_id: str) -> bool:
    return any(piece["id"] == piece_id for piece in pattern["pieces"])


def _segment_length(piece: Mapping[str, Any], segment_id: str) -> float:
    contour = contour_from_data(piece["seam_contour"])
    try:
        return next(segment.length_mm for segment in contour.segments if segment.id == segment_id)
    except StopIteration as error:
        raise BlockConstructionError(
            "MODEL_TARGET_SEGMENT_MISSING", "Не найден целевой участок модельной операции.",
            f"/pattern/pieces/{piece['id']}/seam_contour",
        ) from error


def _required_dimension(dimensions: Mapping[str, Any], key: str, source_id: str) -> float:
    value = dimensions.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _model_error(
            "MODEL_DIMENSION_REQUIRED", f"Для операции нужен размер «{key}» в миллиметрах.",
            source_id,
        )
    return float(value)


def _bounded(value: object, minimum: float, maximum: float, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BlockConstructionError(
            code, "Размер должен быть конечным числом.", "/garment_spec/design_intent"
        )
    number = float(value)
    if not minimum <= number <= maximum:
        raise BlockConstructionError(
            code,
            f"Размер должен находиться от {minimum:g} до {maximum:g} мм.",
            "/garment_spec/design_intent",
        )
    return number


def _model_error(code: str, message: str, source_id: str) -> BlockConstructionError:
    return BlockConstructionError(
        code, message, f"/garment_spec/design_intent/elements/{source_id}"
    )

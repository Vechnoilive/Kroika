"""Cuttable topology transformations introduced at stage 21."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
from typing import Any, Mapping

from .blocks import BlockConstructionError
from .geometry import (
    ArcSegment,
    Contour,
    CubicBezier,
    LineSegment,
    Point,
    contour_from_data,
    contour_to_data,
    validate_simple_contour,
)


STAGE21_TOPOLOGY_MODULES = frozenset({
    "paired_straight_skirt_yoke_v1",
    "paired_equal_skirt_panels_v1",
    "front_waist_to_side_dart_v1",
})
MODULE_ORDER = {
    "front_waist_to_side_dart_v1": 10,
    "paired_straight_skirt_yoke_v1": 20,
    "paired_equal_skirt_panels_v1": 20,
}


@dataclass(frozen=True, slots=True)
class TopologyResult:
    pattern: dict[str, Any]
    applied_count: int
    added_piece_count: int
    maximum_invariant_residual_mm: float


def apply_topology_transformations(
    pattern: Mapping[str, Any], request: Mapping[str, Any],
) -> TopologyResult:
    """Compile reviewed yokes, panels and dart transfer into real geometry."""

    result = deepcopy(dict(pattern))
    original_piece_count = len(result["pieces"])
    operations: list[dict[str, Any]] = []
    intent = request.get("garment_spec", {}).get("design_intent")
    elements = intent.get("elements", []) if isinstance(intent, Mapping) else []
    active = sorted(
        (
            item for item in elements
            if item.get("included") is not False
            and item.get("support_status") == "supported"
            and item.get("module_id") in STAGE21_TOPOLOGY_MODULES
        ),
        key=lambda item: (
            MODULE_ORDER[str(item["module_id"])], str(item["source_element_id"])
        ),
    )

    skirt_topology_seen = False
    for element in active:
        module_id = str(element["module_id"])
        source_id = str(element["source_element_id"])
        dimensions = element.get("dimensions_mm") or {}
        if module_id == "front_waist_to_side_dart_v1":
            transfer = _required_dimension(dimensions, "width", source_id)
            target_ids, residual = _transfer_front_dart(result, transfer, source_id)
            operations.append(_operation(
                source_id, "dart_transfer", module_id, "M21-D01", target_ids,
                {"transferred_intake": transfer}, residual,
            ))
            continue

        if skirt_topology_seen:
            raise _topology_error(
                "TOPOLOGY_SKIRT_TARGET_CONFLICT",
                "Кокетку и панельное членение нельзя одновременно применить к одной юбке.",
                source_id,
            )
        skirt_topology_seen = True
        if module_id == "paired_straight_skirt_yoke_v1":
            depth = _required_dimension(dimensions, "depth", source_id)
            target_ids, residual = _split_skirt_yokes(result, depth, source_id)
            operations.append(_operation(
                source_id, "yoke", module_id, "M21-Y01", target_ids,
                {"depth": depth}, residual,
            ))
        else:
            count = element.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 6:
                raise _topology_error(
                    "TOPOLOGY_PANEL_COUNT_OUTSIDE_DOMAIN",
                    "Для панельной юбки нужно от 2 до 6 панелей на половину переда и спинки.",
                    source_id,
                )
            target_ids, residual = _panelize_skirt(result, count, source_id)
            operations.append(_operation(
                source_id, "panels", module_id, "M21-P01", target_ids, {}, residual,
            ))

    maximum_residual = _pair_residual(result)
    if operations and maximum_residual > 1.0:
        raise BlockConstructionError(
            "TOPOLOGY_INTERFACE_RESIDUAL_EXCEEDED",
            "После топологического преобразования длины парных срезов вышли за допуск 1 мм.",
            "/pattern/seam_pairs",
        )
    result["topology_operations"] = operations
    return TopologyResult(
        result,
        len(operations),
        len(result["pieces"]) - original_piece_count,
        maximum_residual,
    )


def _split_skirt_yokes(
    pattern: dict[str, Any], depth_mm: float, source_id: str,
) -> tuple[list[str], float]:
    depth = _bounded(depth_mm, 60.0, 300.0, "TOPOLOGY_YOKE_DEPTH_OUTSIDE_DOMAIN")
    created: list[str] = []
    side_parts: dict[str, dict[str, list[str] | str]] = {}

    for prefix in ("front", "back"):
        piece_id = f"{prefix}_skirt"
        piece = _piece(pattern, piece_id, source_id)
        contour = contour_from_data(piece["seam_contour"])
        total_length = contour.bounding_box.height_mm
        if depth >= total_length - 80.0:
            raise _topology_error(
                "TOPOLOGY_YOKE_REMAINDER_TOO_SHORT",
                "Под кокеткой должно остаться минимум 80 мм основной детали.",
                source_id,
            )
        split_y = contour.bounding_box.max_y_mm - depth
        center = next(
            (segment for segment in contour.segments if segment.id.endswith("_center")), None
        )
        hem = next(
            (segment for segment in contour.segments if segment.id.endswith("_hem")), None
        )
        waist = next(
            (segment for segment in contour.segments if segment.id.endswith("_waist")), None
        )
        side_segments = [
            segment for segment in contour.segments if "_side_" in segment.id
        ]
        if not isinstance(center, LineSegment) or not isinstance(waist, LineSegment) \
                or hem is None or not side_segments:
            raise _topology_error(
                "TOPOLOGY_SKIRT_CONTOUR_UNSUPPORTED",
                "Кокетка требует базовый контур юбки с центром, талией, низом и боковым срезом.",
                source_id,
            )
        lower_sides, upper_sides, split_point = _split_side_at_y(
            side_segments, split_y, source_id
        )
        waist_pair, skirt_side = _waist_pair(pattern, piece_id, source_id)
        reduction = float(waist_pair[f"{skirt_side}_length_reduction_mm"])
        finished_waist = waist.length_mm - reduction
        if finished_waist <= 40.0:
            raise _topology_error(
                "TOPOLOGY_YOKE_WAIST_DEGENERATE",
                "После поглощения вытачек верх кокетки получился слишком коротким.",
                source_id,
            )
        new_waist_side = Point(waist.start.x_mm - reduction, waist.start.y_mm)
        reshaped_upper = _reshape_upper_side(upper_sides, new_waist_side, source_id)
        split_center = Point(center.start.x_mm, split_y)
        yoke_id = f"{prefix}_skirt_yoke"
        yoke_join_id = f"{yoke_id}_lower_join"
        lower_join_id = f"{piece_id}_yoke_join"
        yoke_side_ids = [segment.id for segment in reshaped_upper]
        lower_side_ids = [segment.id for segment in lower_sides]

        yoke_contour = Contour((
            LineSegment(center.start, split_center, f"{yoke_id}_center"),
            LineSegment(split_center, split_point, yoke_join_id),
            *reshaped_upper,
            LineSegment(new_waist_side, center.start, f"{yoke_id}_waist"),
        ), id=f"{yoke_id}_seam")
        lower_contour = Contour((
            LineSegment(split_center, center.end, center.id),
            hem,
            *lower_sides,
            LineSegment(split_point, split_center, lower_join_id),
        ), id=contour.id)
        validate_simple_contour(yoke_contour)
        validate_simple_contour(lower_contour)

        yoke_piece = {
            "id": yoke_id,
            "name_ru": f"Прямая кокетка · {'перед' if prefix == 'front' else 'спинка'}",
            "cut_quantity": piece["cut_quantity"],
            "cut_on_fold": piece["cut_on_fold"],
            "mirrored_pair": piece["mirrored_pair"],
            "seam_contour": contour_to_data(yoke_contour),
            "cutting_contour": None,
            "internal_paths": [],
            "grainline": {
                "start": [finished_waist * 0.45, split_y + depth * 0.2],
                "end": [finished_waist * 0.45, split_y + depth * 0.8],
            },
            "notches": [],
            "annotations": [{
                "id": f"{yoke_id}_formula",
                "text_ru": (
                    f"Кокетка глубиной {depth:.1f} мм; талиевые вытачки поглощены "
                    "модельным швом."
                ),
                "position": [finished_waist * 0.5, split_y + depth * 0.5],
            }],
        }
        lower_piece = deepcopy(piece)
        lower_piece["seam_contour"] = contour_to_data(lower_contour)
        lower_piece["cutting_contour"] = None
        lower_piece["internal_paths"] = [
            path for path in piece["internal_paths"]
            if _path_below(path, split_y)
        ]
        lower_piece["notches"] = []
        lower_piece["grainline"] = {
            "start": [max(10.0, split_point.x_mm * 0.45), split_y - 20.0],
            "end": [max(10.0, split_point.x_mm * 0.45), contour.bounding_box.min_y_mm + 20.0],
        }
        lower_piece["annotations"] = [{
            "id": f"{piece_id}_below_yoke",
            "text_ru": f"Нижняя часть под кокеткой {source_id}.",
            "position": [split_point.x_mm * 0.5, (split_y + contour.bounding_box.min_y_mm) / 2],
        }]
        index = pattern["pieces"].index(piece)
        pattern["pieces"][index:index + 1] = [yoke_piece, lower_piece]

        waist_pair[f"{skirt_side}_piece_id"] = yoke_id
        waist_pair[f"{skirt_side}_segment_ids"] = [f"{yoke_id}_waist"]
        waist_pair[f"{skirt_side}_length_reduction_mm"] = 0.0
        pattern["seam_pairs"].append({
            "id": f"{prefix}_skirt_yoke_join",
            "first_piece_id": yoke_id,
            "first_segment_ids": [yoke_join_id],
            "second_piece_id": piece_id,
            "second_segment_ids": [lower_join_id],
            "first_length_reduction_mm": 0.0,
            "second_length_reduction_mm": 0.0,
            "allowed_ease_mm": 0.0,
            "tolerance_mm": 1.0,
        })
        side_parts[prefix] = {
            "yoke_piece": yoke_id,
            "yoke_segments": yoke_side_ids,
            "lower_piece": piece_id,
            "lower_segments": lower_side_ids,
        }
        created.extend([yoke_id, piece_id])

    _replace_skirt_side_pair(pattern, side_parts, source_id)
    return created, _pair_residual(pattern)


def _panelize_skirt(
    pattern: dict[str, Any], panel_count: int, source_id: str,
) -> tuple[list[str], float]:
    created: list[str] = []
    outer: dict[str, tuple[str, str]] = {}
    replacement_targets: dict[str, list[str]] = {}
    original_side_pair = next(
        (pair for pair in pattern["seam_pairs"] if pair["id"] == "skirt_side_join"), None
    )
    if original_side_pair is None:
        raise _topology_error(
            "TOPOLOGY_SKIRT_SIDE_PAIR_REQUIRED",
            "Для панельного членения не найдена пара боковых швов юбки.",
            source_id,
        )

    for prefix in ("front", "back"):
        piece_id = f"{prefix}_skirt"
        piece = _piece(pattern, piece_id, source_id)
        contour = contour_from_data(piece["seam_contour"])
        waist = next(
            (segment for segment in contour.segments if segment.id.endswith("_waist")), None
        )
        hem = next(
            (segment for segment in contour.segments if segment.id.endswith("_hem")), None
        )
        if not isinstance(waist, LineSegment) or not isinstance(hem, LineSegment):
            raise _topology_error(
                "TOPOLOGY_PANEL_CONTOUR_UNSUPPORTED",
                "Панели требуют прямые линии талии и низа базовой юбки.",
                source_id,
            )
        waist_pair, skirt_side = _waist_pair(pattern, piece_id, source_id)
        other_side = "second" if skirt_side == "first" else "first"
        other_piece = _piece(
            pattern, str(waist_pair[f"{other_side}_piece_id"]), source_id
        )
        other_segment_ids = list(waist_pair[f"{other_side}_segment_ids"])
        if len(other_segment_ids) != 1:
            raise _topology_error(
                "TOPOLOGY_PANEL_WAIST_INTERFACE_UNSUPPORTED",
                "Панельное членение требует один прямой сопрягаемый участок талии.",
                source_id,
            )
        split_ids = _split_piece_line(other_piece, other_segment_ids[0], panel_count, source_id)
        skirt_reduction = float(waist_pair[f"{skirt_side}_length_reduction_mm"])
        other_reduction = float(waist_pair[f"{other_side}_length_reduction_mm"])
        finished_waist = waist.length_mm - skirt_reduction
        top_width = finished_waist / panel_count
        bottom_width = hem.length_mm / panel_count
        length = contour.bounding_box.height_mm
        if min(top_width, bottom_width) <= 20.0:
            raise _topology_error(
                "TOPOLOGY_PANEL_WIDTH_TOO_SMALL",
                "Одна из панелей получилась уже 20 мм.",
                source_id,
            )
        new_pieces: list[dict[str, Any]] = []
        for index in range(panel_count):
            number = index + 1
            panel_id = f"{prefix}_skirt_panel_{number}"
            left_id = (
                f"{panel_id}_center" if index == 0
                else f"{panel_id}_panel_join_left"
            )
            right_id = (
                f"{panel_id}_side_outer" if index == panel_count - 1
                else f"{panel_id}_panel_join_right"
            )
            p0 = Point(index * top_width, 0.0)
            p1 = Point(index * bottom_width, -length)
            p2 = Point((index + 1) * bottom_width, -length)
            p3 = Point((index + 1) * top_width, 0.0)
            panel_contour = Contour((
                LineSegment(p0, p1, left_id),
                LineSegment(p1, p2, f"{panel_id}_hem"),
                LineSegment(p2, p3, right_id),
                LineSegment(p3, p0, f"{panel_id}_waist"),
            ), id=f"{panel_id}_seam")
            validate_simple_contour(panel_contour)
            cut_on_fold = bool(piece["cut_on_fold"] and index == 0)
            new_pieces.append({
                "id": panel_id,
                "name_ru": (
                    f"Панель {number}/{panel_count} · "
                    f"{'перед' if prefix == 'front' else 'спинка'}"
                ),
                "cut_quantity": 1 if cut_on_fold else 2,
                "cut_on_fold": cut_on_fold,
                "mirrored_pair": not cut_on_fold,
                "seam_contour": contour_to_data(panel_contour),
                "cutting_contour": None,
                "internal_paths": [
                    _panel_hip_path(
                        panel_id, top_width, bottom_width, length, index
                    )
                ],
                "grainline": {
                    "start": [(p0.x_mm + p3.x_mm) * 0.5, -20.0],
                    "end": [(p1.x_mm + p2.x_mm) * 0.5, -length + 20.0],
                },
                "notches": [],
                "annotations": [{
                    "id": f"{panel_id}_formula",
                    "text_ru": (
                        f"Равная панель {number}/{panel_count}; талиевые вытачки "
                        "поглощены вертикальными швами."
                    ),
                    "position": [
                        (p0.x_mm + p1.x_mm + p2.x_mm + p3.x_mm) * 0.25,
                        -length * 0.5,
                    ],
                }],
            })
            created.append(panel_id)

        piece_index = pattern["pieces"].index(piece)
        pattern["pieces"][piece_index:piece_index + 1] = new_pieces
        replacement_targets[piece_id] = [panel["id"] for panel in new_pieces]
        pair_index = pattern["seam_pairs"].index(waist_pair)
        replacement_pairs: list[dict[str, Any]] = []
        for index, (panel, other_segment_id) in enumerate(
            zip(new_pieces, split_ids, strict=True)
        ):
            panel_side = skirt_side
            counterpart_side = other_side
            pair = {
                "id": f"{prefix}_waist_panel_join_{index + 1}",
                f"{panel_side}_piece_id": panel["id"],
                f"{panel_side}_segment_ids": [f"{panel['id']}_waist"],
                f"{panel_side}_length_reduction_mm": 0.0,
                f"{counterpart_side}_piece_id": other_piece["id"],
                f"{counterpart_side}_segment_ids": [other_segment_id],
                f"{counterpart_side}_length_reduction_mm": round(
                    other_reduction / panel_count, 9
                ),
                "allowed_ease_mm": 0.0,
                "tolerance_mm": 1.0,
            }
            replacement_pairs.append(pair)
        pattern["seam_pairs"][pair_index:pair_index + 1] = replacement_pairs

        for index in range(panel_count - 1):
            left = new_pieces[index]
            right = new_pieces[index + 1]
            pattern["seam_pairs"].append({
                "id": f"{prefix}_panel_join_{index + 1}",
                "first_piece_id": left["id"],
                "first_segment_ids": [f"{left['id']}_panel_join_right"],
                "second_piece_id": right["id"],
                "second_segment_ids": [f"{right['id']}_panel_join_left"],
                "first_length_reduction_mm": 0.0,
                "second_length_reduction_mm": 0.0,
                "allowed_ease_mm": 0.0,
                "tolerance_mm": 1.0,
            })
        outer[prefix] = (
            new_pieces[-1]["id"], f"{new_pieces[-1]['id']}_side_outer"
        )

    pattern["seam_pairs"].remove(original_side_pair)
    front_piece, front_segment = outer["front"]
    back_piece, back_segment = outer["back"]
    front_length = _segment_length(_piece(pattern, front_piece, source_id), front_segment)
    back_length = _segment_length(_piece(pattern, back_piece, source_id), back_segment)
    pattern["seam_pairs"].append({
        "id": "skirt_side_join",
        "first_piece_id": front_piece,
        "first_segment_ids": [front_segment],
        "second_piece_id": back_piece,
        "second_segment_ids": [back_segment],
        "first_length_reduction_mm": 0.0,
        "second_length_reduction_mm": 0.0,
        "allowed_ease_mm": round(abs(front_length - back_length), 9),
        "tolerance_mm": 1.0,
    })
    for operation in pattern.get("modeling_operations", []):
        targets: list[str] = []
        for piece_id in operation.get("target_piece_ids", []):
            targets.extend(replacement_targets.get(piece_id, [piece_id]))
        operation["target_piece_ids"] = sorted(set(targets))
    return created, _pair_residual(pattern)


def _transfer_front_dart(
    pattern: dict[str, Any], transfer_mm: float, source_id: str,
) -> tuple[list[str], float]:
    transfer = _bounded(
        transfer_mm, 1.0, 30.0, "TOPOLOGY_DART_TRANSFER_OUTSIDE_DOMAIN"
    )
    piece = _piece(pattern, "front_bodice", source_id)
    contour = contour_from_data(piece["seam_contour"])
    waist = next((item for item in contour.segments if item.id == "front_waist"), None)
    side = next((item for item in contour.segments if item.id == "front_side"), None)
    if not isinstance(waist, LineSegment) or not isinstance(side, CubicBezier):
        raise _topology_error(
            "TOPOLOGY_DART_CONTOUR_UNSUPPORTED",
            "Перенос вытачки требует базовые прямую талию и кривую бокового среза переда.",
            source_id,
        )
    waist_path = next(
        (path for path in piece["internal_paths"] if path["id"] == "front_waist_dart"), None
    )
    side_path = next(
        (path for path in piece["internal_paths"] if path["id"] == "front_side_dart"), None
    )
    if waist_path is None or side_path is None:
        raise _topology_error(
            "TOPOLOGY_SOURCE_DART_REQUIRED",
            "На переде не найдены исходные талиевая и боковая вытачки.",
            source_id,
        )
    waist_pair, waist_pair_side = _pair_for_segment(
        pattern, "front_bodice", "front_waist", source_id
    )
    side_pair, side_pair_side = _pair_for_segment(
        pattern, "front_bodice", "front_side", source_id
    )
    source_intake = float(waist_pair[f"{waist_pair_side}_length_reduction_mm"])
    old_side_intake = float(side_pair[f"{side_pair_side}_length_reduction_mm"])
    if transfer >= source_intake - 1.0:
        raise _topology_error(
            "TOPOLOGY_DART_RETAINED_INTAKE_TOO_SMALL",
            "После переноса в талиевой вытачке должен остаться минимум 1 мм раствора.",
            source_id,
        )

    new_waist_end = Point(waist.end.x_mm - transfer, waist.end.y_mm)
    new_waist = LineSegment(waist.start, new_waist_end, waist.id)
    shifted_side = CubicBezier(
        new_waist_end,
        Point(side.control_1.x_mm - transfer, side.control_1.y_mm),
        side.control_2,
        side.end,
        side.id,
    )
    new_side = _lengthen_side_curve(shifted_side, side.length_mm + transfer, source_id)
    segments = tuple(
        new_waist if item.id == waist.id else new_side if item.id == side.id else item
        for item in contour.segments
    )
    new_contour = Contour(segments, id=contour.id)
    validate_simple_contour(new_contour)
    piece["seam_contour"] = contour_to_data(new_contour)

    waist_geometry = contour_from_data(waist_path)
    waist_legs = waist_geometry.segments
    waist_center = (
        waist_legs[0].start.x_mm + waist_legs[-1].end.x_mm
    ) / 2.0
    retained = source_intake - transfer
    waist_apex = waist_legs[0].end
    retained_path = Contour((
        LineSegment(
            Point(waist_center - retained / 2.0, waist.start.y_mm),
            waist_apex,
            waist_legs[0].id,
        ),
        LineSegment(
            waist_apex,
            Point(waist_center + retained / 2.0, waist.start.y_mm),
            waist_legs[-1].id,
        ),
    ), closed=False, id=waist_geometry.id)

    old_side_geometry = contour_from_data(side_path)
    first_start = old_side_geometry.segments[0].start
    second_start = old_side_geometry.segments[-1].end
    first_t = _nearest_parameter(side, first_start)
    second_t = _nearest_parameter(side, second_start)
    center_length = (
        _partial_curve_length(side, first_t) + _partial_curve_length(side, second_t)
    ) / 2.0
    center_fraction = center_length / side.length_mm
    new_center_length = center_fraction * new_side.length_mm
    new_intake = old_side_intake + transfer
    first_length = new_center_length - new_intake / 2.0
    second_length = new_center_length + new_intake / 2.0
    if first_length <= 1.0 or second_length >= new_side.length_mm - 1.0:
        raise _topology_error(
            "TOPOLOGY_DART_OPENING_OUTSIDE_EDGE",
            "Новый раствор боковой вытачки не помещается на боковом срезе.",
            source_id,
        )
    first_point = new_side.point_at(_parameter_at_length(new_side, first_length))
    second_point = new_side.point_at(_parameter_at_length(new_side, second_length))
    side_apex = old_side_geometry.segments[0].end
    transferred_path = Contour((
        LineSegment(first_point, side_apex, old_side_geometry.segments[0].id),
        LineSegment(side_apex, second_point, old_side_geometry.segments[-1].id),
    ), closed=False, id=old_side_geometry.id)
    piece["internal_paths"] = [
        contour_to_data(retained_path) if path["id"] == "front_waist_dart"
        else contour_to_data(transferred_path) if path["id"] == "front_side_dart"
        else path
        for path in piece["internal_paths"]
    ]
    piece["annotations"].append({
        "id": f"{source_id}_dart_transfer",
        "text_ru": (
            f"Перенесено {transfer:.1f} мм раствора из талиевой вытачки в боковую."
        ),
        "position": [side_apex.x_mm, side_apex.y_mm + 25.0],
    })
    waist_pair[f"{waist_pair_side}_length_reduction_mm"] = round(retained, 9)
    side_pair[f"{side_pair_side}_length_reduction_mm"] = round(new_intake, 9)
    return [piece["id"]], _pair_residual(pattern)


def _split_side_at_y(
    segments: list[Any], split_y: float, source_id: str,
) -> tuple[list[Any], list[Any], Point]:
    lower: list[Any] = []
    upper: list[Any] = []
    split_point: Point | None = None
    for segment in segments:
        low = min(segment.start.y_mm, segment.end.y_mm)
        high = max(segment.start.y_mm, segment.end.y_mm)
        if high < split_y - 1e-7:
            lower.append(segment)
        elif low > split_y + 1e-7:
            upper.append(segment)
        elif split_point is None:
            first, second = _split_curve_at_y(segment, split_y, source_id)
            lower.append(first)
            upper.append(second)
            split_point = first.end
        else:
            raise _topology_error(
                "TOPOLOGY_YOKE_SIDE_NOT_MONOTONIC",
                "Боковой срез пересекает линию кокетки больше одного раза.",
                source_id,
            )
    if split_point is None or not lower or not upper:
        raise _topology_error(
            "TOPOLOGY_YOKE_SPLIT_MISSING",
            "Линия кокетки не пересекла боковой срез внутри детали.",
            source_id,
        )
    return lower, upper, split_point


def _split_curve_at_y(curve: Any, y_mm: float, source_id: str) -> tuple[Any, Any]:
    start_y, end_y = curve.start.y_mm, curve.end.y_mm
    if (start_y - y_mm) * (end_y - y_mm) >= 0:
        raise _topology_error(
            "TOPOLOGY_YOKE_SPLIT_AMBIGUOUS",
            "Линия кокетки должна пересекать боковой сегмент строго внутри.",
            source_id,
        )
    low, high = 0.0, 1.0
    increasing = end_y > start_y
    for _ in range(70):
        middle = (low + high) / 2.0
        value = curve.point_at(middle).y_mm
        if (value < y_mm) == increasing:
            low = middle
        else:
            high = middle
    parameter = (low + high) / 2.0
    if isinstance(curve, CubicBezier):
        first, second = curve.split(parameter)
        return replace(first, id=f"{curve.id}_below_yoke"), replace(
            second, id=f"{curve.id}_in_yoke"
        )
    if isinstance(curve, LineSegment):
        point = curve.point_at(parameter)
        return (
            LineSegment(curve.start, point, f"{curve.id}_below_yoke"),
            LineSegment(point, curve.end, f"{curve.id}_in_yoke"),
        )
    if isinstance(curve, ArcSegment):
        sweep = curve.sweep_angle_rad
        arc_first = ArcSegment(
            curve.center, curve.radius_x_mm, curve.radius_y_mm, curve.rotation_rad,
            curve.start_angle_rad, sweep * parameter, f"{curve.id}_below_yoke",
        )
        arc_second = ArcSegment(
            curve.center, curve.radius_x_mm, curve.radius_y_mm, curve.rotation_rad,
            curve.start_angle_rad + sweep * parameter, sweep * (1.0 - parameter),
            f"{curve.id}_in_yoke",
        )
        return arc_first, arc_second
    raise _topology_error(
        "TOPOLOGY_YOKE_CURVE_UNSUPPORTED",
        "Тип боковой кривой не поддерживается для кокетки.",
        source_id,
    )


def _reshape_upper_side(
    segments: list[Any], new_end: Point, source_id: str,
) -> list[Any]:
    result = list(segments)
    last = result[-1]
    delta_x = new_end.x_mm - last.end.x_mm
    if isinstance(last, CubicBezier):
        result[-1] = CubicBezier(
            last.start,
            last.control_1,
            Point(last.control_2.x_mm + delta_x, last.control_2.y_mm),
            new_end,
            last.id,
        )
    elif isinstance(last, LineSegment):
        result[-1] = LineSegment(last.start, new_end, last.id)
    else:
        raise _topology_error(
            "TOPOLOGY_YOKE_RESHAPE_UNSUPPORTED",
            "Верх бокового среза нельзя безопасно совместить с кокеткой.",
            source_id,
        )
    return result


def _replace_skirt_side_pair(
    pattern: dict[str, Any], parts: Mapping[str, Mapping[str, Any]], source_id: str,
) -> None:
    pair = next(
        (item for item in pattern["seam_pairs"] if item["id"] == "skirt_side_join"), None
    )
    if pair is None:
        raise _topology_error(
            "TOPOLOGY_SKIRT_SIDE_PAIR_REQUIRED",
            "Для кокетки не найдена исходная пара боковых швов юбки.",
            source_id,
        )
    index = pattern["seam_pairs"].index(pair)
    replacements = []
    for kind in ("yoke", "lower"):
        first_piece = str(parts["front"][f"{kind}_piece"])
        second_piece = str(parts["back"][f"{kind}_piece"])
        first_segments = list(parts["front"][f"{kind}_segments"])
        second_segments = list(parts["back"][f"{kind}_segments"])
        first_length = sum(
            _segment_length(_piece(pattern, first_piece, source_id), item)
            for item in first_segments
        )
        second_length = sum(
            _segment_length(_piece(pattern, second_piece, source_id), item)
            for item in second_segments
        )
        replacements.append({
            "id": f"skirt_{kind}_side_join",
            "first_piece_id": first_piece,
            "first_segment_ids": first_segments,
            "second_piece_id": second_piece,
            "second_segment_ids": second_segments,
            "first_length_reduction_mm": 0.0,
            "second_length_reduction_mm": 0.0,
            "allowed_ease_mm": round(abs(first_length - second_length), 9),
            "tolerance_mm": 1.0,
        })
    pattern["seam_pairs"][index:index + 1] = replacements


def _split_piece_line(
    piece: dict[str, Any], segment_id: str, count: int, source_id: str,
) -> list[str]:
    contour = contour_from_data(piece["seam_contour"])
    target = next((item for item in contour.segments if item.id == segment_id), None)
    if not isinstance(target, LineSegment):
        raise _topology_error(
            "TOPOLOGY_PANEL_COUNTERPART_NOT_LINE",
            "Сопрягаемый талиевый срез должен быть прямым отрезком.",
            source_id,
        )
    ids = [f"{segment_id}_panel_{index + 1}" for index in range(count)]
    replacements = tuple(
        LineSegment(target.point_at(index / count), target.point_at((index + 1) / count), ids[index])
        for index in range(count)
    )
    segments: list[Any] = []
    for item in contour.segments:
        segments.extend(replacements if item.id == segment_id else (item,))
    new_contour = Contour(tuple(segments), id=contour.id)
    validate_simple_contour(new_contour)
    piece["seam_contour"] = contour_to_data(new_contour)
    piece["cutting_contour"] = None
    piece["notches"] = [
        notch for notch in piece["notches"] if notch["segment_id"] != segment_id
    ]
    return ids


def _panel_hip_path(
    panel_id: str, top_width: float, bottom_width: float, length: float,
    index: int,
) -> dict[str, Any]:
    depth = min(200.0, length * 0.45)
    left = index * (top_width + (bottom_width - top_width) * depth / length)
    right = (index + 1) * (
        top_width + (bottom_width - top_width) * depth / length
    )
    path = Contour((LineSegment(
        Point(left, -depth), Point(right, -depth), f"{panel_id}_hip_line_segment"
    ),), closed=False, id=f"{panel_id}_hip_line")
    return contour_to_data(path)


def _lengthen_side_curve(
    curve: CubicBezier, target_length: float, source_id: str,
) -> CubicBezier:
    if curve.length_mm >= target_length:
        return curve

    def candidate(offset: float) -> CubicBezier:
        return CubicBezier(
            curve.start,
            Point(curve.control_1.x_mm + offset, curve.control_1.y_mm),
            Point(curve.control_2.x_mm + offset, curve.control_2.y_mm),
            curve.end,
            curve.id,
        )

    low, high = 0.0, 20.0
    while candidate(high).length_mm < target_length and high < 1000.0:
        high *= 2.0
    if high >= 1000.0 and candidate(high).length_mm < target_length:
        raise _topology_error(
            "TOPOLOGY_DART_SIDE_LENGTH_UNSOLVED",
            "Не удалось восстановить длину бокового среза после переноса вытачки.",
            source_id,
        )
    for _ in range(60):
        middle = (low + high) / 2.0
        if candidate(middle).length_mm < target_length:
            low = middle
        else:
            high = middle
    return candidate((low + high) / 2.0)


def _partial_curve_length(curve: CubicBezier, parameter: float) -> float:
    if parameter <= 0.0:
        return 0.0
    if parameter >= 1.0:
        return curve.length_mm
    return curve.split(parameter)[0].length_mm


def _parameter_at_length(curve: CubicBezier, length_mm: float) -> float:
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2.0
        if _partial_curve_length(curve, middle) < length_mm:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _nearest_parameter(curve: CubicBezier, point: Point) -> float:
    samples = curve.flatten(flatness_mm=0.05)
    return min(samples, key=lambda item: item[1].distance_to(point))[0]


def _path_below(path: Mapping[str, Any], split_y: float) -> bool:
    contour = contour_from_data(path)
    return max(
        max(segment.start.y_mm, segment.end.y_mm) for segment in contour.segments
    ) <= split_y + 1e-7


def _waist_pair(
    pattern: Mapping[str, Any], piece_id: str, source_id: str,
) -> tuple[dict[str, Any], str]:
    for pair in pattern["seam_pairs"]:
        for side in ("first", "second"):
            if pair[f"{side}_piece_id"] == piece_id and any(
                segment_id.endswith("_waist")
                for segment_id in pair[f"{side}_segment_ids"]
            ):
                return pair, side
    raise _topology_error(
        "TOPOLOGY_WAIST_PAIR_REQUIRED",
        f"Для детали «{piece_id}» не найден сопрягаемый талиевый срез.",
        source_id,
    )


def _pair_for_segment(
    pattern: Mapping[str, Any], piece_id: str, segment_id: str, source_id: str,
) -> tuple[dict[str, Any], str]:
    for pair in pattern["seam_pairs"]:
        for side in ("first", "second"):
            if pair[f"{side}_piece_id"] == piece_id \
                    and segment_id in pair[f"{side}_segment_ids"]:
                return pair, side
    raise _topology_error(
        "TOPOLOGY_INTERFACE_REQUIRED",
        f"Для участка «{segment_id}» не найдена пара швов.",
        source_id,
    )


def _operation(
    source_id: str, kind: str, module_id: str, formula_id: str,
    target_piece_ids: list[str], parameters_mm: dict[str, float], residual: float,
) -> dict[str, Any]:
    return {
        "operation_id": f"topology_{source_id}_{kind}",
        "source_element_id": source_id,
        "kind": kind,
        "module_id": module_id,
        "formula_id": formula_id,
        "target_piece_ids": sorted(set(target_piece_ids)),
        "parameters_mm": {
            key: round(float(value), 6) for key, value in parameters_mm.items()
        },
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
        raise _topology_error(
            "TOPOLOGY_TARGET_PIECE_MISSING",
            f"Не найдена целевая деталь «{piece_id}».",
            source_id,
        ) from error


def _segment_length(piece: Mapping[str, Any], segment_id: str) -> float:
    contour = contour_from_data(piece["seam_contour"])
    try:
        return next(segment.length_mm for segment in contour.segments if segment.id == segment_id)
    except StopIteration as error:
        raise BlockConstructionError(
            "TOPOLOGY_TARGET_SEGMENT_MISSING",
            "Не найден целевой участок топологической операции.",
            f"/pattern/pieces/{piece['id']}/seam_contour",
        ) from error


def _required_dimension(dimensions: Mapping[str, Any], key: str, source_id: str) -> float:
    value = dimensions.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _topology_error(
            "TOPOLOGY_DIMENSION_REQUIRED",
            f"Для операции нужен размер «{key}» в миллиметрах.",
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


def _topology_error(code: str, message: str, source_id: str) -> BlockConstructionError:
    return BlockConstructionError(
        code, message, f"/garment_spec/design_intent/elements/{source_id}"
    )

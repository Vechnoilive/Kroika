"""Placed fullness and attachment geometry for the second catalogue expansion.

Slashes split the original curves exactly; translations and the inserted strips
are explicit. Joining lengths retain their pre-fold/pre-gather effective value.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
from typing import Any, Mapping

from kroika_contracts.design_modules import FULLNESS_MODULES
from .composites import _operation, _pair_residual, _seam_pair
from .details import (
    _error,
    _find,
    _new_piece,
    _path,
    _quantity,
    _rectangle,
    _reduction,
    _rename_edges,
    _edges,
    _inside,
    _crosses,
    finish_edge_joins,
)
from .geometry import (
    AffineTransform,
    ArcSegment,
    Contour,
    LineSegment,
    Point,
    contour_from_data,
    contour_to_data,
    curve_points,
    validate_simple_contour,
    intersections,
    line_line_intersections,
    OverlappingGeometryError,
)

SIDE_RU = {"both": "обе стороны", "left": "левую сторону", "right": "правую сторону"}
EDGE_RU = {"hem": "низ", "neckline": "горловина", "waist": "талия", "shoulder": "плечо"}
LOCATION_RU = {"skirt_front": "переда юбки", "skirt_back": "спинки юбки"}

FOUNDATION_MODULES = {
    "placed_skirt_pleats_v2",
    "placed_skirt_tucks_v2",
    "placed_skirt_gathers_v2",
    "integrated_bodice_drape_v2",
    "integrated_bodice_gather_v2",
}
TIER_MODULES = {"tiered_hem_ruffle_v2", "tiered_hem_flounce_v2"}


def active(request: Mapping[str, Any]) -> list[dict]:
    return sorted(
        [
            item
            for item in (request["garment_spec"].get("design_intent") or {}).get("elements", [])
            if item.get("included") is not False
            and item.get("support_status") == "supported"
            and item.get("module_id") in FULLNESS_MODULES
        ],
        key=lambda item: (item["module_id"], item["source_element_id"]),
    )


def _target_id(location: str) -> str:
    return {
        "skirt_front": "front_skirt",
        "skirt_back": "back_skirt",
        "bodice_front": "front_bodice",
        "bodice_back": "back_bodice",
        "sleeve": "base_sleeve",
    }[location]


def _subcurve(edge, start: float, end: float):
    if isinstance(edge, LineSegment):
        return LineSegment(edge.point_at(start), edge.point_at(end), edge.id)
    if isinstance(edge, ArcSegment):
        return replace(
            edge,
            start_angle_rad=edge.start_angle_rad + edge.sweep_angle_rad * start,
            sweep_angle_rad=edge.sweep_angle_rad * (end - start),
        )
    part = edge if end >= 1 - 1e-12 else edge.split(end)[0]
    return part if start <= 1e-12 else part.split(start / end)[1]


def _roots(edge, x: float) -> list[float]:
    samples = curve_points(edge, 0.02)
    roots = []
    for (a, pa), (b, pb) in zip(samples, samples[1:]):
        if (pa.x_mm < x) == (pb.x_mm < x):
            continue
        lo, hi = a, b
        increasing = pb.x_mm > pa.x_mm
        for _ in range(50):
            mid = (lo + hi) / 2
            if (edge.point_at(mid).x_mm < x) == increasing:
                lo = mid
            else:
                hi = mid
        t = (lo + hi) / 2
        if 1e-8 < t < 1 - 1e-8 and all(abs(t - old) > 1e-7 for old in roots):
            roots.append(t)
    return roots


def _vertical_range(contour: Contour, x: float, source: str) -> tuple[float, float]:
    values = [edge.point_at(t).y_mm for edge in contour.segments for t in _roots(edge, x)]
    if len(values) != 2:
        raise _error(
            "Линия раскрытия должна пересекать контур ровно дважды. Измените отступ.",
            source,
            "FULLNESS_SLASH_OUTSIDE",
        )
    return min(values), max(values)


def _shift_x(x: float, slashes: list[dict]) -> float:
    return x + sum(slash["addition"] for slash in slashes if x > slash["x"] + 1e-7)


def _spread_path(path: Mapping[str, Any], slashes: list[dict], source: str):
    contour = contour_from_data(path)
    expanded, spans, mapping = [], {}, {}
    for edge in contour.segments:
        cuts = sorted({t for slash in slashes for t in _roots(edge, slash["x"])})
        intervals = list(zip([0.0] + cuts, cuts + [1.0]))
        pieces = []
        for index, (start, end) in enumerate(intervals):
            middle = edge.point_at((start + end) / 2).x_mm
            shift = sum(s["addition"] for s in slashes if middle > s["x"])
            suffix = next(
                (
                    word
                    for word in ("waist", "neckline", "hem", "armhole", "shoulder")
                    if edge.id.endswith("_" + word)
                ),
                "part",
            )
            sid = edge.id if index == 0 else f"{source}_{edge.id}_split_{index}_{suffix}"
            segment = replace(
                _subcurve(edge, start, end).transformed(AffineTransform.translation(shift, 0)),
                id=sid,
            )
            pieces.append(segment)
            # Distances are measured on the source curve, not its t parameter.
            spans[sid] = (
                edge.id,
                _subcurve(edge, 0, start).length_mm if start else 0.0,
                segment.length_mm,
            )
            if index < len(intervals) - 1:
                next_middle = edge.point_at(sum(intervals[index + 1]) / 2).x_mm
                next_shift = sum(s["addition"] for s in slashes if next_middle > s["x"])
                endpoint = edge.point_at(end)
                bridge = LineSegment(
                    segment.end,
                    Point(endpoint.x_mm + next_shift, endpoint.y_mm),
                    f"{source}_{edge.id}_bridge_{index}_{suffix}",
                )
                pieces.append(bridge)
        mapping[edge.id] = [s.id for s in pieces]
        expanded.extend(pieces)
    result = Contour(tuple(expanded), closed=contour.closed, id=contour.id)
    if contour.closed:
        validate_simple_contour(result)
    return contour_to_data(result), mapping, spans


def _reject_dart_slash(piece: dict, x: float, source: str):
    for path in piece["internal_paths"]:
        if "dart" not in path["id"]:
            continue
        box = contour_from_data(path).bounding_box
        if box.min_x_mm - 0.1 <= x <= box.max_x_mm + 0.1:
            raise _error(
                "Раскрытие пересекает раствор вытачки. Измените отступ или интервал.",
                source,
                "FULLNESS_DART_CONFLICT",
            )


def apply_fullness_foundation(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    result = deepcopy(dict(pattern))
    selected = [item for item in active(request) if item["module_id"] in FOUNDATION_MODULES]
    groups: dict[str, list[dict]] = {}
    for item in selected:
        groups.setdefault(_target_id(item["location"]), []).append(item)
    for pid, items in sorted(groups.items()):
        piece = _find(result, pid)
        original = contour_from_data(piece["seam_contour"])
        legacy = sum(
            op["parameters_mm"].get("added_width", 0)
            for op in result.get("modeling_operations", [])
            if pid in op["target_piece_ids"] and op["kind"] in {"tuck", "gather", "pleat"}
        )
        slashes = []
        for item in items:
            dimensions, source = item["dimensions_mm"], item["source_element_id"]
            number = item["count"] // 2
            factor = {"knife": 2, "box": 4, "inverted": 4, "accordion": 2}.get(item["variant"], 1)
            if item["type"] == "tuck":
                factor = 2
            addition = dimensions["depth"] * factor
            for index in range(number):
                x = legacy + dimensions["width"] + index * dimensions["spacing"]
                if any(abs(edge.start.x_mm - x) < 0.1 for edge in original.segments):
                    raise _error(
                        "Линия раскрытия попадает в угол контура. Измените отступ.",
                        source,
                        "FULLNESS_VERTEX_CONFLICT",
                    )
                _reject_dart_slash(piece, x, source)
                lower, upper = _vertical_range(original, x, source)
                length = dimensions.get("length") or min(upper - lower - 20, 250)
                if not 30 <= length <= upper - lower - 20:
                    raise _error(
                        "Контрольная линия не помещается по высоте детали; оставьте минимум 2 см до нижнего среза.",
                        source,
                        "FULLNESS_MARK_LENGTH_OUTSIDE",
                    )
                slashes.append(
                    dict(
                        x=x,
                        addition=addition,
                        item=item,
                        index=index,
                        lower=lower,
                        upper=upper,
                        length=length,
                    )
                )
        slashes.sort(key=lambda entry: entry["x"])
        for left, right in zip(slashes, slashes[1:]):
            if right["x"] - left["x"] < 5:
                raise _error(
                    "Зоны раскрытия совпадают или расположены ближе 5 мм. Измените размещение.",
                    right["item"]["source_element_id"],
                    "FULLNESS_ZONE_CONFLICT",
                )
        old_paths = deepcopy(piece["internal_paths"])
        new_contour, mapping, spans = _spread_path(
            piece["seam_contour"], slashes, f"fullness_{pid}"
        )
        piece["seam_contour"] = new_contour
        piece["internal_paths"] = [
            _spread_path(path, slashes, f"fullness_{pid}")[0] for path in old_paths
        ]
        segments = {edge.id: edge for edge in contour_from_data(new_contour).segments}
        for pair in result["seam_pairs"]:
            for side in ("first", "second"):
                if pair[f"{side}_piece_id"] != pid:
                    continue
                old_ids = pair[f"{side}_segment_ids"]
                new_ids = [new for sid in old_ids for new in mapping.get(sid, [sid])]
                extra = sum(
                    segments[sid].length_mm
                    for sid in new_ids
                    if sid in segments and "_bridge_" in sid
                )
                pair[f"{side}_segment_ids"] = new_ids
                pair[f"{side}_length_reduction_mm"] += extra
        for notch in piece["notches"]:
            sid, distance = notch["segment_id"], notch["distance_from_start_mm"]
            if sid not in mapping:
                continue
            candidates = [
                new
                for new in mapping[sid]
                if new in spans
                and spans[new][1] - 1e-6 <= distance <= spans[new][1] + spans[new][2] + 1e-6
            ]
            if not candidates:
                raise _error(
                    "Не удалось перенести надсечку через раскрытие.",
                    pid,
                    "FULLNESS_NOTCH_TRANSFER_FAILED",
                )
            notch["segment_id"] = candidates[0]
            notch["distance_from_start_mm"] = max(0, distance - spans[candidates[0]][1])
        for key in ("start", "end"):
            piece["grainline"][key][0] = _shift_x(piece["grainline"][key][0], slashes)
        for note in piece["annotations"]:
            note["position"][0] = _shift_x(note["position"][0], slashes)
        for operation in result.get("modeling_operations", []):
            if pid in operation["target_piece_ids"] and operation["kind"] == "decorative_seam":
                operation["parameters_mm"]["center_spacing"] = _shift_x(
                    operation["parameters_mm"]["center_spacing"], slashes
                )
        for item in items:
            source, marks, parameters = item["source_element_id"], [], {}
            for slash in [entry for entry in slashes if entry["item"] is item]:
                i, amount = slash["index"], slash["addition"]
                x = slash["x"] + sum(s["addition"] for s in slashes if s["x"] < slash["x"])
                fractions = (
                    [0, 0.5, 1]
                    if item["type"] == "tuck"
                    else [0, 0.25, 0.5, 0.75, 1]
                    if item["variant"] in {"box", "inverted"}
                    else [0, 0.5, 1]
                )
                for j, fraction in enumerate(fractions):
                    path_id = f"{source}_fullness_{i}_{j}"
                    line = LineSegment(
                        Point(x + amount * fraction, slash["upper"]),
                        Point(x + amount * fraction, slash["upper"] - slash["length"]),
                        f"{path_id}_line",
                    )
                    piece["internal_paths"].append(_path(path_id, [line]))
                    marks.append(path_id)
                    parameters[f"mark_{i}_{j}_x"] = line.start.x_mm
                    parameters[f"mark_{i}_{j}_y"] = line.start.y_mm
                    parameters[f"mark_{i}_{j}_length"] = line.length_mm
                parameters[f"addition_{i}"] = amount
            parameters["full_garment_count"] = item["count"]
            op = dict(
                operation_id=f"fullness_{source}",
                source_element_id=source,
                kind=item["type"],
                module_id=item["module_id"],
                formula_id="F02-S01",
                target_piece_ids=[pid],
                parameters_mm=parameters,
                invariant_residual_mm=0.0,
            )
            result.setdefault("modeling_operations", []).append(op)
            piece["annotations"].append(
                dict(
                    id=f"{source}_fullness_note",
                    position=[parameters["mark_0_1_x"], parameters["mark_0_1_y"] - 15],
                    text_ru=f"{item['description_ru']} Всего {item['count']}; на этой половине {item['count'] // 2}. Добавленный раствор закрыть по контрольным линиям; длины соединений указаны после закрытия.",
                )
            )
    if _pair_residual(result) > 1:
        raise _error(
            "Раскрытие нарушило эффективные длины соединений.", "elements", "FULLNESS_JOIN_MISMATCH"
        )
    return result


def _record(pattern, item, kind, targets, added, interfaces, parameters):
    parameters = {
        **parameters,
        "side_code": {"left": -1, "right": 1, "both": 0}[
            (item.get("placement") or {}).get("side", "both")
        ],
    }
    op = _operation(
        item["source_element_id"],
        "element",
        kind,
        item["module_id"],
        "F02-A01",
        targets,
        added,
        interfaces,
        parameters,
        0.0,
    )
    op["operation_id"] = f"fullness_{item['source_element_id']}"
    pattern.setdefault("composite_operations", []).append(op)


def _annular_piece(pid, name, seam, depth, quantity, angle=180, end_depth=None, *, request=None):
    theta = math.radians(angle)
    radius = seam / theta
    if (
        request is not None
        and radius
        <= (2 if angle > 180 else 1) * request["fit_settings"]["seam_allowances_mm"]["normal"]
    ):
        raise _error(
            "Внутренний радиус волана слишком мал для заданных припусков. Увеличьте длину крепления, уменьшите угол сектора или припуск обычного шва.",
            pid,
            "FULLNESS_SECTOR_ALLOWANCE_CONFLICT",
        )
    start_angle = (math.pi - theta) / 2
    end_angle = start_angle + theta
    inner = ArcSegment.circular(Point(0, 0), radius, start_angle, theta, f"{pid}_join")
    far = radius + (depth if end_depth is None else end_depth)
    outer_end = Point(far * math.cos(end_angle), far * math.sin(end_angle))
    outer_start = Point(
        (radius + depth) * math.cos(start_angle), (radius + depth) * math.sin(start_angle)
    )
    if end_depth is None or abs(end_depth - depth) < 1e-8:
        outer = [ArcSegment.circular(Point(0, 0), radius + depth, end_angle, -theta, f"{pid}_hem")]
    else:
        # Variable-depth polar boundary: each segment remains outside the exact joining arc.
        points = [
            Point(
                (radius + depth + (end_depth - depth) * t) * math.cos(start_angle + theta * t),
                (radius + depth + (end_depth - depth) * t) * math.sin(start_angle + theta * t),
            )
            for t in [i / 64 for i in range(65)]
        ]
        outer = [
            LineSegment(a, b, f"{pid}_{i}_hem")
            for i, (a, b) in enumerate(zip(reversed(points), reversed(points[:-1])))
        ]
    contour = Contour(
        (
            inner,
            LineSegment(inner.end, outer_end, f"{pid}_end_left"),
            *outer,
            LineSegment(outer_start, inner.start, f"{pid}_end_right"),
        ),
        id=f"{pid}_seam",
    )
    validate_simple_contour(contour)
    piece = _new_piece(pid, name, contour, quantity)
    middle_depth = (depth + (end_depth if end_depth is not None else depth)) / 2
    piece["grainline"] = dict(
        start=[-middle_depth / 5, radius + middle_depth / 2],
        end=[middle_depth / 5, radius + middle_depth / 2],
    )
    piece["annotations"][0]["position"] = [0, radius + middle_depth / 2]
    return piece


def _hem_depth(request, depth, source):
    if depth < request["fit_settings"]["seam_allowances_mm"]["hem"] + 10:
        raise _error(
            "Глубина отделки должна превышать припуск на низ минимум на 1 см.",
            source,
            "FULLNESS_HEM_ALLOWANCE_TOO_DEEP",
        )


def _slice_distance(edges, offset, length, source):
    result, consumed = [], 0.0
    for edge in edges:
        start, end = max(0, offset - consumed), min(edge.length_mm, offset + length - consumed)
        if end > start + 1e-7:

            def parameter(distance):
                if distance <= 0:
                    return 0.0
                if distance >= edge.length_mm:
                    return 1.0
                lo, hi = 0.0, 1.0
                for _ in range(45):
                    mid = (lo + hi) / 2
                    if _subcurve(edge, 0, mid).length_mm < distance:
                        lo = mid
                    else:
                        hi = mid
                return (lo + hi) / 2

            result.append(
                replace(
                    _subcurve(edge, parameter(start), parameter(end)),
                    id=f"{source}_anchor_segment_{len(result)}",
                )
            )
        consumed += edge.length_mm
    if abs(sum(edge.length_mm for edge in result) - length) > 0.05:
        raise _error(
            "Участок крепления выходит за выбранный срез. Уменьшите длину или начальный отступ.",
            source,
            "FULLNESS_EDGE_INTERVAL_OUTSIDE",
        )
    return result


def _edge_for(target, edge_name, source):
    suffix = "hem" if target["id"] == "base_sleeve" and edge_name == "hem" else "_" + edge_name
    edges = [
        edge
        for edge in contour_from_data(target["seam_contour"]).segments
        if edge.id.endswith(suffix)
    ]
    if not edges:
        raise _error(
            "Выбранный срез отсутствует либо уже занят отделкой.", source, "FULLNESS_EDGE_MISSING"
        )
    return edges


def _default_edge(location):
    return "neckline" if location.startswith("bodice") else "hem"


def _attach(pattern, target, edges, panel, source, reduction=0, target_reduction=0):
    path_id = f"{source}_anchor"
    target["internal_paths"].append(_path(path_id, edges))
    pair = _seam_pair(
        f"{source}_attachment",
        target["id"],
        [edge.id for edge in edges],
        panel["id"],
        [f"{panel['id']}_join"],
    )
    pair["first_length_reduction_mm"] = target_reduction
    pair["second_length_reduction_mm"] = reduction
    pattern["seam_pairs"].append(pair)
    return [path_id, pair["id"]]


def _local_edge(pattern, item, request):
    source, dims = item["source_element_id"], item["dimensions_mm"]
    placement = item.get("placement") or {}
    target = _find(pattern, _target_id(item["location"]))
    edge_name = placement.get("edge", _default_edge(item["location"]))
    edges = _edge_for(target, edge_name, source)
    selected = _slice_distance(edges, dims["spacing"], dims["length"], source)
    _hem_depth(request, dims["depth"], source)
    quantity = item["count"]
    addition = dims["width"] if item["type"] == "ruffle" else 0
    pid = f"{source}_detail"
    panel = (
        _rectangle(
            pid,
            "Локальная сборчатая оборка",
            dims["length"] + addition,
            dims["depth"],
            quantity,
            hem=True,
        )
        if addition
        else _annular_piece(
            pid,
            "Локальный волан",
            dims["length"],
            dims["depth"],
            quantity,
            placement.get("sweep_angle_deg", 180),
            request=request,
        )
    )
    panel["annotations"][0]["text_ru"] += (
        f" Притачать на {SIDE_RU[placement.get('side', 'both')]}; срез {EDGE_RU[edge_name]}. Сборка: {dims['length'] + addition:g} → {dims['length']:g} мм."
    )
    pattern["pieces"].append(panel)
    interfaces = _attach(pattern, target, selected, panel, source, addition)
    _record(
        pattern,
        item,
        item["type"],
        [target["id"]],
        [pid],
        interfaces,
        dict(
            **{k: v for k, v in dims.items() if v is not None},
            sweep_angle_deg=placement.get("sweep_angle_deg", 180),
        ),
    )


def _peplum(pattern, item, request):
    source, dims = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, _target_id(item["location"]))
    edges = _edge_for(target, "waist", source)
    reduction = _reduction(pattern, target["id"], [edge.id for edge in edges])
    seam = sum(edge.length_mm for edge in edges) - reduction
    _hem_depth(request, min(dims["depth"], dims["length"]), source)
    pid = f"{source}_peplum"
    panel = _annular_piece(
        pid,
        "Асимметричная баска",
        seam,
        dims["depth"],
        1,
        (item.get("placement") or {}).get("sweep_angle_deg", 180),
        dims["length"],
        request=request,
    )
    panel["annotations"][0]["text_ru"] += (
        f" Разместить только на {SIDE_RU[(item.get('placement') or {})['side']]} {LOCATION_RU[item['location']]}."
    )
    pattern["pieces"].append(panel)
    copied = [replace(edge, id=f"{source}_anchor_segment_{i}") for i, edge in enumerate(edges)]
    interfaces = _attach(pattern, target, copied, panel, source, target_reduction=reduction)
    _record(
        pattern,
        item,
        "peplum",
        [target["id"]],
        [pid],
        interfaces,
        dict(depth=dims["depth"], end_depth=dims["length"], joining_length=seam),
    )


def _cascade(pattern, item, request):
    source, dims = item["source_element_id"], item["dimensions_mm"]
    placement = item.get("placement") or {}
    target = _find(pattern, _target_id(item["location"]))
    _hem_depth(request, dims["depth"], source)
    top = contour_from_data(target["seam_contour"]).bounding_box.max_y_mm - placement.get(
        "offset_mm", 0
    )
    line = LineSegment(
        Point(dims["spacing"], top),
        Point(dims["spacing"], top - dims["length"]),
        f"{source}_cascade_anchor_segment",
    )
    pid = f"{source}_cascade"
    panel = _annular_piece(
        pid,
        "Каскадный волан",
        dims["length"],
        dims["depth"],
        item["count"],
        placement.get("sweep_angle_deg", 180),
        request=request,
    )
    pattern["pieces"].append(panel)
    interfaces = _attach(pattern, target, [line], panel, source)
    panel["annotations"][0]["text_ru"] += (
        f" Сторона: {SIDE_RU[placement.get('side', 'both')]}; начало ниже талии на {placement.get('offset_mm', 0):g} мм."
    )
    _record(
        pattern,
        item,
        "cascade",
        [target["id"]],
        [pid],
        interfaces,
        dict(
            depth=dims["depth"],
            length=dims["length"],
            spacing=dims["spacing"],
            start_offset=placement.get("offset_mm", 0),
        ),
    )


def _drape_panel(pattern, item):
    from .advanced import _anchor

    source, dims, placement = (
        item["source_element_id"],
        item["dimensions_mm"],
        item.get("placement") or {},
    )
    target = _find(pattern, _target_id(item["location"]))
    contour = contour_from_data(target["seam_contour"])
    polygon = [p for edge in contour.segments for _, p in curve_points(edge, 0.05)[:-1]]
    upper_y = contour.bounding_box.max_y_mm - 40 - placement.get("offset_mm", 0)
    lower_y = 20.0

    def outside_x(y):
        xs = [
            a.x_mm + (y - a.y_mm) * (b.x_mm - a.x_mm) / (b.y_mm - a.y_mm)
            for a, b in zip(polygon, polygon[1:] + polygon[:1])
            if (a.y_mm > y) != (b.y_mm > y)
        ]
        return max(xs, default=0) - dims["spacing"] - dims["width"]

    upper_x, lower_x = outside_x(upper_y), outside_x(lower_y)
    if min(upper_x, lower_x) < 5 or upper_y - lower_y < 60:
        raise _error(
            "Драпировка не помещается на лифе. Уменьшите ширину, отступ или смещение начала.",
            source,
            "FULLNESS_DRAPE_OUTSIDE",
        )
    full = contour.bounding_box.min_x_mm < -1
    diagonal = item["module_id"] == "diagonal_bodice_drape_v2"
    if diagonal and not full:
        raise _error(
            "Диагональная драпировка требует полного переда без центральной застёжки.",
            source,
            "FULLNESS_DIAGONAL_FOUNDATION_REQUIRED",
        )
    sign = -1 if placement.get("side") == "left" and full else 1
    upper = LineSegment(
        Point(sign * upper_x, upper_y),
        Point(sign * (upper_x + dims["width"]), upper_y),
        f"{source}_upper_anchor_segment",
    )
    lower_sign = -sign if diagonal else sign
    lower = LineSegment(
        Point(lower_sign * lower_x, lower_y),
        Point(lower_sign * (lower_x + dims["width"]), lower_y),
        f"{source}_lower_anchor_segment",
    )
    length = upper.point_at(0.5).distance_to(lower.point_at(0.5)) + (
        dims.get("length") or dims["depth"] / 2
    )
    pid = f"{source}_drape"
    panel = _rectangle(
        pid,
        "Диагональная драпировка" if diagonal else "Вертикальная драпировка",
        length,
        dims["width"] + dims["depth"],
        item["count"],
    )
    panel["grainline"] = dict(
        start=[length / 4, (dims["width"] + dims["depth"]) / 2],
        end=[3 * length / 4, (dims["width"] + dims["depth"]) / 2],
    )
    for index in range(1, 4):
        y = (dims["width"] + dims["depth"]) * index / 4
        panel["internal_paths"].append(
            _path(
                f"{pid}_fold_{index}",
                [LineSegment(Point(0, y), Point(length, y), f"{pid}_fold_{index}_line")],
            )
        )
    panel["annotations"][0]["text_ru"] = (
        f"Собрать оба конца с {dims['width'] + dims['depth']:g} до {dims['width']:g} мм. Пролёт {length:.1f} мм; {SIDE_RU[placement.get('side', 'both')]}."
    )
    pattern["pieces"].append(panel)
    interfaces = [
        _anchor(
            pattern,
            target,
            f"{source}_upper_anchor",
            upper,
            panel,
            f"{pid}_end_left",
            dims["depth"],
        ),
        _anchor(
            pattern,
            target,
            f"{source}_lower_anchor",
            lower,
            panel,
            f"{pid}_end_right",
            dims["depth"],
        ),
    ]
    if full and item["count"] == 2:
        for name, line, end in [("upper", upper, "left"), ("lower", lower, "right")]:
            mirrored = LineSegment(
                Point(-line.start.x_mm, line.start.y_mm),
                Point(-line.end.x_mm, line.end.y_mm),
                f"{source}_{name}_mirror_anchor_segment",
            )
            interface = _anchor(
                pattern,
                target,
                f"{source}_{name}_mirror_anchor",
                mirrored,
                panel,
                f"{pid}_end_{end}",
                dims["depth"],
            )
            next(pair for pair in pattern["seam_pairs"] if pair["id"] == interface)[
                "second_instance"
            ] = "mirror"
            interfaces.append(interface)
    _record(
        pattern,
        item,
        "drape",
        [target["id"]],
        [pid],
        interfaces,
        dict(
            width=dims["width"],
            depth=dims["depth"],
            panel_length=length,
            spacing=dims["spacing"],
            start_offset=placement.get("offset_mm", 0),
        ),
    )


def _tiers(pattern, item, request):
    source, dims = item["source_element_id"], item["dimensions_mm"]
    _hem_depth(request, dims["depth"], source)
    records = _edges(pattern, "hem", source)
    if not all("skirt" in target["id"] for target, _ in records):
        raise _error(
            "Ярусы этого модуля требуют юбочную основу.", source, "FULLNESS_TIER_TARGET_REQUIRED"
        )
    targets = [target["id"] for target, _ in records]
    added, interfaces = [], []
    circular = item["type"] == "flounce"
    for tier in range(item["count"]):
        next_records = []
        finishing_records = []
        for target, edges in records:
            edge_reduction = _reduction(pattern, target["id"], [e.id for e in edges])
            seam = sum(e.length_mm for e in edges) - edge_reduction
            edges = _rename_edges(pattern, target, edges, f"{source}_tier_{tier}")
            pid = (
                f"{source}_tier_{tier + 1}_{target['id']}"
                if tier == 0
                else f"{source}_tier_{tier + 1}_{'overlay_' if target['id'].startswith('overlay_') else ''}{'front' if 'front' in target['id'] else 'back'}_skirt"
            )
            addition = 0 if circular else dims["width"]
            panel = (
                _annular_piece(
                    pid,
                    f"Волан · ярус {tier + 1}",
                    seam,
                    dims["depth"],
                    target["cut_quantity"] if tier else _quantity(target),
                    (item.get("placement") or {}).get("sweep_angle_deg", 180),
                    request=request,
                )
                if circular
                else _rectangle(
                    pid,
                    f"Оборка · ярус {tier + 1}",
                    seam + addition,
                    dims["depth"],
                    target["cut_quantity"] if tier else _quantity(target),
                    hem=True,
                )
            )
            panel["annotations"][0]["text_ru"] += (
                f" Ярус {tier + 1}/{item['count']}; собрать {seam + addition:.1f} до {seam:.1f} мм."
            )
            pattern["pieces"].append(panel)
            pair = _seam_pair(
                f"{pid}_attachment", target["id"], [e.id for e in edges], pid, [f"{pid}_join"]
            )
            pair.update(
                first_length_reduction_mm=edge_reduction, second_length_reduction_mm=addition
            )
            pattern["seam_pairs"].append(pair)
            interfaces.append(pair["id"])
            added.append(pid)
            finishing_records.append((target, panel, edges))
            next_records.append(
                (
                    panel,
                    [
                        e
                        for e in contour_from_data(panel["seam_contour"]).segments
                        if e.id.endswith("_hem")
                    ],
                )
            )
        interfaces += finish_edge_joins(
            pattern, finishing_records, request, "hem", circular, f"{source}_tier_{tier + 1}"
        )
        records = next_records
    _record(
        pattern,
        item,
        item["type"],
        targets,
        added,
        interfaces,
        dict(
            tiers=item["count"],
            tier_depth=dims["depth"],
            total_added_length=item["count"] * dims["depth"],
            gather_addition=dims.get("width") or 0,
            sweep_angle_deg=(item.get("placement") or {}).get("sweep_angle_deg", 180),
        ),
    )


def prepare_fullness_foundation(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    from .advanced import _unfold_front

    result = deepcopy(dict(pattern))
    if any(item["module_id"] == "diagonal_bodice_drape_v2" for item in active(request)):
        target = _find(result, "front_bodice")
        if target["cut_on_fold"]:
            _unfold_front(result)
            target["annotations"][0]["text_ru"] = (
                "Полный перед для диагональной драпировки; кроить одну деталь без сгиба."
            )
        elif contour_from_data(target["seam_contour"]).bounding_box.min_x_mm >= 0:
            raise _error(
                "Для диагональной драпировки нужен перед без центральной застёжки.",
                "elements",
                "FULLNESS_DIAGONAL_FOUNDATION_REQUIRED",
            )
    return result


def apply_fullness_details(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    result = deepcopy(dict(pattern))
    for item in active(request):
        module = item["module_id"]
        if module in FOUNDATION_MODULES:
            continue
        if module in TIER_MODULES:
            _tiers(result, item, request)
        elif module in {"separate_bodice_drape_v2", "diagonal_bodice_drape_v2"}:
            _drape_panel(result, item)
        elif module == "placed_cascade_flounce_v2":
            _cascade(result, item, request)
        elif module == "asymmetric_waist_peplum_v2":
            _peplum(result, item, request)
        else:
            _local_edge(result, item, request)
    validate_fullness_placements(result)
    residual = _pair_residual(result)
    if residual > 1:
        raise _error(
            "Соединения отделки вышли за допуск 1 мм.", "elements", "FULLNESS_JOIN_MISMATCH"
        )
    return result


def _check_line(target, line, source, boundary=False, allow_darts=False):
    contour = contour_from_data(target["seam_contour"])
    polygon = [point for edge in contour.segments for _, point in curve_points(edge, 0.03)[:-1]]

    def on_boundary(point):
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            direction = b - a
            t = max(0.0, min(1.0, (point - a).dot(direction) / direction.dot(direction)))
            if point.distance_to(a + direction.scaled(t)) <= 0.05:
                return True
        return False

    def inside(point):
        return _inside(point, polygon) or (boundary and on_boundary(point))

    # Exact subcurves share the source boundary, while independent flattenings
    # can produce tiny artificial crossings. Boundary coincidence is valid.
    follows_boundary = boundary and all(on_boundary(line.point_at(i / 40)) for i in range(41))
    if not all(inside(line.point_at(i / 40)) for i in range(41)):
        raise _error(
            "Контрольная линия или крепление вышли за контур детали.",
            source,
            "FULLNESS_ANCHOR_OUTSIDE",
        )
    for edge in () if follows_boundary else contour.segments:
        try:
            hits = intersections(line, edge, flatness_mm=0.03)
        except OverlappingGeometryError:
            if boundary:
                continue
            raise _error("Крепление совпало со срезом детали.", source, "FULLNESS_ANCHOR_OUTSIDE")
        if any(
            hit.kind == "crossing"
            and hit.point.distance_to(line.start) > 0.03
            and hit.point.distance_to(line.end) > 0.03
            for hit in hits
        ):
            raise _error("Крепление пересекает срез детали.", source, "FULLNESS_ANCHOR_OUTSIDE")
    if not allow_darts:
        for path in target["internal_paths"]:
            if "dart" not in path["id"]:
                continue
            dart = contour_from_data(path)
            points = [e.start for e in dart.segments] + [dart.segments[-1].end]
            if any(_inside(line.point_at(i / 40), points) for i in range(1, 40)) or any(
                _crosses(LineSegment(a, b), e)
                for (_, a), (_, b) in zip(curve_points(line, 0.03), curve_points(line, 0.03)[1:])
                for e in dart.segments
                if isinstance(e, LineSegment)
            ):
                raise _error(
                    "Крепление пересекает раствор вытачки. Измените размещение.",
                    source,
                    "FULLNESS_ANCHOR_DART_CONFLICT",
                )


def validate_fullness_placements(pattern: Mapping[str, Any]) -> None:
    anchors_by_piece = {}
    for operation in pattern.get("modeling_operations", []):
        if operation["module_id"] not in FOUNDATION_MODULES:
            continue
        source, params = operation["source_element_id"], operation["parameters_mm"]
        target = _find(pattern, operation["target_piece_ids"][0])
        expected = [
            key.removeprefix("mark_").removesuffix("_x")
            for key in params
            if key.startswith("mark_") and key.endswith("_x")
        ]
        for suffix in expected:
            path = next(
                (
                    path
                    for path in target["internal_paths"]
                    if path["id"] == f"{source}_fullness_{suffix}"
                ),
                None,
            )
            if path is None:
                raise _error(
                    "Обязательная контрольная линия отсутствует на лекале.",
                    source,
                    "FULLNESS_MARK_MISSING",
                )
            edges = contour_from_data(path).segments
            if len(edges) != 1 or not isinstance(edges[0], LineSegment):
                raise _error(
                    "Контрольная линия раскрытия повреждена.", source, "FULLNESS_MARK_CHANGED"
                )
            line = edges[0]
            if (
                line.start.distance_to(
                    Point(params[f"mark_{suffix}_x"], params[f"mark_{suffix}_y"])
                )
                > 0.01
                or line.end.distance_to(
                    Point(
                        params[f"mark_{suffix}_x"],
                        params[f"mark_{suffix}_y"] - params[f"mark_{suffix}_length"],
                    )
                )
                > 0.01
            ):
                raise _error(
                    "Контрольная линия не соответствует размещению и размерам.",
                    source,
                    "FULLNESS_MARK_CHANGED",
                )
            _check_line(target, line, source, boundary=True)
    for operation in pattern.get("composite_operations", []):
        if operation["module_id"] not in FULLNESS_MODULES:
            continue
        source = operation["source_id"]
        for pid in operation["target_piece_ids"]:
            target = _find(pattern, pid)
            paths = [
                path
                for path in target["internal_paths"]
                if path["id"].startswith(source + "_") and "anchor" in path["id"]
            ]
            if not paths and operation["module_id"] not in TIER_MODULES:
                raise _error(
                    "Обязательное крепление отсутствует.", source, "FULLNESS_ANCHOR_MISSING"
                )
            for path in paths:
                edges = contour_from_data(path).segments
                anchors_by_piece.setdefault(pid, []).append(
                    (source, operation["parameters_mm"].get("side_code", 0), edges)
                )
                for edge in edges:
                    _check_line(
                        target,
                        edge,
                        source,
                        boundary=True,
                        allow_darts=operation["kind"] == "peplum",
                    )

    for placed in anchors_by_piece.values():
        for index, (source, side, edges) in enumerate(placed):
            for other_source, other_side, other_edges in placed[index + 1 :]:
                if source == other_source or side * other_side == -1:
                    continue
                for edge in edges:
                    points = curve_points(edge, 0.03)
                    for other in other_edges:
                        other_points = curve_points(other, 0.03)
                        for (_, a), (_, b) in zip(points, points[1:]):
                            for (_, c), (_, d) in zip(other_points, other_points[1:]):
                                try:
                                    conflict = any(
                                        hit.kind == "crossing"
                                        for hit in line_line_intersections(
                                            LineSegment(a, b), LineSegment(c, d)
                                        )
                                    )
                                except OverlappingGeometryError:
                                    conflict = True
                                if conflict:
                                    raise _error(
                                        "Крепления отделки пересекаются. Измените отступ, срез или сторону.",
                                        other_source,
                                        "FULLNESS_ATTACHMENT_CONFLICT",
                                    )

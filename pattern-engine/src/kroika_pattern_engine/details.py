"""Parametric separate details, explicit attachment seams and placement proofs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
from typing import Any, Mapping

from kroika_contracts.design_modules import DETAIL_ELEMENT_MODULES, DETAIL_LAYER_MODULES
from .blocks import BlockConstructionError
from .composites import (
    CompositeResult,
    _clone_piece,
    _operation,
    _pair_residual,
    _piece_data,
    _seam_pair,
    _interface_residual,
)
from .geometry import (
    ArcSegment,
    Contour,
    LineSegment,
    Point,
    GeometryError,
    contour_from_data,
    contour_to_data,
)
from .geometry.primitives import curve_points
from .geometry.intersections import line_line_intersections
from .attachments import boundary_records, terminal_records
from .placements import placement_frame, containing_piece, distribute_placement, validate_placement_operations


def _error(
    message: str, source: str, code: str = "DETAIL_GEOMETRY_INVALID"
) -> BlockConstructionError:
    return BlockConstructionError(code, message, f"/garment_spec/design_intent/{source}")


def _rectangle(
    pid: str,
    name: str,
    length: float,
    depth: float,
    quantity: int = 1,
    *,
    hem: bool = False,
) -> dict[str, Any]:
    points = [Point(0, 0), Point(length, 0), Point(length, depth), Point(0, depth)]
    ids = ["join", "end_right", "hem" if hem else "upper", "end_left"]
    contour = Contour(
        tuple(LineSegment(points[i], points[(i + 1) % 4], f"{pid}_{ids[i]}") for i in range(4)),
        id=f"{pid}_seam",
    )
    return _new_piece(pid, name, contour, quantity)


def _new_piece(pid: str, name: str, contour: Contour, quantity: int) -> dict[str, Any]:
    result = _piece_data(
        pid, name, contour, cut_quantity=quantity, cut_on_fold=False, mirrored_pair=quantity == 2
    )
    result["annotations"][0]["text_ru"] = f"{name}; количество кроя: {quantity}."
    return result


def _path(pid: str, segments: list, closed: bool = False) -> dict[str, Any]:
    return contour_to_data(Contour(tuple(segments), id=pid, closed=closed))


def _find(pattern: Mapping[str, Any], pid: str) -> dict[str, Any]:
    target = next((piece for piece in pattern["pieces"] if piece["id"] == pid), None)
    if target is None:
        raise _error("Не найдена основа для дополнительной детали.", pid, "DETAIL_TARGET_MISSING")
    return target


def _quantity(target: Mapping[str, Any]) -> int:
    return target["cut_quantity"] * (2 if target["cut_on_fold"] else 1)


def _edges(pattern: Mapping[str, Any], location: str, source: str) -> list[tuple[dict, list]]:
    ids = {piece["id"] for piece in pattern["pieces"]}
    if location == "sleeve":
        targets, suffix = ["base_sleeve"], "_sleeve_hem"
    elif location == "neckline":
        targets, suffix = ["front_bodice", "back_bodice"], "_neckline"
    elif location == "waist":
        targets, suffix = ["front_skirt", "back_skirt"], "_waist"
    else:
        targets = (
            ["front_skirt", "back_skirt"]
            if any(pid.startswith("front_skirt") for pid in ids)
            else ["front_bodice", "back_bodice"]
        )
        suffix = "_hem"
    targets += [f"overlay_{pid}" for pid in list(targets) if f"overlay_{pid}" in ids]
    result = []
    for pid in targets:
        resolve = terminal_records if location == 'hem' else boundary_records
        result.extend(resolve(pattern, pid, suffix.rsplit('_', 1)[-1], source))
    return result


def _reduction(pattern: Mapping[str, Any], pid: str, edge_ids: list[str]) -> float:
    values = set()
    for pair in pattern["seam_pairs"]:
        for side in ["first", "second"]:
            if pair[f"{side}_piece_id"] == pid and set(pair[f"{side}_segment_ids"]) == set(
                edge_ids
            ):
                values.add(float(pair[f"{side}_length_reduction_mm"]))
    if len(values) > 1:
        raise _error("Неоднозначный раствор вытачек на срезе присоединения.", pid)
    return next(iter(values), 0.0)


def _rename_edges(pattern: dict[str, Any], target: dict, edges: list, source: str) -> list:
    mapping = {seg.id: f"{seg.id}_{source}_join" for seg in edges}
    contour = contour_from_data(target["seam_contour"])
    changed = [replace(seg, id=mapping.get(seg.id, seg.id)) for seg in contour.segments]
    target["seam_contour"] = contour_to_data(Contour(tuple(changed), id=contour.id))
    from .attachments import rename_boundary_references
    rename_boundary_references(pattern, target, mapping)
    return [seg for seg in changed if seg.id in mapping.values()]


def _inside(point: Point, polygon: list[Point]) -> bool:
    crossings = 0
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a.y_mm > point.y_mm) != (b.y_mm > point.y_mm):
            x = a.x_mm + (point.y_mm - a.y_mm) * (b.x_mm - a.x_mm) / (b.y_mm - a.y_mm)
            if x > point.x_mm:
                crossings += 1
    return crossings % 2 == 1


def _crosses(first: LineSegment, second: LineSegment) -> bool:
    try:
        return bool(line_line_intersections(first, second))
    except GeometryError:
        return True


def _check_placement(target: Mapping[str, Any], placement: Mapping[str, Any], source: str) -> None:
    contour = contour_from_data(target["seam_contour"])
    polygon = [p for seg in contour.segments for _, p in curve_points(seg, 0.05)[:-1]]
    shape = contour_from_data(placement)
    shape_lines = [edge for edge in shape.segments if isinstance(edge, LineSegment)]
    if len(shape_lines) != len(shape.segments):
        raise _error("Контур накладной детали должен быть прямоугольным.", source)
    if not all(_inside(seg.start, polygon) for seg in shape.segments):
        raise _error(
            "Карман или панель выходит за контур детали. Уменьшите размеры или отступ.",
            source,
            "DETAIL_PLACEMENT_OUTSIDE",
        )
    boundaries = [LineSegment(a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1])]
    if any(_crosses(edge, border) for edge in shape_lines for border in boundaries):
        raise _error(
            "Накладная деталь пересекает границу лекала.", source, "DETAIL_PLACEMENT_OUTSIDE"
        )
    for path in target["internal_paths"]:
        if "dart" not in path["id"]:
            continue
        if any(
            _inside(seg.start, [s.start for s in shape.segments])
            or _inside(seg.end, [s.start for s in shape.segments])
            or any(
                _crosses(line, edge)
                for edge in shape_lines
                for (_, a), (_, b) in zip(curve_points(seg)[:-1], curve_points(seg)[1:])
                if a.distance_to(b) > 1e-6
                for line in [LineSegment(a, b)]
            )
            for seg in contour_from_data(path).segments
        ):
            raise _error(
                "Накладная деталь пересекает вытачку. Измените размеры или отступ.",
                source,
                "DETAIL_PLACEMENT_DART_CONFLICT",
            )


def apply_detail_transformations(
    pattern: Mapping[str, Any], request: Mapping[str, Any]
) -> CompositeResult:
    result = deepcopy(dict(pattern))
    before_pieces, before_pairs = len(result["pieces"]), len(result["seam_pairs"])
    intent = request["garment_spec"].get("design_intent") or {}
    operations: list[dict[str, Any]] = []
    occupied = set()
    active = [
        (group, item)
        for group, modules in [
            ("elements", DETAIL_ELEMENT_MODULES),
            ("layers", DETAIL_LAYER_MODULES),
        ]
        for item in intent.get(group, [])
        if item.get("included") is not False
        and item.get("support_status") == "supported"
        and item.get("module_id") in modules
    ]
    for group, item in sorted(
        active,
        key=lambda entry: (
            0 if entry[0] == "layers" else 1,
            active.index(entry),
            entry[1].get("source_element_id", entry[1].get("source_layer_id")),
        ),
    ):
        source = item.get("source_element_id", item.get("source_layer_id"))
        module = item["module_id"]
        dimensions = item.get("dimensions_mm") or {}
        parameters = {key: val for key, val in dimensions.items() if val is not None}
        targets, added, interfaces = [], [], []
        kind = "overlay"
        if group == "layers":
            candidates = (
                ["base_sleeve"]
                if item["coverage"] == "sleeves"
                else ["front_bodice", "back_bodice"]
            )
            prefix = item["role"]
            kind = prefix
            for pid in candidates:
                if not any(piece["id"] == pid for piece in result["pieces"]):
                    raise _error("Для слоя не найдена соответствующая основная деталь.", source)
                target = _find(result, pid)
                clone = _clone_piece(target, prefix)
                if any(piece["id"] == clone["id"] for piece in result["pieces"]):
                    raise _error(
                        "Для этого участка уже построен такой слой.",
                        source,
                        "DETAIL_TARGET_CONFLICT",
                    )
                if prefix == "interfacing":
                    clone["name_ru"] = f"Прокладка · {target['name_ru']}"
                    for annotation in clone["annotations"]:
                        annotation["text_ru"] = (
                            "Совместить с основной деталью и продублировать ткань."
                        )
                result["pieces"].append(clone)
                targets.append(pid)
                added.append(clone["id"])
                for edge in target["seam_contour"]["segments"]:
                    pair = _seam_pair(
                        f"{source}_{edge['id']}_attachment",
                        pid,
                        [edge["id"]],
                        clone["id"],
                        [f"{prefix}_{edge['id']}"],
                    )
                    result["seam_pairs"].append(pair)
                    interfaces.append(pair["id"])
        elif module == "straight_sash_v1":
            kind = "sash"
            width, length = dimensions["width"], dimensions["length"]
            waist = request["body_measurements"]["values"]["waist"]["value"]
            waist += (
                request["fit_settings"]["wearing_ease_mm"]["waist"]
                + request["fit_settings"]["design_ease_mm"]["waist"]
            )
            if length < waist + 200:
                raise _error(
                    "Для завязывания кушака добавьте минимум 20 см к обхвату талии.", source
                )
            pid = f"{source}_sash"
            piece = _rectangle(pid, "Кушак", length, 2 * width)
            parameters.update(cut_width=2 * width, finished_waist=waist)
            fold = _path(
                f"{pid}_fold",
                [LineSegment(Point(0, width), Point(length, width), f"{pid}_fold_line")],
            )
            piece["internal_paths"].append(fold)
            piece["annotations"][0]["text_ru"] = (
                f"Кушак: сложить вдоль; готовая ширина {width:g} мм. Завязать на талии."
            )
            result["pieces"].append(piece)
            from .attachments import descendants
            targets = next(([p['id'] for p in descendants(result, root)]
                            for root in ('front_skirt', 'front_bodice', 'front_trouser')
                            if descendants(result, root)), [])
            if not targets:
                raise _error('Не найдена основа для кушака.', source, 'DETAIL_TARGET_MISSING')
            added, interfaces = [pid], [fold["id"]]
        elif module in {"placed_patch_pocket_v1", "rectangular_applied_panel_v1"}:
            kind = "patch_pocket" if module == "placed_patch_pocket_v1" else "overlay"
            pid = {
                "bodice_front": "front_bodice",
                "bodice_back": "back_bodice",
                "skirt_front": "front_skirt",
                "skirt_back": "back_skirt",
                "trouser_front": "front_trouser",
                "trouser_back": "back_trouser",
            }[item["location"]]
            candidates, box = placement_frame(result, pid, source)
            width = dimensions["width"]
            height = dimensions["depth"] if kind == "patch_pocket" else dimensions["length"]
            left, bottom = (
                box.min_x_mm + (box.width_mm - width) / 2,
                box.min_y_mm + dimensions["spacing"],
            )
            piece = _rectangle(
                f"{source}_{kind}",
                "Накладной карман" if kind == "patch_pocket" else "Накладная панель",
                width,
                height,
                item["count"],
            )
            if kind == "patch_pocket":
                segs = piece["seam_contour"]["segments"]
                segs[2]["id"] = f"{piece['id']}_opening_hem"
                segs[0]["id"] = f"{piece['id']}_lower"
            placement = contour_from_data(piece["seam_contour"])
            shifted = [
                LineSegment(
                    Point(seg.start.x_mm + left, seg.start.y_mm + bottom),
                    Point(seg.end.x_mm + left, seg.end.y_mm + bottom),
                    f"{source}_placement_{i}",
                )
                for i, seg in enumerate(placement.segments)
            ]
            target = containing_piece(candidates, shifted, source)
            added = [piece["id"]]
            result["pieces"].append(piece)
            if target is None:
                sewn = [0, 1, 3] if kind == "patch_pocket" else [0, 1, 2, 3]
                targets, interfaces, placement_parameters = distribute_placement(
                    result, pid, shifted, source,
                    {i: (piece, placement.segments[i]) for i in sewn}, footprint=shifted,
                )
                parameters.update(placement_parameters)
                piece["annotations"].append({
                    "id": f"{source}_assembly_order", "position": [width / 2, height / 2],
                    "text_ru": "Сначала стачать швы членения основы и разутюжить припуски. "
                               "Совместить линии нанесения на собранной основе, затем пришить целую деталь.",
                })
            else:
                pid = target["id"]
                piece["name_ru"] += f" · {target['name_ru']}"
                path = _path(f"{source}_placement", shifted, True)
                _check_placement(target, path, source)
                target["internal_paths"].append(path)
                targets = [pid]
                for i in [0, 1, 3] if kind == "patch_pocket" else [0, 1, 2, 3]:
                    pair = _seam_pair(f"{source}_application_{i}", pid, [shifted[i].id],
                                      piece["id"], [piece["seam_contour"]["segments"][i]["id"]])
                    result["seam_pairs"].append(pair)
                    interfaces.append(pair["id"])
                interfaces.append(path["id"])
        elif module == "paired_waist_ties_v1":
            kind = "tie"
            target, edges = _edges(result, "waist", source)[0]
            edge = edges[-1]
            width, length = dimensions["width"], dimensions["length"]
            if not isinstance(edge, LineSegment) or edge.length_mm < width + 20:
                raise _error("Для завязки нужен прямой свободный участок талии.", source)
            pid = f"{source}_ties"
            piece = _rectangle(pid, "Парные завязки по талии", length, width, 2)
            piece["annotations"][0]["text_ru"] = (
                "Однослойные завязки: обработать края; притачать на обеих сторонах по метке талии."
            )
            path = _path(
                f"{source}_tie_anchor",
                [
                    LineSegment(
                        edge.point_at(1 - width / edge.length_mm),
                        edge.end,
                        f"{source}_tie_anchor_segment",
                    )
                ],
            )
            if edge.start.x_mm > edge.end.x_mm:
                path = _path(
                    f"{source}_tie_anchor",
                    [
                        LineSegment(
                            edge.start,
                            edge.point_at(width / edge.length_mm),
                            f"{source}_tie_anchor_segment",
                        )
                    ],
                )
            target["internal_paths"].append(path)
            result["pieces"].append(piece)
            pair = _seam_pair(
                f"{source}_tie_attachment",
                target["id"],
                [path["segments"][0]["id"]],
                pid,
                [f"{pid}_end_left"],
            )
            result["seam_pairs"].append(pair)
            targets, added, interfaces = [target["id"]], [pid], [pair["id"], path["id"]]
        else:
            kind = (
                "ruffle"
                if module == "gathered_edge_ruffle_v1"
                else "peplum"
                if module == "circular_waist_peplum_v1"
                else "flounce"
            )
            location = "waist" if kind == "peplum" else item["location"]
            slot = f"edge:{location}"
            if slot in occupied and location != "hem":
                raise _error(
                    "На один срез назначены две отделочные детали.",
                    source,
                    "DETAIL_TARGET_CONFLICT",
                )
            occupied.add(slot)
            records = []
            for target, edges in _edges(result, location, source):
                reduction = _reduction(result, target["id"], [seg.id for seg in edges])
                seam = sum(seg.length_mm for seg in edges) - reduction
                parameters[f"join_length_{target['id']}"] = seam
                parameters[f"cut_quantity_{target['id']}"] = _quantity(target)
                if seam < 40:
                    raise _error("Слишком короткий срез для отделочной детали.", source)
                if location in {"hem", "sleeve"}:
                    edges = _rename_edges(result, target, edges, source)
                pid = f"{source}_{target['id']}"
                depth = dimensions["depth"]
                if depth < request["fit_settings"]["seam_allowances_mm"]["hem"] + 10:
                    raise _error(
                        "Глубина отделки должна превышать припуск на низ минимум на 1 см. "
                        "Увеличьте глубину или уменьшите припуск на низ.",
                        source,
                        "DETAIL_HEM_ALLOWANCE_TOO_DEEP",
                    )
                addition = dimensions["width"] if kind == "ruffle" else 0
                if kind == "ruffle":
                    piece = _rectangle(
                        pid,
                        "Сборчатая оборка",
                        seam + addition,
                        depth,
                        _quantity(target),
                        hem=True,
                    )
                    piece["annotations"][0]["text_ru"] = (
                        f"Собрать срез {seam + addition:.1f} мм до {seam:.1f} мм. Глубина {depth:g} мм."
                    )
                else:
                    radius = seam / math.pi
                    parameters[f"inner_radius_{target['id']}"] = radius
                    contour = Contour(
                        (
                            ArcSegment.circular(Point(0, 0), radius, 0, math.pi, f"{pid}_join"),
                            LineSegment(
                                Point(-radius, 0), Point(-radius - depth, 0), f"{pid}_end_left"
                            ),
                            ArcSegment.circular(
                                Point(0, 0), radius + depth, math.pi, -math.pi, f"{pid}_hem"
                            ),
                            LineSegment(
                                Point(radius + depth, 0), Point(radius, 0), f"{pid}_end_right"
                            ),
                        ),
                        id=f"{pid}_seam",
                    )
                    piece = _new_piece(
                        pid,
                        "Круговая баска" if kind == "peplum" else "Круговой волан",
                        contour,
                        _quantity(target),
                    )
                    piece["grainline"] = {
                        "start": [-depth / 4, radius + depth / 2],
                        "end": [depth / 4, radius + depth / 2],
                    }
                    piece["annotations"][0]["position"] = [0, radius + depth / 2]
                    piece["annotations"][0]["text_ru"] = (
                        f"{piece['name_ru']}: r={radius:.1f} мм, глубина={depth:g} мм; срез {seam:.1f} мм."
                    )
                result["pieces"].append(piece)
                piece["name_ru"] += f" · {target['name_ru']}"
                pair = _seam_pair(
                    f"{pid}_attachment",
                    target["id"],
                    [seg.id for seg in edges],
                    pid,
                    [f"{pid}_join"],
                )
                pair.update(
                    first_length_reduction_mm=reduction, second_length_reduction_mm=addition
                )
                if len(edges) == 1 and reduction == 0:
                    match_id = f"{pid}_join_middle"
                    target["notches"].append(
                        {
                            "id": f"{pid}_target_notch",
                            "match_id": match_id,
                            "segment_id": edges[0].id,
                            "distance_from_start_mm": seam / 2,
                            "kind": "single",
                        }
                    )
                    piece["notches"].append(
                        {
                            "id": f"{pid}_detail_notch",
                            "match_id": match_id,
                            "segment_id": f"{pid}_join",
                            "distance_from_start_mm": (seam + addition) / 2,
                            "kind": "single",
                        }
                    )
                result["seam_pairs"].append(pair)
                targets.append(target["id"])
                added.append(pid)
                interfaces.append(pair["id"])
                records.append((target, piece, edges))
                if target["id"].startswith("overlay_"):
                    for layer_op in result.get("composite_operations", []) + operations:
                        if (
                            layer_op["source_kind"] == "layer"
                            and target["id"] in layer_op["added_piece_ids"]
                        ):
                            layer_op["added_piece_ids"].append(pid)
                            layer_op["interface_ids"].append(pair["id"])
            interfaces.extend(
                finish_edge_joins(result, records, request, location, kind != "ruffle", source)
            )
        operations.append(
            _operation(
                source,
                "layer" if group == "layers" else "element",
                kind,
                module,
                {
                    "sash": "D02-S01",
                    "tie": "D02-T01",
                    "patch_pocket": "D02-P01",
                    "overlay": "D02-O01",
                    "ruffle": "D02-R01",
                    "flounce": "D02-F01",
                    "peplum": "D02-B01",
                    "interfacing": "D02-I01",
                }[kind],
                targets,
                added,
                interfaces,
                parameters,
                _interface_residual(result, interfaces),
            )
        )
        operations[-1]["operation_id"] = f"detail_{group}_{source}_{kind}"
    result["composite_operations"] = result.get("composite_operations", []) + operations
    validate_detail_placements(result)
    residual = _pair_residual(result)
    if residual > 1:
        raise _error(
            "Парные срезы дополнительных деталей вышли за допуск 1 мм.",
            "elements",
            "DETAIL_INTERFACE_MISMATCH",
        )
    return CompositeResult(
        result,
        len(operations),
        len(result["pieces"]) - before_pieces,
        len(result["seam_pairs"]) - before_pairs,
        residual,
    )


def validate_detail_placements(pattern: Mapping[str, Any]) -> None:
    validate_placement_operations(pattern)
    for op in pattern.get("composite_operations", []):
        if op["module_id"] in {"placed_patch_pocket_v1", "rectangular_applied_panel_v1"}:
            if 'placement_fragment_count' in op['parameters_mm']:
                continue
            target = _find(pattern, op["target_piece_ids"][0])
            path = next(
                p for p in target["internal_paths"] if p["id"] == f"{op['source_id']}_placement"
            )
            _check_placement(target, path, op["source_id"])
        elif op["module_id"] == "paired_waist_ties_v1":
            target = _find(pattern, op["target_piece_ids"][0])
            path = next(
                p for p in target["internal_paths"] if p["id"] == f"{op['source_id']}_tie_anchor"
            )
            line = contour_from_data(path).segments[0]
            contour = contour_from_data(target["seam_contour"])
            found = False
            for edge in contour.segments:
                if isinstance(edge, LineSegment) and "_waist" in edge.id:

                    def on_edge(point: Point) -> bool:
                        return (
                            abs(
                                point.distance_to(edge.start)
                                + point.distance_to(edge.end)
                                - edge.length_mm
                            )
                            < 0.01
                        )

                    if on_edge(line.start) and on_edge(line.end):
                        found = True
            if not found:
                raise _error(
                    "Метка крепления завязки больше не совпадает со срезом талии.", op["source_id"]
                )


def finish_edge_joins(
    pattern: dict[str, Any],
    records: list[tuple[dict, dict, list]],
    request: Mapping[str, Any],
    location: str,
    circular: bool,
    source: str,
    suffix: str = "end",
) -> list[str]:
    """Join side edges and explicitly identify seams between mirrored copies."""
    interfaces = []
    by_layer: dict[bool, list[tuple[dict, dict, str]]] = {}
    closure = request["garment_spec"]["parameters"]["closure"]
    garment = request["garment_spec"]["garment_type"]
    for target, piece, edges in records:
        pid = piece["id"]
        if location == "sleeve":
            pair = _seam_pair(
                f"{source}_{pid}_closing",
                pid,
                [f"{pid}_{suffix}_left"],
                pid,
                [f"{pid}_{suffix}_right"],
            )
            pattern["seam_pairs"].append(pair)
            interfaces.append(pair["id"])
            continue
        center_start = edges[0].start.x_mm <= edges[-1].end.x_mm
        center = (
            ("right" if center_start else "left")
            if circular
            else ("left" if center_start else "right")
        )
        side = "left" if center == "right" else "right"
        by_layer.setdefault(target["id"].startswith("overlay_"), []).append((target, piece, side))
        opening = closure["location"] == (
            "center_front" if "front" in target["id"] else "center_back"
        )
        has_center = (any('_center' in e.id for e in contour_from_data(target['seam_contour']).segments)
                      or any(pair.get('copy_pairing') == 'mirrored_copies'
                             and pair['first_piece_id'] == target['id'] == pair['second_piece_id']
                             for pair in pattern['seam_pairs']))
        closed = (target["cut_on_fold"] or not opening) and has_center
        if opening and location == "hem":
            total = request["garment_spec"]["parameters"]["skirt"]["length_from_waist_mm"]
            if garment != "skirt":
                total += request["body_measurements"]["values"]["front_neck_to_waist_over_bust"][
                    "value"
                ]
            closed = has_center and float(closure.get("length_mm") or 0) < total - 1
        if closed and piece["cut_quantity"] == 2:
            sid = f"{pid}_{suffix}_{center}"
            pair = _seam_pair(f"{source}_{pid}_center_copies", pid, [sid], pid, [sid])
            pair["copy_pairing"] = "mirrored_copies"
            pattern["seam_pairs"].append(pair)
            interfaces.append(pair["id"])
            piece["annotations"].append(
                {
                    "id": f"{pid}_center_instruction",
                    "text_ru": "Соединить центральные срезы двух зеркальных деталей.",
                    "position": [
                        piece["annotations"][0]["position"][0],
                        piece["annotations"][0]["position"][1] + 8,
                    ],
                }
            )
    for layer, group in by_layer.items():
        if len(group) > 2:
            by_target = {target['id']: (target, piece, edges) for target, piece, edges in records
                         if target['id'].startswith('overlay_') == layer}
            for join in list(pattern['seam_pairs']):
                a, b = join['first_piece_id'], join['second_piece_id']
                if a == b or a not in by_target or b not in by_target:
                    continue
                endpoints = []
                for name, pid in [('first', a), ('second', b)]:
                    target, detail, edges = by_target[pid]
                    borders = [e for e in contour_from_data(target['seam_contour']).segments
                               if e.id in join[f'{name}_segment_ids']]
                    if not borders:
                        break
                    distances = [min(point.distance_to(end) for border in borders
                                     for end in (border.start, border.end))
                                 for point in (edges[0].start, edges[-1].end)]
                    if min(distances) > 0.1:
                        break
                    at_start = distances[0] < distances[1]
                    edge_side = 'right' if at_start == circular else 'left'
                    endpoints.append((detail['id'], f"{detail['id']}_{suffix}_{edge_side}"))
                if len(endpoints) == 2:
                    pair = _seam_pair(f'{source}_{join["id"]}_trim_join',
                                      endpoints[0][0], [endpoints[0][1]],
                                      endpoints[1][0], [endpoints[1][1]])
                    pattern['seam_pairs'].append(pair)
                    interfaces.append(pair['id'])
            continue
        if len(group) != 2:
            raise _error("Для бокового соединения нужны передняя и задняя детали.", source)
        (_, front, fs), (_, back, bs) = group
        pair = _seam_pair(
            f"{source}_{'overlay' if layer else 'main'}_side_join",
            front["id"],
            [f"{front['id']}_{suffix}_{fs}"],
            back["id"],
            [f"{back['id']}_{suffix}_{bs}"],
        )
        pattern["seam_pairs"].append(pair)
        interfaces.append(pair["id"])
    return interfaces

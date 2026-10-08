"""Stage-three measured structural details and cut-boundary transformations.

Recipes use calculated foundation edges, never photographic pixel dimensions.
Every sewn interface uses the actual subcurve and a paired cut boundary.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
from typing import Any, Mapping

from kroika_contracts.design_modules import STRUCTURAL_MODULES
from .blocks import BlockConstructionError
from .composites import _operation, _seam_pair, _interface_residual
from .details import _find, _rectangle, _new_piece, _path, _quantity, _inside, _reduction
from .geometry import (
    Contour,
    LineSegment,
    CubicBezier,
    Point,
    contour_from_data,
    contour_to_data,
    validate_simple_contour,
)
from .geometry.primitives import curve_points
from .fullness import _subcurve, _slice_distance, _edge_for, _annular_piece, _check_line
from .modeling import _resize_waistbands
from .attachments import boundary_edges, boundary_records

FOUNDATION = {
    "side_skirt_slit_v3",
    "back_skirt_slit_v3",
    "back_skirt_vent_v3",
    "front_bodice_yoke_v3",
    "back_bodice_yoke_v3",
    "offset_skirt_panel_v3",
    "shoulder_princess_seam_v3",
    "side_to_waist_dart_v3",
    "straight_shoulder_straps_v3",
}


def _target_id(location):
    return {
        "bodice_front": "front_bodice",
        "bodice_back": "back_bodice",
        "skirt_front": "front_skirt",
        "skirt_back": "back_skirt",
        "trouser_front": "front_trouser",
        "trouser_back": "back_trouser",
        "sleeve": "base_sleeve",
    }[location]


def _error(message, source, code="STRUCTURAL_GEOMETRY_INVALID"):
    return BlockConstructionError(code, message, f"/garment_spec/design_intent/elements/{source}")


def _active(request):
    return sorted(
        [
            i
            for i in (request["garment_spec"].get("design_intent") or {}).get("elements", [])
            if i.get("included") is not False
            and i.get("support_status") == "supported"
            and i.get("module_id") in STRUCTURAL_MODULES
        ],
        key=lambda i: (0 if i['module_id'] == 'straight_shoulder_straps_v3' else 1,
                       i["module_id"], i["source_element_id"]),
    )


def _note(piece, source, text):
    box = contour_from_data(piece["seam_contour"]).bounding_box
    piece["annotations"].append(
        dict(
            id=f"{source}_{piece['id']}_note",
            text_ru=text,
            position=[box.min_x_mm + box.width_mm / 2, box.min_y_mm + box.height_mm / 2],
        )
    )


def _record(pattern, item, kind, targets, added, interfaces, parameters):
    parameters = {
        **{k: v for k, v in (item.get("dimensions_mm") or {}).items() if v is not None},
        **parameters,
    }
    parameters["side_code"] = {"both": 0, "right": 1, "left": -1}[
        (item.get("placement") or {}).get("side", "both")
    ]
    # Preserve original marker coordinates as a manual-edit/export invariant.
    for pid in targets + added:
        piece = _find(pattern, pid)
        for path in [piece["seam_contour"], *piece["internal_paths"]]:
            marker = (
                pid in added
                or path["id"].startswith(item["source_element_id"] + "_")
                or kind == "dart"
                and "dart" in path["id"]
                or kind == "waistband"
            )
            if marker and path in piece["internal_paths"]:
                interfaces.append(path["id"])
            for edge in contour_from_data(path).segments:
                if not marker and not edge.id.startswith(item["source_element_id"] + "_"):
                    continue
                for end in (
                    "start",
                    "end",
                    *(["control_1", "control_2"] if isinstance(edge, CubicBezier) else []),
                ):
                    p = getattr(edge, end)
                    parameters[f"{edge.id}_{end}_x"] = p.x_mm
                    parameters[f"{edge.id}_{end}_y"] = p.y_mm
    op = _operation(
        item["source_element_id"],
        "element",
        kind,
        item["module_id"],
        "C03-S01",
        list(dict.fromkeys(targets)),
        list(dict.fromkeys(added)),
        list(dict.fromkeys(interfaces)),
        parameters,
        _interface_residual(pattern, interfaces),
    )
    op["operation_id"] = f"structural_{item['source_element_id']}_{kind}"
    for pair in pattern["seam_pairs"]:
        if pair["id"] in interfaces and "physical_side" not in pair:
            pair["physical_side"] = (item.get("placement") or {}).get("side", "both")
    for pid in added:
        _note(
            _find(pattern, pid),
            item["source_element_id"] + "_side",
            "Сторона применения: " + (item.get("placement") or {}).get("side", "both") + ".",
        )
    pattern.setdefault("composite_operations", []).append(op)


def _anchor(target, edges, source):
    path = _path(
        f"{source}_{target['id']}_anchor",
        [replace(e, id=f"{source}_{target['id']}_anchor_{i}") for i, e in enumerate(edges)],
    )
    for edge in contour_from_data(path).segments:
        _check_line(target, edge, source, boundary=True)
    target["internal_paths"].append(path)
    return contour_from_data(path).segments


def _join(pattern, source, target, edges, detail, detail_edges, reduction=0, detail_reduction=0):
    pair = _seam_pair(
        f"{source}_{target['id']}_{detail['id']}_join",
        target["id"],
        [e.id for e in edges],
        detail["id"],
        [e.id for e in detail_edges],
    )
    pair.update(first_length_reduction_mm=reduction, second_length_reduction_mm=detail_reduction)
    pattern["seam_pairs"].append(pair)
    return pair["id"]


def _neck_edges(pattern, source):
    records = []
    for prefix in ("front", "back"):
        group = [
            (
                p,
                [
                    e
                    for e in boundary_edges(p, 'neckline')
                    if not e.id.startswith('mirror_')
                ],
            )
            for p in pattern["pieces"]
            if p["id"] == f"{prefix}_bodice" or p["id"].startswith(f"{prefix}_bodice__")
        ]
        records += [(p, e) for p, e in group if e]
    if len(records) < 2:
        raise _error("Нужны отдельные свободные срезы горловины переда и спинки.", source)
    return records


def _hood_or_collar(pattern, item, request):
    source, module, d = item["source_element_id"], item["module_id"], item["dimensions_mm"]
    records = _neck_edges(pattern, source)
    lengths = [
        sum(e.length_mm for e in edges) - _reduction(pattern, p["id"], [e.id for e in edges])
        for p, edges in records
    ]
    total = sum(lengths)
    pid = f"{source}_hood" if module == "fitted_two_piece_hood_v3" else f"{source}_collar"
    if module == "fitted_two_piece_hood_v3":
        w, h = d["width"], d["length"]
        points = [Point(0, 0), Point(total, 0), Point(w, h)]
        edges = [
            LineSegment(points[0], points[1], f"{pid}_join"),
            LineSegment(points[1], points[2], f"{pid}_face"),
            CubicBezier(
                points[2],
                Point(w * 0.45, h),
                Point(-w * 0.08, h * 0.8),
                points[0],
                f"{pid}_crown",
            ),
        ]
        piece = _new_piece(
            pid, "Капюшон из двух половин · половина", Contour(tuple(edges), id=f"{pid}_seam"), 2
        )
        facing = _rectangle(
            f"{source}_hood_facing", "Обтачка лица капюшона", edges[1].length_mm, d["depth"], 2
        )
        pattern["pieces"].append(facing)
        joins = [
            _join(
                pattern,
                source,
                piece,
                [edges[1]],
                facing,
                [contour_from_data(facing["seam_contour"]).segments[0]],
            )
        ]
        pair = _seam_pair(f"{source}_hood_crown", pid, [edges[2].id], pid, [edges[2].id])
        pair["copy_pairing"] = "mirrored_copies"
        pattern["seam_pairs"].append(pair)
        joins.append(pair["id"])
        added = [pid, facing["id"]]
        _note(
            piece,
            source,
            "Кроить две зеркальные половины. Стачать затылочный шов; метки делят горловину на перед и спинку. Посадку головы проверить на макете.",
        )
        kind = "hood"
    else:
        piece = _annular_piece(
            pid,
            "Плоский шалевый воротник"
            if module == "shawl_collar_v3"
            else "Плоский фигурный воротник",
            total,
            d["width"],
            2,
            end_depth=d["depth"],
            request=request,
        )
        joins, added, kind = [], [pid], "collar"
        _note(
            piece,
            source,
            "Кроить четыре половины: верх и подворотник. Стачать внешний край, вывернуть; соединить половины по центру спинки. Это плоский воротник без лацкана и стойки.",
        )
    inner = contour_from_data(piece["seam_contour"]).segments[0]
    split, cursor = [], 0.0
    for index, length in enumerate(lengths):
        split.extend(replace(e, id=f'{pid}_join_{index}')
                     for e in _slice_distance([inner], cursor, length, source))
        cursor += length
    contour = contour_from_data(piece["seam_contour"])
    piece["seam_contour"] = contour_to_data(
        Contour(tuple([*split, *contour.segments[1:]]), id=contour.id)
    )
    pattern["pieces"].append(piece)
    for i, (target, edges) in enumerate(records):
        joins.append(
            _join(
                pattern,
                source,
                target,
                edges,
                piece,
                [split[i]],
                reduction=_reduction(pattern, target["id"], [e.id for e in edges]),
            )
        )
    # A full front has two physical neckline halves, including after a yoke.
    unused = [(i, length) for i, ((target, _), length) in enumerate(zip(records, lengths))
              if target['id'].startswith('front_')]
    mirrored_records = []
    for target in pattern['pieces']:
        if not target['id'].startswith('front_bodice'):
            continue
        edges = [e for e in boundary_edges(target, 'neckline') if e.id.startswith('mirror_')]
        if not edges:
            continue
        length = sum(e.length_mm for e in edges)-_reduction(pattern, target['id'], [e.id for e in edges])
        if not unused:
            raise _error('Не найдена парная половина горловины.', source)
        match = min(range(len(unused)), key=lambda i: abs(unused[i][1]-length))
        index, expected = unused.pop(match)
        if abs(expected-length) > 1:
            raise _error('Для разных половин горловины нужен асимметричный воротник.', source)
        pair = _seam_pair(f'{source}_{target["id"]}_neck_mirror', target['id'],
                          [e.id for e in edges], pid, [split[index].id])
        pair.update(first_length_reduction_mm=_reduction(pattern, target['id'], [e.id for e in edges]),
                    second_instance='mirror')
        pattern['seam_pairs'].append(pair)
        joins.append(pair['id'])
        mirrored_records.append((target, edges, index))
    records_for_coverage = records + [(target, edges) for target, edges, _ in mirrored_records]
    if kind == "collar":
        from .composites import _clone_piece

        under = _clone_piece(piece, "under")
        under["name_ru"] = "Подворотник · " + piece["name_ru"]
        pattern["pieces"].append(under)
        added.append(under["id"])
        seam_edges = contour_from_data(piece["seam_contour"]).segments
        free_edges = [
            e for e in seam_edges if e.id not in {*(edge.id for edge in split), f"{pid}_end_left"}
        ]
        pair = _seam_pair(
            f"{source}_collar_layers",
            pid,
            [e.id for e in free_edges],
            under["id"],
            ["under_" + e.id for e in free_edges],
        )
        pattern["seam_pairs"].append(pair)
        joins.append(pair["id"])
        for surface in [piece, under]:
            edge_id = ("under_" if surface is under else "") + f"{pid}_end_left"
            pair = _seam_pair(
                f"{surface['id']}_back_center", surface["id"], [edge_id], surface["id"], [edge_id]
            )
            pair["copy_pairing"] = "mirrored_copies"
            pattern["seam_pairs"].append(pair)
            joins.append(pair["id"])
        for i, (target, edges) in enumerate(records):
            pair = _seam_pair(
                f"{source}_{target['id']}_undercollar_join",
                target["id"],
                [e.id for e in edges],
                under["id"],
                ["under_" + split[i].id],
            )
            pair["first_length_reduction_mm"] = _reduction(
                pattern, target["id"], [e.id for e in edges]
            )
            pattern["seam_pairs"].append(pair)
            joins.append(pair["id"])
    if kind == 'collar':
        for target, edges, index in mirrored_records:
            pair = _seam_pair(f'{source}_{target["id"]}_undercollar_mirror', target['id'],
                              [e.id for e in edges], under['id'], ['under_'+split[index].id])
            pair.update(first_length_reduction_mm=_reduction(pattern, target['id'], [e.id for e in edges]),
                        second_instance='mirror')
            pattern['seam_pairs'].append(pair)
            joins.append(pair['id'])
    _record(
        pattern,
        item,
        kind,
        [p["id"] for p, _ in records_for_coverage],
        added,
        joins,
        {"front_neck_join": sum(length for (target, _), length in zip(records, lengths) if target["id"].startswith("front_")),
         "back_neck_join": sum(length for (target, _), length in zip(records, lengths) if target["id"].startswith("back_"))},
    )


def _cuff(pattern, item):
    source, d = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, "base_sleeve")
    edges = _edge_for(target, "hem", source)
    length = sum(e.length_mm for e in edges)
    pid = f"{source}_cuff"
    height = d["width"]
    if item["module_id"] == "doubled_cuff_v3":
        piece = _rectangle(pid, "Двойная отворотная манжета", length + d["depth"], 4 * height, 2)
        for n in (1, 2, 3):
            piece["internal_paths"].append(
                _path(
                    f"{source}_cuff_fold_{n}",
                    [
                        LineSegment(
                            Point(0, n * height),
                            Point(length + d["depth"], n * height),
                            f"{source}_fold_{n}",
                        )
                    ],
                )
            )
        _note(
            piece,
            source,
            "Сложить ткань по среднему сгибу, притачать до метки длины рукава; отвернуть манжету по второму сгибу. Выступ за меткой — нахлёст застёжки.",
        )
    else:
        points = [Point(0, 0), Point(length, 0), Point(length, d["depth"]), Point(0, height)]
        piece = _new_piece(
            pid,
            "Фигурная открытая манжета",
            Contour(
                tuple(LineSegment(points[i], points[(i + 1) % 4], f"{pid}_{i}") for i in range(4)),
                id=f"{pid}_seam",
            ),
            2,
        )
        _note(
            piece,
            source,
            "Высоты концов различаются. Обработать свободные края; манжета остаётся открытой у шва рукава, соединение концов не закладывается.",
        )
    attachment = LineSegment(Point(0, 0), Point(length, 0), f"{source}_cuff_attachment_edge")
    piece["internal_paths"].append(_path(f"{source}_cuff_attachment", [attachment]))
    pattern["pieces"].append(piece)
    join = _join(pattern, source, target, edges, piece, [attachment])
    _record(pattern, item, "cuff", [target["id"]], [pid], [join], {"sleeve_join_length": length})


def _belt(pattern, item, request):
    source, d = item["source_element_id"], item["dimensions_mm"]
    w, length, taper = d["width"], d["length"], d["depth"]
    waist = request["body_measurements"]["values"]["waist"]["value"]
    # Both recipes are tied; a belt without a buckle needs reserve for its knot too.
    if length < waist + 200 or taper * 2 >= length:
        raise _error(
            "Длина не охватывает талию с запасом для завязывания или сужения перекрываются.", source
        )
    pid = f"{source}_{item['type']}"
    points = [
        Point(0, w / 2),
        Point(taper, 0),
        Point(length - taper, 0),
        Point(length, w / 2),
        Point(length - taper, w),
        Point(taper, w),
    ]
    piece = _new_piece(
        pid,
        "Фигурный ремень" if item["type"] == "belt" else "Кушак с зауженными концами",
        Contour(
            tuple(LineSegment(points[i], points[(i + 1) % 6], f"{pid}_{i}") for i in range(6)),
            id=f"{pid}_seam",
        ),
        2,
    )
    _note(
        piece,
        source,
        "Две одинаковые детали — верх и низ. Стачать края лицом к лицу, оставить отверстие, вывернуть и закрыть отверстие. Завязать; отдельная пряжка в конструкции не предусмотрена.",
    )
    pattern["pieces"].append(piece)
    pair = _seam_pair(
        f"{source}_belt_layers",
        pid,
        [e.id for e in contour_from_data(piece["seam_contour"]).segments],
        pid,
        [e.id for e in contour_from_data(piece["seam_contour"]).segments],
    )
    pair["copy_pairing"] = "mirrored_copies"
    pattern["seam_pairs"].append(pair)
    target = next(
        p for p in pattern["pieces"] if p["id"] in {"front_bodice", "front_skirt", "front_trouser"}
    )
    _record(
        pattern,
        item,
        item["type"],
        [target["id"]],
        [pid],
        [pair["id"]],
        {"finished_width": w, "finished_length": length},
    )


def _elastic(pattern, item, request):
    source, d = item["source_element_id"], item["dimensions_mm"]
    targets = _resize_waistbands(pattern, 2 * d["width"], source)
    waist = request["body_measurements"]["values"]["waist"]["value"]
    if not 0.6 * waist <= d["length"] <= waist:
        raise _error(
            "Длина резинки должна быть от 60% до 100% обхвата талии. Уточните по своей резинке.",
            source,
        )
    paths = []
    for pid in targets:
        p = _find(pattern, pid)
        box = contour_from_data(p["seam_contour"]).bounding_box
        p["internal_paths"] = [path for path in p["internal_paths"] if "fold" not in path["id"]]
        for n, y in [("fold", box.min_y_mm + d["width"]), ("channel", box.min_y_mm + 5)]:
            path = _path(
                f"{source}_{pid}_{n}",
                [
                    LineSegment(
                        Point(box.min_x_mm, y), Point(box.max_x_mm, y), f"{source}_{pid}_{n}_edge"
                    )
                ],
            )
            p["internal_paths"].append(path)
            paths.append(path["id"])
        _note(
            p,
            source,
            f"Сгиб по середине; оставить вход для покупной резинки длиной {d['length']:g} мм и шириной не более {d['width'] - 5:g} мм. Прибавка по бёдрам и возможность надевания требуют проверки; застёжка основы сохраняется.",
        )
    _record(pattern, item, "waistband", targets, [], paths, {"elastic_length": d["length"]})


def _pocket(pattern, item):
    source, d = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, _target_id(item["location"]))
    box = contour_from_data(target["seam_contour"]).bounding_box
    x = box.min_x_mm + d["spacing"]
    y = box.max_y_mm - item.get("placement", {}).get("offset_mm", 20)
    count = item["count"]
    pid = f"{source}_pocket"
    interfaces = []
    if item["module_id"] == "rounded_patch_pocket_v3":
        w, h = d["width"], d["depth"]
        r = min(w, h) * 0.2
        pts = [Point(0, h), Point(w, h), Point(w, r), Point(w - r, 0), Point(r, 0), Point(0, r)]
        edges = [
            LineSegment(pts[0], pts[1], f"{pid}_opening_hem"),
            LineSegment(pts[1], pts[2], f"{pid}_right"),
            CubicBezier(pts[2], Point(w, 0), Point(w, 0), pts[3], f"{pid}_round_right"),
            LineSegment(pts[3], pts[4], f"{pid}_bottom"),
            CubicBezier(pts[4], Point(0, 0), Point(0, 0), pts[5], f"{pid}_round_left"),
            LineSegment(pts[5], pts[0], f"{pid}_left"),
        ]
        piece = _new_piece(
            pid, "Карман со скруглённым низом", Contour(tuple(edges), id=f"{pid}_seam"), count
        )
        placed = []
        for i, e in enumerate(edges):

            def shift(p):
                return Point(p.x_mm + x, p.y_mm + y - h)

            if isinstance(e, CubicBezier):
                ne = CubicBezier(
                    shift(e.start),
                    shift(e.control_1),
                    shift(e.control_2),
                    shift(e.end),
                    f"{source}_placement_{i}",
                )
            else:
                ne = LineSegment(shift(e.start), shift(e.end), f"{source}_placement_{i}")
            _check_line(target, ne, source)
            placed.append(ne)
        path = _path(f"{source}_pocket_placement", placed, True)
        target["internal_paths"].append(path)
        pattern["pieces"].append(piece)
        for i in range(1, len(edges)):
            pair = _seam_pair(
                f"{source}_patch_{i}", target["id"], [placed[i].id], pid, [edges[i].id]
            )
            pattern["seam_pairs"].append(pair)
            interfaces.append(pair["id"])
        added = [pid]
        kind = "patch_pocket"
    else:
        length, w, h = d["length"], d["width"], d["depth"]
        opening = LineSegment(Point(x, y), Point(x + length, y), f"{source}_welt_cut")
        _check_line(target, opening, source)
        lines = []
        for n, dy in [("upper", w), ("lower", -w)]:
            line = LineSegment(Point(x, y + dy), Point(x + length, y + dy), f"{source}_welt_{n}")
            _check_line(target, line, source)
            lines.append(line)
        # Cut from opening centre to corner triangles; stitch the two lips first.
        cut = LineSegment(Point(x + w, y), Point(x + length - w, y), opening.id)
        triangles = [
            LineSegment(cut.start, lines[i].start, f"{source}_welt_triangle_left_{i}")
            for i in range(2)
        ] + [
            LineSegment(cut.end, lines[i].end, f"{source}_welt_triangle_right_{i}")
            for i in range(2)
        ]
        for i, e in enumerate([cut, *triangles, *lines]):
            target["internal_paths"].append(_path(f"{source}_welt_mark_{i}", [e]))
        welts = []
        bags = []
        for i, line in enumerate(lines):
            welt = _rectangle(
                f"{source}_welt_{i}",
                "Обтачка прорезного кармана · " + ("верх" if i == 0 else "низ"),
                length,
                2 * w,
                count,
            )
            bag = _rectangle(
                f"{source}_bag_{i}",
                "Мешковина прорезного кармана · " + ("верх" if i == 0 else "низ"),
                length,
                h,
                count,
            )
            welt["internal_paths"].append(
                _path(
                    f"{source}_welt_fold_{i}",
                    [LineSegment(Point(0, w), Point(length, w), f"{source}_welt_fold_edge_{i}")],
                )
            )
            pattern["pieces"].extend([welt, bag])
            welts.append(welt)
            bags.append(bag)
            interfaces.append(
                _join(
                    pattern,
                    f"{source}_{i}",
                    target,
                    [line],
                    welt,
                    [contour_from_data(welt["seam_contour"]).segments[0]],
                )
            )
            interfaces.append(
                _join(
                    pattern,
                    f"{source}_{i}",
                    welt,
                    [contour_from_data(welt["seam_contour"]).segments[2]],
                    bag,
                    [contour_from_data(bag["seam_contour"]).segments[0]],
                )
            )
            _note(
                welt,
                source,
                "Сложить пополам. Сначала притачать две обтачки по параллельным линиям, затем прорезать середину и уголки. После выворачивания закрепить треугольники.",
            )
        pair = _seam_pair(
            f"{source}_bag_closing",
            bags[0]["id"],
            [e.id for e in contour_from_data(bags[0]["seam_contour"]).segments[1:]],
            bags[1]["id"],
            [e.id for e in contour_from_data(bags[1]["seam_contour"]).segments[1:]],
        )
        pattern["seam_pairs"].append(pair)
        interfaces.append(pair["id"])
        added = [p["id"] for p in [*welts, *bags]]
        kind = "welt_pocket"
    _note(
        target,
        source,
        f"Карман: сторона {item.get('placement', {}).get('side', 'both')}; количество {count}. Отсчёт положения — от верхней точки детали и центра.",
    )
    _record(
        pattern, item, kind, [target["id"]], added, interfaces, {"placement_x": x, "placement_y": y}
    )


def _custom(pattern, item):
    source, d = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, _target_id(item["location"]))
    placement = item.get("placement") or {}
    points = [Point(*p) for p in item["outline_mm"]]
    pid = f"{source}_detail"
    contour = Contour(
        tuple(
            LineSegment(points[i], points[(i + 1) % len(points)], f"{pid}_{i}")
            for i in range(len(points))
        ),
        id=f"{pid}_seam",
    )
    validate_simple_contour(contour)
    join_edge = contour.segments[placement.get("outline_edge_index", 0)]
    if abs(join_edge.length_mm - d["length"]) > 1:
        raise _error(
            "Длина выбранного ребра контура должна совпадать с длиной крепления с допуском 1 мм.",
            source,
        )
    edges = _slice_distance(
        _edge_for(target, placement.get("edge", "hem"), source), d["spacing"], d["length"], source
    )
    anchor = _anchor(target, edges, source)
    piece = _new_piece(pid, "Дополнительная деталь по заданному контуру", contour, item["count"])
    pattern["pieces"].append(piece)
    join = _join(pattern, source, target, anchor, piece, [join_edge])
    _note(
        piece,
        source,
        f"Пришить ребро {placement.get('outline_edge_index', 0) + 1} к отмеченному срезу. Контур задан пользователем; форма и направление долевой требуют макета.",
    )
    _record(
        pattern,
        item,
        "other",
        [target["id"]],
        [pid],
        [join],
        {"outline_edge_index": placement.get("outline_edge_index", 0)},
    )


def _decorative(pattern, item):
    source, d = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, _target_id(item["location"]))
    box = contour_from_data(target["seam_contour"]).bounding_box
    placement = item.get("placement") or {}
    x = box.min_x_mm + d["spacing"]
    y = box.max_y_mm - placement.get("offset_mm", 20)
    end = (
        Point(x + d["length"], y)
        if placement.get("orientation", "vertical") == "horizontal"
        else Point(x, y - d["length"])
    )
    line = LineSegment(Point(x, y), end, f"{source}_stitch_edge")
    _check_line(target, line, source)
    target["internal_paths"].append(_path(f"{source}_decorative_stitch", [line]))
    _note(
        target,
        source,
        "Декоративная строчка: не разрезать лекало. " + placement.get("side", "both"),
    )
    _record(
        pattern,
        item,
        "decorative_seam",
        [target["id"]],
        [],
        [],
        {"orientation_code": int(placement.get("orientation") == "horizontal")},
    )


def apply_structural_details(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    result = deepcopy(dict(pattern))
    for item in _active(request):
        module = item["module_id"]
        if module in {"fitted_two_piece_hood_v3", "shaped_flat_collar_v3", "shawl_collar_v3"}:
            _hood_or_collar(result, item, request)
        elif module in {"doubled_cuff_v3", "shaped_cuff_v3"}:
            _cuff(result, item)
        elif module in {"shaped_belt_v3", "tapered_sash_v3"}:
            _belt(result, item, request)
        elif module == "elastic_waistband_v3":
            _elastic(result, item, request)
        elif module in {"rounded_patch_pocket_v3", "welt_pocket_v3"}:
            _pocket(result, item)
        elif module == "explicit_polygon_detail_v3":
            _custom(result, item)
        elif module == "placed_decorative_stitch_v3":
            _decorative(result, item)
        elif module == "straight_shoulder_straps_v3":
            _straps(result, item)
    validate_structural_placements(result)
    return result


def validate_structural_placements(pattern):
    for op in pattern.get("composite_operations", []):
        if op["module_id"] not in STRUCTURAL_MODULES:
            continue
        params = op["parameters_mm"]
        protected = {key[:-8] for key in params if key.endswith("_start_x")}
        available = {
            e.id
            for p in pattern["pieces"]
            if p["id"] in op["target_piece_ids"] + op["added_piece_ids"]
            for path in [p["seam_contour"], *p["internal_paths"]]
            for e in contour_from_data(path).segments
        }
        if protected - available:
            raise _error(
                "Удалён обязательный срез или контрольная линия элемента.",
                op["source_id"],
                "STRUCTURAL_MARKER_MISSING",
            )
        for pid in op["target_piece_ids"] + op["added_piece_ids"]:
            target = _find(pattern, pid)
            for path in [target["seam_contour"], *target["internal_paths"]]:
                for edge in contour_from_data(path).segments:
                    if edge.id not in protected and not path['id'].startswith(op['source_id'] + '_'):
                        continue
                    for end in (
                        "start",
                        "end",
                        *(["control_1", "control_2"] if isinstance(edge, CubicBezier) else []),
                    ):
                        if f"{edge.id}_{end}_x" not in params:
                            continue
                        p = getattr(edge, end)
                        if (
                            abs(p.x_mm - params[f"{edge.id}_{end}_x"]) > 1e-5
                            or abs(p.y_mm - params[f"{edge.id}_{end}_y"]) > 1e-5
                        ):
                            raise _error(
                                "Ручная правка сдвинула контрольную линию конструктивного элемента. Перестройте элемент.",
                                op["source_id"],
                                "STRUCTURAL_MARKER_MOVED",
                            )
                    if path["id"].endswith(("_anchor", "_center_slit", "_closed_center")):
                        boundary = contour_from_data(target["seam_contour"]).segments
                        if not all(
                            any(_point_on(border, edge.point_at(i / 40)) for border in boundary)
                            for i in range(41)
                        ):
                            raise _error(
                                "Линия крепления или разреза отделилась от среза основы.",
                                op["source_id"],
                                "STRUCTURAL_ANCHOR_DETACHED",
                            )
                    if path["id"].endswith("_anchor"):
                        _check_line(target, edge, op["source_id"], boundary=True)
                    elif (
                        op["kind"] in {"patch_pocket", "welt_pocket", "decorative_seam"}
                        and pid in op["target_piece_ids"]
                        and path["id"].startswith(op["source_id"] + "_")
                    ):
                        _check_line(target, edge, op["source_id"])


def _slit(pattern, item, request):
    source, d = item["source_element_id"], item["dimensions_mm"]
    length = d["length"]
    width = d["width"]
    module = item["module_id"]
    joins = []
    added = []
    targets = []
    if module == "side_skirt_slit_v3":
        pair = next((p for p in pattern["seam_pairs"] if p["id"] == "skirt_side_join"), None)
        if pair is None:
            raise _error("Для разреза нужен целый боковой шов юбки.", source)
        if item.get("placement", {}).get("side", "both") != "both":
            other = deepcopy(pair)
            other["id"] = f"{source}_other_side_closed"
            other["physical_side"] = "right" if item["placement"]["side"] == "left" else "left"
            pattern["seam_pairs"].append(other)
        pair["physical_side"] = item.get("placement", {}).get("side", "both")
        for side in ("first", "second"):
            target = _find(pattern, pair[f"{side}_piece_id"])
            all_edges = {e.id: e for e in contour_from_data(target["seam_contour"]).segments}
            edges = [all_edges[e] for e in pair[f"{side}_segment_ids"]]
            # Foundation skirt side is directed from hem to waist.
            if edges[0].start.y_mm > edges[-1].end.y_mm:
                edges = [e.reversed() for e in reversed(edges)]
            total = sum(e.length_mm for e in edges)
            if length > total - 40:
                raise _error("Над разрезом должно остаться минимум 4 см бокового шва.", source)
            opening = _anchor(
                target, _slice_distance(edges, 0, length, source), f"{source}_{side}_opening"
            )
            closed = _anchor(
                target,
                _slice_distance(edges, length, total - length, source),
                f"{source}_{side}_closed",
            )
            pair[f"{side}_segment_ids"] = [e.id for e in closed]
            facing = _rectangle(
                f"{source}_{side}_facing", "Обтачка бокового разреза", length, width, item["count"]
            )
            pattern["pieces"].append(facing)
            joins.append(
                _join(
                    pattern,
                    source,
                    target,
                    opening,
                    facing,
                    [contour_from_data(facing["seam_contour"]).segments[0]],
                )
            )
            added.append(facing["id"])
            targets.append(target["id"])
            _note(
                target,
                source,
                "Разрез: участок от низа до метки не стачивать. Сторона "
                + item.get("placement", {}).get("side", "both"),
            )
    else:
        target = _find(pattern, "back_skirt")
        contour = contour_from_data(target["seam_contour"])
        center = next(
            (
                e
                for e in contour.segments
                if isinstance(e, LineSegment)
                and abs(e.start.x_mm) < 1e-6
                and abs(e.end.x_mm) < 1e-6
            ),
            None,
        )
        if center is None or length >= center.length_mm - 40:
            raise _error("Центральный разрез требует прямой свободный центр спинки.", source)
        low = min(center.start.y_mm, center.end.y_mm)
        top = low + length
        target.update(cut_on_fold=False, cut_quantity=2, mirrored_pair=True)
        targets = [target["id"]]
        if request["garment_spec"]["garment_type"] == "skirt":
            closure = request["garment_spec"]["parameters"]["closure"]
            high = max(center.start.y_mm, center.end.y_mm)
            stop = high - (
                float(closure.get("length_mm") or 0) if closure["location"] == "center_back" else 0
            )
            if stop < top + 10:
                raise _error(
                    "Верхняя застёжка и нижний разрез должны разделяться швом минимум 1 см.",
                    source,
                    "BACK_OPENINGS_OVERLAP",
                )
            line = LineSegment(Point(0, stop), Point(0, top), f"{source}_closed_center_segment")
            target["internal_paths"].append(_path(f"{source}_closed_center", [line]))
            pair = _seam_pair(
                f"{source}_closed_center_join", target["id"], [line.id], target["id"], [line.id]
            )
            pair["copy_pairing"] = "mirrored_copies"
            pattern["seam_pairs"].append(pair)
            joins.append(pair["id"])
        if module == "back_skirt_vent_v3":
            if center.start.y_mm < center.end.y_mm:
                raise _error("Шлица требует направление центра спинки от талии к низу.", source)
            a = Point(0, top)
            b = Point(-width, top)
            c = Point(-width, low)
            end = Point(0, low)
            changed = [
                replace(center, end=a),
                LineSegment(a, b, f"{source}_vent_top"),
                LineSegment(b, c, f"{source}_vent_outer"),
                LineSegment(c, end, f"{source}_vent_hem"),
            ]
            edges = [
                e
                for original in contour.segments
                for e in (changed if original.id == center.id else [original])
            ]
            target["seam_contour"] = contour_to_data(Contour(tuple(edges), id=contour.id))
            target["notches"] = [
                n
                for n in target["notches"]
                if n["segment_id"] != center.id
                or n["distance_from_start_mm"] <= changed[0].length_mm
            ]
            target["internal_paths"].append(
                _path(f"{source}_vent_fold", [LineSegment(a, end, f"{source}_vent_fold_edge")])
            )
            _note(
                target,
                source,
                f"Цельнокроеная шлица: две зеркальные половины с расширением {width:g} мм. Слева подгибка, справа нахлёст. Стачать центр только выше шлицы; верх закрепить поперечной строчкой.",
            )
            _record(
                pattern,
                item,
                "vent",
                targets,
                [],
                [],
                {"vent_top_y": top, "added_area": width * length},
            )
            return
        line = LineSegment(Point(0, low), Point(0, top), f"{source}_center_slit_edge")
        target["internal_paths"].append(_path(f"{source}_center_slit", [line]))
        facing = _rectangle(
            f"{source}_center_facing", "Обтачки центрального разреза юбки", length, width, 2
        )
        pattern["pieces"].append(facing)
        joins += [
            _join(
                pattern,
                source,
                target,
                [line],
                facing,
                [contour_from_data(facing["seam_contour"]).segments[0]],
            )
        ]
        added = [facing["id"]]
        _note(
            target,
            source,
            "Кроить две зеркальные половины. Не стачивать отмеченный нижний разрез; центральный шов выше разреза сохраняется.",
        )
    _record(pattern, item, "slit", targets, added, joins, {"opening_length": length})


def _straps(pattern, item):
    source, d = item["source_element_id"], item["dimensions_mm"]
    width, length = d["width"], d["length"]
    pid = f"{source}_straps"
    piece = _rectangle(pid, "Плечевые бретели", length, 2 * width, 2)
    piece["internal_paths"].append(
        _path(
            f"{source}_strap_fold",
            [LineSegment(Point(0, width), Point(length, width), f"{source}_strap_fold_edge")],
        )
    )
    pattern["pieces"].append(piece)
    joins = []
    targets = []
    for prefix, end_name in [("front", "end_left"), ("back", "end_right")]:
        records = boundary_records(pattern, f'{prefix}_bodice', 'neckline', source)
        candidates = [(target, edges) for target, edges in records
                      if len(edges) == 1 and isinstance(edges[0], LineSegment)
                      and min(edges[0].start.x_mm, edges[0].end.x_mm) <= d['spacing']
                      and max(edges[0].start.x_mm, edges[0].end.x_mm) >= d['spacing'] + width]
        if len(candidates) != 1:
            raise _error("Для бретели нужен прямой верх лифа.", source)
        target, edges = candidates[0]
        edge = edges[0]
        center = Point(0, edge.start.y_mm)
        start = Point(d["spacing"], center.y_mm)
        end = Point(d["spacing"] + width, center.y_mm)
        anchor = _anchor(target, [LineSegment(start, end, f"{source}_{prefix}_strap")], source)
        cut_edge = next(
            e
            for e in contour_from_data(piece["seam_contour"]).segments
            if e.id == f"{pid}_{end_name}"
        )
        joins.append(
            _join(
                pattern,
                f"{source}_{prefix}",
                target,
                anchor,
                piece,
                [cut_edge],
                detail_reduction=width,
            )
        )
        targets.append(target["id"])
    _note(
        piece,
        source,
        f"Сложить вдоль до готовой ширины {width:g} мм. Длина между срезами {length:g} мм; притачать концами к меткам переда и спинки. До окончательной строчки проверить длину на человеке.",
    )
    _record(pattern, item, "strap", targets, [pid], joins, {"cut_width": 2 * width})


def _boundary_hits(contour, line, source, half_side=None):
    direction = line.end - line.start
    hits = []
    for i, edge in enumerate(contour.segments):

        def f(t):
            return (edge.point_at(t) - line.start).cross(direction)

        previous = f(0)
        roots = []
        for k in range(1, 257):
            a, b = (k - 1) / 256, k / 256
            current = f(b)
            if abs(previous) < 1e-7:
                roots.append(a)
            elif previous * current < 0:
                for _ in range(45):
                    m = (a + b) / 2
                    if f(a) * f(m) <= 0:
                        b = m
                    else:
                        a = m
                roots.append((a + b) / 2)
            previous = current
        if abs(f(1)) < 1e-7:
            roots.append(1.0)
        for t in roots:
            p = edge.point_at(t)
            if half_side == 'right' and p.x_mm < -1e-6 or half_side == 'left' and p.x_mm > 1e-6:
                continue
            if not any(p.distance_to(h[2]) < 0.01 for h in hits):
                hits.append((i, t, p))
    if len(hits) != 2:
        raise _error(
            "Линия членения должна пересекать контур ровно в двух точках.",
            source,
            "STRUCTURAL_CUT_INTERSECTIONS",
        )
    return sorted(hits, key=lambda h: h[0])


def _point_on(edge, p):
    points = curve_points(edge, 0.02)
    return any(
        abs(p.distance_to(a) + p.distance_to(b) - a.distance_to(b)) < 0.02
        for (_, a), (_, b) in zip(points, points[1:])
    )


def _dart_reduction(piece, edges):
    total = sum(e.length_mm for e in edges if '_bridge_' in e.id)
    for path in piece["internal_paths"]:
        if "dart" not in path["id"]:
            continue
        dart = contour_from_data(path)
        a, b = dart.segments[0].start, dart.segments[-1].end
        if any(_point_on(e, a) for e in edges) and any(_point_on(e, b) for e in edges):
            if all(isinstance(e, LineSegment) for e in edges):
                total += a.distance_to(b)
            else:
                # Curve opening: use the exact partial boundary lengths.
                from .topology import _nearest_parameter, _partial_curve_length

                e = next(
                    (
                        e
                        for e in edges
                        if isinstance(e, CubicBezier) and _point_on(e, a) and _point_on(e, b)
                    ),
                    None,
                )
                if e:
                    total += abs(
                        _partial_curve_length(e, _nearest_parameter(e, a))
                        - _partial_curve_length(e, _nearest_parameter(e, b))
                    )
    return total


def _split_source(pattern, target, parts, item, absorbed=0):
    """Preserve external edges, split existing joins and keep reductions at darts."""
    source = item["source_element_id"]
    owners = {}
    for piece, fragments in parts:
        for original, edge, offset in fragments:
            owners.setdefault(original, []).append((piece, edge, offset))
    for original in owners:
        owners[original].sort(key=lambda rec: rec[2])
    old_pairs = [
        p
        for p in pattern["seam_pairs"]
        if target["id"] in (p["first_piece_id"], p["second_piece_id"])
    ]
    for pair in old_pairs:
        side = "first" if pair["first_piece_id"] == target["id"] else "second"
        other = "second" if side == "first" else "first"
        groups = []
        for sid in pair[f"{side}_segment_ids"]:
            for owner, e, offset in owners.get(sid, []):
                if groups and groups[-1][0]["id"] == owner["id"]:
                    groups[-1][1].append(e)
                else:
                    groups.append((owner, [e]))
        if not groups:
            raise _error("Членение потеряло исходный срез соединения.", source)
        if len(groups) == 1:
            owner, edges = groups[0]
            pair[f"{side}_piece_id"] = owner["id"]
            pair[f"{side}_segment_ids"] = [e.id for e in edges]
            if absorbed and any("_waist" in sid for sid in pair[f"{side}_segment_ids"]):
                pair[f"{side}_length_reduction_mm"] = 0
            continue
        opposite = _find(pattern, pair[f"{other}_piece_id"])
        all_opp = {
            e.id: e
            for path in [opposite["seam_contour"], *opposite["internal_paths"]]
            for e in contour_from_data(path).segments
        }
        opp_edges = [all_opp[sid] for sid in pair[f"{other}_segment_ids"]]
        original_edges = {e.id: e for e in contour_from_data(target["seam_contour"]).segments}
        own_chain = [original_edges[sid] for sid in pair[f"{side}_segment_ids"]]
        own_direction = own_chain[-1].end - own_chain[0].start
        opp_direction = opp_edges[-1].end - opp_edges[0].start
        if own_direction.dot(opp_direction) < 0:
            opp_edges = [e.reversed() for e in reversed(opp_edges)]
        own_reductions = [_dart_reduction(p, edges) for p, edges in groups]
        original_r = pair[f"{side}_length_reduction_mm"] - (
            absorbed if any("_waist" in sid for sid in pair[f"{side}_segment_ids"]) else 0
        )
        if abs(sum(own_reductions) - original_r) > 1:
            raise _error(
                "Членение не может распределить раствор исходного шва; выберите линию вне складки или сборки.",
                source,
                "STRUCTURAL_JOIN_REDUCTION",
            )
        opp_total = sum(e.length_mm for e in opp_edges)
        opp_r = pair[f"{other}_length_reduction_mm"]
        cursor = 0.0
        allocated_r = 0.0
        newpairs = []
        # Determine dart intervals on the opposite boundary in its traversal order.
        intervals = []
        base = 0.0
        for e in opp_edges:
            for path in opposite["internal_paths"]:
                if "dart" not in path["id"]:
                    continue
                dart = contour_from_data(path)
                a, b = dart.segments[0].start, dart.segments[-1].end
                if isinstance(e, LineSegment) and _point_on(e, a) and _point_on(e, b):
                    lo, hi = sorted([e.start.distance_to(a), e.start.distance_to(b)])
                    intervals.append((base + lo, base + hi))
            base += e.length_mm
        if opp_r and abs(sum(b - a for a, b in intervals) - opp_r) > 1:
            raise _error(
                "Сопряжённый раствор требует отдельной совместимости членения.",
                source,
                "STRUCTURAL_OPPOSITE_REDUCTION",
            )
        own_eff = sum(
            sum(e.length_mm for e in edges) - r for (_, edges), r in zip(groups, own_reductions)
        )
        opp_eff = opp_total - opp_r
        for index, ((owner, edges), r) in enumerate(zip(groups, own_reductions)):
            own_length = sum(e.length_mm for e in edges) - r
            eff = own_length * opp_eff / own_eff
            end = cursor + eff
            rr = 0.0
            if index == len(groups) - 1:
                end = opp_total
                rr = opp_r - allocated_r
            else:
                for _ in range(8):
                    rr = sum(b - a for a, b in intervals if a >= cursor - 0.01 and a < end - 0.01)
                    new_end = cursor + eff + rr
                    if abs(end - new_end) < 1e-7:
                        break
                    end = new_end
                if any(a + 0.01 < end < b - 0.01 for a, b in intervals):
                    raise _error("Линия членения попала внутрь сопряжённой вытачки.", source)
            pieces = _slice_distance(opp_edges, cursor, end - cursor, source)
            renamed = [
                replace(e, id=f"{source}_{pair['id']}_{index}_{j}") for j, e in enumerate(pieces)
            ]
            opposite["internal_paths"].append(
                _path(f"{source}_{pair['id']}_{index}_match", renamed)
            )
            copy = deepcopy(pair)
            copy["id"] = f"{pair['id']}_{source}_{index}"
            copy[f"{side}_piece_id"] = owner["id"]
            copy[f"{side}_segment_ids"] = [e.id for e in edges]
            copy[f"{side}_length_reduction_mm"] = r
            copy[f"{other}_segment_ids"] = [e.id for e in renamed]
            copy[f"{other}_length_reduction_mm"] = rr
            copy["allowed_ease_mm"] = abs(own_length - eff)
            newpairs.append(copy)
            cursor = end
            allocated_r += rr
        i = pattern["seam_pairs"].index(pair)
        pattern["seam_pairs"][i : i + 1] = newpairs
    i = pattern["pieces"].index(target)
    pattern["pieces"][i : i + 1] = [p for p, _ in parts]
    # Existing operation references need to identify every resulting cut piece.
    for key in ("modeling_operations", "topology_operations", "composite_operations"):
        for op in pattern.get(key, []):
            params = op.get('parameters_mm', {})
            for original, fragments in owners.items():
                if f'{original}_start_x' not in params:
                    continue
                for end in ('start','end','control_1','control_2'):
                    for axis in ('x','y'):
                        params.pop(f'{original}_{end}_{axis}', None)
                for _, edge, _ in fragments:
                    for end in ('start','end', *(['control_1','control_2'] if isinstance(edge, CubicBezier) else [])):
                        point = getattr(edge,end)
                        params[f'{edge.id}_{end}_x'] = point.x_mm
                        params[f'{edge.id}_{end}_y'] = point.y_mm
            for field in ("target_piece_ids", "added_piece_ids"):
                if target["id"] in op.get(field, []):
                    op[field] = list(
                        dict.fromkeys(
                            pid
                            for original in op[field]
                            for pid in (
                                [p["id"] for p, _ in parts]
                                if original == target["id"]
                                else [original]
                            )
                        )
                    )


def _make_part(target, contour, pid, name, source):
    piece = deepcopy(target)
    piece.update(id=pid, name_ru=name, seam_contour=contour_to_data(contour), cutting_contour=None)
    polygon = [p for e in contour.segments for _, p in curve_points(e, 0.03)[:-1]]

    def inside(p):
        return _inside(p, polygon) or any(_point_on(e, p) for e in contour.segments)

    paths = []
    for path in target["internal_paths"]:
        shape = contour_from_data(path)
        allinside = all(inside(e.point_at(t / 20)) for e in shape.segments for t in range(21))
        anyinside = any(
            _inside(e.point_at(t / 20), polygon) for e in shape.segments for t in range(21)
        )
        if allinside:
            paths.append(deepcopy(path))
        elif "dart" not in path["id"]:
            from .geometry.intersections import intersections
            from .geometry.errors import OverlappingGeometryError

            clipped = []
            for line in shape.segments:
                roots = [0.0, 1.0]
                for border in contour.segments:
                    try:
                        roots += [h.first_parameter for h in intersections(line, border)]
                    except OverlappingGeometryError:
                        pass
                roots = sorted(set(round(t, 10) for t in roots))
                for i, (a, b) in enumerate(zip(roots, roots[1:])):
                    if b - a > 1e-7 and inside(line.point_at((a + b) / 2)):
                        clipped.append(
                            replace(_subcurve(line, a, b), id=f"{line.id}_{source}_{pid}_{i}")
                        )
            if clipped:
                paths.append(_path(f"{path['id']}_{source}_{pid}", clipped))
        elif anyinside and "dart" in path["id"]:
            raise _error(
                "Членение пересекает раствор вытачки. Измените глубину или расположение шва.",
                source,
                "STRUCTURAL_CUT_DART_CONFLICT",
            )
    piece["internal_paths"] = paths
    piece["notches"] = []
    piece["annotations"] = []
    # Centre/fold identity survives only on the piece with an original fold boundary.
    fold = any(
        abs(e.start.x_mm) < 1e-6 and abs(e.end.x_mm) < 1e-6 and isinstance(e, LineSegment)
        for e in contour.segments
    )
    piece["cut_on_fold"] = target["cut_on_fold"] and fold
    piece["cut_quantity"] = target["cut_quantity"] if piece["cut_on_fold"] else _quantity(target)
    piece["mirrored_pair"] = not piece["cut_on_fold"] and piece["cut_quantity"] == 2
    box = contour.bounding_box
    piece["grainline"] = {
        "start": [box.min_x_mm + box.width_mm * 0.5, box.min_y_mm + box.height_mm * 0.3],
        "end": [box.min_x_mm + box.width_mm * 0.5, box.min_y_mm + box.height_mm * 0.7],
    }
    _note(piece, source, name + "; соединить по парному срезу.")
    return piece


def _cut(pattern, item, line, kind, half_side=None):
    source = item["source_element_id"]
    target = _find(pattern, _target_id(item["location"]))
    contour = contour_from_data(target["seam_contour"])
    (ai, at, a), (bi, bt, b) = _boundary_hits(contour, line, source, half_side)
    _check_line(target, LineSegment(a, b), source, boundary=True)

    # Arc A goes forward from A to B; arc B wraps around the remaining original outline.
    def arc(indices, start_t, end_t, label):
        edges = []
        fragments = []
        for j, index in enumerate(indices):
            original = contour.segments[index]
            lo = start_t if j == 0 else 0
            hi = end_t if j == len(indices) - 1 else 1
            if hi - lo < 1e-8:
                continue
            edge = _subcurve(original, lo, hi)
            if lo > 1e-8 or hi < 1 - 1e-8:
                edge = replace(edge, id=f"{original.id}_{source}_{label}")
            edges.append(edge)
            fragments.append(
                (original.id, edge, _subcurve(original, 0, lo).length_mm if lo > 1e-8 else 0.0)
            )
        return edges, fragments

    first, fa = arc(list(range(ai, bi + 1)), at, bt, "a")
    second, fb = arc([*range(bi, len(contour.segments)), *range(0, ai + 1)], bt, at, "b")
    ca = Contour(tuple([*first, LineSegment(b, a, f"{source}_cut_a")]), id=f"{source}_a_seam")
    cb = Contour(tuple([*second, LineSegment(a, b, f"{source}_cut_b")]), id=f"{source}_b_seam")
    for c in (ca, cb):
        validate_simple_contour(c)
    # Keep the waist-containing piece's ID for downstream waist operations.
    keep_a = any(e.id.endswith("_waist") for e in first)
    if kind == "panel":
        keep_a = any(
            isinstance(e, LineSegment) and abs(e.start.x_mm) < 1e-6 and abs(e.end.x_mm) < 1e-6
            for e in first
        )
    pa = _make_part(
        target,
        ca,
        target["id"] if keep_a else f"{target['id']}__{source}",
        f"{target['name_ru']} · {kind} A",
        source,
    )
    pb = _make_part(
        target,
        cb,
        f"{target['id']}__{source}" if keep_a else target["id"],
        f"{target['name_ru']} · {kind} B",
        source,
    )
    _carry_notches(target, [(pa, fa), (pb, fb)])
    _split_source(pattern, target, [(pa, fa), (pb, fb)], item)
    pair = _seam_pair(
        f"{source}_cut_join", pa["id"], [f"{source}_cut_a"], pb["id"], [f"{source}_cut_b"]
    )
    pattern["seam_pairs"].append(pair)
    for piece, edge_id in [(pa, f"{source}_cut_a"), (pb, f"{source}_cut_b")]:
        piece["notches"].append(
            dict(
                id=f"{source}_{piece['id']}_join_notch",
                match_id=pair["id"],
                segment_id=edge_id,
                distance_from_start_mm=a.distance_to(b) / 2,
                kind="double",
            )
        )
    _record(
        pattern,
        item,
        kind,
        [target["id"]],
        [p["id"] for p in (pa, pb) if p["id"] != target["id"]],
        [pair["id"]],
        {"cut_length": a.distance_to(b)},
    )


def _carry_notches(target, parts):
    for notch in target["notches"]:
        for piece, fragments in parts:
            for original, e, offset in fragments:
                d = notch["distance_from_start_mm"]
                if (
                    original == notch["segment_id"]
                    and offset - 0.001 <= d <= offset + e.length_mm + 0.001
                ):
                    n = deepcopy(notch)
                    n.update(
                        id=f"{notch['id']}_{piece['id']}",
                        segment_id=e.id,
                        distance_from_start_mm=max(0, min(e.length_mm, d - offset)),
                    )
                    piece["notches"].append(n)
                    break


def prepare_structural_foundation(pattern, request):
    result = deepcopy(dict(pattern))
    for item in _active(request):
        d, module = item["dimensions_mm"], item["module_id"]
        if module not in FOUNDATION:
            continue
        if module in {"side_skirt_slit_v3", "back_skirt_slit_v3", "back_skirt_vent_v3"}:
            _slit(result, item, request)
        elif module == "straight_shoulder_straps_v3":
            from .advanced import _open_shoulders

            before = len(result.get("composite_operations", []))
            _open_shoulders(result, item)
            result["composite_operations"] = result.get("composite_operations", [])[:before]
        elif module in {"front_bodice_yoke_v3", "back_bodice_yoke_v3"}:
            target = _find(result, _target_id(item["location"]))
            box = contour_from_data(target["seam_contour"]).bounding_box
            y = box.max_y_mm - d["depth"]
            delta = d.get("width") or 0
            line = LineSegment(Point(0, y), Point(box.max_x_mm, y - delta))
            try:
                _boundary_hits(contour_from_data(target['seam_contour']), line, item['source_element_id'])
            except BlockConstructionError as error:
                if box.min_x_mm >= -1 or error.code != 'STRUCTURAL_CUT_INTERSECTIONS':
                    raise
                for side in ('right', 'left'):
                    source = item['source_element_id']
                    copied = {**item, 'source_element_id': source + '_' + side}
                    cut_line = line if side == 'right' else LineSegment(Point(0,y), Point(box.min_x_mm,y-delta))
                    _cut(result, copied, cut_line, 'yoke', side)
                    result['composite_operations'][-1]['source_id'] = source
            else:
                _cut(result, item, line, 'yoke')
        elif module == "offset_skirt_panel_v3":
            target = _find(result, _target_id(item["location"]))
            box = contour_from_data(target["seam_contour"]).bounding_box
            x = d["width"]
            delta = d.get("depth") or 0
            _cut(
                result,
                item,
                LineSegment(Point(x, box.max_y_mm), Point(x + delta, box.min_y_mm)),
                "panel",
            )
        elif module == "shoulder_princess_seam_v3":
            _princess(result, item)
        elif module == "side_to_waist_dart_v3":
            _reverse_dart(result, item)
    return result


def _princess(pattern, item):
    source = item["source_element_id"]
    target = _find(pattern, _target_id(item["location"]))
    contour = contour_from_data(target["seam_contour"])
    waist = next(e for e in contour.segments if e.id.endswith("_waist"))
    shoulder = next(e for e in contour.segments if e.id.endswith("_shoulder"))
    dart_path = next((p for p in target["internal_paths"] if "waist_dart" in p["id"]), None)
    if (
        dart_path is None
        or not isinstance(waist, LineSegment)
        or not isinstance(shoulder, LineSegment)
    ):
        raise _error("Рельеф требует исходную талиевую вытачку и прямое плечо.", source)
    dart = contour_from_data(dart_path)
    a, apex, b = dart.segments[0].start, dart.segments[0].end, dart.segments[-1].end
    if a.x_mm > b.x_mm:
        a, b = b, a
    spacing = item["dimensions_mm"]["spacing"]
    if spacing >= shoulder.length_mm - 15:
        raise _error("На внешнем конце плеча должно остаться минимум 1,5 см.", source)
    t = 1 - spacing / shoulder.length_mm
    upper = shoulder.point_at(t)
    wi = contour.segments.index(waist)
    si = contour.segments.index(shoulder)
    if wi != 0 or si < 2:
        raise _error("Исходный контур рельефа уже изменён другой операцией.", source)
    left_waist = LineSegment(waist.start, a, f"{waist.id}_{source}_center")
    right_waist = LineSegment(b, waist.end, f"{waist.id}_{source}_side")
    shoulder_outer = replace(_subcurve(shoulder, 0, t), id=f"{shoulder.id}_{source}_side")
    shoulder_inner = replace(_subcurve(shoulder, t, 1), id=f"{shoulder.id}_{source}_center")
    # The two waist-dart legs become the lower part of the actual princess seam.
    centre_edges = [
        left_waist,
        LineSegment(a, apex, f"{source}_center_lower"),
        LineSegment(apex, upper, f"{source}_center_upper"),
        shoulder_inner,
        *contour.segments[si + 1 :],
    ]
    side_edges = [
        right_waist,
        *contour.segments[1:si],
        shoulder_outer,
        LineSegment(upper, apex, f"{source}_side_upper"),
        LineSegment(apex, b, f"{source}_side_lower"),
    ]
    cc = Contour(tuple(centre_edges), id=contour.id)
    sc = Contour(tuple(side_edges), id=f"{source}_side_seam")
    for c in (cc, sc):
        validate_simple_contour(c)
    # Do not retain the dart which is now consumed by this cut seam.
    reduced = deepcopy(target)
    reduced["internal_paths"] = [p for p in target["internal_paths"] if p["id"] != dart_path["id"]]
    centre = _make_part(
        reduced, cc, target["id"], target["name_ru"] + " · центральная часть рельефа", source
    )
    side = _make_part(
        reduced,
        sc,
        f"{target['id']}__{source}",
        target["name_ru"] + " · боковая часть рельефа",
        source,
    )
    cf = [
        (waist.id, left_waist, 0.0),
        (shoulder.id, shoulder_inner, shoulder.length_mm - spacing),
        *[(e.id, e, 0.0) for e in contour.segments[si + 1 :]],
    ]
    sf = [
        (waist.id, right_waist, waist.start.distance_to(b)),
        *[(e.id, e, 0.0) for e in contour.segments[1:si]],
        (shoulder.id, shoulder_outer, 0.0),
    ]
    _carry_notches(target, [(centre, cf), (side, sf)])
    _split_source(pattern, target, [(centre, cf), (side, sf)], item, absorbed=a.distance_to(b))
    residual = abs(a.distance_to(apex) - b.distance_to(apex))
    if residual > 1:
        raise _error(
            "Нижние срезы рельефа расходятся более чем на 1 мм. Для этой вытачки требуется дополнительное выравнивание.",
            source,
        )
    pair = _seam_pair(
        f"{source}_princess_join",
        centre["id"],
        [f"{source}_center_lower", f"{source}_center_upper"],
        side["id"],
        [f"{source}_side_lower", f"{source}_side_upper"],
    )
    pattern["seam_pairs"].append(pair)
    _record(
        pattern,
        item,
        "princess_seam",
        [centre["id"]],
        [side["id"]],
        [pair["id"]],
        {"absorbed_intake": a.distance_to(b), "dart_leg_residual": residual},
    )


def _reverse_dart(pattern, item):
    """Rotate the lower outer panel about the bust apex and open a waist dart.

    A rigid rotation preserves the closed side and waist seam lengths. The new
    waist intake is measured from the rotated gap rather than copied from the
    side: radii at the two openings differ.
    """
    from .topology import (
        _pair_for_segment,
        _nearest_parameter,
        _parameter_at_length,
        _partial_curve_length,
    )

    source = item["source_element_id"]
    target = _find(pattern, "front_bodice")
    contour = contour_from_data(target["seam_contour"])
    waist = next(e for e in contour.segments if e.id == "front_waist")
    side = next(e for e in contour.segments if e.id == "front_side")
    if not isinstance(waist, LineSegment) or not isinstance(side, CubicBezier):
        raise _error("Перенос требует целый перед с прямой талией и боковой вытачкой.", source)
    path = next(p for p in target["internal_paths"] if p["id"] == "front_side_dart")
    dart = contour_from_data(path)
    lower, apex, upper = dart.segments[0].start, dart.segments[0].end, dart.segments[-1].end
    side_pair, side_key = _pair_for_segment(pattern, "front_bodice", "front_side", source)
    waist_pair, waist_key = _pair_for_segment(pattern, "front_bodice", "front_waist", source)
    old_intake = side_pair[f"{side_key}_length_reduction_mm"]
    wanted = old_intake - item["dimensions_mm"]["width"]
    if wanted <= 1:
        raise _error("В боковой вытачке должен остаться минимум 1 мм раствора.", source)

    # Locate endpoints by arc distance; refine the nearest flattened parameter.
    def nearest(p):
        t = _nearest_parameter(side, p)
        lo, hi = max(0, t - 0.05), min(1, t + 0.05)
        for _ in range(60):
            a, b = (2 * lo + hi) / 3, (lo + 2 * hi) / 3
            if side.point_at(a).distance_to(p) < side.point_at(b).distance_to(p):
                hi = b
            else:
                lo = a
        return (lo + hi) / 2

    lo_t, _ = sorted([nearest(lower), nearest(upper)])
    lower = side.point_at(lo_t)
    # Match the retained side reduction exactly, including numerical block rounding.
    upper_t = _parameter_at_length(side, _partial_curve_length(side, lo_t) + old_intake)
    upper = side.point_at(upper_t)
    q = Point(apex.x_mm, waist.start.y_mm)
    for p in target["internal_paths"]:
        if "waist_dart" in p["id"]:
            legs = contour_from_data(p).segments
            if max(legs[0].start.x_mm, legs[-1].end.x_mm) >= q.x_mm - 5:
                raise _error("Новый перенос пересекает исходную талиевую вытачку.", source)
    angle = math.atan2((upper - apex).dy_mm, (upper - apex).dx_mm) - math.atan2(
        (lower - apex).dy_mm, (lower - apex).dx_mm
    )

    def rotate(p, theta):
        dx, dy = p.x_mm - apex.x_mm, p.y_mm - apex.y_mm
        return Point(
            apex.x_mm + dx * math.cos(theta) - dy * math.sin(theta),
            apex.y_mm + dx * math.sin(theta) + dy * math.cos(theta),
        )

    if angle <= 0 or angle >= math.pi / 2:
        raise _error("Для этого раствора направление поворота требует отдельной рецептуры.", source)
    if rotate(lower, angle).distance_to(upper) > wanted:
        raise _error("Заданный перенос больше доступного раствора между радиусами вытачки.", source)
    low, high = 0.0, angle
    for _ in range(60):
        mid = (low + high) / 2
        if rotate(lower, mid).distance_to(upper) > wanted:
            low = mid
        else:
            high = mid
    theta = (low + high) / 2
    qr = rotate(q, theta)
    outer = rotate(waist.end, theta)
    lower_curve = _subcurve(side, 0, lo_t)
    rotated = CubicBezier(
        rotate(lower_curve.start, theta),
        rotate(lower_curve.control_1, theta),
        rotate(lower_curve.control_2, theta),
        rotate(lower_curve.end, theta),
        f"{source}_side_lower",
    )
    upper_curve = replace(_subcurve(side, upper_t, 1), id=f"{source}_side_upper")
    gap = LineSegment(rotated.end, upper, f"{source}_side_opening")
    waist_edges = [
        LineSegment(waist.start, q, f"{source}_waist_inner"),
        LineSegment(q, qr, f"{source}_waist_opening"),
        LineSegment(qr, outer, f"{source}_waist_outer"),
    ]
    side_edges = [rotated, gap, upper_curve]
    new = Contour(tuple([*waist_edges, *side_edges, *contour.segments[2:]]), id=contour.id)
    validate_simple_contour(new)
    target["seam_contour"] = contour_to_data(new)
    waist_pair[f"{waist_key}_segment_ids"] = [e.id for e in waist_edges]
    waist_pair[f"{waist_key}_length_reduction_mm"] += q.distance_to(qr)
    side_pair[f"{side_key}_segment_ids"] = [e.id for e in side_edges]
    side_pair[f"{side_key}_length_reduction_mm"] = gap.length_mm
    target["internal_paths"] = [
        p for p in target["internal_paths"] if p["id"] not in {"front_side_dart", "front_bust_line"}
    ]
    target["internal_paths"].append(
        _path(
            "front_side_dart",
            [
                LineSegment(rotated.end, apex, f"{source}_side_dart_1"),
                LineSegment(apex, upper, f"{source}_side_dart_2"),
            ],
        )
    )
    target["internal_paths"].append(
        _path(
            f"{source}_new_waist_dart",
            [
                LineSegment(q, apex, f"{source}_new_waist_dart_1"),
                LineSegment(apex, qr, f"{source}_new_waist_dart_2"),
            ],
        )
    )
    for notch in target["notches"]:
        if notch["segment_id"] == waist.id:
            distance = notch["distance_from_start_mm"]
            segment = waist_edges[0] if distance <= waist.start.distance_to(q) else waist_edges[2]
            notch["segment_id"] = segment.id
            notch["distance_from_start_mm"] = (
                distance if segment == waist_edges[0] else distance - waist.start.distance_to(q)
            )
        elif notch["segment_id"] == side.id:
            distance = notch["distance_from_start_mm"]
            lower_length = lower_curve.length_mm
            if distance <= lower_length:
                segment = rotated
                d = distance
            elif distance >= lower_length + old_intake:
                segment = upper_curve
                d = distance - lower_length - old_intake
            else:
                segment = gap
                d = (distance - lower_length) / old_intake * gap.length_mm
            notch["segment_id"] = segment.id
            notch["distance_from_start_mm"] = d
    _note(
        target,
        source,
        f"Поворот вокруг вершины груди: боковой раствор уменьшен на {item['dimensions_mm']['width']:g} мм; открыта новая талиевая вытачка {q.distance_to(qr):.2f} мм. Исходная талиевая вытачка сохраняется; закрыть обе.",
    )
    _record(
        pattern,
        item,
        "dart",
        [target["id"]],
        [],
        ["front_side_dart", f"{source}_new_waist_dart", side_pair["id"], waist_pair["id"]],
        {
            "transferred_side_intake": item["dimensions_mm"]["width"],
            "opened_waist_intake": q.distance_to(qr),
            "rotation_degrees": math.degrees(theta),
        },
    )

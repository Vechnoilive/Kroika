"""Bounded draped overlays, open shoulders and measured silhouette changes.

All lengths refer to seam lines. The modules retain the fitted foundation;
fullness is added to separate draped panels, never guessed from an image.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
from typing import Any, Mapping

from kroika_contracts.design_modules import ADVANCED_ELEMENT_MODULES
from .composites import CompositeResult, _operation, _pair_residual, _seam_pair
from .details import _error, _find, _inside, _new_piece, _path, _rectangle, _crosses
from .geometry import (
    ArcSegment,
    Contour,
    CubicBezier,
    LineSegment,
    Point,
    contour_from_data,
    contour_to_data,
)
from .geometry.primitives import curve_points


def _active(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    intent = request["garment_spec"].get("design_intent") or {}
    return sorted(
        [
            item
            for item in intent.get("elements", [])
            if item.get("included") is not False
            and item.get("support_status") == "supported"
            and item.get("module_id") in ADVANCED_ELEMENT_MODULES
        ],
        key=lambda item: (item["module_id"], item["source_element_id"]),
    )


def prepare_proportions(request: Mapping[str, Any]) -> dict[str, Any]:
    """Derive construction inputs without altering the saved anatomical measures."""
    effective = deepcopy(dict(request))
    prop = (request["garment_spec"].get("design_intent") or {}).get("proportions") or {}
    if prop.get("module_id") != "parametric_visual_proportions_v1":
        return effective
    volume = prop["volume"]
    minimum = {"fitted": 0, "regular": 0, "relaxed": 60, "voluminous": 120}[volume]
    for key in ("bust", "waist", "hips", "upper_arm"):
        effective["fit_settings"]["design_ease_mm"][key] = max(
            effective["fit_settings"]["design_ease_mm"][key],
            minimum / 2 if key == "upper_arm" else minimum,
        )
    if prop["waist_position"] != "natural":
        shift = prop["waist_shift_mm"] * (1 if prop["waist_position"] == "low" else -1)
        values = effective["body_measurements"]["values"]
        for key in ("front_neck_to_waist_over_bust", "back_neck_to_waist"):
            values[key]["value"] += shift
        values["hip_depth"]["value"] -= shift
        values["waist"]["value"] = prop["waist_level_circumference_mm"]
        values["back_waist_arc"]["value"] = prop["back_waist_level_arc_mm"]
        effective["garment_spec"]["parameters"]["skirt"]["length_from_waist_mm"] -= shift
        if values["hip_depth"]["value"] < 80:
            raise _error("Смещение талии оставляет менее 8 см до линии бёдер.", "proportions")
    return effective


def _operation_record(
    pattern: dict,
    source: str,
    kind: str,
    module: str,
    targets: list[str],
    added: list[str],
    interfaces: list[str],
    parameters: dict,
) -> None:
    op = _operation(
        source,
        "element",
        kind,
        module,
        {
            "drape": "A03-D01",
            "off_shoulder": "A03-S01",
            "cascade": "A03-F01",
            "proportions": "A03-P01",
        }[kind],
        targets,
        added,
        interfaces,
        parameters,
    )
    op["operation_id"] = f"advanced_{source}_{kind}"
    pattern.setdefault("composite_operations", []).append(op)


def apply_silhouette(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(pattern))
    active = _active(request)
    modules = [item["module_id"] for item in active]
    if len(modules) != len(set(modules)):
        raise _error(
            "Одну сложную конструкцию нельзя назначить дважды.",
            "elements",
            "ADVANCED_TARGET_CONFLICT",
        )
    for item in active:
        if item["module_id"] == "off_shoulder_bands_v1":
            _open_shoulders(result, item)
    prop = (request["garment_spec"].get("design_intent") or {}).get("proportions") or {}
    if prop.get("module_id") == "parametric_visual_proportions_v1":
        if prop["hem_shape"] != "straight":
            _shape_hem(result, prop)
        if (
            prop["asymmetry"] == "yes"
            and prop["hem_shape"] != "asymmetric"
            and "vertical_cascade_flounce_v1" not in modules
        ):
            raise _error(
                "Асимметрия требует каскадного волана или разновысокого низа.",
                "proportions",
                "ASYMMETRY_GEOMETRY_REQUIRED",
            )
        targets = [
            p["id"]
            for p in result["pieces"]
            if p["id"]
            in {
                "front_bodice",
                "back_bodice",
                "front_skirt",
                "back_skirt",
                "front_trouser",
                "back_trouser",
                "base_sleeve",
            }
        ]
        params = {k: v for k, v in prop.items() if k.endswith("_mm") and v is not None}
        params["minimum_design_ease"] = {
            "fitted": 0,
            "regular": 0,
            "relaxed": 60,
            "voluminous": 120,
        }[prop["volume"]]
        params.update(
            {
                f"effective_design_{key}": value
                for key, value in request["fit_settings"]["design_ease_mm"].items()
            }
        )
        if prop["waist_position"] != "natural":
            params["signed_waist_shift"] = prop["waist_shift_mm"] * (
                1 if prop["waist_position"] == "low" else -1
            )
        _operation_record(
            result, "visual_proportions", "proportions", prop["module_id"], targets, [], [], params
        )
    return result


def _shape_hem(pattern: dict, prop: Mapping[str, Any]) -> None:
    for prefix in ("front", "back"):
        if prop["hem_shape"] == "asymmetric" and prefix == "back":
            continue
        target = _find(pattern, f"{prefix}_skirt")
        contour = contour_from_data(target["seam_contour"])
        edges = list(contour.segments)
        hem = next((edge for edge in edges if edge.id == f"{prefix}_skirt_hem"), None)
        if not isinstance(hem, LineSegment):
            raise _error("Для изменения низа нужна цельная юбочная деталь.", "proportions")
        delta = prop["hem_delta_mm"]
        if abs(hem.start.y_mm) - delta < 250:
            raise _error(
                "После изменения низа длина по центру должна быть не менее 25 см.", "proportions"
            )
        start = Point(hem.start.x_mm, hem.start.y_mm + delta)
        replacement = CubicBezier(
            start,
            Point(hem.end.x_mm * 0.35, start.y_mm),
            Point(hem.end.x_mm * 0.65, hem.end.y_mm),
            hem.end,
            hem.id,
        )
        edges[edges.index(hem)] = replacement
        center = edges[0]
        if not isinstance(center, LineSegment) or center.end != hem.start:
            raise _error("Не удалось найти центральный срез юбки.", "proportions")
        edges[0] = replace(center, end=start)
        target["seam_contour"] = contour_to_data(Contour(tuple(edges), id=contour.id))
        target["grainline"]["end"][1] = start.y_mm + 30
        target["annotations"].append(
            dict(
                id=f"{prefix}_hem_shape_note",
                text_ru=f"Подъём низа по центру {delta:g} мм.",
                position=[40, start.y_mm + 45],
            )
        )


def _trim_arm(edge: Any, height: float) -> Any:
    if not edge.start.y_mm < height < edge.end.y_mm:
        raise _error("Высота открытого верха должна пересекать нижнюю часть проймы.", "elements")
    low, high = 0.0, 1.0
    for _ in range(55):
        t = (low + high) / 2
        if edge.point_at(t).y_mm < height:
            low = t
        else:
            high = t
    return edge.split((low + high) / 2)[0]


def _open_shoulders(pattern: dict, item: Mapping[str, Any]) -> None:
    source = item["source_element_id"]
    d = item["dimensions_mm"]
    modified = []
    for prefix in ("front", "back"):
        target = _find(pattern, f"{prefix}_bodice")
        edges = list(contour_from_data(target["seam_contour"]).segments)
        arm = next(e for e in edges if e.id == f"{prefix}_armhole")
        trimmed = replace(_trim_arm(arm, arm.start.y_mm + d["depth"]), id=arm.id)
        top = LineSegment(trimmed.end, Point(0, trimmed.end.y_mm), f"{prefix}_neckline")
        center = next(e for e in edges if e.id == f"{prefix}_center")
        if not isinstance(center, LineSegment):
            raise _error("Для открытого верха нужен прямой центральный срез.", source)
        target["seam_contour"] = contour_to_data(
            Contour(
                (edges[0], edges[1], trimmed, top, replace(center, start=top.end)),
                id=f"{prefix}_bodice_seam",
            )
        )
        target["grainline"]["end"][1] = top.end.y_mm - 20
        # Old shoulder notches and references cannot survive removal of that edge.
        target["notches"] = [
            n
            for n in target["notches"]
            if n["segment_id"] != f"{prefix}_shoulder"
            and (n["segment_id"] != arm.id or n["distance_from_start_mm"] <= trimmed.length_mm)
        ]
        target["annotations"] = [
            dict(
                id=f"{prefix}_open_top_note",
                text_ru="Открытый верх: контроль посадки и удержания на макете.",
                position=[30, top.end.y_mm - 30],
            )
        ]
        facing_id = f"{prefix}_facing"
        facing = next((p for p in pattern["pieces"] if p["id"] == facing_id), None)
        if facing:
            # A narrow facing copies both remaining upper edges exactly.
            bottom_y = arm.start.y_mm - 30
            a, c, e = top.end, trimmed.start, Point(trimmed.start.x_mm, bottom_y)
            fc = Contour(
                (
                    LineSegment(Point(0, bottom_y), a, f"{facing_id}_center"),
                    replace(top.reversed(), id=f"{facing_id}_neckline"),
                    replace(trimmed.reversed(), id=f"{facing_id}_armhole"),
                    LineSegment(c, e, f"{facing_id}_side"),
                    LineSegment(e, Point(0, bottom_y), f"{facing_id}_inner"),
                ),
                id=f"{facing_id}_seam",
            )
            facing["seam_contour"] = contour_to_data(fc)
            facing["grainline"] = dict(start=[20, bottom_y + 5], end=[20, a.y_mm - 5])
            facing["annotations"] = [
                dict(
                    id=f"{facing_id}_open_note",
                    text_ru="Обтачка открытого верха.",
                    position=[60, a.y_mm - 10],
                )
            ]
            facing["notches"] = []
            modified.append(facing_id)
        modified.append(target["id"])
    pattern["seam_pairs"] = [pair for pair in pattern["seam_pairs"] if "shoulder" not in pair["id"]]
    interfaces = [pair["id"] for pair in pattern["seam_pairs"] if "facing" in pair["id"]]
    _operation_record(
        pattern,
        source,
        "off_shoulder",
        item["module_id"],
        modified,
        [],
        interfaces,
        {k: v for k, v in d.items() if v is not None},
    )


def _mirror_edge(edge: dict, prefix: str = "mirror_") -> dict:
    out = deepcopy(edge)
    out["id"] = prefix + edge["id"]
    for k in ("start", "end", "control_1", "control_2", "center"):
        if k in out:
            out[k][0] *= -1
    # Only line and Bezier geometry is unfolded by this module.
    return out


def prepare_advanced_foundation(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    """Unfold the foundation before dependent layers and neckline details are copied."""
    result = deepcopy(dict(pattern))
    if any(item["module_id"] == "crossed_bodice_drape_v1" for item in _active(request)):
        _unfold_front(result)
    return result


def _unfold_front(pattern: dict) -> dict:
    target = _find(pattern, "front_bodice")
    if not target["cut_on_fold"]:
        raise _error("Перекрёстная драпировка требует переда без центральной застёжки.", "elements")
    contour = contour_from_data(target["seam_contour"])
    edges = [e for e in contour.segments if e.id != "front_center"]
    # True the round half-neckline at the fold before unfolding: the
    # original block's vertical end tangent otherwise creates a cusp.
    for i, edge in enumerate(edges):
        if edge.id == "front_neckline" and isinstance(edge, CubicBezier):
            edges[i] = replace(edge, control_2=Point(edge.start.x_mm * 0.4, edge.end.y_mm))
            facing = next((p for p in pattern["pieces"] if p["id"] == "front_facing"), None)
            if facing:
                fc = contour_from_data(facing["seam_contour"])
                facing["seam_contour"] = contour_to_data(
                    Contour(
                        tuple(
                            replace(edges[i].reversed(), id="front_facing_neckline")
                            if e.id == "front_facing_neckline"
                            else e
                            for e in fc.segments
                        ),
                        id=fc.id,
                    )
                )
    mirror = [
        contour_from_data(
            dict(
                id="unfold",
                closed=False,
                segments=[
                    _mirror_edge(
                        contour_to_data(Contour((e,), closed=False, id="edge"))["segments"][0]
                    )
                ],
            )
        )
        .segments[0]
        .reversed()
        for e in reversed(edges)
    ]
    target["seam_contour"] = contour_to_data(Contour(tuple(edges + mirror), id=contour.id))
    target["internal_paths"] += [
        dict(
            id="mirror_" + path["id"],
            closed=path["closed"],
            segments=[_mirror_edge(edge) for edge in path["segments"]],
        )
        for path in list(target["internal_paths"])
    ]
    mirror_lengths = {edge.id: edge.length_mm for edge in mirror}
    target["notches"] += [
        {
            **notch,
            "id": "mirror_" + notch["id"],
            "segment_id": "mirror_" + notch["segment_id"],
            "distance_from_start_mm": mirror_lengths["mirror_" + notch["segment_id"]]
            - notch["distance_from_start_mm"],
        }
        for notch in list(target["notches"])
        if "mirror_" + notch["segment_id"] in mirror_lengths
    ]
    for pair in list(pattern["seam_pairs"]):
        if pair["first_piece_id"] == target["id"] and all(
            any(e.id == "mirror_" + sid for e in mirror) for sid in pair["first_segment_ids"]
        ):
            mirrored = deepcopy(pair)
            mirrored["id"] += "_mirror"
            mirrored["first_segment_ids"] = ["mirror_" + sid for sid in pair["first_segment_ids"]]
            mirrored["second_instance"] = "mirror"
            pattern["seam_pairs"].append(mirrored)
    target["cut_on_fold"] = False
    target["cut_quantity"] = 1
    target["mirrored_pair"] = False
    target["annotations"].append(
        dict(
            id="front_unfold_instruction",
            text_ru="Полный перед; кроить 1 деталь без сгиба. Драпировки перекрещиваются.",
            position=[-180, 40],
        )
    )
    return target


def _anchor(
    pattern: dict,
    target: dict,
    path_id: str,
    line: LineSegment,
    piece: dict,
    edge_id: str,
    reduction: float = 0,
) -> str:
    path = _path(path_id, [line])
    target["internal_paths"].append(path)
    pair = _seam_pair(f"{path_id}_join", target["id"], [line.id], piece["id"], [edge_id])
    pair["second_length_reduction_mm"] = reduction
    pattern["seam_pairs"].append(pair)
    # Mark center of each gather interval on both sides of the joint.
    target["notches"].append(
        dict(
            id=f"{path_id}_target_mark",
            match_id=path_id,
            segment_id=line.id,
            distance_from_start_mm=line.length_mm / 2,
            kind="single",
        )
    )
    piece["notches"].append(
        dict(
            id=f"{path_id}_panel_mark",
            match_id=path_id,
            segment_id=edge_id,
            distance_from_start_mm=(line.length_mm + reduction) / 2,
            kind="single",
        )
    )
    return pair["id"]


def _drape(pattern: dict, item: Mapping[str, Any]) -> None:
    source, d = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, "front_bodice")
    contour = contour_from_data(target["seam_contour"])
    w, extra, inset = d["width"], d["depth"], d["spacing"]
    waist = next(e for e in contour.segments if e.id == "front_waist")
    top = next(e for e in contour.segments if e.id == "front_neckline")
    shoulder = next((e for e in contour.segments if e.id == "front_shoulder"), None)
    upper_y = (shoulder.start.y_mm - 30) if shoulder else top.end.y_mm - 15
    lower_y = 20
    x = waist.end.x_mm - inset - w
    polygon = [point for edge in contour.segments for _, point in curve_points(edge, 0.05)[:-1]]
    crossings = [
        a.x_mm + (upper_y - a.y_mm) * (b.x_mm - a.x_mm) / (b.y_mm - a.y_mm)
        for a, b in zip(polygon, polygon[1:] + polygon[:1])
        if (a.y_mm > upper_y) != (b.y_mm > upper_y)
    ]
    upper_x = max(crossings, default=0) - inset - w
    if x < 80 or upper_x < 50 or upper_y < 150:
        raise _error("Лиф слишком мал для выбранной ширины и отступа драпировки.", source)
    added, interfaces = [], []
    parameters = {k: v for k, v in d.items() if v is not None}
    for index, sign in enumerate((1, -1)):
        upper = LineSegment(
            Point(sign * upper_x, upper_y),
            Point(sign * (upper_x + w), upper_y),
            f"{source}_{index}_upper",
        )
        lower = LineSegment(
            Point(-sign * x, lower_y), Point(-sign * (x + w), lower_y), f"{source}_{index}_lower"
        )
        # Fullness across the panel is gathered at both short ends.
        length = upper.point_at(0.5).distance_to(lower.point_at(0.5)) + extra / 2
        parameters[f"panel_length_{index + 1}"] = length
        pid = f"{source}_drape_{index + 1}"
        panel = _rectangle(pid, f"Перекрёстная драпировка {index + 1}", length, w + extra)
        panel["grainline"] = dict(
            start=[length * 0.25, (w + extra) / 2], end=[length * 0.75, (w + extra) / 2]
        )
        for j in range(1, 4):
            y = w / 2 + extra * j / 4
            panel["internal_paths"].append(
                _path(
                    f"{pid}_fold_{j}",
                    [LineSegment(Point(0, y), Point(length, y), f"{pid}_fold_line_{j}")],
                )
            )
        panel["annotations"][0]["text_ru"] = (
            f"Собрать оба конца с {w + extra:g} до {w:g} мм. Закрепить по меткам {index + 1}; свободный пролёт {length:.1f} мм."
        )
        pattern["pieces"].append(panel)
        interfaces += [
            _anchor(
                pattern,
                target,
                f"{source}_{index}_upper_anchor",
                upper,
                panel,
                f"{pid}_end_left",
                extra,
            ),
            _anchor(
                pattern,
                target,
                f"{source}_{index}_lower_anchor",
                lower,
                panel,
                f"{pid}_end_right",
                extra,
            ),
        ]
        added.append(pid)
    _operation_record(
        pattern,
        source,
        "drape",
        item["module_id"],
        [target["id"]],
        added,
        interfaces,
        parameters,
    )


def _bands(pattern: dict, item: Mapping[str, Any]) -> None:
    source, d = item["source_element_id"], item["dimensions_mm"]
    pid = f"{source}_arm_bands"
    band = _rectangle(pid, "Полосы вокруг верхней части рук", d["length"], d["width"], 2)
    band["annotations"][0]["text_ru"] = (
        "Кроить 2 зеркальные полосы. Концы закрепить на верхе переда и спинки; длину вокруг руки проверить на макете."
    )
    pattern["pieces"].append(band)
    interfaces, targets = [], []
    for prefix, end in [("front", "left"), ("back", "right")]:
        target = _find(pattern, f"{prefix}_bodice")
        top = next(
            e
            for e in contour_from_data(target["seam_contour"]).segments
            if e.id == f"{prefix}_neckline"
        )
        if top.length_mm < d["width"] + 20:
            raise _error("Ширина полосы не помещается на верхнем срезе лифа.", source)
        line = LineSegment(
            top.start, top.point_at(d["width"] / top.length_mm), f"{source}_{prefix}_anchor_segment"
        )
        interfaces.append(
            _anchor(pattern, target, f"{source}_{prefix}_anchor", line, band, f"{pid}_end_{end}")
        )
        if (
            prefix == "front"
            and contour_from_data(target["seam_contour"]).bounding_box.min_x_mm < 0
        ):
            mirrored_line = LineSegment(
                Point(-line.start.x_mm, line.start.y_mm),
                Point(-line.end.x_mm, line.end.y_mm),
                f"{source}_front_mirror_anchor_segment",
            )
            mirrored_id = _anchor(
                pattern,
                target,
                f"{source}_front_mirror_anchor",
                mirrored_line,
                band,
                f"{pid}_end_{end}",
            )
            next(pair for pair in pattern["seam_pairs"] if pair["id"] == mirrored_id)[
                "second_instance"
            ] = "mirror"
            interfaces.append(mirrored_id)
        targets.append(target["id"])
    op = next(op for op in pattern["composite_operations"] if op["module_id"] == item["module_id"])
    op["added_piece_ids"] += [pid]
    op["interface_ids"] += interfaces


def _cascade(pattern: dict, item: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    source, d = item["source_element_id"], item["dimensions_mm"]
    target = _find(pattern, "front_skirt")
    length, depth, x = d["length"], d["depth"], d["spacing"]
    if length > abs(contour_from_data(target["seam_contour"]).bounding_box.min_y_mm) - 10:
        raise _error(
            "Длина крепления каскада должна заканчиваться минимум на 1 см выше низа юбки.", source
        )
    if depth < request["fit_settings"]["seam_allowances_mm"]["hem"] + 10:
        raise _error("Глубина волана должна превышать припуск на низ минимум на 1 см.", source)
    radius = length / math.pi
    pid = f"{source}_cascade"
    contour = Contour(
        (
            ArcSegment.circular(Point(0, 0), radius, 0, math.pi, f"{pid}_join"),
            LineSegment(Point(-radius, 0), Point(-radius - depth, 0), f"{pid}_end_left"),
            ArcSegment.circular(Point(0, 0), radius + depth, math.pi, -math.pi, f"{pid}_hem"),
            LineSegment(Point(radius + depth, 0), Point(radius, 0), f"{pid}_end_right"),
        ),
        id=f"{pid}_seam",
    )
    piece = _new_piece(pid, "Каскадный волан от талии", contour, 1)
    piece["grainline"] = dict(
        start=[-depth / 4, radius + depth / 2], end=[depth / 4, radius + depth / 2]
    )
    piece["annotations"][0].update(
        text_ru=f"Притачать внутреннюю дугу {length:g} мм по линии каскада. Кроить 1 деталь; размещение на правой стороне переда.",
        position=[0, radius + depth / 2],
    )
    pattern["pieces"].append(piece)
    line = LineSegment(Point(x, 0), Point(x, -length), f"{source}_cascade_anchor_segment")
    interface = _anchor(pattern, target, f"{source}_cascade_anchor", line, piece, f"{pid}_join")
    target["annotations"].append(
        dict(
            id=f"{source}_side_note",
            text_ru="Каскад: метка относится только к правой стороне переда.",
            position=[x + 15, -length / 2],
        )
    )
    _operation_record(
        pattern,
        source,
        "cascade",
        item["module_id"],
        [target["id"]],
        [pid],
        [interface],
        dict(length=length, depth=depth, spacing=x, inner_radius=radius),
    )


def validate_advanced_placements(pattern: Mapping[str, Any]) -> None:
    """Keep anchors on the foundation after generation and manual contour edits."""
    for op in pattern.get("composite_operations", []):
        if op["kind"] not in {"drape", "cascade", "off_shoulder"}:
            continue
        for target_id in op["target_piece_ids"]:
            target = _find(pattern, target_id)
            contour = contour_from_data(target["seam_contour"])
            polygon = [p for edge in contour.segments for _, p in curve_points(edge, 0.05)[:-1]]
            for path in target["internal_paths"]:
                if not path["id"].startswith(op["source_id"]) or "anchor" not in path["id"]:
                    continue
                for edge in contour_from_data(path).segments:
                    if not all(
                        _inside(edge.point_at(t), polygon)
                        or any(
                            edge.point_at(t).distance_to(e.point_at(u)) < 0.1
                            for e in contour.segments
                            for u in (0.0, 1.0)
                        )
                        for t in (0.01, 0.25, 0.5, 0.75, 0.99)
                    ):
                        # Off-shoulder attachments lie on the new top boundary.
                        top = next(
                            (
                                e
                                for e in contour.segments
                                if e.id.endswith("_neckline")
                                and isinstance(e, LineSegment)
                                and min(e.start.x_mm, e.end.x_mm) - 0.01
                                <= edge.point_at(0.5).x_mm
                                <= max(e.start.x_mm, e.end.x_mm) + 0.01
                            ),
                            None,
                        )
                        if not (
                            op["kind"] == "off_shoulder"
                            and isinstance(top, LineSegment)
                            and all(
                                abs(p.y_mm - top.start.y_mm) < 0.01 for p in (edge.start, edge.end)
                            )
                            and max(edge.start.x_mm, edge.end.x_mm)
                            <= max(top.start.x_mm, top.end.x_mm) + 0.01
                            and min(edge.start.x_mm, edge.end.x_mm)
                            >= min(top.start.x_mm, top.end.x_mm) - 0.01
                        ):
                            raise _error(
                                "Метка крепления вышла за контур основы.",
                                op["source_id"],
                                "ADVANCED_ANCHOR_OUTSIDE",
                            )
                    if op["kind"] in {"cascade", "drape"}:
                        for dart in target["internal_paths"]:
                            if (
                                "dart" in dart["id"]
                                and isinstance(edge, LineSegment)
                                and any(
                                    _crosses(edge, e)
                                    for e in contour_from_data(dart).segments
                                    if isinstance(e, LineSegment)
                                )
                            ):
                                raise _error(
                                    "Линия крепления сложной детали пересекает вытачку.",
                                    op["source_id"],
                                    "ADVANCED_ANCHOR_DART_CONFLICT",
                                )


def apply_advanced_details(
    pattern: Mapping[str, Any], request: Mapping[str, Any]
) -> CompositeResult:
    result = deepcopy(dict(pattern))
    before, pairs = len(result["pieces"]), len(result["seam_pairs"])
    for item in _active(request):
        if item["module_id"] == "crossed_bodice_drape_v1":
            _drape(result, item)
        elif item["module_id"] == "off_shoulder_bands_v1":
            _bands(result, item)
        else:
            _cascade(result, item, request)
    validate_advanced_placements(result)
    residual = _pair_residual(result)
    if residual > 1:
        raise _error(
            "Соединения сложных деталей вышли за допуск 1 мм.",
            "elements",
            "ADVANCED_INTERFACE_MISMATCH",
        )
    for op in result.get("composite_operations", []):
        if op["module_id"] in ADVANCED_ELEMENT_MODULES:
            op["invariant_residual_mm"] = residual
    return CompositeResult(
        result,
        len(_active(request)),
        len(result["pieces"]) - before,
        len(result["seam_pairs"]) - pairs,
        residual,
    )

"""Measured center-back openings, loop closures and printable sewing evidence."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from .blocks import BlockConstructionError
from .composites import _operation, _seam_pair, _interface_residual
from .details import _rectangle, _path
from .geometry import LineSegment, Point, Contour, contour_from_data, contour_to_data


BACK_GARMENTS = {"dress", "sundress", "top", "blouse"}


def prepare_closure_foundation(request: Mapping[str, Any]) -> Mapping[str, Any]:
    closure = request["garment_spec"]["parameters"]["closure"]
    if (
        request["garment_spec"]["garment_type"] not in BACK_GARMENTS
        or closure["location"] != "center_back"
        or closure["type"] == "zipper"
    ):
        return request
    result = deepcopy(dict(request))
    result["garment_spec"]["parameters"]["closure"] = {
        "type": "zipper",
        "location": "center_back",
        "length_mm": closure["length_mm"],
    }
    return result


def _fail(code: str, message: str) -> None:
    raise BlockConstructionError(code, message, "/garment_spec/parameters/closure")


def _centers(pattern: Mapping[str, Any], prefix: str = "") -> list[tuple[dict, LineSegment]]:
    result = []
    for piece in pattern["pieces"]:
        pid = piece["id"]
        if prefix and not pid.startswith(prefix):
            continue
        base = pid.removeprefix(prefix)
        if base not in {"back_bodice", "back_skirt", "back_skirt_yoke"} and not base.startswith(
            "back_skirt_panel_"
        ):
            continue
        for edge in contour_from_data(piece["seam_contour"]).segments:
            if (
                isinstance(edge, LineSegment)
                and abs(edge.start.x_mm) < 1e-7
                and abs(edge.end.x_mm) < 1e-7
                and edge.length_mm > 1
            ):
                result.append((piece, edge))
    return sorted(result, key=lambda item: -max(item[1].start.y_mm, item[1].end.y_mm))


def _note(piece: dict, suffix: str, text: str, y: float) -> None:
    piece["annotations"].append(
        {
            "id": f"{piece['id']}_{suffix}",
            "text_ru": text,
            "position": [25, y],
        }
    )


def apply_back_closure(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    spec = request["garment_spec"]
    closure = spec["parameters"]["closure"]
    result = deepcopy(dict(pattern))
    if spec["garment_type"] not in BACK_GARMENTS or closure["location"] != "center_back":
        return result
    typ, raw_length = closure["type"], closure["length_mm"]
    if not isinstance(raw_length, (int, float)) or not math.isfinite(raw_length):
        _fail("BACK_OPENING_LENGTH_INVALID", "Укажите длину разреза спинки в сантиметрах.")
    length = float(raw_length)
    centers = _centers(result)
    if not centers:
        _fail("BACK_OPENING_TARGET_MISSING", "Не найден центральный срез спинки.")
    top = max(centers[0][1].start.y_mm, centers[0][1].end.y_mm)
    bottom = min(min(edge.start.y_mm, edge.end.y_mm) for _, edge in centers)
    if length < 100 or length > top - bottom - 10:
        _fail(
            "BACK_OPENING_LENGTH_INVALID",
            f"Разрез должен быть длиной от 10 см до {(top - bottom - 10) / 10:.1f} см и закончиться выше низа.",
        )
    stop = top - length
    interfaces, targets, records = [], [], []
    labels = {
        "zipper": "Молния",
        "buttons": "Пуговицы с навесными петлями",
        "lacing": "Шнуровка лентой",
    }
    for prefix in ("", "lining_", "overlay_", "interfacing_"):
        for piece, edge in _centers(result, prefix):
            high, low = max(edge.start.y_mm, edge.end.y_mm), min(edge.start.y_mm, edge.end.y_mm)
            opening_low = max(low, stop)
            if opening_low < high:
                pid = f"{piece['id']}_back_opening"
                line = LineSegment(Point(0, high), Point(0, opening_low), f"{pid}_segment")
                piece["internal_paths"].append(_path(pid, [line]))
                interfaces.append(pid)
                if prefix == "":
                    records.append((piece, line))
                _note(
                    piece,
                    "opening_note",
                    f"{labels[typ]}: центр спинки, разрез {length:g} мм от горловины. Этот участок не стачивать; метки относятся к двум зеркальным половинам.",
                    high,
                )
                if low <= stop <= high:
                    piece["notches"].append(
                        {
                            "id": f"{piece['id']}_back_opening_stop",
                            "match_id": "back_opening_stop",
                            "segment_id": edge.id,
                            "distance_from_start_mm": abs(edge.start.y_mm - stop),
                            "kind": "double",
                        }
                    )
            closed_high = min(high, stop)
            if closed_high > low + 1:
                pid = f"{piece['id']}_closed_center"
                line = LineSegment(Point(0, closed_high), Point(0, low), f"{pid}_segment")
                piece["internal_paths"].append(_path(pid, [line]))
                pair = _seam_pair(f"{pid}_join", piece["id"], [line.id], piece["id"], [line.id])
                pair["copy_pairing"] = "mirrored_copies"
                result["seam_pairs"].append(pair)
                for copy_side in ("first", "second"):
                    piece["notches"].append(
                        {
                            "id": f"{pid}_{copy_side}_match",
                            "match_id": pair["id"],
                            "segment_id": edge.id,
                            "distance_from_start_mm": abs(
                                edge.start.y_mm - (closed_high + low) / 2
                            ),
                            "kind": "single",
                        }
                    )
                interfaces.append(pair["id"])
                _note(
                    piece,
                    "closed_center_note",
                    "Ниже метки конца разреза стачать центральные срезы двух зеркальных половин.",
                    low,
                )
            targets.append(piece["id"])
    if abs(sum(line.length_mm for _, line in records) - length) > 1e-6:
        _fail("BACK_OPENING_DISCONNECTED", "Линия разреза спинки разорвана между деталями.")
    added = []
    parameters = {"opening_length": length}
    if typ != "zipper":
        pitch = float(closure.get("loop_pitch_mm", 80))
        count = math.floor((length - 40) / pitch) + 1
        maximum = 10 if typ == "lacing" else 20
        if count < 2 or count > maximum:
            _fail(
                "BACK_LOOP_COUNT_INVALID",
                f"Для этого разреза нужно от 2 до {maximum} рядов петель. Измените длину или расстояние между петлями.",
            )
        parameters.update(loop_count=count, loop_pitch=pitch, facing_width=30)
        binding = _rectangle("back_closure_facing", "Обтачка разреза спинки", length, 30, 2)
        edges = list(contour_from_data(binding["seam_contour"]).segments)
        cursor = 0.0
        join_edges = []
        for index, (target, line) in enumerate(records):
            end = cursor + line.length_mm
            join = LineSegment(Point(cursor, 0), Point(end, 0), f"back_closure_facing_join_{index}")
            join_edges.append(join)
            pair = _seam_pair(
                f"back_closure_facing_attachment_{index}",
                target["id"],
                [line.id],
                binding["id"],
                [join.id],
            )
            result["seam_pairs"].append(pair)
            interfaces.append(pair["id"])
            cursor = end
        binding["seam_contour"] = contour_to_data(
            Contour(tuple([*join_edges, *edges[1:]]), id="back_closure_facing_seam")
        )
        _note(
            binding,
            "finish_note",
            "Кроить 2 зеркальные обтачки. Притачать к краям разреза, отвернуть внутрь; петли втачать между спинкой и обтачкой. Верх согласовать с обтачкой горловины.",
            15,
        )
        loops = _rectangle(
            "back_closure_loops",
            "Навесные петли спинки",
            60,
            20,
            count * (2 if typ == "lacing" else 1),
        )
        _note(
            loops,
            "fold_note",
            "Полоска 60 × 20 мм дана по линии среза, без дополнительных припусков. Ширину сложить вчетверо до 5 мм. Отрезок сложить петлёй; оба конца закрепить у одной метки. Для шнуровки петли с обеих сторон, для пуговиц — только справа.",
            10,
        )
        for index in range(count):
            distance = 20 + index * pitch
            y = top - distance
            target, _ = next(
                (
                    record
                    for record in records
                    if record[1].end.y_mm - 1e-6 <= y <= record[1].start.y_mm + 1e-6
                )
            )
            anchor = LineSegment(Point(0, y), Point(5, y), f"back_closure_loop_{index}_segment")
            path_id = f"back_closure_loop_{index}"
            target["internal_paths"].append(_path(path_id, [anchor]))
            _note(
                target,
                f"loop_{index}_note",
                f"Метка {index + 1}: {distance:g} мм от горловины. {'Петли с обеих сторон.' if typ == 'lacing' else 'Петля справа, пуговица слева; края сходятся без нахлёста.'}",
                y,
            )
            binding_anchor = LineSegment(
                Point(distance, 0), Point(distance, 5), f"binding_loop_{index}_anchor"
            )
            binding["internal_paths"].append(
                _path(f"binding_loop_{index}_attachment", [binding_anchor])
            )
            for loop_end in ("left", "right"):
                pair = _seam_pair(
                    f"{path_id}_{loop_end}_join",
                    binding["id"],
                    [binding_anchor.id],
                    loops["id"],
                    [f"back_closure_loops_end_{loop_end}"],
                )
                pair["second_length_reduction_mm"] = 15
                result["seam_pairs"].append(pair)
                interfaces.append(pair["id"])
            binding["internal_paths"].append(
                _path(
                    f"binding_loop_{index}",
                    [
                        LineSegment(
                            Point(distance, 0), Point(distance, 30), f"binding_loop_{index}_segment"
                        )
                    ],
                )
            )
            target["notches"].append(
                {
                    "id": f"{path_id}_mark",
                    "match_id": path_id,
                    "segment_id": anchor.id,
                    "distance_from_start_mm": 2.5,
                    "kind": "single",
                }
            )
        result["pieces"].extend([binding, loops])
        added += [binding["id"], loops["id"]]
        if typ == "lacing":
            modesty = _rectangle(
                "back_lacing_underlap", "Подкладная планка под шнуровку", length, 80
            )
            edges = list(contour_from_data(modesty["seam_contour"]).segments)
            underlap_joins = [
                LineSegment(edge.start, edge.end, edge.id.replace("facing", "underlap"))
                for edge in join_edges
            ]
            modesty["seam_contour"] = contour_to_data(
                Contour(tuple([*underlap_joins, *edges[1:]]), id="back_lacing_underlap_seam")
            )
            for index, (target, line) in enumerate(records):
                pair = _seam_pair(
                    f"back_underlap_attachment_{index}",
                    target["id"],
                    [line.id],
                    modesty["id"],
                    [underlap_joins[index].id],
                )
                result["seam_pairs"].append(pair)
                interfaces.append(pair["id"])
            _note(
                modesty,
                "attachment_note",
                "Закрепить только под левой стороной разреза; правая сторона свободна. Планка закрывает кожу при раскрытии шнуровки. Зазор не вырезан из основы.",
                40,
            )
            ribbon_length = 2 * (count - 1) * math.hypot(pitch, 40) + 420
            ribbon = _rectangle("back_lacing_ribbon", "Лента для шнуровки", ribbon_length, 30)
            _note(
                ribbon,
                "fold_note",
                "Полоска дана по линии среза, без дополнительных припусков. Ширину 30 мм сложить втрое до 10 мм, закрыть срезы. Длина включает зазор до 40 мм, два хвоста по 200 мм и подгибку концов по 10 мм. Продеть крест-накрест; можно заменить готовой лентой 10 мм.",
                15,
            )
            result["pieces"].extend([modesty, ribbon])
            added += [modesty["id"], ribbon["id"]]
            parameters.update(ribbon_length=ribbon_length, trial_gap=40, underlap_width=80)
    module_id = {
        "zipper": "back_zipper_v1",
        "buttons": "back_button_loops_v1",
        "lacing": "back_lacing_v1",
    }[typ]
    result.setdefault("composite_operations", []).append(
        _operation(
            "configured_back",
            "element",
            "closure",
            module_id,
            "A03-C01",
            sorted(set(targets)),
            added,
            interfaces,
            parameters,
            _interface_residual(result, interfaces),
        )
    )
    return result


def validate_back_closure_placements(pattern: Mapping[str, Any]) -> None:
    """Reject manual moves that detach measured openings from their actual cut edges."""
    targets = {
        pid
        for operation in pattern.get("composite_operations", [])
        if operation["kind"] == "closure"
        for pid in operation["target_piece_ids"]
    }
    for piece in pattern["pieces"]:
        if piece["id"] not in targets:
            continue
        edges = contour_from_data(piece["seam_contour"]).segments
        for path in piece["internal_paths"]:
            if not path["id"].endswith(("_back_opening", "_closed_center")):
                continue
            for segment in contour_from_data(path).segments:
                for point in (segment.start, segment.end):
                    if not any(
                        isinstance(edge, LineSegment)
                        and abs(
                            math.hypot(point.x_mm - edge.start.x_mm, point.y_mm - edge.start.y_mm)
                            + math.hypot(point.x_mm - edge.end.x_mm, point.y_mm - edge.end.y_mm)
                            - edge.length_mm
                        )
                        < 1e-6
                        for edge in edges
                    ):
                        raise ValueError("Линия застёжки отделилась от центрального среза спинки.")

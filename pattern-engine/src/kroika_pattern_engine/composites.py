"""Bounded composite details and garment layers introduced at stage 19."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
from typing import Any, Mapping

from .blocks import BlockConstructionError
from .geometry import Contour, LineSegment, Point, contour_from_data, contour_to_data


STAGE19_ELEMENT_MODULES = frozenset({
    "sleeve_cuff_band_v1",
    "stand_collar_v1",
    "paired_patch_pocket_v1",
})
STAGE19_LAYER_MODULES = frozenset({
    "skirt_full_lining_v1",
    "skirt_overlay_layer_v1",
})
STAGE19_MODULES = STAGE19_ELEMENT_MODULES | STAGE19_LAYER_MODULES

ELEMENT_ORDER = {
    "sleeve_cuff_band_v1": 10,
    "stand_collar_v1": 20,
    "paired_patch_pocket_v1": 30,
}
LAYER_ORDER = {
    "skirt_full_lining_v1": 10,
    "skirt_overlay_layer_v1": 20,
}


@dataclass(frozen=True, slots=True)
class CompositeResult:
    pattern: dict[str, Any]
    applied_count: int
    added_piece_count: int
    added_interface_count: int
    maximum_invariant_residual_mm: float


def cuff_dimensions_mm(join_length_mm: float, finished_depth_mm: float) -> tuple[float, float]:
    """Return the exact sleeve join and bounded finished depth of a straight cuff."""

    return (
        _bounded(join_length_mm, 80.0, 800.0, "COMPOSITE_CUFF_JOIN_OUTSIDE_DOMAIN"),
        _bounded(finished_depth_mm, 25.0, 120.0, "COMPOSITE_CUFF_DEPTH_OUTSIDE_DOMAIN"),
    )


def collar_dimensions_mm(
    front_neckline_mm: float, back_neckline_mm: float, finished_height_mm: float,
) -> tuple[float, float, float]:
    """Return front/back joins and the bounded height of a straight stand collar."""

    front = _bounded(
        front_neckline_mm, 20.0, 500.0, "COMPOSITE_COLLAR_FRONT_OUTSIDE_DOMAIN"
    )
    back = _bounded(
        back_neckline_mm, 20.0, 500.0, "COMPOSITE_COLLAR_BACK_OUTSIDE_DOMAIN"
    )
    height = _bounded(
        finished_height_mm, 20.0, 80.0, "COMPOSITE_COLLAR_HEIGHT_OUTSIDE_DOMAIN"
    )
    return front, back, height


def pocket_dimensions_mm(width_mm: float, depth_mm: float) -> tuple[float, float]:
    """Return bounded finished dimensions of the supported patch-pocket pair."""

    return (
        _bounded(width_mm, 80.0, 220.0, "COMPOSITE_POCKET_WIDTH_OUTSIDE_DOMAIN"),
        _bounded(depth_mm, 80.0, 260.0, "COMPOSITE_POCKET_DEPTH_OUTSIDE_DOMAIN"),
    )


def apply_composite_transformations(
    pattern: Mapping[str, Any], request: Mapping[str, Any],
) -> CompositeResult:
    """Compile reviewed stage-19 modules into cuttable pieces and explicit joins."""

    result = deepcopy(dict(pattern))
    original_piece_count = len(result["pieces"])
    original_pair_count = len(result["seam_pairs"])
    operations: list[dict[str, Any]] = []
    intent = request.get("garment_spec", {}).get("design_intent")
    elements = intent.get("elements", []) if isinstance(intent, Mapping) else []
    layers = intent.get("layers", []) if isinstance(intent, Mapping) else []

    active_layers = sorted(
        (
            layer for layer in layers
            if layer.get("included") is not False
            and layer.get("support_status") == "supported"
            and layer.get("module_id") in STAGE19_LAYER_MODULES
        ),
        key=lambda layer: (
            LAYER_ORDER[str(layer["module_id"])], str(layer["source_layer_id"])
        ),
    )
    occupied_layer_roles: set[str] = set()
    for layer in active_layers:
        role = str(layer["role"])
        source_id = str(layer["source_layer_id"])
        if role in occupied_layer_roles:
            raise _layer_error(
                "COMPOSITE_LAYER_ROLE_CONFLICT",
                "Для одной роли можно применить только один геометрический слой.",
                source_id,
            )
        occupied_layer_roles.add(role)
        include_flounces = layer["module_id"] == "skirt_overlay_layer_v1"
        added_piece_ids, interface_ids = _add_skirt_layer(
            result, role, source_id, include_flounces=include_flounces
        )
        operations.append(_operation(
            source_id=source_id,
            source_kind="layer",
            kind="overlay" if role == "overlay" else "lining",
            module_id=str(layer["module_id"]),
            formula_id="M19-L02" if role == "overlay" else "M19-L01",
            target_piece_ids=["front_skirt", "back_skirt"],
            added_piece_ids=added_piece_ids,
            interface_ids=interface_ids,
            parameters_mm={},
            residual=_interface_residual(result, interface_ids),
        ))

    active_elements = sorted(
        (
            element for element in elements
            if element.get("included") is not False
            and element.get("support_status") == "supported"
            and element.get("module_id") in STAGE19_ELEMENT_MODULES
        ),
        key=lambda element: (
            ELEMENT_ORDER[str(element["module_id"])], str(element["source_element_id"])
        ),
    )
    occupied_targets: set[str] = set()
    for element in active_elements:
        module_id = str(element["module_id"])
        source_id = str(element["source_element_id"])
        dimensions = element.get("dimensions_mm") or {}
        if module_id == "sleeve_cuff_band_v1":
            _claim_target(occupied_targets, "sleeve_cuff", source_id)
            depth = _required_dimension(dimensions, "width", source_id)
            piece_id, interface_id, join_length = _add_cuff(result, depth, source_id)
            operations.append(_operation(
                source_id, "element", "cuff", module_id, "M19-C01",
                ["base_sleeve"], [piece_id], [interface_id],
                {"join_length": join_length, "finished_depth": depth},
                _interface_residual(result, [interface_id]),
            ))
        elif module_id == "stand_collar_v1":
            _claim_target(occupied_targets, "neckline_collar", source_id)
            height = _required_dimension(dimensions, "width", source_id)
            piece_id, interface_ids, front_length, back_length = _add_stand_collar(
                result, height, source_id
            )
            operations.append(_operation(
                source_id, "element", "collar", module_id, "M19-C02",
                ["front_bodice", "back_bodice"], [piece_id], interface_ids,
                {
                    "front_join_length": front_length,
                    "back_join_length": back_length,
                    "finished_height": height,
                },
                _interface_residual(result, interface_ids),
            ))
        elif module_id == "paired_patch_pocket_v1":
            _claim_target(occupied_targets, "skirt_front_pocket", source_id)
            width = _required_dimension(dimensions, "width", source_id)
            depth = _required_dimension(dimensions, "depth", source_id)
            target_id = (
                "overlay_front_skirt"
                if _has_piece(result, "overlay_front_skirt")
                else "front_skirt"
            )
            piece_id, placement_id = _add_patch_pocket(
                result, target_id, width, depth, source_id
            )
            operations.append(_operation(
                source_id, "element", "patch_pocket", module_id, "M19-P01",
                [target_id], [piece_id], [placement_id],
                {"finished_width": width, "finished_depth": depth},
            ))

    maximum_residual = _pair_residual(result)
    if operations and maximum_residual > 1.0:
        raise BlockConstructionError(
            "COMPOSITE_INTERFACE_RESIDUAL_EXCEEDED",
            "После добавления составных деталей длины соединений вышли за допуск 1 мм.",
            "/pattern/seam_pairs",
        )
    result["composite_operations"] = operations
    return CompositeResult(
        pattern=result,
        applied_count=len(operations),
        added_piece_count=len(result["pieces"]) - original_piece_count,
        added_interface_count=len(result["seam_pairs"]) - original_pair_count,
        maximum_invariant_residual_mm=maximum_residual,
    )


def _add_skirt_layer(
    pattern: dict[str, Any], role: str, source_id: str, *, include_flounces: bool,
) -> tuple[list[str], list[str]]:
    source_piece_ids = ["front_skirt", "back_skirt"]
    if include_flounces:
        source_piece_ids.extend(sorted(
            piece["id"] for piece in pattern["pieces"]
            if piece["id"].startswith(("front_skirt_", "back_skirt_"))
            and piece["id"].endswith("_flounce")
        ))
    if not all(_has_piece(pattern, piece_id) for piece_id in source_piece_ids):
        raise _layer_error(
            "COMPOSITE_LAYER_TARGET_MISSING",
            "Для юбочного слоя нужны детали переднего и заднего полотнища.",
            source_id,
        )

    existing_pairs = list(pattern["seam_pairs"])
    mapping: dict[str, str] = {}
    added_piece_ids: list[str] = []
    for source_piece_id in source_piece_ids:
        source_piece = _piece(pattern, source_piece_id, source_id, source_kind="layers")
        cloned = _clone_piece(source_piece, role)
        if _has_piece(pattern, cloned["id"]):
            raise _layer_error(
                "COMPOSITE_LAYER_PIECE_DUPLICATE",
                "Деталь этого слоя уже существует.",
                source_id,
            )
        mapping[source_piece_id] = cloned["id"]
        pattern["pieces"].append(cloned)
        added_piece_ids.append(cloned["id"])

    interface_ids: list[str] = []
    source_set = set(source_piece_ids)
    for pair in existing_pairs:
        if pair["first_piece_id"] not in source_set or pair["second_piece_id"] not in source_set:
            continue
        cloned_pair = deepcopy(pair)
        cloned_pair["id"] = f"{role}_{pair['id']}"
        cloned_pair["first_piece_id"] = mapping[pair["first_piece_id"]]
        cloned_pair["second_piece_id"] = mapping[pair["second_piece_id"]]
        cloned_pair["first_segment_ids"] = [
            f"{role}_{segment_id}" for segment_id in pair["first_segment_ids"]
        ]
        cloned_pair["second_segment_ids"] = [
            f"{role}_{segment_id}" for segment_id in pair["second_segment_ids"]
        ]
        pattern["seam_pairs"].append(cloned_pair)
        interface_ids.append(cloned_pair["id"])

    for source_piece_id in ("front_skirt", "back_skirt"):
        source_piece = _piece(pattern, source_piece_id, source_id, source_kind="layers")
        waist_ids = [
            segment["id"] for segment in source_piece["seam_contour"]["segments"]
            if segment["id"].endswith("_waist")
        ]
        if not waist_ids:
            raise _layer_error(
                "COMPOSITE_LAYER_WAIST_MISSING",
                "Для закрепления слоя не найден срез талии.",
                source_id,
            )
        pair_id = f"{role}_{source_piece_id}_waist_attachment"
        pattern["seam_pairs"].append(_seam_pair(
            pair_id,
            source_piece_id,
            waist_ids,
            mapping[source_piece_id],
            [f"{role}_{segment_id}" for segment_id in waist_ids],
        ))
        interface_ids.append(pair_id)

    return added_piece_ids, interface_ids


def _clone_piece(source: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    cloned = deepcopy(dict(source))
    original_piece_id = str(source["id"])
    cloned["id"] = f"{prefix}_{original_piece_id}"
    layer_name = "Подкладка" if prefix == "lining" else "Верхний слой"
    cloned["name_ru"] = f"{layer_name} · {source['name_ru']}"
    cloned["seam_contour"]["id"] = f"{prefix}_{source['seam_contour']['id']}"
    for segment in cloned["seam_contour"]["segments"]:
        segment["id"] = f"{prefix}_{segment['id']}"
    cloned["cutting_contour"] = None
    cloned.pop("edge_allowances", None)
    for path in cloned["internal_paths"]:
        path["id"] = f"{prefix}_{path['id']}"
        for segment in path["segments"]:
            segment["id"] = f"{prefix}_{segment['id']}"
    for notch in cloned["notches"]:
        notch["id"] = f"{prefix}_{notch['id']}"
        notch["segment_id"] = f"{prefix}_{notch['segment_id']}"
        if "match_id" in notch:
            notch["match_id"] = f"{prefix}_{notch['match_id']}"
    for annotation in cloned["annotations"]:
        annotation["id"] = f"{prefix}_{annotation['id']}"
        annotation["text_ru"] = f"{layer_name}. {annotation['text_ru']}"
    return cloned


def _add_cuff(
    pattern: dict[str, Any], depth_mm: float, source_id: str,
) -> tuple[str, str, float]:
    sleeve = _piece(pattern, "base_sleeve", source_id)
    hem_id = _only_segment_ending(sleeve, "sleeve_hem", source_id)
    join_length, depth = cuff_dimensions_mm(_segment_length(sleeve, hem_id), depth_mm)
    join_id = f"{source_id}_cuff_join"
    _rename_segment(pattern, "base_sleeve", hem_id, join_id)
    piece_id = f"{source_id}_cuff"
    if _has_piece(pattern, piece_id):
        raise _element_error(
            "COMPOSITE_PIECE_ID_DUPLICATE", "Деталь манжеты уже существует.", source_id
        )
    cuff = _rectangle_piece(
        piece_id,
        "Прямая манжета",
        join_length,
        depth,
        cut_quantity=2,
        cut_on_fold=False,
        mirrored_pair=True,
        lower_suffix="join",
    )
    pattern["pieces"].append(cuff)
    pair_id = f"{source_id}_cuff_attachment"
    pattern["seam_pairs"].append(_seam_pair(
        pair_id, "base_sleeve", [join_id], piece_id, [f"{piece_id}_join"]
    ))
    return piece_id, pair_id, join_length


def _add_stand_collar(
    pattern: dict[str, Any], height_mm: float, source_id: str,
) -> tuple[str, list[str], float, float]:
    front = _piece(pattern, "front_bodice", source_id)
    back = _piece(pattern, "back_bodice", source_id)
    front_length, back_length, height = collar_dimensions_mm(
        _segment_length(front, "front_neckline"),
        _segment_length(back, "back_neckline"),
        height_mm,
    )
    piece_id = f"{source_id}_stand_collar"
    if _has_piece(pattern, piece_id):
        raise _element_error(
            "COMPOSITE_PIECE_ID_DUPLICATE", "Деталь воротника уже существует.", source_id
        )
    total = front_length + back_length
    p0 = Point(0.0, 0.0)
    split = Point(front_length, 0.0)
    p1 = Point(total, 0.0)
    p2 = Point(total, height)
    p3 = Point(0.0, height)
    contour = Contour((
        LineSegment(p0, split, f"{piece_id}_front_neckline"),
        LineSegment(split, p1, f"{piece_id}_back_neckline"),
        LineSegment(p1, p2, f"{piece_id}_front_edge"),
        LineSegment(p2, p3, f"{piece_id}_upper"),
        LineSegment(p3, p0, f"{piece_id}_center"),
    ), id=f"{piece_id}_seam")
    pattern["pieces"].append(_piece_data(
        piece_id,
        "Отдельная стойка воротника",
        contour,
        cut_quantity=2,
        cut_on_fold=True,
        mirrored_pair=False,
    ))
    front_pair = f"{source_id}_front_collar_attachment"
    back_pair = f"{source_id}_back_collar_attachment"
    pattern["seam_pairs"].extend((
        _seam_pair(
            front_pair, "front_bodice", ["front_neckline"], piece_id,
            [f"{piece_id}_front_neckline"],
        ),
        _seam_pair(
            back_pair, "back_bodice", ["back_neckline"], piece_id,
            [f"{piece_id}_back_neckline"],
        ),
    ))
    return piece_id, [front_pair, back_pair], front_length, back_length


def _add_patch_pocket(
    pattern: dict[str, Any], target_id: str, width_mm: float, depth_mm: float,
    source_id: str,
) -> tuple[str, str]:
    width, depth = pocket_dimensions_mm(width_mm, depth_mm)
    target = _piece(pattern, target_id, source_id)
    box = contour_from_data(target["seam_contour"]).bounding_box
    horizontal_margin = 20.0
    vertical_margin = 30.0
    if width > box.width_mm - 2.0 * horizontal_margin or depth > box.height_mm - 2.0 * vertical_margin:
        raise _element_error(
            "COMPOSITE_POCKET_DOES_NOT_FIT",
            "Карман не помещается внутри выбранного переднего полотнища.",
            source_id,
        )
    left = box.min_x_mm + (box.width_mm - width) / 2.0
    bottom = box.min_y_mm + (box.height_mm - depth) / 2.0
    right = left + width
    top = bottom + depth
    placement_id = f"{source_id}_placement"
    placement = Contour((
        LineSegment(Point(left, bottom), Point(right, bottom), f"{placement_id}_lower"),
        LineSegment(Point(right, bottom), Point(right, top), f"{placement_id}_side"),
        LineSegment(Point(right, top), Point(left, top), f"{placement_id}_opening"),
        LineSegment(Point(left, top), Point(left, bottom), f"{placement_id}_center"),
    ), id=placement_id)
    target["internal_paths"].append(contour_to_data(placement))

    piece_id = f"{source_id}_patch_pocket"
    if _has_piece(pattern, piece_id):
        raise _element_error(
            "COMPOSITE_PIECE_ID_DUPLICATE", "Деталь кармана уже существует.", source_id
        )
    pattern["pieces"].append(_rectangle_piece(
        piece_id,
        "Парный накладной карман",
        width,
        depth,
        cut_quantity=2,
        cut_on_fold=False,
        mirrored_pair=True,
        lower_suffix="lower",
        upper_suffix="opening_hem",
    ))
    return piece_id, placement_id


def _rectangle_piece(
    piece_id: str,
    name_ru: str,
    width_mm: float,
    height_mm: float,
    *,
    cut_quantity: int,
    cut_on_fold: bool,
    mirrored_pair: bool,
    lower_suffix: str,
    upper_suffix: str = "upper",
) -> dict[str, Any]:
    p0 = Point(0.0, 0.0)
    p1 = Point(width_mm, 0.0)
    p2 = Point(width_mm, height_mm)
    p3 = Point(0.0, height_mm)
    contour = Contour((
        LineSegment(p0, p1, f"{piece_id}_{lower_suffix}"),
        LineSegment(p1, p2, f"{piece_id}_side"),
        LineSegment(p2, p3, f"{piece_id}_{upper_suffix}"),
        LineSegment(p3, p0, f"{piece_id}_center"),
    ), id=f"{piece_id}_seam")
    return _piece_data(
        piece_id, name_ru, contour, cut_quantity=cut_quantity,
        cut_on_fold=cut_on_fold, mirrored_pair=mirrored_pair,
    )


def _piece_data(
    piece_id: str,
    name_ru: str,
    contour: Contour,
    *,
    cut_quantity: int,
    cut_on_fold: bool,
    mirrored_pair: bool,
) -> dict[str, Any]:
    box = contour.bounding_box
    return {
        "id": piece_id,
        "name_ru": name_ru,
        "cut_quantity": cut_quantity,
        "cut_on_fold": cut_on_fold,
        "mirrored_pair": mirrored_pair,
        "seam_contour": contour_to_data(contour),
        "cutting_contour": None,
        "internal_paths": [],
        "grainline": {
            "start": [box.min_x_mm + box.width_mm * 0.25, box.min_y_mm + box.height_mm / 2.0],
            "end": [box.min_x_mm + box.width_mm * 0.75, box.min_y_mm + box.height_mm / 2.0],
        },
        "notches": [],
        "annotations": [{
            "id": f"{piece_id}_formula",
            "text_ru": f"{name_ru}; геометрический модуль этапа 19.",
            "position": [
                box.min_x_mm + box.width_mm / 2.0,
                box.min_y_mm + box.height_mm / 2.0,
            ],
        }],
    }


def _seam_pair(
    pair_id: str,
    first_piece_id: str,
    first_segment_ids: list[str],
    second_piece_id: str,
    second_segment_ids: list[str],
) -> dict[str, Any]:
    return {
        "id": pair_id,
        "first_piece_id": first_piece_id,
        "first_segment_ids": first_segment_ids,
        "second_piece_id": second_piece_id,
        "second_segment_ids": second_segment_ids,
        "first_length_reduction_mm": 0.0,
        "second_length_reduction_mm": 0.0,
        "allowed_ease_mm": 0.0,
        "tolerance_mm": 1.0,
    }


def _rename_segment(
    pattern: dict[str, Any], piece_id: str, old_id: str, new_id: str,
) -> None:
    piece = _piece(pattern, piece_id, old_id)
    contour = contour_from_data(piece["seam_contour"])
    changed = False
    segments = []
    for segment in contour.segments:
        if segment.id == old_id:
            segments.append(replace(segment, id=new_id))
            changed = True
        else:
            segments.append(segment)
    if not changed:
        raise BlockConstructionError(
            "COMPOSITE_TARGET_SEGMENT_MISSING",
            "Не найден срез для составной детали.",
            f"/pattern/pieces/{piece_id}/seam_contour",
        )
    piece["seam_contour"] = contour_to_data(
        Contour(tuple(segments), closed=contour.closed, id=contour.id)
    )
    for notch in piece["notches"]:
        if notch["segment_id"] == old_id:
            notch["segment_id"] = new_id
    for pair in pattern["seam_pairs"]:
        for key in ("first_segment_ids", "second_segment_ids"):
            pair[key] = [new_id if segment_id == old_id else segment_id for segment_id in pair[key]]


def _operation(
    source_id: str,
    source_kind: str,
    kind: str,
    module_id: str,
    formula_id: str,
    target_piece_ids: list[str],
    added_piece_ids: list[str],
    interface_ids: list[str],
    parameters_mm: dict[str, float],
    residual: float = 0.0,
) -> dict[str, Any]:
    return {
        "operation_id": f"composite_{source_id}_{kind}",
        "source_kind": source_kind,
        "source_id": source_id,
        "kind": kind,
        "module_id": module_id,
        "formula_id": formula_id,
        "target_piece_ids": target_piece_ids,
        "added_piece_ids": added_piece_ids,
        "interface_ids": interface_ids,
        "parameters_mm": {key: round(float(value), 6) for key, value in parameters_mm.items()},
        "invariant_residual_mm": round(float(residual), 9),
    }


def _interface_residual(pattern: Mapping[str, Any], interface_ids: list[str]) -> float:
    pair_ids = set(interface_ids)
    pairs = [pair for pair in pattern["seam_pairs"] if pair["id"] in pair_ids]
    if not pairs:
        return 0.0
    subset = {"pieces": pattern["pieces"], "seam_pairs": pairs}
    return _pair_residual(subset)


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


def _piece(
    pattern: Mapping[str, Any], piece_id: str, source_id: str, *, source_kind: str = "elements",
) -> dict[str, Any]:
    try:
        return next(piece for piece in pattern["pieces"] if piece["id"] == piece_id)
    except StopIteration as error:
        pointer = f"/garment_spec/design_intent/{source_kind}/{source_id}"
        raise BlockConstructionError(
            "COMPOSITE_TARGET_PIECE_MISSING",
            f"Не найдена целевая деталь «{piece_id}».",
            pointer,
        ) from error


def _has_piece(pattern: Mapping[str, Any], piece_id: str) -> bool:
    return any(piece["id"] == piece_id for piece in pattern["pieces"])


def _segment_length(piece: Mapping[str, Any], segment_id: str) -> float:
    contour = contour_from_data(piece["seam_contour"])
    try:
        return next(segment.length_mm for segment in contour.segments if segment.id == segment_id)
    except StopIteration as error:
        raise BlockConstructionError(
            "COMPOSITE_TARGET_SEGMENT_MISSING",
            "Не найден целевой участок составной детали.",
            f"/pattern/pieces/{piece['id']}/seam_contour",
        ) from error


def _only_segment_ending(
    piece: Mapping[str, Any], suffix: str, source_id: str,
) -> str:
    matches = [
        segment["id"] for segment in piece["seam_contour"]["segments"]
        if segment["id"].endswith(suffix)
    ]
    if len(matches) != 1:
        raise _element_error(
            "COMPOSITE_TARGET_SEGMENT_AMBIGUOUS",
            "Для составной детали нужен ровно один подходящий срез.",
            source_id,
        )
    return matches[0]


def _required_dimension(dimensions: Mapping[str, Any], key: str, source_id: str) -> float:
    value = dimensions.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _element_error(
            "COMPOSITE_DIMENSION_REQUIRED",
            f"Для составной детали нужен размер «{key}» в миллиметрах.",
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


def _claim_target(occupied: set[str], target: str, source_id: str) -> None:
    if target in occupied:
        raise _element_error(
            "COMPOSITE_TARGET_CONFLICT",
            "На один конструктивный участок назначено несколько составных деталей.",
            source_id,
        )
    occupied.add(target)


def _element_error(code: str, message: str, source_id: str) -> BlockConstructionError:
    return BlockConstructionError(
        code, message, f"/garment_spec/design_intent/elements/{source_id}"
    )


def _layer_error(code: str, message: str, source_id: str) -> BlockConstructionError:
    return BlockConstructionError(
        code, message, f"/garment_spec/design_intent/layers/{source_id}"
    )

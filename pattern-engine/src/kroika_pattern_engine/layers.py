"""Stage-4 material layers resolved against the final, already partitioned pattern."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import re
from typing import Any, Mapping

from kroika_contracts.design_modules import FOUNDATION_LAYER_MODULES, REGISTRY, composition_order
from .blocks import BlockConstructionError
from .composites import _clone_piece, _operation, _seam_pair
from .geometry import Contour, LineSegment, Point, contour_from_data, validate_simple_contour
from .structural import _boundary_hits, _subcurve, _make_part, _carry_notches

BODY = {"front_bodice", "back_bodice", "jacket_front_center", "jacket_side_front"}
SKIRT = {"front_skirt", "back_skirt", "front_trouser", "back_trouser"}
SLEEVE = {"base_sleeve"}
NAMES = {"lining": "Подкладка", "interfacing": "Прокладка", "overlay": "Накладной слой"}


def _fail(message, source, code="LAYER_GEOMETRY_INVALID"):
    raise BlockConstructionError(code, message, f"/garment_spec/design_intent/layers/{source}")


def _base_id(piece_id):
    return piece_id.split("__")[0].split("_panel_")[0].removesuffix("_yoke")


def _targets(pattern, layer):
    coverage = layer["coverage"]
    if coverage == "detail":
        wanted = set(layer.get("detail_source_ids") or [])
        ops = [op for op in pattern.get("composite_operations", []) if op["source_kind"] == "element" and op["source_id"] in wanted]
        found = {op["source_id"] for op in ops if op["added_piece_ids"]}
        if found != wanted:
            _fail("Выбранная дополнительная деталь должна иметь отдельные лекала; цельнокроеные преобразования покрываются слоем лифа или юбки.", layer["source_layer_id"], "LAYER_DETAIL_TARGET_MISSING")
        ids = {pid for op in ops for pid in op["added_piece_ids"]}
    else:
        bases = BODY if coverage == "bodice" else SKIRT if coverage == "skirt" else SLEEVE if coverage == "sleeves" else BODY | SKIRT | SLEEVE
        ids = {p["id"] for p in pattern["pieces"] if _base_id(p["id"]) in bases}
    if layer['module_id'] == 'skirt_overlay_layer_v1':
        # Preserve the legacy overlay recipe's sewn hem trim, now resolved last.
        trim_ids = {pid for key in ('composite_operations', 'modeling_operations')
                    for op in pattern.get(key, [])
                    if op['module_id'] in REGISTRY['combinations']['sequential_hem_modules']
                    for pid in op.get('added_piece_ids', op['target_piece_ids'])}
        while True:
            children = {pair['second_piece_id'] for pair in pattern['seam_pairs']
                        if pair['first_piece_id'] in ids and pair['second_piece_id'] in trim_ids}
            if children <= ids:
                break
            ids.update(children)
    if not ids:
        _fail("Для выбранного покрытия в изделии нет деталей.", layer["source_layer_id"], "LAYER_COVERAGE_EMPTY")
    return sorted(ids)


def _shorten(piece, amount, source, level=None):
    """Clip below a horizontal hem line; exact subcurves retain their source IDs."""
    if not amount:
        return deepcopy(piece)
    contour = contour_from_data(piece["seam_contour"])
    if not any(re.search(r'(?:^|_)hem(?:_|$)', e.id) for e in contour.segments):
        return deepcopy(piece)
    box = contour.bounding_box
    # Skirts and sleeves run downward; trouser blocks use the opposite Y direction.
    trousers = _base_id(piece["id"]) in {"front_trouser", "back_trouser"}
    level = (box.max_y_mm - amount if trousers else box.min_y_mm + amount) if level is None else level
    line = LineSegment(Point(box.min_x_mm - 20, level), Point(box.max_x_mm + 20, level))
    (ai, at, a), (bi, bt, b) = _boundary_hits(contour, line, source)
    arcs = []
    for indices, lo, hi, close in [
        (list(range(ai, bi + 1)), at, bt, LineSegment(b, a, f"{piece['id']}_layer_hem")),
        ([*range(bi, len(contour.segments)), *range(0, ai + 1)], bt, at, LineSegment(a, b, f"{piece['id']}_layer_hem")),
    ]:
        edges, fragments = [], []
        for j, i in enumerate(indices):
            original = contour.segments[i]
            start = lo if j == 0 else 0
            end = hi if j == len(indices) - 1 else 1
            if end - start < 1e-8:
                continue
            edge = replace(_subcurve(original, start, end), id=original.id)
            edges.append(edge)
            fragments.append((original.id, edge, _subcurve(original, 0, start).length_mm if start > 1e-8 else 0))
        shape = Contour(tuple([*edges, close]), id=contour.id)
        mean = sum(e.start.y_mm for e in edges) / len(edges)
        keep = mean < level if trousers else mean > level
        if keep:
            arcs.append((shape, fragments))
    if len(arcs) != 1 or arcs[0][0].bounding_box.height_mm < 50:
        _fail("После укорочения должно остаться не менее 5 см высоты слоя.", source)
    shape, fragments = arcs[0]
    validate_simple_contour(shape)
    trimmed = _make_part(piece, shape, piece["id"], piece["name_ru"], source)
    _carry_notches(piece, [(trimmed, fragments)])
    return trimmed


def _effective(piece, ids, reduction):
    edges = {e.id: e for path in [piece["seam_contour"], *piece["internal_paths"]] for e in contour_from_data(path).segments}
    return sum(edges[sid].length_mm for sid in ids) - reduction


def apply_foundation_layers(pattern: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(pattern))
    base = {p["id"]: p for p in pattern["pieces"]}
    pairs = list(pattern["seam_pairs"])
    occupied = set()
    jacket_lining = {"jacket_front_lining": "jacket_front_center", "jacket_side_front_lining": "jacket_side_front", "jacket_back_lining": "back_bodice", "jacket_sleeve_lining": "base_sleeve"}
    occupied.update(("lining", jacket_lining[p["id"]]) for p in pattern["pieces"] if p["id"] in jacket_lining)
    # Earlier layer recipes may already occupy a body region (including jacket lining).
    for p in pattern["pieces"]:
        for role in NAMES:
            if p["id"].startswith(role + "_"):
                occupied.add((role, p["id"][len(role) + 1:]))
    modules = FOUNDATION_LAYER_MODULES | deferred_layer_modules(request)
    active = sorted((layer for layer in (request["garment_spec"].get("design_intent") or {}).get("layers", []) if layer.get("included") is not False and layer.get("support_status") == "supported" and layer.get("module_id") in modules), key=lambda item: item["source_layer_id"])
    for layer in active:
        source, role = layer["source_layer_id"], layer["role"]
        targets = _targets(pattern, layer)
        if any((role, pid) in occupied for pid in targets):
            _fail("Два слоя одной роли покрывают одну деталь. Выберите непересекающиеся покрытия.", source, "LAYER_ROLE_OVERLAP")
        occupied.update((role, pid) for pid in targets)
        prefix = role if layer["module_id"] in REGISTRY["combinations"]["deferred_layer_modules"] else f"{role}_{source}"
        amount = float(layer.get("hem_shortening_mm") or 0)
        levels = {}
        def family(pid):
            root = _base_id(pid)
            return 'skirt' if root in {'front_skirt', 'back_skirt'} else root
        for root in {family(pid) for pid in targets}:
            hem_parts = [pid for pid in targets if family(pid) == root and
                         any(re.search(r'(?:^|_)hem(?:_|$)', e.id)
                             for e in contour_from_data(base[pid]['seam_contour']).segments)]
            if not hem_parts or not amount:
                continue
            boxes = [contour_from_data(base[pid]['seam_contour']).bounding_box for pid in hem_parts]
            level = min(box.max_y_mm for box in boxes)-amount if root in {'front_trouser','back_trouser'} else max(box.min_y_mm for box in boxes)+amount
            levels.update({pid: round(level, 6) for pid in hem_parts})
        derived = {pid: _shorten(base[pid], amount, source, levels.get(pid)) for pid in targets}
        clones = {pid: _clone_piece(derived[pid], prefix) for pid in targets}
        interfaces = []
        for pid, clone in clones.items():
            clone["name_ru"] = f"{NAMES[role]} · {base[pid]['name_ru']}"
            clone["annotations"] = [dict(id=f"{clone['id']}_layer_note", text_ru=f"{clone['name_ru']}. Крой {clone['cut_quantity']}; {'со сгибом' if clone['cut_on_fold'] else 'зеркально' if clone['mirrored_pair'] else 'одна деталь'}. Укорочение низа {amount:g} мм.", position=clone["grainline"]["start"])]
            # Retained upper edge registers the layer to its actual foundation.
            edges = contour_from_data(derived[pid]["seam_contour"]).segments
            original_edges = {e.id: e for e in contour_from_data(base[pid]["seam_contour"]).segments}
            retained = [e for e in edges if original_edges.get(e.id) == e]
            if not retained:
                _fail("Укорочение удалило все исходные срезы крепления слоя.", source)
            attach = next((e for e in retained if e.id.endswith(("_neckline", "_waist", "_cap_front", "_upper"))), retained[0])
            if attach.id not in {e.id for e in contour_from_data(base[pid]["seam_contour"]).segments}:
                _fail("Не найден сохранённый срез крепления слоя.", source)
            attach_ids = [e.id for e in edges if e.id.endswith("_neckline")] if attach.id.endswith("_neckline") else [e.id for e in edges if "sleeve_cap_" in e.id] if "sleeve_cap_" in attach.id else [attach.id]
            pair = _seam_pair(f"{prefix}_{pid}_layer_attachment", pid, attach_ids, clone["id"], [f"{prefix}_{sid}" for sid in attach_ids])
            result["seam_pairs"].append(pair)
            interfaces.append(pair["id"])
        for pair in pairs:
            if pair["first_piece_id"] not in clones or pair["second_piece_id"] not in clones:
                continue
            available = {pid: {e["id"] for path in [p["seam_contour"], *p["internal_paths"]] for e in path["segments"]} for pid, p in derived.items()}
            if any(set(pair[f"{side}_segment_ids"]) - available[pair[f"{side}_piece_id"]] for side in ("first", "second")):
                continue
            copied = deepcopy(pair)
            copied["id"] = f"{prefix}_{pair['id']}"
            lengths = []
            for side in ("first", "second"):
                pid = pair[f"{side}_piece_id"]
                lengths.append(_effective(derived[pid], pair[f"{side}_segment_ids"], pair[f"{side}_length_reduction_mm"]))
                copied[f"{side}_piece_id"] = clones[pid]["id"]
                copied[f"{side}_segment_ids"] = [f"{prefix}_{sid}" for sid in pair[f"{side}_segment_ids"]]
            if amount:
                ease = abs(lengths[0] - lengths[1])
                if ease > max(5, pair["allowed_ease_mm"] + 1):
                    _fail(f"Укороченный слой требует уточнения шва {pair['id']}: {lengths[0]:.2f} и {lengths[1]:.2f} мм.", source)
                copied["allowed_ease_mm"] = round(ease, 6)
            result["seam_pairs"].append(copied)
            interfaces.append(copied["id"])
        result["pieces"].extend(clones.values())
        result.setdefault("composite_operations", []).append(_operation(source, "layer", role, layer["module_id"], "L04-L01", targets, [clones[pid]["id"] for pid in targets], interfaces, {"hem_shortening": amount, **{f'clip_level_{pid}': level for pid,level in levels.items()}}))
    validate_foundation_layers(result)
    return result


def validate_foundation_layers(pattern):
    """Recheck layer identity in generation, manual edits and exports."""
    pieces = {p["id"]: p for p in pattern["pieces"]}
    for op in pattern.get("composite_operations", []):
        if op['formula_id'] != 'L04-L01':
            continue
        if len(op["target_piece_ids"]) != len(op["added_piece_ids"]):
            _fail("Потеряны лекала материального слоя.", op["source_id"])
        prefix = op["kind"] if op["module_id"] in REGISTRY["combinations"]["deferred_layer_modules"] else f"{op['kind']}_{op['source_id']}"
        for pid, cid in zip(op["target_piece_ids"], op["added_piece_ids"]):
            if pid not in pieces or cid not in pieces:
                _fail("Потеряны лекала материального слоя.", op["source_id"])
            expected = _clone_piece(_shorten(pieces[pid], op["parameters_mm"]["hem_shortening"], op["source_id"], op['parameters_mm'].get(f'clip_level_{pid}')), prefix)
            actual = pieces[cid]
            for field in ("seam_contour", "internal_paths", "cut_quantity", "cut_on_fold", "mirrored_pair", "grainline", "notches"):
                if actual[field] != expected[field]:
                    _fail("Слой расходится с геометрией основы или количеством кроя; перестройте комплект.", op["source_id"], "LAYER_FOUNDATION_MISMATCH")


def deferred_layer_modules(request):
    spec = request['garment_spec']
    active = {e.get('module_id') for e in (spec.get('design_intent') or {}).get('elements', [])
              if e.get('included') is not False and e.get('support_status') == 'supported'}
    partitions = set(REGISTRY['combinations']['partition_modules']) | {
        'paired_equal_skirt_panels_v1', 'paired_straight_skirt_yoke_v1'}
    return set(REGISTRY['combinations']['deferred_layer_modules']) if composition_order(spec) or active & partitions else set()


def defer_composed_layers(request):
    modules = deferred_layer_modules(request)
    if not modules:
        return request
    result = deepcopy(request)
    intent = result['garment_spec'].get('design_intent')
    intent['layers'] = [layer for layer in intent['layers'] if layer.get('module_id') not in modules]
    return result

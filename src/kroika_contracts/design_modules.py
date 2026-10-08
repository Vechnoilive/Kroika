"""Shared capabilities for design review, hashing and geometry compilation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

REGISTRY = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
MODULES = tuple(REGISTRY['modules'])
DIMENSIONS = ('width', 'length', 'depth', 'spacing')


def module_ids(group: str) -> frozenset[str]:
    return frozenset(module['id'] for module in MODULES if module['group'] == group)


STAGE18_MODELING_MODULES = module_ids('modeling')
STAGE19_ELEMENT_MODULES = module_ids('composite_element')
STAGE19_LAYER_MODULES = module_ids('composite_layer')
STAGE21_TOPOLOGY_MODULES = module_ids('topology')
FIXED_ELEMENT_MODULES = module_ids('fixed_element')
FIXED_LAYER_MODULES = module_ids('fixed_layer')
DETAIL_ELEMENT_MODULES = module_ids('detail_element')
DETAIL_LAYER_MODULES = module_ids('detail_layer')
ADVANCED_ELEMENT_MODULES = module_ids('advanced_element')
FULLNESS_MODULES = module_ids('fullness')
STRUCTURAL_MODULES = module_ids('structural')
FOUNDATION_LAYER_MODULES = module_ids('foundation_layer')


def composition_order(spec):
    """Composition order is geometry, so unlike tiers cannot share a cache key."""
    active = [e for e in (spec.get('design_intent') or {}).get('elements', [])
              if e.get('included') is not False and e.get('support_status') == 'supported']
    ids = {e.get('module_id') for e in active}
    partitions = set(REGISTRY['combinations']['partition_modules']) | {
        'paired_straight_skirt_yoke_v1', 'paired_equal_skirt_panels_v1'}
    trims = set(REGISTRY['combinations']['sequential_hem_modules'])
    interactions = {m['id'] for m in MODULES if m['group'] in {
        'modeling', 'fullness', 'structural', 'composite_element', 'detail_element', 'advanced_element'}
        and m['id'] not in partitions}
    legacy_layers = any(layer.get('included') is not False and layer.get('module_id') in REGISTRY['combinations']['deferred_layer_modules'] for layer in (spec.get('design_intent') or {}).get('layers', []))
    composed = (bool(ids & partitions) and (bool(ids & interactions) or legacy_layers)
                or sum(e.get('module_id') in trims and e.get('location') == 'hem' for e in active) > 1
                or bool(ids & {'diagonal_bodice_drape_v2', 'crossed_bodice_drape_v1'})
                and bool(ids & {'integrated_bodice_drape_v2', 'integrated_bodice_gather_v2'}))
    return [[e['source_element_id'], e['module_id']] for e in active] if composed else []


def placement_matches(module: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    placement = item.get('placement') or {}
    if not isinstance(placement, Mapping):
        return False
    allowed = module.get('placement') or {}
    if any(key not in allowed for key in placement):
        return False
    for key, value in placement.items():
        bounds = allowed[key]
        if key in {'side', 'edge', 'orientation'}:
            if value not in bounds:
                return False
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            return False
    if module['id'] in {'placed_edge_ruffle_v2', 'placed_edge_flounce_v2', 'explicit_polygon_detail_v3'}:
        location = item.get('location', '')
        edges = {'hem', 'waist'} if location.startswith('skirt') else {'neckline', 'waist', 'shoulder'} if location.startswith('bodice') else {'hem'}
        if placement.get('edge', 'neckline' if location.startswith('bodice') else 'hem') not in edges:
            return False
    if 'side' in allowed:
        side = placement.get('side', 'both')
        if item.get('symmetry') == 'symmetric':
            if side != 'both' or item.get('count') != 2:
                return False
        elif side not in {'right', 'left'} or item.get('count') != 1:
            return False
    return True


def _rule_matches(
    rule: Mapping[str, Any], item: Mapping[str, Any], spec: Mapping[str, Any],
) -> bool:
    for field, allowed in rule.items():
        if field == 'configured_closure':
            closure = spec['parameters']['closure']
            locations = {
                'center_back': ('bodice_back',),
                'center_front': ('bodice_front', 'trouser_front'),
                'side': ('waist',),
            }
            variant = 'tie' if closure['type'] == 'lacing' else closure['type']
            if (item.get('variant') != variant
                    or item.get('location') not in locations.get(closure['location'], ())):
                return False
            continue
        value = spec.get('garment_type') if field == 'garment_type' else item.get(field)
        if field == 'sleeve_type':
            value = spec['parameters']['sleeve']['type']
        elif field == 'bodice_fit':
            value = spec['parameters']['bodice_fit']
        if field == 'count':
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value != int(value)):
                return False
        if value not in allowed:
            return False
    return True


def module_matches(
    module_id: str | None, item: Mapping[str, Any], spec: Mapping[str, Any],
    *, kind: str, check_dimensions: bool = True,
) -> bool:
    module = next((entry for entry in MODULES if entry['id'] == module_id), None)
    if module is None or module['kind'] != kind:
        return False
    if not any(_rule_matches(rule, item, spec) for rule in module['rules']):
        return False
    if not placement_matches(module, item):
        return False
    if kind == 'proportions' and module_id == 'bounded_visual_proportions':
        return all(item.get(key) is None for key in (
            'waist_shift_mm', 'waist_level_circumference_mm', 'back_waist_level_arc_mm', 'hem_delta_mm'))
    if kind == 'proportions' and module_id == 'parametric_visual_proportions_v1':
        return proportion_dimensions_match(item, spec, check_dimensions=check_dimensions)
    if kind == 'layer':
        return layer_parameters_match(item, spec, module_id, check_dimensions=check_dimensions)
    if kind != 'element' or not check_dimensions:
        return True
    dimensions = item.get('dimensions_mm') or {}
    if not isinstance(dimensions, Mapping):
        return False
    for field in DIMENSIONS:
        value = dimensions.get(field)
        required = module['dimensions']['required']
        bounds = required.get(field) or module['dimensions']['optional'].get(field)
        if value is None:
            if field in required:
                return False
            continue
        if (bounds is None or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            return False
        maximum = bounds[1]
        if maximum == 'skirt_length_minus_20':
            maximum = spec['parameters']['skirt']['length_from_waist_mm'] - 20
        if not bounds[0] <= value <= maximum:
            return False
    if module.get('custom_outline'):
        outline = item.get('outline_mm')
        if not isinstance(outline, list) or not 3 <= len(outline) <= 24:
            return False
        if any(not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 2000 for v in p) for p in outline):
            return False
        index = (item.get('placement') or {}).get('outline_edge_index', 0)
        if not isinstance(index, int) or not 0 <= index < len(outline):
            return False
        a, b = outline[index], outline[(index + 1) % len(outline)]
        if abs(math.hypot(b[0]-a[0], b[1]-a[1]) - dimensions['length']) > 1:
            return False
    elif item.get('outline_mm') is not None:
        return False
    if module_id in {'front_bodice_yoke_v3', 'back_bodice_yoke_v3', 'offset_skirt_panel_v3'}:
        extra = 'depth' if module_id == 'offset_skirt_panel_v3' else 'width'
        if (dimensions.get(extra) is not None) != (item.get('variant') == 'shaped'):
            return False
    return True


def layer_parameters_match(item, spec, module_id, *, check_dimensions=True):
    targets = item.get('detail_source_ids') or []
    shortening = item.get('hem_shortening_mm') or 0
    if module_id not in FOUNDATION_LAYER_MODULES:
        return not targets and not shortening
    if isinstance(shortening, bool) or not isinstance(shortening, (int, float)) or not math.isfinite(shortening) or not 0 <= shortening <= 300:
        return False
    if shortening and item.get('coverage') not in {'skirt', 'sleeves'}:
        return False
    if not check_dimensions:
        return True
    if item.get('coverage') == 'detail':
        active = {e['source_element_id'] for e in (spec.get('design_intent') or {}).get('elements', []) if e.get('included') is not False}
        return bool(targets) and len(targets) == len(set(targets)) and set(targets) <= active
    return not targets


def matching_module(
    item: Mapping[str, Any], spec: Mapping[str, Any], *, kind: str,
) -> str | None:
    if item.get('selected_module_id') is not None or item.get('module_id') is not None:
        selected = item.get('selected_module_id') or item['module_id']
        return selected if module_matches(selected, item, spec, kind=kind) else None
    return next((module['id'] for module in MODULES
                 if module_matches(module['id'], item, spec, kind=kind)), None)


def proportion_dimensions_match(item: Mapping[str, Any], spec: Mapping[str, Any], *, check_dimensions: bool = True) -> bool:
    def bounded(key: str, low: float, high: float) -> bool:
        value = item.get(key)
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and low <= value <= high)
    shifted = item.get('waist_position') != 'natural'
    if shifted:
        if spec['garment_type'] not in {'dress', 'sundress', 'skirt', 'top', 'blouse', 'shirt', 'vest', 'jacket', 'trousers', 'shorts'}:
            return False
        if check_dimensions and not (bounded('waist_shift_mm', 10, 100)
                and bounded('waist_level_circumference_mm', 400, 1800)
                and bounded('back_waist_level_arc_mm', 100, 1000)):
            return False
        if check_dimensions and item['back_waist_level_arc_mm'] >= item['waist_level_circumference_mm']:
            return False
    elif check_dimensions and any(item.get(k) is not None for k in (
            'waist_shift_mm', 'waist_level_circumference_mm', 'back_waist_level_arc_mm')):
        return False
    tiered = item.get('hem_shape') == 'tiered'
    if tiered:
        if item.get('hem_delta_mm') is not None or not any(
            entry.get('included') is not False and entry.get('module_id') in {
                'tiered_hem_ruffle_v2', 'tiered_hem_flounce_v2',
            } and entry.get('support_status') == 'supported'
            for entry in (spec.get('design_intent') or {}).get('elements', [])
        ):
            return False
    shaped = item.get('hem_shape') not in {'straight', 'tiered'}
    if shaped:
        if spec['garment_type'] not in {'dress', 'sundress', 'skirt', 'top', 'blouse', 'shirt', 'vest', 'jacket', 'trousers', 'shorts'}:
            return False
        if check_dimensions and not bounded('hem_delta_mm', 20, 250):
            return False
        if item['hem_shape'] == 'asymmetric' and item['asymmetry'] != 'yes':
            return False
    elif check_dimensions and item.get('hem_delta_mm') is not None:
        return False
    return True


def structural_conflicts(spec: Mapping[str, Any]) -> list[str]:
    """Known shared-target conflicts; independent targets remain available."""
    intent = spec.get('design_intent') or {}
    active = [i for i in intent.get('elements', []) if i.get('included') is not False and i.get('support_status') == 'supported']
    ids = [i.get('module_id') for i in active]
    messages = []
    groups = [set(group) for group in REGISTRY['combinations']['exclusive_groups']]
    if any(sum(id in group for id in ids) > 1 for group in groups):
        messages.append('На один срез назначены две альтернативные конструктивные детали. Выберите одну конструкцию этого участка.')
    # Dart relocation is a preparation operation; two competing relocations still conflict.
    for item in active:
        if item.get('module_id') == 'side_to_waist_dart_v3' and any(
            other is not item and other.get('location') == item.get('location')
            and other.get('module_id') == 'front_waist_to_side_dart_v1' for other in active
        ):
            messages.append('Для одной вытачки выберите одно направление переноса.')
    if any(id in ids for id in {'fitted_two_piece_hood_v3', 'shaped_flat_collar_v3', 'shawl_collar_v3'}) and any(id in ids for id in {'straight_shoulder_straps_v3', 'off_shoulder_bands_v1'}):
        messages.append('Воротник и капюшон требуют горловину с плечами; открытый верх под бретели использует другую конструкцию.')
    if 'straight_shoulder_straps_v3' in ids and any(id in ids for id in {'integrated_bodice_drape_v2', 'integrated_bodice_gather_v2'}):
        messages.append('Раскрытия до горловины и срезанный верх под бретели используют разные верхние срезы. Выберите раскрытие ниже верха или отдельную драпировку.')
    layers = [layer for layer in intent.get('layers', []) if layer.get('included') is not False and layer.get('support_status') == 'supported' and layer.get('role') != 'main']
    for index, layer in enumerate(layers):
        scope = layer['coverage']
        if spec['garment_type'] == 'jacket' and layer['role'] == 'lining' and scope in {'full', 'bodice', 'sleeves'} and layer.get('module_id') in FOUNDATION_LAYER_MODULES:
            messages.append('Полная подкладка жакета уже включена в основу. Не добавляйте второй слой подкладки на те же детали.')
        for other in layers[index + 1:]:
            if layer['role'] != other['role']:
                continue
            same = scope == other['coverage'] and (scope != 'detail' or bool(set(layer.get('detail_source_ids') or []) & set(other.get('detail_source_ids') or [])))
            whole = scope == 'full' and other['coverage'] != 'detail' or other['coverage'] == 'full' and scope != 'detail'
            if same or whole:
                messages.append('Два слоя одной роли покрывают одну часть изделия. Выберите непересекающиеся покрытия.')
    return list(dict.fromkeys(messages))

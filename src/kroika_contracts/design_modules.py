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


def placement_matches(module: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    placement = item.get('placement') or {}
    if not isinstance(placement, Mapping):
        return False
    allowed = module.get('placement') or {}
    if any(key not in allowed for key in placement):
        return False
    for key, value in placement.items():
        bounds = allowed[key]
        if key in {'side', 'edge'}:
            if value not in bounds:
                return False
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            return False
    if module['id'] in {'placed_edge_ruffle_v2', 'placed_edge_flounce_v2'}:
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
    return True


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
        if spec['garment_type'] not in {'dress', 'sundress'}:
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
        if spec['garment_type'] not in {'dress', 'sundress', 'skirt'}:
            return False
        if check_dimensions and not bounded('hem_delta_mm', 20, 250):
            return False
        if item['hem_shape'] == 'asymmetric' and item['asymmetry'] != 'yes':
            return False
    elif check_dimensions and item.get('hem_delta_mm') is not None:
        return False
    return True

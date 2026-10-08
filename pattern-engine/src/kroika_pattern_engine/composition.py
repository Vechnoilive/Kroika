"""Schedule full hem modules in the reviewed order across recipe generations."""
from copy import deepcopy

from kroika_contracts.design_modules import REGISTRY
from .modeling import apply_modeling_transformations
from .details import apply_detail_transformations
from .fullness import apply_fullness_details


def hem_sequence(request):
    return [e for e in (request['garment_spec'].get('design_intent') or {}).get('elements', [])
            if e.get('included') is not False and e.get('support_status') == 'supported'
            and e.get('location') == 'hem'
            and e.get('module_id') in REGISTRY['combinations']['sequential_hem_modules']]


def defer_hem_sequence(request):
    sequence = hem_sequence(request)
    if len(sequence) < 2:
        return request
    result = deepcopy(request)
    ids = {e['source_element_id'] for e in sequence}
    result['garment_spec']['design_intent']['elements'] = [e for e in result['garment_spec']['design_intent']['elements']
                                                        if e['source_element_id'] not in ids]
    return result


def apply_hem_sequence(pattern, request):
    sequence = hem_sequence(request)
    if len(sequence) < 2:
        return pattern
    result = pattern
    for item in sequence:
        current = deepcopy(request)
        current['garment_spec']['design_intent']['elements'] = [item]
        current['garment_spec']['design_intent']['layers'] = []
        module = item['module_id']
        if module == 'circular_hem_flounce_v1':
            previous = result.get('modeling_operations', [])
            result = apply_modeling_transformations(result,current).pattern
            existing = {op['operation_id'] for op in previous}
            result['modeling_operations'] = previous + [op for op in result['modeling_operations'] if op['operation_id'] not in existing]
        elif module.startswith('tiered_hem_'):
            result = apply_fullness_details(result,current)
        else:
            result = apply_detail_transformations(result,current).pattern
    return result

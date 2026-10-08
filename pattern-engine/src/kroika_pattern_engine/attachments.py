"""Resolve physical boundaries after partitioning, rather than stale block IDs."""

import re
from kroika_contracts.design_modules import REGISTRY

from .blocks import BlockConstructionError
from .geometry import contour_from_data


def descendants(pattern, root):
    return [p for p in pattern['pieces'] if p['id'] == root
            or p['id'].startswith((root + '__', root + '_panel_', root + '_yoke'))]


def boundary_edges(piece, name):
    # Renamed occupied edges end in _join. Fragmented original boundaries retain
    # their semantic token; new partition joins never acquire that token.
    return [e for e in contour_from_data(piece['seam_contour']).segments
            if re.search(r'(?:^|_)' + re.escape(name) + r'(?:_|$)', e.id)
            and not e.id.endswith('_join')]


def boundary_records(pattern, root, name, source):
    records = [(p, boundary_edges(p, name)) for p in descendants(pattern, root)]
    records = [(p, edges) for p, edges in records if edges]
    if not records:
        raise BlockConstructionError('ATTACHMENT_BOUNDARY_MISSING',
                                     'Выбранный срез отсутствует на итоговых деталях.',
                                     f'/garment_spec/design_intent/elements/{source}')
    # Traverse the reconstructed boundary consistently from the centre outwards.
    records.sort(key=lambda rec: min(min(e.start.x_mm, e.end.x_mm) for e in rec[1]))
    return records


def terminal_records(pattern, root, name, source):
    """Follow sewn trim to its free edge, supporting successive unlike tiers."""
    candidates = descendants(pattern, root)
    visited = set()
    records = []
    while candidates:
        piece = candidates.pop(0)
        if piece['id'] in visited:
            continue
        visited.add(piece['id'])
        edges = boundary_edges(piece, name)
        if edges:
            records.append((piece, edges))
            continue
        child_ids = {pair['second_piece_id'] for pair in pattern['seam_pairs']
                     if pair['first_piece_id'] == piece['id']
                     and any('_' + name + '_' in sid for sid in pair['first_segment_ids'])}
        if name == 'hem':
            trimmed = {pid for key in ('composite_operations', 'modeling_operations')
                       for op in pattern.get(key, [])
                       if op['module_id'] in REGISTRY['combinations']['sequential_hem_modules']
                       for pid in op.get('added_piece_ids', op['target_piece_ids'])}
            child_ids.update(pair['second_piece_id'] for pair in pattern['seam_pairs']
                             if pair['first_piece_id'] == piece['id']
                             and pair['second_piece_id'] in trimmed)
        candidates.extend(p for p in pattern['pieces'] if p['id'] in child_ids)
    if not records:
        return boundary_records(pattern, root, name, source)
    return records


def rename_boundary_references(pattern, target, mapping):
    """Keep joins and saved marker coordinates attached to an unchanged edge."""
    for notch in target['notches']:
        notch['segment_id'] = mapping.get(notch['segment_id'], notch['segment_id'])
    for pair in pattern['seam_pairs']:
        for side in ('first', 'second'):
            if pair[f'{side}_piece_id'] == target['id']:
                pair[f'{side}_segment_ids'] = [mapping.get(sid, sid) for sid in pair[f'{side}_segment_ids']]
    for key in ('modeling_operations', 'topology_operations', 'composite_operations'):
        for op in pattern.get(key, []):
            parameters = {}
            for name, value in op['parameters_mm'].items():
                for old in sorted(mapping, key=len, reverse=True):
                    if name.startswith(old+'_'):
                        name = mapping[old]+name[len(old):]
                        break
                parameters[name] = value
            op['parameters_mm'] = parameters

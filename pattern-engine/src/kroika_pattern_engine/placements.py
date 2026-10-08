"""Continuous applications on an assembled foundation, split at real cut seams."""

from dataclasses import replace

from .attachments import descendants
from .blocks import BlockConstructionError
from .geometry import BoundingBox, Contour, CubicBezier, LineSegment, Point, contour_from_data, contour_to_data
from .geometry.errors import OverlappingGeometryError
from .geometry.intersections import intersections
from .geometry.primitives import curve_points

ROOTS = ('front_bodice', 'back_bodice', 'front_skirt', 'back_skirt', 'front_trouser', 'back_trouser')


def _error(source, message, code='DETAIL_PLACEMENT_OUTSIDE'):
    return BlockConstructionError(code, message, f'/garment_spec/design_intent/elements/{source}')


def placement_frame(pattern, root, source):
    pieces = descendants(pattern, root)
    if not pieces:
        raise _error(source, 'Нет итоговых деталей для выбранного расположения.', 'DETAIL_TARGET_MISSING')
    boxes = [contour_from_data(p['seam_contour']).bounding_box for p in pieces]
    return pieces, BoundingBox(min(b.min_x_mm for b in boxes), min(b.min_y_mm for b in boxes),
                              max(b.max_x_mm for b in boxes), max(b.max_y_mm for b in boxes))


def _clip(pieces, curve, source):
    from .details import _inside
    from .fullness import _subcurve, _check_line

    found = []
    for piece in pieces:
        contour = contour_from_data(piece['seam_contour'])
        polygon = [p for e in contour.segments for _, p in curve_points(e, 0.02)[:-1]]
        roots = [0.0, 1.0]
        for edge in contour.segments:
            try:
                roots.extend(hit.first_parameter for hit in intersections(curve, edge, flatness_mm=0.01))
            except OverlappingGeometryError as exc:
                raise _error(source, 'Линия нанесения совпала со срезом или швом членения. '
                             'Немного измените положение детали.', 'DETAIL_PLACEMENT_COINCIDENT') from exc
        roots = sorted(set(round(t, 9) for t in roots))
        for a, b in zip(roots, roots[1:]):
            if b - a > 1e-8 and _inside(curve.point_at((a + b) / 2), polygon):
                fragment = _subcurve(curve, a, b)
                _check_line(piece, fragment, source, boundary=True)
                found.append((a, b, piece, fragment))
    found.sort(key=lambda rec: rec[0])
    cursor = 0.0
    for a, b, _, _ in found:
        if abs(a - cursor) > 1e-6:
            raise _error(source, 'Контур или вход кармана выходит за основу либо попадает '
                         'в разрыв/перекрытие деталей. Измените размер или положение.')
        cursor = b
    if abs(cursor - 1) > 1e-6:
        raise _error(source, 'Контур или вход кармана выходит за основу. Измените размер или положение.')
    return found


def _region(pattern, pieces, footprint, source):
    """Reject enclosed darts/holes too, not just intersections of the perimeter."""
    from .details import _inside

    polygon = [p for edge in footprint for _, p in curve_points(edge, 0.02)[:-1]]
    ids = {p['id'] for p in pieces}
    paired = {(pair[f'{side}_piece_id'], sid)
              for pair in pattern['seam_pairs']
              if pair['first_piece_id'] in ids and pair['second_piece_id'] in ids
              for side in ('first', 'second') for sid in pair[f'{side}_segment_ids']}
    for piece in pieces:
        for path in piece['internal_paths']:
            if 'dart' in path['id'] and any(_inside(p, polygon) for e in contour_from_data(path).segments
                                            for _, p in curve_points(e, 0.02)):
                raise _error(source, 'Накладная деталь или вход кармана перекрывает вытачку. '
                             'Измените положение.', 'DETAIL_PLACEMENT_DART_CONFLICT')
        for edge in contour_from_data(piece['seam_contour']).segments:
            if (piece['id'], edge.id) not in paired and any(_inside(edge.point_at(t), polygon)
                                                           for t in (0.25, 0.5, 0.75)):
                raise _error(source, 'Область нанесения перекрывает открытый срез или разрыв основы.')


def _save_curve(params, prefix, curve):
    params[prefix + '_kind'] = int(isinstance(curve, CubicBezier))
    for end in ('start', 'end', *(['control_1', 'control_2'] if isinstance(curve, CubicBezier) else [])):
        point = getattr(curve, end)
        params[f'{prefix}_{end}_px'] = point.x_mm
        params[f'{prefix}_{end}_py'] = point.y_mm


def _load_curve(params, prefix, cid):
    def point(end):
        return Point(params[f'{prefix}_{end}_px'], params[f'{prefix}_{end}_py'])
    return (CubicBezier(point('start'), point('control_1'), point('control_2'), point('end'), cid)
            if params[prefix + '_kind'] == 1 else LineSegment(point('start'), point('end'), cid))


def _on_boundary(edges, point):
    for edge in edges:
        points = curve_points(edge, 0.01)
        for (_, a), (_, b) in zip(points, points[1:]):
            dx, dy = b.x_mm - a.x_mm, b.y_mm - a.y_mm
            denominator = dx * dx + dy * dy
            t = max(0, min(1, ((point.x_mm - a.x_mm) * dx + (point.y_mm - a.y_mm) * dy) / denominator)) if denominator else 0
            if point.distance_to(Point(a.x_mm + t * dx, a.y_mm + t * dy)) <= 0.03:
                return True
    return False


def distribute_placement(pattern, root, curves, source, attachments=None, footprint=None):
    """Mark one continuous placement, retaining exact parameter intervals and joins.

    attachments maps curve index to (separate piece, matching original edge).
    Matching subcurves are print guides on the original whole detail, not new cut pieces.
    """
    from .composites import _seam_pair
    from .fullness import _subcurve

    attachments = attachments or {}
    pieces, _ = placement_frame(pattern, root, source)
    if footprint:
        _region(pattern, pieces, footprint, source)
    clips = [_clip(pieces, curve, source) for curve in curves]
    targets = list(dict.fromkeys(piece['id'] for records in clips for _, _, piece, _ in records))
    added = list(dict.fromkeys(piece['id'] for piece, _ in attachments.values()))
    params = {'placement_root': ROOTS.index(root), 'placement_curve_count': len(curves)}
    interfaces = []
    fragment_index = 0
    for i, (curve, records) in enumerate(zip(curves, clips)):
        _save_curve(params, f'placement_curve_{i}', curve)
        for a, b, target, fragment in records:
            prefix = f'placement_fragment_{fragment_index}'
            pid = f'{source}_placement_fragment_{fragment_index}'
            edge = replace(fragment, id=pid + '_edge')
            target['internal_paths'].append(contour_to_data(Contour((edge,), id=pid, closed=False)))
            interfaces.append(pid)
            params.update({prefix + '_curve': i, prefix + '_target': targets.index(target['id']),
                           prefix + '_a': a, prefix + '_b': b, prefix + '_match': -1})
            _save_curve(params, prefix, edge)
            if i in attachments:
                detail, original = attachments[i]
                mid = pid + '_match'
                match = replace(_subcurve(original, a, b), id=mid + '_edge')
                detail['internal_paths'].append(contour_to_data(Contour((match,), id=mid, closed=False)))
                pair = _seam_pair(pid + '_join', target['id'], [edge.id], detail['id'], [match.id])
                pattern['seam_pairs'].append(pair)
                interfaces.extend([mid, pair['id']])
                params[prefix + '_match'] = added.index(detail['id'])
                _save_curve(params, prefix + '_match', match)
            fragment_index += 1
    params['placement_fragment_count'] = fragment_index
    params['placement_footprint_count'] = len(footprint or [])
    for i, edge in enumerate(footprint or []):
        _save_curve(params, f'placement_footprint_{i}', edge)
    return targets, interfaces, params


def validate_placement_operations(pattern):
    """Called again after manual editing and before SVG/PDF export."""
    from .fullness import _check_line, _subcurve

    by_id = {p['id']: p for p in pattern['pieces']}
    pairs = {p['id']: p for p in pattern['seam_pairs']}
    for op in pattern.get('composite_operations', []):
        params, source = op['parameters_mm'], op['source_id']
        if 'placement_fragment_count' not in params:
            continue
        root = ROOTS[int(params['placement_root'])]
        pieces, _ = placement_frame(pattern, root, source)
        footprint = [_load_curve(params, f'placement_footprint_{i}', f'footprint_{i}')
                     for i in range(int(params['placement_footprint_count']))]
        if footprint:
            _region(pattern, pieces, footprint, source)
        intervals = {}
        for i in range(int(params['placement_fragment_count'])):
            prefix, pid = f'placement_fragment_{i}', f'{source}_placement_fragment_{i}'
            target = by_id.get(op['target_piece_ids'][int(params[prefix + '_target'])])
            path = next((p for p in (target or {}).get('internal_paths', []) if p['id'] == pid), None)
            if not path or len(path['segments']) != 1:
                raise _error(source, 'Удалена линия нанесения детали.', 'DETAIL_PLACEMENT_MARKER_MISSING')
            actual = contour_from_data(path).segments[0]
            expected = _load_curve(params, prefix, pid + '_edge')
            if actual.id != expected.id or any(actual.point_at(t).distance_to(expected.point_at(t)) > 1e-5
                                               for t in (0, 0.25, 0.5, 0.75, 1)):
                raise _error(source, 'Изменена линия нанесения детали. Перестройте её по новым размерам.',
                             'DETAIL_PLACEMENT_MARKER_MOVED')
            _check_line(target, actual, source, boundary=True)
            curve_index = int(params[prefix + '_curve'])
            original = _load_curve(params, f'placement_curve_{curve_index}', f'original_{curve_index}')
            a, b = params[prefix + '_a'], params[prefix + '_b']
            section = _subcurve(original, a, b)
            if any(actual.point_at(t).distance_to(section.point_at(t)) > 0.05 for t in (0, 0.25, 0.5, 0.75, 1)):
                raise _error(source, 'Линия нанесения потеряла связь с исходным контуром.', 'DETAIL_PLACEMENT_INTERVAL_INVALID')
            boundary = contour_from_data(target['seam_contour']).segments
            if ((a > 1e-6 and not _on_boundary(boundary, actual.start))
                    or (b < 1 - 1e-6 and not _on_boundary(boundary, actual.end))):
                raise _error(source, 'Шов членения сместился относительно метки нанесения. Перестройте деталь.',
                             'DETAIL_PLACEMENT_TOPOLOGY_CHANGED')
            intervals.setdefault(curve_index, []).append((params[prefix + '_a'], params[prefix + '_b']))
            match_index = int(params[prefix + '_match'])
            if match_index >= 0:
                detail_id = op['added_piece_ids'][match_index]
                detail = by_id.get(detail_id)
                mid = pid + '_match'
                match_path = next((p for p in (detail or {}).get('internal_paths', []) if p['id'] == mid), None)
                pair = pairs.get(pid + '_join')
                if not match_path or not pair or len(match_path['segments']) != 1:
                    raise _error(source, 'Удалено парное крепление детали.', 'DETAIL_PLACEMENT_JOIN_MISSING')
                match = contour_from_data(match_path).segments[0]
                expected_match = _load_curve(params, prefix + '_match', mid + '_edge')
                if match.id != expected_match.id or any(match.point_at(t).distance_to(expected_match.point_at(t)) > 1e-5
                                                        for t in (0, 0.25, 0.5, 0.75, 1)):
                    raise _error(source, 'Изменён парный участок детали.', 'DETAIL_PLACEMENT_MARKER_MOVED')
                detail_boundary = contour_from_data(detail['seam_contour']).segments
                if not all(_on_boundary(detail_boundary, match.point_at(t)) for t in (0, 0.25, 0.5, 0.75, 1)):
                    raise _error(source, 'Крепление отделилось от среза дополнительной детали.',
                                 'DETAIL_PLACEMENT_JOIN_DETACHED')
                if abs(actual.length_mm - match.length_mm) > 0.05:
                    raise _error(source, 'Длины парных участков крепления различаются.', 'DETAIL_PLACEMENT_JOIN_CHANGED')
                if (pair['first_piece_id'], pair['first_segment_ids'], pair['second_piece_id'], pair['second_segment_ids']) != (target['id'], [actual.id], detail_id, [match.id]):
                    raise _error(source, 'Крепление перенаправлено на другие линии.', 'DETAIL_PLACEMENT_JOIN_CHANGED')
        for i in range(int(params['placement_curve_count'])):
            cursor = 0.0
            for a, b in sorted(intervals.get(i, [])):
                if abs(a - cursor) > 1e-6 or b <= a:
                    raise _error(source, 'В линии нанесения возник разрыв или перекрытие.', 'DETAIL_PLACEMENT_INTERVAL_INVALID')
                cursor = b
            if abs(cursor - 1) > 1e-6:
                raise _error(source, 'Потерян участок нанесения.', 'DETAIL_PLACEMENT_INTERVAL_INVALID')


def containing_piece(pieces, edges, source):
    """Keep legacy whole-piece geometry when possible; otherwise use split placement."""
    from .fullness import _check_line
    for piece in pieces:
        try:
            for edge in edges:
                _check_line(piece, edge, source)
        except BlockConstructionError:
            continue
        return piece
    return None

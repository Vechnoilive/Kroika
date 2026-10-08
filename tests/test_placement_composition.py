"""Continuous placed applications across the seams of actual cut foundations."""
from collections import defaultdict
from copy import deepcopy
from io import BytesIO
import json

import pytest
from pypdf import PdfReader
from kroika_contracts.contract_io import validate_document
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg
from kroika_pattern_engine.blocks import BlockConstructionError
from kroika_pattern_engine.geometry import CubicBezier, contour_from_data
from kroika_pattern_engine.pdf import render_pattern_pdf
from kroika_pattern_engine.placements import _load_curve, validate_placement_operations
from kroika_pattern_engine.validation import validate_pattern_assembly, validate_export_coverage
from tests.test_additional_details import request, element, CASES
from tests.test_repository_audit import structural, build
from tests.test_stage21_topology import _panels, _yoke
from tests.test_stage12_garments import _project, _client

MODULES = ['placed_patch_pocket_v1', 'rectangular_applied_panel_v1', 'rounded_patch_pocket_v3', 'welt_pocket_v3']


def application(module):
    return element(CASES[2 if module == MODULES[0] else 3]) if module in MODULES[:2] else structural(module)


def operation(pattern, module):
    return next(op for op in pattern['composite_operations'] if op['module_id'] == module)


@pytest.fixture(scope='module', params=MODULES)
def crossing(request):
    module = request.param
    return module, build([_panels(), application(module)])


def test_all_placed_recipes_keep_whole_details_and_continuous_exact_interfaces(crossing):
    module, p = crossing
    op = operation(p, module)
    params = op['parameters_mm']
    assert len(op['target_piece_ids']) == 2
    assert len(op['added_piece_ids']) == (4 if module == 'welt_pocket_v3' else 1)
    assert all(next(piece for piece in p['pieces'] if piece['id'] == pid)['cutting_contour']['closed'] for pid in op['added_piece_ids'])
    by_id = {piece['id']: piece for piece in p['pieces']}
    intervals, lengths = defaultdict(list), defaultdict(float)
    for i in range(int(params['placement_fragment_count'])):
        key = f'placement_fragment_{i}'
        curve = int(params[key + '_curve'])
        intervals[curve].append((params[key + '_a'], params[key + '_b']))
        path = next(path for path in by_id[op['target_piece_ids'][int(params[key + '_target'])]]['internal_paths'] if path['id'] == f"{op['source_id']}_placement_fragment_{i}")
        edge = contour_from_data(path).segments[0]
        lengths[curve] += edge.length_mm
        if params[key + '_match'] >= 0:
            pair = next(pair for pair in p['seam_pairs'] if pair['id'] == path['id'] + '_join')
            match = next(path for path in by_id[pair['second_piece_id']]['internal_paths'] if path['id'] == f"{op['source_id']}_placement_fragment_{i}_match")
            assert edge.length_mm == pytest.approx(contour_from_data(match).segments[0].length_mm, abs=.05)
    for curve, ranges in intervals.items():
        ordered = sorted(ranges)
        assert ordered[0][0] == 0 and ordered[-1][1] == 1
        assert all(a[1] == pytest.approx(b[0], abs=1e-6) for a, b in zip(ordered, ordered[1:]))
        original = _load_curve(params, f'placement_curve_{curve}', 'original')
        assert lengths[curve] == pytest.approx(original.length_mm, abs=.05)
    assert any('Сначала стачать' in a['text_ru'] for pid in op['added_piece_ids'] for a in by_id[pid]['annotations'])
    validate_placement_operations(json.loads(json.dumps(p)))


@pytest.mark.parametrize('damage,code', [('move', 'DETAIL_PLACEMENT_MARKER_MOVED'), ('remove', 'DETAIL_PLACEMENT_MARKER_MISSING'), ('join', 'DETAIL_PLACEMENT_JOIN_CHANGED'), ('detach', 'DETAIL_PLACEMENT_JOIN_DETACHED')])
def test_invalid_manual_changes_cannot_reach_svg_or_pdf(crossing, damage, code):
    module, pattern = crossing
    p = deepcopy(pattern)
    op = operation(p, module)
    pair = next(pair for pair in p['seam_pairs'] if pair['id'].startswith(op['source_id'] + '_placement_fragment_'))
    target = next(piece for piece in p['pieces'] if piece['id'] == pair['first_piece_id'])
    path = next(path for path in target['internal_paths'] if path['segments'][0]['id'] == pair['first_segment_ids'][0])
    if damage == 'move':
        path['segments'][0]['start'][0] += 1
    elif damage == 'remove':
        target['internal_paths'].remove(path)
    elif damage == 'join':
        pair['first_piece_id'] = op['target_piece_ids'][1] if op['target_piece_ids'][0] == target['id'] else op['target_piece_ids'][0]
    else:
        detail = next(piece for piece in p['pieces'] if piece['id'] == pair['second_piece_id'])
        for edge in detail['seam_contour']['segments']:
            for key in ('start', 'end', 'control_1', 'control_2'):
                if key in edge:
                    edge[key][0] += 2
    with pytest.raises(BlockConstructionError, match=code):
        validate_export_coverage(p)
    for export in (render_pattern_svg, render_pattern_pdf):
        with pytest.raises(ValueError) as rejected:
            export(p)
        assert code in str(rejected.value.__cause__)


def test_curved_corner_crosses_a_join_without_straightening():
    e = structural('rounded_patch_pocket_v3')
    e['dimensions_mm']['spacing'] = 95
    p = build([_panels(), e])
    op = operation(p, e['module_id'])
    params = op['parameters_mm']
    curved = [i for i in range(int(params['placement_fragment_count'])) if params[f'placement_fragment_{i}_kind'] == 1]
    assert any(params[f'placement_fragment_{i}_a'] > 0 or params[f'placement_fragment_{i}_b'] < 1 for i in curved)
    assert all(isinstance(_load_curve(params, f'placement_fragment_{i}', 'curve'), CubicBezier) for i in curved)


@pytest.mark.parametrize('module', MODULES)
def test_placement_across_horizontal_yoke_seam(module):
    e = application(module)
    if module in MODULES[:2]:
        e['dimensions_mm']['spacing'] = 360
    else:
        e['placement']['offset_mm'] = 115 if module == 'welt_pocket_v3' else 80
        e['dimensions_mm']['spacing'] = 20
    p = build([_yoke(), e])
    assert len(operation(p, module)['target_piece_ids']) == 2


def test_welt_preserves_cut_triangles_and_two_continuous_stitch_lines():
    p = build([_panels(), application('welt_pocket_v3')])
    op = operation(p, 'welt_pocket_v3')
    assert op['parameters_mm']['placement_curve_count'] == 7
    assert op['parameters_mm']['placement_fragment_count'] > 7
    assert len([pair for pair in p['seam_pairs'] if pair['id'].endswith('_bag_closing')]) == 1


@pytest.mark.parametrize('invalid', ['outside', 'coincident'])
def test_invalid_placement_has_specific_geometry_error(invalid):
    e = structural('rounded_patch_pocket_v3')
    if invalid == 'outside':
        e['dimensions_mm']['spacing'] = 250
    else:
        e['dimensions_mm']['spacing'] = 20
        e['placement']['offset_mm'] = 120
    r = request([_panels() if invalid == 'outside' else _yoke(), e], project=_project('skirt'))
    r['input_hash'] = compute_input_hash(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is None
    assert any(i['code'] == ('DETAIL_PLACEMENT_OUTSIDE' if invalid == 'outside' else 'DETAIL_PLACEMENT_COINCIDENT') for i in out['validation_report']['issues'])


def test_saved_crossing_welt_reopens_uses_cache_and_prints_a4(tmp_path):
    project = _project('skirt')
    r = request([_panels(), structural('welt_pocket_v3')], project=project)
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    with _client(tmp_path) as api:
        assert api.post('/api/v1/projects', json=project).status_code == 201
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert reopened['garment_spec']['design_intent'] == r['garment_spec']['design_intent']
        response = api.post('/api/v1/patterns/generate', json=r)
        assert response.status_code == 200, response.text
        out = response.json()
        assert out['pattern'] is not None, out['validation_report']['issues']
        p = out['pattern']
        validate_document('pattern-data', p)
        validate_pattern_assembly(p)
        assert api.post('/api/v1/patterns/generate', json=r).json()['generation_id'] == out['generation_id']
        op = operation(p, 'welt_pocket_v3')
        assert f"{op['source_id']}_placement_fragment_0" in render_pattern_svg(p)
        pdf = render_pattern_pdf(p)
        pages = PdfReader(BytesIO(pdf.content)).pages
        assert len(pages) == pdf.page_count and len(pages) > 1
        assert all(abs(float(page.mediabox.width) - 595.28) < .1 for page in pages)
        text = '\n'.join(page.extract_text() for page in pages)
        assert 'Сначала стачать' in text and 'Обтачка прорезного кармана' in text


def test_pocket_crosses_a_bodice_yoke_in_the_same_coordinate_frame():
    cut = structural('back_bodice_yoke_v3')
    cut['source_element_id'] = 'cut'
    pocket = structural('rounded_patch_pocket_v3')
    pocket.update(source_element_id='pocket', location='bodice_back')
    pocket['dimensions_mm']['spacing'] = 30
    pocket['placement']['offset_mm'] = 50
    r = request([cut, pocket])
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    p = out['pattern']
    assert set(operation(p, pocket['module_id'])['target_piece_ids']) == {'back_bodice__cut', 'back_bodice'}
    validate_export_coverage(p)


def test_composed_lining_clones_the_final_foundation_and_retains_application():
    from tests.test_stage19_composites import _layer
    e = structural('rounded_patch_pocket_v3')
    r = request([_panels(), e], layers=[_layer('lining', 'lining', 'skirt', 'opaque', 'skirt_full_lining_v1')], project=_project('skirt'))
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    p = out['pattern']
    assert any(piece['id'].startswith('lining_') for piece in p['pieces'])
    assert len(operation(p, e['module_id'])['target_piece_ids']) == 2
    validate_pattern_assembly(p)
    validate_export_coverage(p)


def test_enclosed_dart_is_rejected_even_without_a_perimeter_intersection():
    from kroika_pattern_engine.placements import _region
    from kroika_pattern_engine.geometry import LineSegment, Point
    r = request([])
    out = GeometryPatternEngine().generate(r)
    p = out['pattern']
    piece = next(piece for piece in p['pieces'] if piece['id'] == 'back_bodice')
    dart = next(path for path in piece['internal_paths'] if 'dart' in path['id'])
    box = contour_from_data(dart).bounding_box
    points = [Point(box.min_x_mm - 5, box.min_y_mm - 5), Point(box.max_x_mm + 5, box.min_y_mm - 5), Point(box.max_x_mm + 5, box.max_y_mm + 5), Point(box.min_x_mm - 5, box.max_y_mm + 5)]
    footprint = [LineSegment(points[i], points[(i + 1) % 4], f'edge_{i}') for i in range(4)]
    with pytest.raises(BlockConstructionError, match='DETAIL_PLACEMENT_DART_CONFLICT'):
        _region(p, [piece], footprint, 'enclosed_dart')


def test_one_applied_panel_spans_three_foundation_parts():
    e = application('rectangular_applied_panel_v1')
    e['dimensions_mm']['width'] = 180
    p = build([_panels(), e])
    op = operation(p, e['module_id'])
    assert len(op['target_piece_ids']) == 3
    assert len(op['added_piece_ids']) == 1
    validate_placement_operations(p)

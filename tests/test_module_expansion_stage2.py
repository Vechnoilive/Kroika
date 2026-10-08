"""Shirt neck replacement, intersecting source-space cuts and read-only preview."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader
from kroika_contracts.contract_io import validate_document
from kroika_contracts.design_modules import matching_module, structural_conflicts
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg
from kroika_pattern_engine.blocks import BlockConstructionError
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.pdf import render_pattern_pdf
from kroika_pattern_engine.structural import validate_partition_joins
from kroika_pattern_engine.validation import validate_pattern_assembly, validate_export_coverage
from tests.test_repository_audit import structural
from tests.test_design_modules_step4 import base_request
from tests.test_stage21_topology import _panels, _yoke
from tests.test_stage19_composites import _element, _dimensions, _layer
from tests.test_stage12_garments import _client, _project
from tests.test_additional_details import request


def generate(r):
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    validate_document('pattern-data', out['pattern'])
    validate_pattern_assembly(out['pattern'])
    validate_export_coverage(out['pattern'])
    return out['pattern']


def neck(module):
    return _element('neck', 'collar', 'stand', 'neckline', 'separate_piece', 1, module, _dimensions(width=35)) if module == 'stand_collar_v1' else structural(module)


@pytest.mark.parametrize('module', ['stand_collar_v1', 'shaped_flat_collar_v3', 'shawl_collar_v3', 'fitted_two_piece_hood_v3'])
@pytest.mark.parametrize('shape', ['round', 'v'])
def test_shirt_uses_selected_neck_with_actual_neckline_and_no_original_assembly(module, shape):
    r = base_request('shirt')
    r['garment_spec']['parameters']['neckline']['type'] = shape
    e = neck(module)
    r['garment_spec']['design_intent']['elements'] = [e]
    assert matching_module(e, r['garment_spec'], kind='element') == module
    p = generate(r)
    ids = {piece['id'] for piece in p['pieces']}
    assert not {'collar_band', 'shirt_collar'} & ids
    assert not any(pair['id'] in {'front_collar_band_join', 'back_collar_band_join', 'collar_join'} for pair in p['seam_pairs'])
    op = next(op for op in p['composite_operations'] if op['module_id'] == module)
    assert {'front_bodice', 'back_bodice'} <= set(op['target_piece_ids'])
    assert op['added_piece_ids'] and all(pid in ids for pid in op['added_piece_ids'])
    front = next(piece for piece in p['pieces'] if piece['id'] == 'front_bodice')
    assert any('placket' in path['id'] for path in front['internal_paths'])


def test_shirt_standard_neck_is_restored_when_replacement_is_excluded():
    r = base_request('shirt')
    e = neck('shawl_collar_v3')
    e.update(included=False, support_status='excluded', module_id=None)
    r['garment_spec']['design_intent']['elements'] = [e]
    p = generate(r)
    assert {'collar_band', 'shirt_collar'} <= {piece['id'] for piece in p['pieces']}


@pytest.mark.parametrize('location', ['bodice_front', 'bodice_back'])
@pytest.mark.parametrize('reverse', [False, True])
def test_yoke_and_princess_form_four_cells_with_retained_joins(location, reverse):
    r = base_request()
    yoke = structural('front_bodice_yoke_v3' if location == 'bodice_front' else 'back_bodice_yoke_v3')
    yoke['source_element_id'] = 'yoke'
    princess = structural('shoulder_princess_seam_v3')
    princess.update(source_element_id='princess', location=location)
    r['garment_spec']['design_intent']['elements'] = [princess, yoke] if reverse else [yoke, princess]
    p = generate(r)
    root = 'front_bodice' if location == 'bodice_front' else 'back_bodice'
    cells = [piece for piece in p['pieces'] if piece['id'].startswith(root)]
    assert len(cells) == 4
    assert all(contour_from_data(piece['seam_contour']).area_mm2 > 25 for piece in cells)
    for source in ['yoke', 'princess']:
        evidence = next(m for m in p['design_coverage']['modules'] if source in m['source_evidence'])['source_evidence'][source]
        assert evidence['piece_ids'] and evidence['seam_pair_ids']
    validate_partition_joins(p)


@pytest.mark.parametrize('count', [2, 3, 4])
def test_yoke_and_equal_panels_form_complete_grid(count):
    p = generate(request([_yoke(), _panels(count)], project=_project('skirt')))
    assert len([piece for piece in p['pieces'] if piece['id'].startswith('front_skirt')]) == 2*count
    assert len([piece for piece in p['pieces'] if piece['id'].startswith('back_skirt')]) == 2*count
    validate_partition_joins(p)
    changed = deepcopy(p)
    pair = next(pair for pair in changed['seam_pairs'] if 'cut_join' in pair['id'])
    changed['seam_pairs'].remove(pair)
    with pytest.raises(BlockConstructionError, match='STRUCTURAL_CELL_JOIN_COVERAGE'):
        validate_partition_joins(changed)


def test_two_crossing_offset_panels_form_four_cells():
    a, b = structural('offset_skirt_panel_v3'), structural('offset_skirt_panel_v3')
    a.update(source_element_id='cut_a', variant='shaped', dimensions_mm=_dimensions(width=40, depth=150))
    b.update(source_element_id='cut_b', variant='shaped', dimensions_mm=_dimensions(width=140, depth=10))
    p = generate(request([a, b], project=_project('skirt')))
    assert len([piece for piece in p['pieces'] if piece['id'].startswith('front_skirt')]) == 4


def test_repeated_yoke_has_geometry_reason_instead_of_silent_noop():
    a, b = structural('front_bodice_yoke_v3'), structural('front_bodice_yoke_v3')
    a['source_element_id'], b['source_element_id'] = 'cut_a', 'cut_b'
    r = request([a, b])
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is None
    assert any(issue['code'] == 'STRUCTURAL_CUT_NO_NEW_CELLS' for issue in out['validation_report']['issues'])


def test_cell_grid_preserves_crossing_pocket_and_final_lining():
    pocket = structural('rounded_patch_pocket_v3')
    pocket['placement']['offset_mm'] = 100
    pocket['dimensions_mm']['spacing'] = 90
    p = generate(request([_panels(), _yoke(), pocket], layers=[_layer('lining', 'lining', 'skirt', 'opaque', 'skirt_full_lining_v1')], project=_project('skirt')))
    op = next(op for op in p['composite_operations'] if op['module_id'] == pocket['module_id'])
    assert len(op['target_piece_ids']) >= 3
    assert len(op['added_piece_ids']) == 1
    assert any(piece['id'].startswith('lining_') for piece in p['pieces'])
    assert pocket['source_element_id'] in render_pattern_svg(p)


def test_shirt_replacement_with_cell_grid_and_layer_prints_new_collar_only():
    r = base_request('shirt')
    yoke, princess, collar = structural('front_bodice_yoke_v3'), structural('shoulder_princess_seam_v3'), neck('shaped_flat_collar_v3')
    yoke['source_element_id'], princess['source_element_id'], collar['source_element_id'] = 'yoke', 'princess', 'collar'
    r['garment_spec']['design_intent']['elements'] = [yoke, princess, collar]
    r['garment_spec']['design_intent']['layers'].append(_layer('lining', 'lining', 'full', 'opaque', 'foundation_lining_v4'))
    p = generate(r)
    assert not any(piece['id'] in {'shirt_collar', 'collar_band'} for piece in p['pieces'])
    pdf = render_pattern_pdf(p)
    pages = PdfReader(BytesIO(pdf.content)).pages
    assert len(pages) == pdf.page_count
    assert 'Плоский фигурный воротник' in '\n'.join(page.extract_text() for page in pages)


def test_alternative_necks_are_mutually_exclusive():
    r = base_request('shirt')
    r['garment_spec']['design_intent']['elements'] = [neck('stand_collar_v1'), neck('shaped_flat_collar_v3')]
    assert structural_conflicts(r['garment_spec'])


def test_preview_is_read_only_and_bound_to_actual_inputs(tmp_path):
    project = _project('skirt')
    r = request([_panels(), _yoke(), structural('welt_pocket_v3')], project=project)
    r['input_hash'] = compute_input_hash(r)
    with _client(tmp_path) as api:
        assert api.post('/api/v1/projects', json=project).status_code == 201
        before = api.get(f"/api/v1/projects/{project['project_id']}").json()
        history = api.get(f"/api/v1/projects/{project['project_id']}/history").json()
        response = api.post('/api/v1/patterns/preview', json=r)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview['status'] == 'succeeded' and preview['input_hash'] == r['input_hash']
        assert preview['piece_count'] > 10 and '_placement_fragment_' in preview['svg']
        assert api.get(f"/api/v1/projects/{project['project_id']}").json() == before
        assert api.get(f"/api/v1/projects/{project['project_id']}/history").json() == history
        assert api.get(f"/api/v1/projects/{project['project_id']}/generations").json()['items'] == []
        out = api.post('/api/v1/patterns/generate', json=r).json()
        assert out['status'] == preview['status'] and len(out['pattern']['pieces']) == preview['piece_count']
        r['garment_spec']['design_intent']['elements'][-1]['dimensions_mm']['spacing'] = 250
        r['input_hash'] = compute_input_hash(r)
        blocked = api.post('/api/v1/patterns/preview', json=r).json()
        assert blocked['svg'] is None and blocked['status'] == 'rejected'
        assert any(i['code'] == 'DETAIL_PLACEMENT_OUTSIDE' for i in blocked['issues'])


def test_cell_grid_reopens_caches_and_survives_safe_manual_edit(tmp_path):
    from tests.test_stage27_manual_geometry import _safe_edit
    project = _project('skirt')
    r = request([_panels(), _yoke(), _element('sash', 'sash', 'straight', 'waist', 'separate_piece', 1, 'straight_sash_v1', _dimensions(width=80, length=1600))], project=project)
    for field in ('pattern_method', 'body_measurements', 'garment_spec', 'fit_settings', 'fabric_properties'):
        project[field] = deepcopy(r[field])
    r['input_hash'] = compute_input_hash(r)
    with _client(tmp_path) as api:
        assert api.post('/api/v1/projects', json=project).status_code == 201
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert reopened['garment_spec'] == r['garment_spec']
        response = api.post('/api/v1/patterns/generate', json=r)
        assert response.status_code == 200, response.text
        base = response.json()
        assert base['status'] == 'succeeded', base['validation_report']['issues']
        assert api.post('/api/v1/patterns/generate', json=r).json()['generation_id'] == base['generation_id']
        revision = api.get(f"/api/v1/projects/{project['project_id']}").json()['revision']
        edited = api.post(f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={'If-Match': str(revision)}, json={'note': 'Уточнение свободного угла кушака', 'edits': [_safe_edit({'pattern': {'pieces': [piece for piece in base['pattern']['pieces'] if piece['id'] == 'sash_sash'], 'seam_pairs': base['pattern']['seam_pairs']}})]})
        assert edited.status_code == 200, edited.text
        p = edited.json()['pattern']
        assert p['design_coverage'] == base['pattern']['design_coverage']
        validate_partition_joins(p)
        assert render_pattern_pdf(p).content.startswith(b'%PDF')
        assert api.get(f"/api/v1/projects/{project['project_id']}").json()['latest_generation']['generation_id'] == edited.json()['generation_id']


def test_cell_cut_displacement_is_rejected_before_export():
    p = generate(request([_panels(), _yoke()], project=_project('skirt')))
    piece = next(piece for piece in p['pieces'] if any(edge['id'].endswith('_cut_a') for edge in piece['seam_contour']['segments']))
    segments = piece['seam_contour']['segments']
    index = next(i for i, edge in enumerate(segments) if edge['id'].endswith('_cut_a'))
    segments[index]['start'][0] += 2
    segments[index-1]['end'][0] += 2
    with pytest.raises(BlockConstructionError, match='STRUCTURAL_CELL_JOIN_COVERAGE|STRUCTURAL_MARKER_MOVED'):
        validate_export_coverage(p)

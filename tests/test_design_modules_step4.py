"""Geometry matrix for foundations, fit, neckline/sleeve interfaces and final layers."""
from copy import deepcopy

import pytest

from kroika_contracts.contract_io import validate_document
from kroika_contracts.design_modules import matching_module
from kroika_contracts.hashing import compute_input_hash, canonical_generation_payload
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg
from kroika_pattern_engine.advanced import prepare_proportions, apply_silhouette
from kroika_pattern_engine.assembly import assemble_garment
from kroika_pattern_engine.blocks import build_base_blocks, build_skirt_blocks, build_trouser_blocks, BlockConstructionError
from kroika_pattern_engine.layers import apply_foundation_layers, validate_foundation_layers
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.validation import validate_pattern_assembly
from tests.test_additional_details import request
from tests.test_stage12_garments import _project, CANONICAL_EXTRA_MEASUREMENTS
from tests.test_stage13_jacket import _project as jacket_project
from tests.test_stage14_lower_garments import _project as lower_project
from tests.test_stage19_composites import _layer
from tests.test_design_modules_step3 import make_request

GARMENTS = ['dress', 'sundress', 'top', 'blouse', 'shirt', 'vest', 'jacket', 'skirt', 'trousers', 'shorts']


def base_request(garment='dress'):
    project = jacket_project() if garment == 'jacket' else lower_project(garment) if garment in {'trousers', 'shorts'} else _project(garment) if garment not in {'dress', 'sundress'} else None
    r = request([], project=project)
    r['garment_spec']['garment_type'] = garment
    if garment in {'dress', 'sundress'}:
        for key, value in CANONICAL_EXTRA_MEASUREMENTS.items():
            r['body_measurements']['values'][key] = dict(value=value, unit='mm', source='user')
    return r


def assembly(r):
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    effective = prepare_proportions(r)
    garment = r['garment_spec']['garment_type']
    builder = build_skirt_blocks if garment == 'skirt' else build_trouser_blocks if garment in {'trousers', 'shorts'} else build_base_blocks
    blocks = builder(effective)
    pattern = apply_silhouette(assemble_garment(effective, blocks).pattern, effective)
    return pattern, effective, blocks


@pytest.mark.parametrize('garment', GARMENTS)
@pytest.mark.parametrize('fit', ['loose', 'oversized'])
def test_free_foundations_preserve_anatomical_measures_and_sewable_interfaces(garment, fit):
    r = base_request(garment)
    r['garment_spec']['parameters']['bodice_fit'] = fit
    original = deepcopy(r['body_measurements'])
    pattern, effective, blocks = assembly(r)
    assert effective['body_measurements'] == original == r['body_measurements']
    assert effective['fit_settings']['design_ease_mm']['hips'] >= (60 if fit == 'loose' else 120)
    validate_pattern_assembly(pattern)
    if garment not in {'skirt', 'trousers', 'shorts', 'jacket'}:
        assert not any('waist_dart' in p['id'] for piece in pattern['pieces'] if piece['id'].endswith('_bodice') for p in piece['internal_paths'])
        assert blocks.controls['front_bodice_waist_residual_mm'] == 0
    assert canonical_generation_payload(r)['hash_contract_version'] == '1.10.0'


@pytest.mark.parametrize('garment', ['dress', 'top', 'blouse', 'shirt', 'vest', 'jacket'])
@pytest.mark.parametrize('kind', ['v', 'square'])
def test_new_necklines_have_real_edges_and_complete_facing_or_collar_joins(garment, kind):
    r = base_request(garment)
    r['garment_spec']['parameters']['neckline']['type'] = kind
    pattern, _, _ = assembly(r)
    validate_pattern_assembly(pattern)
    front = next(p for p in pattern['pieces'] if p['id'] in {'front_bodice', 'jacket_front_center'})
    necks = [e for e in front['seam_contour']['segments'] if e['id'].endswith('_neckline')]
    assert len(necks) == (2 if kind == 'square' else 1)
    assert all(e['type'] == 'line' for e in necks)
    pair = next(p for p in pattern['seam_pairs'] if p['first_piece_id'] == front['id'] and any(e['id'] in p['first_segment_ids'] for e in necks))
    assert set(e['id'] for e in necks) <= set(pair['first_segment_ids'])


@pytest.mark.parametrize('garment', ['dress', 'top', 'blouse', 'shirt'])
@pytest.mark.parametrize('sleeve', ['short', 'long'])
def test_sleeve_cap_halves_match_and_short_hem_uses_arm_girth(garment, sleeve):
    r = base_request(garment)
    params = r['garment_spec']['parameters']
    params['sleeve'] = dict(type=sleeve, length_mm=180 if sleeve == 'short' else 580)
    params['neckline']['type'] = 'square'
    params['finishing']['armhole_facing'] = False
    pattern, effective, _ = assembly(r)
    validate_pattern_assembly(pattern)
    for prefix in ('front', 'back'):
        pair = next(p for p in pattern['seam_pairs'] if p['id'] == f'{prefix}_sleeve_join')
        assert pair['allowed_ease_mm'] <= 5
    piece = next(p for p in pattern['pieces'] if p['id'] == 'base_sleeve')
    assert contour_from_data(piece['seam_contour']).bounding_box.height_mm == pytest.approx(params['sleeve']['length_mm'])
    if sleeve == 'short':
        hem = next(e for e in contour_from_data(piece['seam_contour']).segments if e.id == 'sleeve_hem')
        fit = effective['fit_settings']
        assert hem.length_mm == pytest.approx(r['body_measurements']['values']['upper_arm_circumference']['value'] + fit['wearing_ease_mm']['upper_arm'] + fit['design_ease_mm']['upper_arm'])


def add_layer(r, role, coverage, *, source='trial_layer', shortening=0, targets=None):
    layer = _layer(source, role, coverage, 'opaque', f'foundation_{role}_v4')
    layer['hem_shortening_mm'] = shortening
    if targets:
        layer['detail_source_ids'] = targets
    r['garment_spec']['design_intent']['layers'].append(layer)
    return layer


@pytest.mark.parametrize('garment,role,coverage,shortening', [
    ('dress', 'lining', 'full', 0), ('dress', 'interfacing', 'bodice', 0),
    ('skirt', 'lining', 'skirt', 30), ('blouse', 'overlay', 'sleeves', 30),
    ('shirt', 'lining', 'full', 0), ('trousers', 'lining', 'skirt', 30),
    ('shorts', 'overlay', 'full', 0), ('jacket', 'interfacing', 'bodice', 0),
])
def test_layer_scopes_shortening_cut_counts_and_interface_integrity(garment, role, coverage, shortening):
    r = base_request(garment)
    layer = add_layer(r, role, coverage, shortening=shortening)
    assert matching_module(layer, r['garment_spec'], kind='layer') == layer['module_id']
    pattern, effective, _ = assembly(r)
    result = apply_foundation_layers(pattern, effective)
    validate_pattern_assembly(result)
    validate_document('pattern-data', result)
    op = result['composite_operations'][-1]
    assert op['added_piece_ids'] and op['interface_ids']
    for pid, cid in zip(op['target_piece_ids'], op['added_piece_ids']):
        original = next(p for p in result['pieces'] if p['id'] == pid)
        clone = next(p for p in result['pieces'] if p['id'] == cid)
        assert (clone['cut_quantity'], clone['cut_on_fold'], clone['mirrored_pair']) == (original['cut_quantity'], original['cut_on_fold'], original['mirrored_pair'])
        if shortening:
            assert contour_from_data(original['seam_contour']).bounding_box.height_mm - contour_from_data(clone['seam_contour']).bounding_box.height_mm == pytest.approx(shortening)
    changed = deepcopy(result)
    next(p for p in changed['pieces'] if p['id'] == op['added_piece_ids'][0])['cut_quantity'] += 1
    with pytest.raises(BlockConstructionError, match='LAYER_FOUNDATION_MISMATCH'):
        validate_foundation_layers(changed)


@pytest.mark.parametrize('garment', GARMENTS)
def test_shifted_waist_is_derived_separately_for_every_foundation(garment):
    r = base_request(garment)
    prop = r['garment_spec']['design_intent']['proportions']
    prop.update(module_id='parametric_visual_proportions_v1', waist_position='high', waist_shift_mm=30, waist_level_circumference_mm=760, back_waist_level_arc_mm=370)
    anatomical = deepcopy(r['body_measurements'])
    pattern, effective, _ = assembly(r)
    assert anatomical == r['body_measurements'] == effective['body_measurements']
    validate_pattern_assembly(pattern)


@pytest.mark.parametrize('garment', ['skirt', 'top', 'shirt', 'jacket', 'trousers', 'shorts'])
@pytest.mark.parametrize('shape', ['curved', 'asymmetric'])
def test_hem_forms_preserve_sewing_interfaces(garment, shape):
    r = base_request(garment)
    r['garment_spec']['design_intent']['proportions'].update(module_id='parametric_visual_proportions_v1', hem_shape=shape, asymmetry='yes' if shape == 'asymmetric' else 'no', hem_delta_mm=20)
    pattern, _, _ = assembly(r)
    validate_pattern_assembly(pattern)
    assert any(p['id'].endswith('_hem_shape') or p['id'].endswith('_hem_shape_note') for piece in pattern['pieces'] for p in piece['annotations'])


@pytest.mark.parametrize('module,coverage', [('front_bodice_yoke_v3','bodice'), ('offset_skirt_panel_v3','skirt'), ('shaped_belt_v3','detail')])
def test_final_layers_cover_real_partitioned_or_additional_pieces_and_print(module, coverage):
    r = make_request(module)
    layer = add_layer(r, 'lining', coverage, targets=['structural_detail'] if coverage == 'detail' else None)
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    output = GeometryPatternEngine().generate(r)
    assert output['pattern'] is not None, output['validation_report']['issues']
    result = output['pattern']
    validate_document('pattern-data', result)
    op = next(op for op in result['composite_operations'] if op['source_id'] == layer['source_layer_id'])
    assert op['added_piece_ids']
    assert all(pid in render_pattern_svg(result) for pid in op['added_piece_ids'])
    assert any(m['module_id'] == layer['module_id'] for m in result['design_coverage']['modules'])


def test_disjoint_layer_scopes_work_and_overlapping_roles_are_rejected():
    r = base_request()
    add_layer(r, 'lining', 'bodice', source='bodice_layer')
    add_layer(r, 'lining', 'skirt', source='skirt_layer')
    pattern, effective, _ = assembly(r)
    validate_pattern_assembly(apply_foundation_layers(pattern, effective))
    add_layer(effective, 'lining', 'full', source='overlap_layer')
    with pytest.raises(BlockConstructionError, match='LAYER_ROLE_OVERLAP'):
        apply_foundation_layers(pattern, effective)


def test_layer_shortening_and_source_selection_change_generation_hash():
    r = base_request()
    layer = add_layer(r, 'lining', 'skirt')
    first = compute_input_hash(r)
    layer['hem_shortening_mm'] = 30
    assert compute_input_hash(r) != first


@pytest.mark.parametrize('garment', ['top', 'jacket', 'shorts'])
def test_excessive_hem_lift_cannot_cut_through_waist_or_leg_balance(garment):
    r = base_request(garment)
    r['garment_spec']['design_intent']['proportions'].update(module_id='parametric_visual_proportions_v1', hem_shape='curved', hem_delta_mm=250)
    with pytest.raises(BlockConstructionError, match='Подъём|подъёма'):
        assembly(r)

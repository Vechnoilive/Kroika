"""Regressions found by auditing catalogue promises against final cut geometry."""

from copy import deepcopy

import pytest

from kroika_contracts.contract_io import validate_document
from kroika_contracts.design_modules import MODULES, matching_module
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg
from kroika_pattern_engine.blocks import BlockConstructionError
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.structural import validate_structural_placements
from kroika_pattern_engine.validation import validate_pattern_assembly, validate_export_coverage
from tests.test_additional_details import request, element, CASES
from tests.test_design_modules_step3 import make_request
from tests.test_stage12_garments import _project
from tests.test_stage21_topology import _panels
from tests.test_stage21_topology import _dart_transfer
from tests.test_design_modules_step4 import base_request
from tests.test_design_modules_step2 import element as fullness_element


def build(elements):
    r = request(elements, project=_project('skirt'))
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    p = out['pattern']
    validate_document('pattern-data', p)
    validate_pattern_assembly(p)
    validate_export_coverage(p)
    return p


def structural(module):
    return make_request(module)['garment_spec']['design_intent']['elements'][0]


@pytest.mark.parametrize('module', ['shaped_belt_v3', 'tapered_sash_v3'])
def test_tied_accessory_survives_a_skirt_with_no_unsplit_root(module):
    p = build([_panels(), structural(module)])
    op = next(o for o in p['composite_operations'] if o['module_id'] == module)
    assert len(op['target_piece_ids']) == 3
    assert all(pid.startswith('front_skirt_panel_') for pid in op['target_piece_ids'])
    assert op['added_piece_ids'] and op['invariant_residual_mm'] <= 1


@pytest.mark.parametrize('module', ['rounded_patch_pocket_v3', 'welt_pocket_v3'])
def test_pocket_binds_to_the_panel_containing_its_measured_position(module):
    e = structural(module)
    e['dimensions_mm']['spacing'] = 10
    e['dimensions_mm']['width' if module.startswith('rounded') else 'length'] = 60 if module.startswith('rounded') else 80
    p = build([_panels(count=2), e])
    op = next(o for o in p['composite_operations'] if o['module_id'] == module)
    assert op['target_piece_ids'] == ['front_skirt_panel_1']
    assert op['parameters_mm']['placement_x'] == pytest.approx(10)
    assert e['source_element_id'] in render_pattern_svg(p)


def test_pocket_crossing_a_panel_join_preserves_one_whole_pocket():
    p = build([_panels(), structural('rounded_patch_pocket_v3')])
    op = next(o for o in p['composite_operations'] if o['module_id'] == 'rounded_patch_pocket_v3')
    assert op['target_piece_ids'] == ['front_skirt_panel_2', 'front_skirt_panel_3']
    assert len(op['added_piece_ids']) == 1
    assert op['parameters_mm']['placement_fragment_count'] == 8
    validate_structural_placements(p)


@pytest.mark.parametrize('index', [2, 3])
def test_legacy_rectangular_application_uses_the_actual_middle_panel(index):
    e = element(CASES[index])
    e['dimensions_mm']['width'] = 60 if index == 2 else 50
    e['dimensions_mm']['spacing'] = 20
    p = build([_panels(), e])
    op = next(o for o in p['composite_operations'] if o['module_id'] == e['module_id'])
    prefix = 'back' if e['location'] == 'skirt_back' else 'front'
    assert op['target_piece_ids'] == [f'{prefix}_skirt_panel_2']
    assert op['invariant_residual_mm'] <= 1


def test_decorative_line_retains_its_entire_length_across_panels_and_is_protected():
    e = structural('placed_decorative_stitch_v3')
    e['placement']['orientation'] = 'horizontal'
    e['dimensions_mm']['spacing'] = 40
    p = build([_panels(), e])
    op = next(o for o in p['composite_operations'] if o['module_id'] == e['module_id'])
    assert len(op['target_piece_ids']) == 2
    paths = [path for piece in p['pieces'] for path in piece['internal_paths']
             if path['id'].startswith(e['source_element_id'] + '_decorative_stitch')]
    assert sum(edge.length_mm for path in paths for edge in contour_from_data(path).segments) == pytest.approx(100)
    changed = deepcopy(p)
    path = next(path for piece in changed['pieces'] for path in piece['internal_paths']
                if path['id'] == paths[0]['id'])
    path['segments'][0]['start'][1] += 1
    with pytest.raises(BlockConstructionError, match='STRUCTURAL_MARKER_MOVED'):
        validate_structural_placements(changed)


def test_explicit_detail_sews_across_panels_without_colliding_marker_ids():
    e = structural('explicit_polygon_detail_v3')
    p = build([_panels(), e])
    op = next(o for o in p['composite_operations'] if o['module_id'] == e['module_id'])
    assert len(op['target_piece_ids']) == 2
    pairs = [pair for pair in p['seam_pairs'] if pair['id'] in op['interface_ids']]
    assert len(pairs) == 2 and op['invariant_residual_mm'] <= 1
    assert all(set(pair['first_segment_ids']).isdisjoint(pair['second_segment_ids']) for pair in pairs)
    validate_structural_placements(p)


def test_main_material_evidence_includes_the_actual_bodice_cut_fragments():
    r = make_request('front_bodice_yoke_v3')
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    p = out['pattern']
    fragments = {piece['id'] for piece in p['pieces'] if piece['id'].startswith('front_bodice__')}
    assert fragments
    main = next(m for m in p['design_coverage']['modules'] if m['module_id'] == 'main_fabric_layer')
    assert fragments <= set(main['evidence']['piece_ids'])


@pytest.mark.parametrize('module', ['fitted_two_piece_hood_v3', 'shaped_flat_collar_v3', 'shawl_collar_v3'])
def test_catalogue_does_not_offer_recipes_that_cannot_replace_a_shirt_collar(module):
    r = make_request(module)
    r['garment_spec']['garment_type'] = 'shirt'
    e = r['garment_spec']['design_intent']['elements'][0]
    assert matching_module(e, r['garment_spec'], kind='element') is None
    recipe = next(m for m in MODULES if m['id'] == module)
    assert all('shirt' not in rule['garment_type'] for rule in recipe['rules'])


@pytest.mark.parametrize('fit', ['loose', 'oversized'])
def test_waist_dart_transfer_is_unavailable_when_the_fit_removes_the_source_dart(fit):
    r = base_request()
    r['garment_spec']['parameters']['bodice_fit'] = fit
    assert matching_module(_dart_transfer(), r['garment_spec'], kind='element') is None


@pytest.mark.parametrize('fit', ['loose', 'oversized'])
@pytest.mark.parametrize('index', [3, 4, 6])
def test_integrated_and_diagonal_draping_remain_available_with_free_fit(fit, index):
    r = base_request()
    e = fullness_element(index)
    r['garment_spec']['parameters']['bodice_fit'] = fit
    r['garment_spec']['design_intent']['elements'] = [e]
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    validate_pattern_assembly(out['pattern'])
    module = next(m for m in out['pattern']['design_coverage']['modules'] if m['module_id'] == e['module_id'])
    assert module['source_evidence'][e['source_element_id']]['piece_ids']

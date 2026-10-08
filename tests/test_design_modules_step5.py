"""Composition regressions: final geometry, sewn lengths, evidence and export."""
from copy import deepcopy
import pytest
from kroika_contracts.contract_io import validate_document
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg, render_pattern_pdf
from kroika_pattern_engine.validation import validate_pattern_assembly, validate_export_coverage
from kroika_pattern_engine.geometry import contour_from_data
from tests.test_additional_details import request
from tests.test_design_modules_step2 import element
from tests.test_design_modules_step3 import make_request
from tests.test_design_modules_step4 import add_layer
from tests.test_stage21_topology import _panels, _yoke


def generate(elements, *, shape=None, layer=False):
    r = request(elements)
    if shape:
        r['garment_spec']['design_intent']['proportions'].update(module_id='parametric_visual_proportions_v1',
            hem_shape=shape, hem_delta_mm=30, asymmetry='yes' if shape == 'asymmetric' else 'no')
    if layer:
        add_layer(r, 'lining', 'skirt', shortening=20)
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    p = out['pattern']
    validate_document('pattern-data', p)
    validate_pattern_assembly(p)
    validate_export_coverage(p)
    for item in elements:
        coverage = next(c for c in p['design_coverage']['modules'] if c['module_id'] == item['module_id'])
        assert item['source_element_id'] in coverage['source_evidence']
    return r, p


@pytest.mark.parametrize('partition', [_panels, _yoke])
@pytest.mark.parametrize('detail', [7, 9, 10, 11])
def test_skirt_partition_preserves_real_attachment_intervals(partition, detail):
    e = element(detail)
    if detail == 7:
        e['dimensions_mm']['length'] = 180
    if detail == 11:
        e['count'] = 1
    _, p = generate([partition(), e])
    op = next(op for op in p['composite_operations'] if op['source_id'] == e['source_element_id'])
    assert op['interface_ids'] and op['added_piece_ids']
    if detail == 10 and partition == _yoke:
        assert set(op['target_piece_ids']) == {'back_skirt_yoke', 'back_skirt'}


@pytest.mark.parametrize('shape', ['curved', 'asymmetric'])
def test_panels_retain_selected_hem_and_final_shortened_lining(shape):
    _, p = generate([_panels(), element(11, count=1)], shape=shape, layer=True)
    panels = [piece for piece in p['pieces'] if piece['id'].startswith('front_skirt_panel_')]
    assert len(panels) == 3
    layer_op = next(o for o in p['composite_operations'] if o['kind'] == 'lining')
    by_id = {piece['id']: piece for piece in p['pieces']}
    for pid,cid in zip(layer_op['target_piece_ids'], layer_op['added_piece_ids']):
        assert contour_from_data(by_id[pid]['seam_contour']).bounding_box.height_mm - contour_from_data(by_id[cid]['seam_contour']).bounding_box.height_mm >= 20-0.01
    ys = [edge.start.y_mm for piece in panels for edge in contour_from_data(piece['seam_contour']).segments
          if '_hem_' in edge.id]
    assert max(ys)-min(ys) > 1
    svg = render_pattern_svg(p)
    assert all(piece['id'] in svg for piece in panels)


def test_unlike_tiers_attach_to_previous_free_edge_and_print():
    _, p = generate([_panels(), element(11, count=1), element(12, count=1)])
    first, second = [o for o in p['composite_operations'] if o['module_id'].startswith('tiered_hem_')]
    assert set(second['target_piece_ids']) == set(first['added_piece_ids'])
    assert len(set(second['added_piece_ids'])) == 6
    assert render_pattern_pdf(p).content.startswith(b'%PDF')


@pytest.mark.parametrize('cut', ['front_bodice_yoke_v3', 'back_bodice_yoke_v3'])
def test_collar_uses_final_neckline_after_bodice_partition(cut):
    a = make_request(cut)['garment_spec']['design_intent']['elements'][0]
    a['source_element_id'] = 'cut'
    b = make_request('shaped_flat_collar_v3')['garment_spec']['design_intent']['elements'][0]
    _, p = generate([a,b])
    collar = next(o for o in p['composite_operations'] if o['kind'] == 'collar')
    assert any('__cut' in pid for pid in collar['target_piece_ids'])


@pytest.mark.parametrize('integrated', [3,4])
def test_front_spread_is_unfolded_with_diagonal_drape(integrated):
    _, p = generate([element(integrated, location='bodice_front'), element(6)])
    front = next(piece for piece in p['pieces'] if piece['id'] == 'front_bodice')
    assert not front['cut_on_fold'] and front['cut_quantity'] == 1
    assert contour_from_data(front['seam_contour']).bounding_box.min_x_mm < 0
    assert any(path['id'].startswith('mirror_') and 'fullness_' in path['id'] for path in front['internal_paths'])


def test_offset_panel_supports_local_trim_across_its_join():
    a = make_request('offset_skirt_panel_v3')['garment_spec']['design_intent']['elements'][0]
    e = element(7)
    _, p = generate([a,e])
    op = next(o for o in p['composite_operations'] if o['source_id'] == e['source_element_id'])
    assert len(op['target_piece_ids']) == 2


@pytest.mark.parametrize('partition', [_panels, _yoke])
def test_distributed_fullness_retains_all_control_marks_after_partition(partition):
    _, p = generate([partition(), element(1)])
    op = next(o for o in p['modeling_operations'] if o['module_id'] == 'placed_skirt_tucks_v2')
    assert op['target_piece_ids']
    assert any('fullness_1_fullness_' in path['id'] for piece in p['pieces'] for path in piece['internal_paths'])


def test_bodice_cut_clips_fullness_marks_without_losing_intervals():
    from kroika_pattern_engine.blocks import BlockConstructionError
    a = make_request('front_bodice_yoke_v3')['garment_spec']['design_intent']['elements'][0]
    a['source_element_id'] = 'cut'
    _, p = generate([element(3), a])
    op = next(o for o in p['modeling_operations'] if o['module_id'] == 'integrated_bodice_drape_v2')
    assert len(op['target_piece_ids']) == 2
    changed = deepcopy(p)
    piece = next(piece for piece in changed['pieces'] if any('fullness_3_fullness_' in path['id'] for path in piece['internal_paths']))
    piece['internal_paths'] = [path for path in piece['internal_paths'] if 'fullness_3_fullness_' not in path['id']]
    with pytest.raises(BlockConstructionError, match='FULLNESS_MARK_MISSING'):
        validate_export_coverage(changed)


@pytest.mark.parametrize('detail', [5,6])
def test_bodice_yoke_keeps_separate_drape_on_actual_anchor_pieces(detail):
    a = make_request('front_bodice_yoke_v3')['garment_spec']['design_intent']['elements'][0]
    a['source_element_id'] = 'cut'
    _, p = generate([a, element(detail, location='bodice_front')])
    op = next(o for o in p['composite_operations'] if o['source_id'] == f'fullness_{detail}')
    assert any('__cut' in pid for pid in op['target_piece_ids'])


@pytest.mark.parametrize('count', [2,4,6])
def test_panel_count_preserves_sewing_and_cut_quantity(count):
    _, p = generate([_panels(count), element(11, count=1)])
    op = next(o for o in p['composite_operations'] if o['module_id'] == 'tiered_hem_ruffle_v2')
    assert len(op['added_piece_ids']) == 2*count
    assert all(next(piece for piece in p['pieces'] if piece['id'] == pid)['cut_quantity'] == 2 for pid in op['added_piece_ids'])


@pytest.mark.parametrize('fit', ['fitted','semi_fitted','loose','oversized'])
def test_composition_has_no_artificial_fit_gate(fit):
    from tests.test_design_modules_step4 import base_request
    r = base_request()
    r['garment_spec']['parameters']['bodice_fit'] = fit
    if fit == 'fitted':
        r['fit_settings']['preset']['id'] = 'woven_fitted_trial'
        r['fit_settings']['wearing_ease_mm'].update(bust=40,waist=20,hips=40)
    r['garment_spec']['design_intent']['elements'] = [_panels(),element(9)]
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out=GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']


def test_legacy_layer_is_compiled_after_partition_and_new_details():
    from tests.test_stage19_composites import _layer
    r=request([_panels(),element(10)], [_layer('legacy_lining','lining','skirt','opaque','skirt_full_lining_v1')])
    r['input_hash']=compute_input_hash(r)
    validate_engine_request(r)
    out=GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    op=next(o for o in out['pattern']['composite_operations'] if o['source_id']=='legacy_lining')
    assert op['formula_id']=='L04-L01' and len(op['added_piece_ids']) == 6
    assert any('anchor' in path['id'] for piece in out['pattern']['pieces'] if piece['id'] in op['added_piece_ids'] for path in piece['internal_paths'])


def test_crossed_drape_accepts_spread_and_preserves_mirror_markers():
    from tests.test_advanced_design import elements
    generate([element(3),elements()[0]])


def test_stand_collar_attaches_to_partitioned_neckline():
    from tests.test_module_assembly import collar
    a=make_request('front_bodice_yoke_v3')['garment_spec']['design_intent']['elements'][0]
    generate([a,collar()])


@pytest.mark.parametrize('module', ['fitted_two_piece_hood_v3', 'shaped_flat_collar_v3'])
def test_full_front_partition_preserves_both_neckline_half_attachments(module):
    yoke = make_request('front_bodice_yoke_v3')['garment_spec']['design_intent']['elements'][0]
    yoke['source_element_id'] = 'cut'
    collar = make_request(module)['garment_spec']['design_intent']['elements'][0]
    collar['source_element_id'] = 'neck_detail'
    _, p = generate([element(6), yoke, collar])
    op = next(op for op in p['composite_operations'] if op['source_id'] == 'neck_detail')
    mirrors = [pair for pair in p['seam_pairs'] if pair['id'] in op['interface_ids']
               and pair.get('second_instance') == 'mirror']
    assert mirrors and all(any('mirror_' in sid for sid in pair['first_segment_ids']) for pair in mirrors)
    if module == 'shaped_flat_collar_v3':
        assert any(pair['second_piece_id'].startswith('under_') for pair in mirrors)


def test_legacy_overlay_keeps_all_attached_hem_tiers_after_partition():
    from tests.test_stage19_composites import _layer
    r = request([_panels(), element(11, count=1), element(12, count=1)],
                [_layer('saved_overlay', 'overlay', 'skirt', 'semi_transparent', 'skirt_overlay_layer_v1')])
    r['input_hash'] = compute_input_hash(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is not None, out['validation_report']['issues']
    p = out['pattern']
    layer = next(op for op in p['composite_operations'] if op['source_id'] == 'saved_overlay')
    trims = {pid for op in p['composite_operations'] if op['module_id'].startswith('tiered_hem_')
             for pid in op['added_piece_ids']}
    assert trims <= set(layer['target_piece_ids'])
    assert len(layer['added_piece_ids']) == 18


def test_offset_loop_cleanup_preserves_seam_and_rejects_large_cycle():
    from kroika_pattern_engine.geometry.offset import _trim_approximation_loops
    from kroika_pattern_engine.geometry import Point, OffsetCollapseError
    from kroika_pattern_engine.geometry.primitives import DEFAULT_TOLERANCE
    points = [Point(0,0),Point(10,0),Point(10,10),Point(6,10),
              Point(5,8),Point(6,8),Point(5,10),Point(0,10)]
    seam = [(Point(1,1),Point(9,1),1)]
    cleaned = _trim_approximation_loops(points,seam,DEFAULT_TOLERANCE)
    assert len(cleaned) < len(points)
    # The same cycle must not be clipped when it exceeds the allowance budget.
    with pytest.raises(OffsetCollapseError):
        _trim_approximation_loops(points,[(Point(1,1),Point(9,1),.1)],DEFAULT_TOLERANCE)
    with pytest.raises(OffsetCollapseError):
        _trim_approximation_loops(points,[(Point(5.5,9),Point(5.5,9.5),1)],DEFAULT_TOLERANCE)


def test_classic_patch_pocket_keeps_placement_on_all_panel_fragments():
    from tests.test_module_assembly import detail
    pocket = detail('pocket', 'pocket', 'patch', 'skirt_front', 2,
                    'paired_patch_pocket_v1', width=160, depth=180)
    pocket['construction'] = 'applied'
    _, p = generate([_panels(), pocket])
    op = next(op for op in p['composite_operations'] if op['source_id'] == 'pocket')
    assert len(op['target_piece_ids']) >= 2
    assert len(op['interface_ids']) > 4
    assert any(piece['id'] == 'pocket_patch_pocket' for piece in p['pieces'])


def test_short_partition_edge_reports_flounce_allowance_conflict():
    from tests.test_module_assembly import flounce
    from tests.test_additional_details import element as old_element, CASES
    panel = make_request('offset_skirt_panel_v3')['garment_spec']['design_intent']['elements'][0]
    panel['dimensions_mm']['width'] = 40
    r = request([panel, flounce(), old_element(CASES[4], 'ruffle')])
    r['input_hash'] = compute_input_hash(r)
    validate_engine_request(r)
    out = GeometryPatternEngine().generate(r)
    assert out['pattern'] is None
    assert any(issue['code'] == 'MODEL_FLOUNCE_ALLOWANCE_CONFLICT'
               for issue in out['validation_report']['issues'])

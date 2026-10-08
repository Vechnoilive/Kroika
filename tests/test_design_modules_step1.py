from __future__ import annotations

from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from tests.test_additional_details import request
from tests.test_stage19_composites import _element, _dimensions
from tests.test_stage11_workflow import client, project_document, engine_request
from tests.test_stage12_garments import _project
from kroika_contracts.contract_io import validate_document
from kroika_contracts.design_modules import matching_module
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.semantic import SemanticContractError, validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.validation import validate_pattern_assembly


def tuck(depth=5, length=150):
    return _element('tuck', 'tuck', 'straight', 'skirt_front', 'integrated', 1,
                    'center_stitched_tuck_v1', _dimensions(depth=depth, length=length))


def stitch(spacing=30, length=150, location='skirt_front'):
    return _element('stitch', 'decorative_seam', 'straight', location, 'applied', 2,
                    'paired_straight_decorative_stitch_v1', _dimensions(spacing=spacing, length=length))


def generate(req):
    req['input_hash'] = compute_input_hash(req)
    validate_engine_request(req)
    result = GeometryPatternEngine().generate(req)
    assert result['status'] == 'succeeded', result['validation_report']
    validate_document('pattern-data', result['pattern'])
    assert validate_pattern_assembly(result['pattern']) < 1
    return result['pattern']


@pytest.mark.parametrize('garment,fit,volume', [
    ('dress', 'fitted', 'regular'), ('dress', 'semi_fitted', 'relaxed'),
    ('sundress', 'semi_fitted', 'voluminous'), ('skirt', 'semi_fitted', 'regular'),
])
def test_new_operations_preserve_joins_and_have_real_paths(garment, fit, volume):
    project = _project('skirt') if garment == 'skirt' else project_document()
    project['garment_spec']['garment_type'] = garment
    project['garment_spec']['parameters']['bodice_fit'] = fit
    if garment == 'dress':
        project['fit_settings']['preset']['id'] = 'woven_fitted_trial' if fit == 'fitted' else 'woven_semi_fitted_trial'
    req = request([tuck(), stitch()], project=project)
    req['garment_spec']['design_intent']['proportions'].update(
        volume=volume, module_id='parametric_visual_proportions_v1' if volume != 'regular' else 'bounded_visual_proportions')
    pattern = generate(req)
    front = next(p for p in pattern['pieces'] if p['id'] == 'front_skirt')
    assert front['cut_on_fold']
    paths = {p['id']: contour_from_data(p) for p in front['internal_paths']}
    assert paths['tuck_tuck_fold'].segments[0].start.x_mm == 0
    assert paths['tuck_tuck_stitch'].segments[0].start.x_mm == 5
    assert paths['tuck_tuck_stitch'].segments[0].length_mm == 150
    assert paths['stitch_decorative_stitch'].segments[0].start.x_mm == 30
    assert paths['stitch_decorative_stitch'].segments[0].length_mm == 150
    assert len([p for p in front['internal_paths'] if p['id'] == 'stitch_decorative_stitch']) == 1
    coverage = {m['module_id']: m for m in pattern['design_coverage']['modules']}
    assert set(coverage['center_stitched_tuck_v1']['evidence']['path_ids']) == {
        'tuck_tuck_fold', 'tuck_tuck_stitch',
    }
    assert coverage['paired_straight_decorative_stitch_v1']['evidence']['path_ids'] == ['stitch_decorative_stitch']
    waist_pair = next(p for p in pattern['seam_pairs'] if p['first_piece_id'] == 'front_skirt'
                      or p['second_piece_id'] == 'front_skirt')
    side = 'first' if waist_pair['first_piece_id'] == 'front_skirt' else 'second'
    assert waist_pair[f'{side}_length_reduction_mm'] >= 5


def test_tuck_intake_equals_twice_the_depth_on_the_whole_front():
    base = generate(request([]))
    modified = generate(request([tuck(depth=8)]))
    def front_bounds(pattern):
        return contour_from_data(next(p for p in pattern['pieces'] if p['id'] == 'front_skirt')['seam_contour']).bounding_box
    assert front_bounds(modified).max_x_mm - front_bounds(base).max_x_mm == pytest.approx(8)
    pair = next(p for p in modified['seam_pairs'] if 'tuck_center_extension_waist' in
                p['first_segment_ids'] + p['second_segment_ids'])
    side = 'first' if 'tuck_center_extension_waist' in pair['first_segment_ids'] else 'second'
    base_pair = next(p for p in base['seam_pairs'] if p['id'] == pair['id'])
    assert pair[f'{side}_length_reduction_mm'] - base_pair[f'{side}_length_reduction_mm'] == 8


@pytest.mark.parametrize('spacing,length,code', [
    (105, 150, 'MODEL_STITCH_DART_CONFLICT'), (105, 30, 'MODEL_STITCH_DART_CONFLICT'),
    (1000, 150, 'MODEL_STITCH_OUTSIDE'), (30, 900, 'MODEL_STITCH_OUTSIDE'),
    (4, 150, 'MODEL_STITCH_TUCK_CONFLICT'),
])
def test_stitch_rejects_darts_cut_edges_and_tuck_intake(spacing, length, code):
    # Exercise the geometry validator directly as well as the bounded public registry.
    from kroika_pattern_engine.modeling import _decorative_stitch
    from kroika_pattern_engine.blocks import BlockConstructionError
    pattern = generate(request([tuck()]))
    with pytest.raises(BlockConstructionError) as error:
        _decorative_stitch(pattern, 'front_skirt', length, spacing, 'invalid')
    assert error.value.code == code


@pytest.mark.parametrize('field,value', [('depth', 1), ('depth', 21), ('length', None), ('width', 10)])
def test_tuck_outside_its_recipe_is_not_marked_supported(field, value):
    req = request([tuck()])
    item = req['garment_spec']['design_intent']['elements'][0]
    item['dimensions_mm'][field] = value
    assert matching_module(item, req['garment_spec'], kind='element') is None
    with pytest.raises(SemanticContractError):
        validate_engine_request(req)


@pytest.mark.parametrize('new_element', [tuck(), stitch()])
@pytest.mark.parametrize('topology', ['panel', 'yoke'])
def test_topology_combinations_keep_source_geometry(new_element, topology):
    other = _element('topology', topology, 'straight', 'full_garment' if topology == 'panel' else 'waist',
                     'separate_piece', 2,
                     'paired_equal_skirt_panels_v1' if topology == 'panel' else 'paired_straight_skirt_yoke_v1',
                     _dimensions() if topology == 'panel' else _dimensions(depth=100))
    req = request([deepcopy(new_element), other])
    validate_engine_request(req)
    pattern = generate(req)
    coverage = next(c for c in pattern["design_coverage"]["modules"] if c["module_id"] == new_element["module_id"])
    assert new_element["source_element_id"] in coverage["source_evidence"]


def test_central_width_operations_cannot_silently_overwrite_each_other():
    gather = _element('gather', 'gather', 'gathered', 'skirt_front', 'integrated', 1,
                      'waist_gather_allowance_v1', _dimensions(width=100))
    with pytest.raises(SemanticContractError) as error:
        validate_engine_request(request([tuck(), gather]))
    assert 'DESIGN_MODEL_TARGET_CONFLICT' in str(error.value)


@pytest.mark.parametrize('index,field,value', [(0, 'depth', 8), (0, 'length', 160),
                                             (1, 'spacing', 40), (1, 'length', 160)])
def test_every_geometry_parameter_invalidates_cached_results(index, field, value):
    req = request([tuck(), stitch()])
    before = compute_input_hash(req)
    req['garment_spec']['design_intent']['elements'][index]['dimensions_mm'][field] = value
    assert compute_input_hash(req) != before


def test_save_reopen_cache_svg_and_pdf_keep_the_operations(tmp_path):
    req = request([tuck(), stitch(location='skirt_back')])
    project = project_document()
    project['garment_spec'] = deepcopy(req['garment_spec'])
    with client(tmp_path) as api:
        saved = api.post('/api/v1/projects', json=project)
        assert saved.status_code == 201, saved.text
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        result = api.post('/api/v1/patterns/generate', json=engine_request(reopened), headers={'If-Match': '1'})
        assert result.status_code == 200, result.text
        result = result.json()
        assert result['status'] == 'succeeded', result['validation_report']
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert [e['module_id'] for e in current['garment_spec']['design_intent']['elements']] == [
            'center_stitched_tuck_v1', 'paired_straight_decorative_stitch_v1',
        ]
        cached = api.post('/api/v1/patterns/generate', json=engine_request(current),
                          headers={'If-Match': str(current['revision'])})
        assert cached.status_code == 200, cached.text
        assert cached.json()['generation_id'] == result['generation_id']
        svg = api.get(f"/api/v1/patterns/{result['generation_id']}/preview.svg")
        assert svg.status_code == 200
        for path in ['tuck_tuck_fold', 'tuck_tuck_stitch', 'stitch_decorative_stitch']:
            assert path in svg.text
        pdf = api.post(f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf")
        assert pdf.status_code == 200, pdf.text
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert 'Защип по сгибу переда' in text
        assert 'декоративные строчки' in text
        assert '50 x 50 mm' in text


def test_skirt_neckline_ruffle_no_longer_advertises_a_missing_bodice():
    item = _element('ruffle', 'ruffle', 'gathered', 'neckline', 'separate_piece', 1,
                    'gathered_edge_ruffle_v1', _dimensions(depth=80, width=150))
    req = request([item], project=_project('skirt'))
    assert matching_module(item, req['garment_spec'], kind='element') is None


@pytest.fixture(scope='module')
def printable_new_operations():
    return generate(request([tuck(), stitch()]))


@pytest.mark.parametrize('path_id', ['tuck_tuck_fold', 'tuck_tuck_stitch', 'stitch_decorative_stitch'])
def test_export_rejects_displaced_or_missing_modeling_marks(printable_new_operations, path_id):
    from kroika_pattern_engine import render_pattern_svg, render_pattern_pdf
    from kroika_pattern_engine.svg import SVGRenderError
    from kroika_pattern_engine.pdf import PDFRenderError
    pattern = deepcopy(printable_new_operations)
    front = next(p for p in pattern['pieces'] if p['id'] == 'front_skirt')
    path = next(p for p in front['internal_paths'] if p['id'] == path_id)
    path['segments'][0]['start'][0] += 5
    with pytest.raises(SVGRenderError):
        render_pattern_svg(pattern)
    with pytest.raises(PDFRenderError):
        render_pattern_pdf(pattern)
    front['internal_paths'].remove(path)
    with pytest.raises(SVGRenderError):
        render_pattern_svg(pattern)


def test_manual_edit_rechecks_modeling_anchors(printable_new_operations):
    from kroika_pattern_engine.manual_edit import apply_manual_edits, ManualEditError
    from kroika_pattern_engine.blocks import BlockConstructionError
    pattern = deepcopy(printable_new_operations)
    front = next(p for p in pattern['pieces'] if p['id'] == 'front_skirt')
    hem = next(s for s in front['seam_contour']['segments'] if s['id'].endswith('_hem')
               and not s['id'].startswith('tuck'))
    # A small change of the outer hem corner leaves the protected fold intact.
    edit = dict(piece_id='front_skirt', segment_id=hem['id'], handle='end',
                x_mm=hem['end'][0] - 0.2, y_mm=hem['end'][1])
    edited = apply_manual_edits(pattern, [edit], request([tuck(), stitch()]), base_generation_id='base')
    assert any(p['id'] == 'stitch_decorative_stitch' for p in
               next(p for p in edited.pattern['pieces'] if p['id'] == 'front_skirt')['internal_paths'])
    # A stored displaced mark must never be propagated through the manual editor.
    next(p for p in front['internal_paths'] if p['id'] == 'stitch_decorative_stitch')['segments'][0]['end'][0] += 5
    with pytest.raises((BlockConstructionError, ManualEditError)):
        apply_manual_edits(pattern, [edit], request([tuck(), stitch()]), base_generation_id='base')

"""Cross-runtime hashing, persistence and printable stage-4 workflow."""
from copy import deepcopy
from io import BytesIO
import json
import subprocess

import pytest
from pypdf import PdfReader

from kroika_contracts.hashing import canonical_generation_payload, compute_input_hash
from kroika_pattern_engine.pdf import render_pattern_pdf
from tests.test_design_modules_step4 import base_request, add_layer
from tests.test_stage11_workflow import project_document
from tests.test_stage12_garments import _client


@pytest.mark.parametrize('garment,coverage', [('dress', 'bodice'), ('blouse', 'sleeves'), ('trousers', 'skirt')])
def test_actual_python_and_typescript_hash_payloads_agree(garment, coverage):
    r = base_request(garment)
    r['garment_spec']['parameters']['bodice_fit'] = 'loose'
    add_layer(r, 'lining', coverage, shortening=30 if coverage != 'bodice' else 0)
    script = "import {stripTypeScriptTypes as strip} from 'node:module'; import fs from 'node:fs'; const gen=strip(fs.readFileSync('src/generation.ts','utf8'),{mode:'transform'}); const mod=strip(fs.readFileSync('src/designModules.ts','utf8'),{mode:'transform'}); const reg=JSON.parse(fs.readFileSync('../src/kroika_contracts/design_modules.json','utf8')); const moduleUrl='data:text/javascript;base64,'+Buffer.from(mod.replace(/import registry.*;/, 'const registry='+JSON.stringify(reg)+';')).toString('base64'); const code=gen.replace(\"'./designModules'\",JSON.stringify(moduleUrl)); const lib=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64')); process.stdout.write(lib.stableJson(lib.canonicalGenerationPayload(JSON.parse(process.argv[1]))));"
    text = subprocess.check_output(['node', '--input-type=module', '-e', script, json.dumps(r)], text=True, cwd='frontend')
    assert json.loads(text) == canonical_generation_payload(r)


def test_short_free_dress_layer_survives_reopening_generation_cache_and_a4_pdf(tmp_path):
    r = base_request()
    p = r['garment_spec']['parameters']
    p['bodice_fit'] = 'loose'
    p['neckline']['type'] = 'square'
    p['sleeve'] = dict(type='short', length_mm=180)
    p['finishing']['armhole_facing'] = False
    add_layer(r, 'lining', 'skirt', shortening=30)
    r['input_hash'] = compute_input_hash(r)
    project = project_document()
    r['project_id'] = project['project_id']
    for key in ('pattern_method', 'body_measurements', 'garment_spec', 'fit_settings', 'fabric_properties'):
        project[key] = deepcopy(r[key])
    with _client(tmp_path) as api:
        response = api.post('/api/v1/projects', json=project)
        assert response.status_code == 201, response.text
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert reopened['garment_spec'] == r['garment_spec']
        assert reopened['body_measurements'] == r['body_measurements']
        response = api.post('/api/v1/patterns/generate', json=r)
        assert response.status_code == 200, response.text
        generated = response.json()
        assert generated['status'] == 'succeeded', generated['validation_report']['issues']
        cached = api.post('/api/v1/patterns/generate', json=r).json()
        assert cached['generation_id'] == generated['generation_id']
        pattern = generated['pattern']
        rendered = render_pattern_pdf(pattern)
        reader = PdfReader(BytesIO(rendered.content))
        assert len(reader.pages) == rendered.page_count
        assert all(abs(float(page.mediabox.width) - 595.28) < .1 for page in reader.pages)
        assert any('Подкладка' in page.extract_text() for page in reader.pages)


def test_shortened_lining_preserves_panel_join_and_shortens_every_hem_fragment():
    from tests.test_design_modules_step3 import make_request
    from kroika_pattern_engine import GeometryPatternEngine
    from kroika_pattern_engine.geometry import contour_from_data
    r = make_request('offset_skirt_panel_v3')
    layer = add_layer(r, 'lining', 'skirt', shortening=30)
    r['input_hash'] = compute_input_hash(r)
    output = GeometryPatternEngine().generate(r)
    assert output['pattern'] is not None, output['validation_report']['issues']
    pattern = output['pattern']
    op = next(o for o in pattern['composite_operations'] if o['source_id'] == layer['source_layer_id'])
    pieces = {p['id']: p for p in pattern['pieces']}
    for pid, cid in zip(op['target_piece_ids'], op['added_piece_ids']):
        original = contour_from_data(pieces[pid]['seam_contour'])
        shortened = contour_from_data(pieces[cid]['seam_contour'])
        assert original.bounding_box.height_mm - shortened.bounding_box.height_mm == pytest.approx(30)
    assert any('cut_join' in pair['id'] and pair['id'] in op['interface_ids'] for pair in pattern['seam_pairs'])

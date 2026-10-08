"""Persistence, cache order, shared capabilities and printable composition."""
from copy import deepcopy
from io import BytesIO
import json
import subprocess

import pytest
from pypdf import PdfReader
from kroika_contracts.design_modules import REGISTRY
from kroika_contracts.hashing import canonical_generation_payload, compute_input_hash
from kroika_pattern_engine.pdf import render_pattern_pdf
from tests.test_additional_details import request, element as old_element, CASES
from tests.test_design_modules_step2 import element
from tests.test_stage21_topology import _panels
from tests.test_stage11_workflow import project_document
from tests.test_stage12_garments import _client
from kroika_backend.vision_prompt import analysis_instruction, recognition_capabilities


def composed_request():
    return request([_panels(),element(11,count=1),element(12,count=1)])


@pytest.mark.parametrize('legacy', [False,True])
def test_actual_typescript_and_python_composition_payloads_match(legacy):
    r=composed_request()
    if legacy:
        from tests.test_stage19_composites import _layer
        r=request([_panels()],[_layer('saved_lining','lining','skirt','opaque','skirt_full_lining_v1')])
    script="import {stripTypeScriptTypes as strip} from 'node:module'; import fs from 'node:fs'; const gen=strip(fs.readFileSync('src/generation.ts','utf8'),{mode:'transform'}); const mod=strip(fs.readFileSync('src/designModules.ts','utf8'),{mode:'transform'}); const reg=JSON.parse(fs.readFileSync('../src/kroika_contracts/design_modules.json','utf8')); const url='data:text/javascript;base64,'+Buffer.from(mod.replace(/import registry.*;/, 'const registry='+JSON.stringify(reg)+';')).toString('base64'); const code=gen.replace(\"'./designModules'\",JSON.stringify(url)); const lib=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64')); process.stdout.write(lib.stableJson(lib.canonicalGenerationPayload(JSON.parse(process.argv[1]))));"
    text=subprocess.check_output(['node','--input-type=module','-e',script,json.dumps(r)],text=True,cwd='frontend')
    assert json.loads(text)==canonical_generation_payload(r)
    assert canonical_generation_payload(r)['hash_contract_version']=='1.11.0'


def test_saved_sequence_reopens_uses_cache_and_renders_all_pieces_on_a4(tmp_path):
    r=composed_request()
    project=project_document()
    r['project_id']=project['project_id']
    for key in ('pattern_method','body_measurements','garment_spec','fit_settings','fabric_properties'):
        project[key]=deepcopy(r[key])
    r['input_hash']=compute_input_hash(r)
    with _client(tmp_path) as api:
        response=api.post('/api/v1/projects',json=project)
        assert response.status_code==201,response.text
        reopened=api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert reopened['garment_spec']['design_intent']['elements']==r['garment_spec']['design_intent']['elements']
        response=api.post('/api/v1/patterns/generate',json=r)
        assert response.status_code==200,response.text
        out=response.json()
        assert out['status']=='succeeded',out['validation_report']['issues']
        cached=api.post('/api/v1/patterns/generate',json=r).json()
        assert cached['generation_id']==out['generation_id']
        rendered=render_pattern_pdf(out['pattern'])
        pdf=PdfReader(BytesIO(rendered.content))
        assert len(pdf.pages)==rendered.page_count
        assert all(abs(float(page.mediabox.width)-595.28)<.1 for page in pdf.pages)
        assert 'Оборка' in '\n'.join(page.extract_text() for page in pdf.pages)
        before=r['input_hash']
        r['garment_spec']['design_intent']['elements'][1:]=list(reversed(r['garment_spec']['design_intent']['elements'][1:]))
        assert compute_input_hash(r)!=before


def test_ai_and_editor_use_same_registry_without_inventing_dimensions():
    capabilities=recognition_capabilities()
    assert capabilities['registry_version']==REGISTRY['registry_version']
    assert {'soft'} <= set(capabilities['element_variants']['drape'])
    prompt=analysis_instruction(['dress'],{'sleeve_types':['sleeveless']})
    assert REGISTRY['registry_version'] in prompt and 'Не объединяй' in prompt
    assert 'не назначай геометрические модули самостоятельно' in prompt


@pytest.mark.parametrize('reverse',[False,True])
def test_legacy_ruffle_and_flounce_are_sewn_in_reviewed_order(reverse):
    from tests.test_design_modules_step5 import generate
    ruffle=old_element(CASES[4],source='ruffle')
    flounce=old_element(CASES[5],source='flounce')
    flounce.update(location='hem',module_id='circular_hem_flounce_v1',dimensions_mm={'width':None,'length':None,'depth':80,'spacing':None})
    first,second=([flounce,ruffle] if reverse else [ruffle,flounce])
    _,p=generate([first,second])
    ops=p['composite_operations']+p['modeling_operations']
    before=next(o for o in ops if o.get('source_id',o.get('source_element_id'))==first['source_element_id'])
    after=next(o for o in ops if o.get('source_id',o.get('source_element_id'))==second['source_element_id'])
    added_before=set(before.get('added_piece_ids',before['target_piece_ids']))
    added_after=set(after.get('added_piece_ids',after['target_piece_ids']))
    targets={pair['first_piece_id'] for pair in p['seam_pairs'] if pair['second_piece_id'] in added_after and pair['first_piece_id'] not in added_after}
    assert targets==added_before


def test_composed_pattern_manual_edit_preserves_sources_and_base(tmp_path):
    from tests.test_stage27_manual_geometry import _safe_edit
    project = project_document()
    r = composed_request()
    r['project_id'] = project['project_id']
    for field in ('pattern_method', 'body_measurements', 'garment_spec', 'fit_settings', 'fabric_properties'):
        project[field] = deepcopy(r[field])
    r['input_hash'] = compute_input_hash(r)
    with _client(tmp_path) as api:
        assert api.post('/api/v1/projects', json=project).status_code == 201
        base = api.post('/api/v1/patterns/generate', json=r).json()
        assert base['pattern'] is not None, base['validation_report']['issues']
        revision = api.get(f"/api/v1/projects/{project['project_id']}").json()['revision']
        response = api.post(f"/api/v1/patterns/{base['generation_id']}/manual-edit",
                            headers={'If-Match': str(revision)},
                            json={'note': 'Уточнение свободного угла обтачки', 'edits': [_safe_edit(base)]})
        assert response.status_code == 200, response.text
        edited = response.json()
        assert edited['generation_id'] != base['generation_id']
        assert edited['pattern']['design_coverage'] == base['pattern']['design_coverage']
        stored_base = api.get(f"/api/v1/patterns/{base['generation_id']}/validation")
        assert stored_base.status_code == 200
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert reopened['latest_generation']['generation_id'] == edited['generation_id']
        assert len(reopened['generation_history']) == 2
        assert render_pattern_pdf(edited['pattern']).content.startswith(b'%PDF')


@pytest.mark.parametrize("modern", [False, True])
def test_legacy_hem_sequence_resolves_structural_panel_boundary_fragments(modern):
    from tests.test_design_modules_step3 import make_request
    from tests.test_design_modules_step5 import generate
    from tests.test_module_assembly import flounce
    panel = make_request('offset_skirt_panel_v3')['garment_spec']['design_intent']['elements'][0]
    panel['dimensions_mm']['width'] = 140
    ruffle = old_element(CASES[4], source='ruffle')
    if modern:
        ruffle = element(11, count=1)
        _, p = generate([panel, ruffle, element(12, count=1)])
        op = next(op for op in p['composite_operations'] if op['source_id'] == ruffle['source_element_id'])
        assert any('__' in pid for pid in op['target_piece_ids'])
        return
    _, p = generate([panel, flounce(), ruffle])
    ruffle_op = next(op for op in p['composite_operations'] if op['source_id'] == 'ruffle')
    flounce_op = next(op for op in p['modeling_operations'] if op['module_id'] == 'circular_hem_flounce_v1')
    assert set(ruffle_op['target_piece_ids']) == set(flounce_op['target_piece_ids'])
    assert any('__' in pid for pid in flounce_op['target_piece_ids'])

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'pattern-engine' / 'src'),
               str(ROOT / 'backend' / 'src')]

from kroika_contracts.design_modules import matching_module, module_matches  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402
from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.repository import SQLiteRepository  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tests.test_stage11_workflow import client, engine_request, project_document  # noqa: E402
from tests.test_stage19_composites import _dimensions, _element, _intent, _layer  # noqa: E402


def layered_project() -> dict:
    project = project_document('Волан и подкладка')
    flounce = _element(
        'photo_flounce', 'flounce', 'circular', 'hem', 'separate_piece', 1,
        'circular_hem_flounce_v1', _dimensions(depth=80),
    )
    lining = _layer('photo_lining', 'lining', 'skirt', 'opaque', 'skirt_full_lining_v1')
    project['garment_spec']['design_intent'] = _intent([flounce], [lining])
    project['garment_spec']['design_intent']['coverage_schema_version'] = '1.0.0'
    return project


def test_saved_flounce_and_lining_reach_cached_geometry_and_pdf(tmp_path: Path):
    project = layered_project()
    with client(tmp_path) as api:
        created = api.post('/api/v1/projects', json=project)
        assert created.status_code == 201, created.text
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert reopened['garment_spec']['design_intent'] == project['garment_spec']['design_intent']
        request = engine_request(reopened)
        response = api.post('/api/v1/patterns/generate', json=request, headers={'If-Match': '1'})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'succeeded'
        names = {piece['id'] for piece in result['pattern']['pieces']}
        assert {'front_skirt_flounce', 'back_skirt_flounce',
                'lining_front_skirt', 'lining_back_skirt'} <= names
        assert len(names) == 10
        required = result['pattern']['design_coverage']['modules']
        assert {'circular_hem_flounce_v1', 'skirt_full_lining_v1'} <= {
            module['module_id'] for module in required
        }
        saved = api.get(f"/api/v1/projects/{project['project_id']}").json()
        repeated = api.post('/api/v1/patterns/generate', json=engine_request(saved),
                            headers={'If-Match': str(saved['revision'])})
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()['generation_id'] == result['generation_id']
        exported = api.post(f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf")
        assert exported.status_code == 200, exported.text
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(exported.content)).pages)
        for piece in result['pattern']['pieces']:
            assert piece['name_ru'] in text
        assert '50 x 50 mm' in text


def test_old_base_request_cannot_replace_saved_flounce_even_without_revision_header(tmp_path: Path):
    project = project_document()
    with client(tmp_path) as api:
        api.post('/api/v1/projects', json=project)
        base_request = engine_request(project)
        base = api.post('/api/v1/patterns/generate', json=base_request)
        assert base.status_code == 200, base.text
        saved = api.get(f"/api/v1/projects/{project['project_id']}").json()
        changed = deepcopy(saved)
        changed['status'] = 'draft'
        changed['garment_spec']['design_intent'] = layered_project()['garment_spec']['design_intent']
        response = api.put(f"/api/v1/projects/{project['project_id']}", json=changed,
                           headers={'If-Match': str(saved['revision'])})
        assert response.status_code == 200, response.text
        assert response.json()['latest_generation'] is None
        stale = api.post('/api/v1/patterns/generate', json=base_request)
        assert stale.status_code == 409, stale.text
        assert stale.json()['code'] == 'GENERATION_INPUTS_STALE'
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert current['latest_generation'] is None
        assert current['garment_spec']['design_intent']['elements'][0]['included'] is True


def test_changes_during_generation_do_not_attach_an_outdated_result(tmp_path: Path):
    repository = SQLiteRepository(tmp_path / 'race.db')
    settings = Settings(database_path=repository.database_path, image_storage_path=tmp_path / 'images')

    class EditingEngine(GeometryPatternEngine):
        def generate(self, request):
            project = repository.get_project(request['project_id'])
            project['status'] = 'draft'
            project['garment_spec']['parameters']['skirt']['length_from_waist_mm'] += 10
            repository.replace_project(project['project_id'], project['revision'], project)
            return super().generate(request)

    with TestClient(create_app(settings, repository=repository, pattern_engine=EditingEngine())) as api:
        project = project_document()
        api.post('/api/v1/projects', json=project)
        response = api.post('/api/v1/patterns/generate', json=engine_request(project),
                            headers={'If-Match': '1'})
        assert response.status_code == 409, response.text
        assert response.json()['code'] == 'PROJECT_REVISION_CONFLICT'
        current = repository.get_project(project['project_id'])
        assert current['latest_generation'] is None
        assert current['generation_history'] == []
        assert current['garment_spec']['parameters']['skirt']['length_from_waist_mm'] == 560


def test_uncompiled_drape_cannot_be_bypassed_with_a_matching_old_hash(tmp_path: Path):
    project = project_document()
    project['garment_spec']['design_intent'] = _intent([])
    project['garment_spec']['design_intent']['coverage_schema_version'] = '1.0.0'
    with client(tmp_path) as api:
        assert api.post('/api/v1/projects', json=project).status_code == 201
        old_request = engine_request(project)
        base = api.post('/api/v1/patterns/generate', json=old_request)
        assert base.status_code == 200, base.text
        changed = api.get(f"/api/v1/projects/{project['project_id']}").json()
        changed['status'] = 'draft'
        changed['garment_spec'].update(selection_status='proposed', confirmed_at=None)
        intent = changed['garment_spec']['design_intent']
        drape = _element('new_drape', 'drape', 'soft', 'bodice_front',
                         'separate_piece', 1, 'circular_hem_flounce_v1', _dimensions())
        drape.update(support_status='planned', module_id=None)
        intent.update(status='partial', elements=[drape])
        assert compute_input_hash(changed) == old_request['input_hash']
        saved = api.put(f"/api/v1/projects/{project['project_id']}", json=changed,
                        headers={'If-Match': str(changed['revision'])})
        assert saved.status_code == 200, saved.text
        bypass = api.post('/api/v1/patterns/generate', json=old_request)
        assert bypass.status_code == 409, bypass.text
        assert bypass.json()['code'] == 'GENERATION_INPUTS_STALE'
        assert api.get(f"/api/v1/projects/{project['project_id']}").json()['latest_generation'] is None


def test_ready_measurements_can_be_saved_with_an_uncompiled_drape(tmp_path: Path):
    project = layered_project()
    project['status'] = 'draft'
    project['garment_spec'].update(selection_status='proposed', confirmed_at=None)
    intent = project['garment_spec']['design_intent']
    intent['status'] = 'partial'
    element = intent['elements'][0]
    element.update(type='drape', variant='soft', location='bodice_front',
                   support_status='planned', module_id=None, dimensions_mm=_dimensions())
    with client(tmp_path) as api:
        response = api.post('/api/v1/projects', json=project)
        assert response.status_code == 201, response.text
        saved = response.json()
        saved['body_measurements']['name'] = 'Мерки до моделирования драпировки'
        response = api.put(f"/api/v1/projects/{project['project_id']}", json=saved,
                           headers={'If-Match': '1'})
        assert response.status_code == 200, response.text
        assert response.json()['body_measurements']['status'] == 'ready'
        blocked = api.post('/api/v1/patterns/generate', json=engine_request(response.json()))
        assert blocked.status_code == 422


def test_registry_rejects_missing_extra_and_out_of_range_flounce_dimensions():
    project = layered_project()
    spec = project['garment_spec']
    element = spec['design_intent']['elements'][0]
    assert matching_module(element, spec, kind='element') == 'circular_hem_flounce_v1'
    for dimensions in [{}, _dimensions(), _dimensions(depth=29), _dimensions(depth=401),
                       _dimensions(depth=80, width=10), _dimensions(depth=True)]:
        changed = {**element, 'dimensions_mm': dimensions}
        assert not module_matches('circular_hem_flounce_v1', changed, spec, kind='element')
    assert module_matches('circular_hem_flounce_v1', element, spec, kind='element')
    assert module_matches('circular_hem_flounce_v1', {**element, 'count': 1.0}, spec, kind='element')
    assert not module_matches('circular_hem_flounce_v1', {**element, 'count': True}, spec, kind='element')
    assert compute_input_hash(project) != compute_input_hash(project_document())

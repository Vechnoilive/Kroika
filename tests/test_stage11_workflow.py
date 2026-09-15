from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402


def example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def project_document(name: str = "Этап 11") -> dict:
    project = example("example-dress-project.json")
    now = "2026-09-15T12:00:00Z"
    project.update({
        "project_id": str(uuid4()),
        "revision": 1,
        "name": name,
        "created_at": now,
        "updated_at": now,
        "status": "inputs_confirmed",
        "style_analysis_provider": None,
        "style_analysis": None,
    })
    project["body_measurements"]["profile_id"] = str(uuid4())
    project["garment_spec"]["garment_id"] = str(uuid4())
    project["fit_settings"]["settings_id"] = str(uuid4())
    project["fabric_properties"]["fabric_id"] = str(uuid4())
    return project


def engine_request(project: dict) -> dict:
    request = example("example-engine-request.json")
    request["request_id"] = str(uuid4())
    request["project_id"] = project["project_id"]
    for field in (
        "pattern_method", "body_measurements", "garment_spec", "fit_settings",
        "fabric_properties",
    ):
        request[field] = deepcopy(project[field])
    request["input_hash"] = compute_input_hash(request)
    return request


def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        log_level="CRITICAL",
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_qwen_is_the_only_user_visible_external_provider(tmp_path: Path):
    with client(tmp_path) as api:
        response = api.get("/api/v1/ai/providers")
        assert response.status_code == 200
        statuses = {item["provider_id"]: item for item in response.json()["items"]}
        assert statuses["mock"]["enabled_for_users"] is True
        assert statuses["qwen"]["enabled_for_users"] is True
        assert statuses["gemini"]["enabled_for_users"] is False

    Settings(
        database_path=tmp_path / "enabled.db",
        ai_provider="gemini",
        enabled_ai_providers=("mock", "qwen", "gemini"),
    ).validate()


def test_project_revisions_are_auditable_and_restore_creates_a_new_draft(tmp_path: Path):
    project = project_document()
    with client(tmp_path) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        changed = deepcopy(project)
        changed["name"] = "Платье с уточнённой длиной"
        saved = api.put(
            f"/api/v1/projects/{project['project_id']}",
            headers={"If-Match": "1"},
            json=changed,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 2

        history = api.get(f"/api/v1/projects/{project['project_id']}/history")
        assert history.status_code == 200
        assert [item["revision"] for item in history.json()["items"]] == [2, 1]
        assert history.json()["items"][0]["is_current"] is True
        assert "название" in history.json()["items"][0]["change_summary"]

        restored = api.post(
            f"/api/v1/projects/{project['project_id']}/history/1/restore",
            headers={"If-Match": "2"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["revision"] == 3
        assert restored.json()["name"] == project["name"]
        assert restored.json()["status"] == "draft"
        assert restored.json()["latest_generation"] is None


def test_editing_inputs_invalidates_only_latest_result_and_cached_result_can_be_reopened(tmp_path: Path):
    project = project_document()
    with client(tmp_path) as api:
        api.post("/api/v1/projects", json=project)
        request = engine_request(project)
        generated = api.post("/api/v1/patterns/generate", json=request)
        assert generated.status_code == 200, generated.text
        after_generation = api.get(f"/api/v1/projects/{project['project_id']}").json()
        history_before = list(after_generation["generation_history"])

        edited = deepcopy(after_generation)
        edited["status"] = "draft"
        edited["garment_spec"]["parameters"]["skirt"]["length_from_waist_mm"] += 10
        changed = api.put(
            f"/api/v1/projects/{project['project_id']}",
            headers={"If-Match": str(after_generation["revision"])},
            json=edited,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["latest_generation"] is None
        assert changed.json()["generation_history"] == history_before

        reverted = deepcopy(changed.json())
        reverted["garment_spec"] = deepcopy(project["garment_spec"])
        reverted["fit_settings"] = deepcopy(project["fit_settings"])
        reverted["fabric_properties"] = deepcopy(project["fabric_properties"])
        reverted["status"] = "inputs_confirmed"
        saved = api.put(
            f"/api/v1/projects/{project['project_id']}",
            headers={"If-Match": str(reverted["revision"])},
            json=reverted,
        ).json()
        reopened_request = engine_request(saved)
        reopened = api.post("/api/v1/patterns/generate", json=reopened_request)
        assert reopened.status_code == 200, reopened.text
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert current["latest_generation"]["generation_id"] == generated.json()["generation_id"]
        assert len(current["generation_history"]) == 1


def test_svg_preview_filters_layers_but_exports_remain_complete(tmp_path: Path):
    project = project_document()
    with client(tmp_path) as api:
        api.post("/api/v1/projects", json=project)
        result = api.post("/api/v1/patterns/generate", json=engine_request(project)).json()
        generation_id = result["generation_id"]
        preview = api.get(
            f"/api/v1/patterns/{generation_id}/preview.svg?layers=cutting,dimensions"
        )
        assert preview.status_code == 200
        assert 'data-layer="cutting"' in preview.text
        assert 'data-layer="dimensions"' in preview.text
        assert 'data-layer="seam"' not in preview.text
        assert 'data-layer="grain"' not in preview.text
        assert "мм</text>" in preview.text

        invalid = api.get(
            f"/api/v1/patterns/{generation_id}/preview.svg?layers=cutting,scripts"
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "SVG_LAYER_UNKNOWN"
        export = api.get(f"/api/v1/patterns/{generation_id}/export/print.svg")
        assert 'data-layer="seam"' in export.text
        assert 'data-layer="grain"' in export.text


def test_stage11_contract_and_current_only_ci_are_wired(tmp_path: Path):
    launcher = (ROOT / "scripts/start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage11.txt"' in launcher
    assert "python scripts/verify_stage11.py" in workflow
    assert "verify_all.py" not in workflow

    spec, base_uri = read_from_filename(str(ROOT / "schemas/openapi.v1.yaml"))
    validate(spec, base_uri=base_uri)
    documented = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    app = create_app(Settings(
        database_path=tmp_path / "contract.db",
        image_storage_path=tmp_path / "contract-images",
        log_level="CRITICAL",
    ))
    runtime = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert runtime == documented

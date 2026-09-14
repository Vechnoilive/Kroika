from __future__ import annotations

from copy import deepcopy
import json
import logging
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
                str(ROOT / "backend" / "src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.logging_config import JsonFormatter  # noqa: E402
from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.semantic import validate_ai_analysis, validate_validation_report  # noqa: E402
from kroika_pattern_engine import ScaffoldPatternEngine  # noqa: E402


def example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


@pytest.fixture
def app(tmp_path: Path):
    return create_app(Settings(database_path=tmp_path / "kroika.db", log_level="CRITICAL"))


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def create_example_project(client: TestClient) -> dict:
    project = example("example-dress-project.json")
    response = client.post("/api/v1/projects", json=project)
    assert response.status_code == 201, response.text
    return project


def test_health_checks_dependencies_and_request_id(client: TestClient):
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == ready.status_code == 200
    assert ready.json() == {
        "status": "ok", "service": "kroika-backend", "version": "0.6.0",
        "database": "ok", "ai_provider": "mock",
        "pattern_engine": "kroika-geometry:0.2.0",
    }
    assert len(ready.headers["X-Request-ID"]) == 36


def test_mock_provider_is_strict_and_never_accepts_measurements(client: TestClient):
    request = example("example-ai-request.json")
    response = client.post("/api/v1/garments/analyze-image", json=request)
    assert response.status_code == 200
    validate_ai_analysis(response.json())
    request["body_measurements"] = {"bust": 920}
    rejected = client.post("/api/v1/garments/analyze-image", json=request)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "CONTRACT_VALIDATION_FAILED"
    assert "920" not in json.dumps(rejected.json().get("issues", []), ensure_ascii=False)


def test_projects_persist_and_revision_conflicts_do_not_overwrite(client: TestClient, app):
    project = create_example_project(client)
    project_id = project["project_id"]
    listed = client.get("/api/v1/projects").json()["items"]
    assert listed == [{
        "project_id": project_id, "name": project["name"], "revision": 1,
        "status": "inputs_confirmed", "updated_at": project["updated_at"],
    }]
    changed = deepcopy(project)
    changed["name"] = "Обновлённое название"
    updated = client.put(
        f"/api/v1/projects/{project_id}", headers={"If-Match": "1"}, json=changed
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["name"] == "Обновлённое название"
    stale = client.put(
        f"/api/v1/projects/{project_id}", headers={"If-Match": "1"}, json=changed
    )
    assert stale.status_code == 409
    assert client.get(f"/api/v1/projects/{project_id}").json()["name"] == "Обновлённое название"
    reopened = create_app(Settings(database_path=app.state.settings.database_path, log_level="CRITICAL"))
    with TestClient(reopened) as second_client:
        assert second_client.get(f"/api/v1/projects/{project_id}").json()["revision"] == 2


def test_invalid_project_returns_field_error_not_internal_trace(client: TestClient):
    response = client.post("/api/v1/projects", json={"name": "неполный"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "CONTRACT_VALIDATION_FAILED"
    assert body["message_ru"] == "Проверьте отмеченные поля и попробуйте ещё раз."
    assert "Traceback" not in response.text
    assert "jsonschema" not in response.text


def test_generation_is_idempotent_per_project_and_fails_closed(client: TestClient):
    project = create_example_project(client)
    request = example("example-engine-request.json")
    first = client.post("/api/v1/patterns/generate", json=request)
    second = client.post("/api/v1/patterns/generate", json=deepcopy(request))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    result = first.json()
    validate_document("pattern-engine-result", result)
    validate_validation_report(result["validation_report"])
    assert result["status"] == "rejected"
    assert result["pattern"] is None
    assert result["validation_report"]["production_export_allowed"] is False
    saved = client.get(f"/api/v1/projects/{project['project_id']}").json()
    assert saved["revision"] == 2
    assert len(saved["generation_history"]) == 1
    assert saved["status"] == "validation_failed"

    other_project = example("example-dress-project.json")
    other_project["project_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert client.post("/api/v1/projects", json=other_project).status_code == 201
    other_request = example("example-engine-request.json")
    other_request["project_id"] = other_project["project_id"]
    other_result = client.post("/api/v1/patterns/generate", json=other_request)
    assert other_result.status_code == 200
    assert other_result.json()["project_id"] == other_project["project_id"]
    assert other_result.json()["generation_id"] != result["generation_id"]


def test_exports_are_blocked_until_geometry_and_toile_are_verified(client: TestClient):
    create_example_project(client)
    result = client.post(
        "/api/v1/patterns/generate", json=example("example-engine-request.json")
    ).json()
    generation_id = result["generation_id"]
    assert client.get(f"/api/v1/patterns/{generation_id}/validation").status_code == 200
    assert client.get(f"/api/v1/patterns/{generation_id}/preview.svg").status_code == 409
    blocked = client.post(f"/api/v1/patterns/{generation_id}/export/a4-pdf")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "PRODUCTION_EXPORT_BLOCKED"
    exported = client.get(f"/api/v1/patterns/{generation_id}/export/project-json")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"].startswith("attachment;")


def test_backend_rejects_a_result_bound_to_another_project(tmp_path: Path):
    class MismatchedEngine(ScaffoldPatternEngine):
        def generate(self, request):
            result = super().generate(request)
            result["project_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            return result

    app = create_app(
        Settings(database_path=tmp_path / "mismatch.db", log_level="CRITICAL"),
        pattern_engine=MismatchedEngine(),
    )
    with TestClient(app, raise_server_exceptions=False) as isolated_client:
        project = create_example_project(isolated_client)
        response = isolated_client.post(
            "/api/v1/patterns/generate", json=example("example-engine-request.json")
        )
        assert response.status_code == 500
        assert response.json()["code"] == "ENGINE_RESULT_MISMATCH"
        assert isolated_client.get(
            f"/api/v1/projects/{project['project_id']}"
        ).json()["revision"] == 1


def test_missing_resources_and_bad_paths_have_friendly_errors(client: TestClient):
    missing = client.get("/api/v1/projects/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    assert missing.status_code == 404
    assert missing.json()["message_ru"] == "Проект не найден."
    malformed = client.get("/api/v1/projects/not-a-uuid")
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "REQUEST_VALIDATION_FAILED"


def test_log_formatter_drops_unapproved_sensitive_fields():
    record = logging.LogRecord("kroika.backend", logging.INFO, __file__, 1,
                               "request_completed", (), None)
    record.request_id = "safe-id"
    record.method = "POST"
    record.route = "/api/v1/projects"
    record.body = {"bust": 920, "api_key": "secret"}
    payload = JsonFormatter().format(record)
    assert "safe-id" in payload
    assert "920" not in payload
    assert "secret" not in payload


def test_pattern_engine_package_has_no_web_or_ai_dependency():
    source = (ROOT / "pattern-engine" / "src" / "kroika_pattern_engine" / "scaffold.py").read_text(
        encoding="utf-8"
    ).lower()
    assert "fastapi" not in source
    assert "qwen" not in source
    assert "sqlite" not in source
    assert isinstance(ScaffoldPatternEngine().engine_version, str)


def test_runtime_routes_match_versioned_openapi_contract(app):
    canonical = yaml.safe_load((ROOT / "schemas" / "openapi.v1.yaml").read_text(encoding="utf-8"))
    documented = {
        (method.upper(), path)
        for path, item in canonical["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    runtime = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert runtime == documented


def test_compose_defines_both_health_checked_services():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"backend", "frontend"}
    assert all("healthcheck" in service for service in compose["services"].values())
    assert compose["services"]["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"


def test_only_mock_provider_is_allowed_in_stage4(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "db.sqlite", ai_provider="qwen")
    with pytest.raises(ValueError, match="этапа 10"):
        settings.validate()

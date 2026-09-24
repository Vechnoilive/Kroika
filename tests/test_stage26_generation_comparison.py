from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import APP_VERSION, create_app  # noqa: E402
from kroika_backend.comparison import compare_generations  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine  # noqa: E402
from tests.wiring import assert_current_only_workflow, assert_current_versions  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples/v1" / name).read_text(encoding="utf-8"))


def _project(name: str = "Сравнение версий") -> dict:
    project = _example("example-dress-project.json")
    project.update({
        "project_id": str(uuid4()),
        "revision": 1,
        "name": name,
        "created_at": "2026-09-24T01:00:00Z",
        "updated_at": "2026-09-24T01:00:00Z",
        "status": "inputs_confirmed",
    })
    project["body_measurements"]["profile_id"] = str(uuid4())
    project["garment_spec"]["garment_id"] = str(uuid4())
    project["fit_settings"]["settings_id"] = str(uuid4())
    project["fabric_properties"]["fabric_id"] = str(uuid4())
    return project


def _request(project: dict) -> dict:
    request = _example("example-engine-request.json")
    request["request_id"] = str(uuid4())
    request["project_id"] = project["project_id"]
    for field in (
        "pattern_method", "body_measurements", "garment_spec", "fit_settings",
        "fabric_properties",
    ):
        request[field] = deepcopy(project[field])
    request["input_hash"] = compute_input_hash(request)
    return request


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        log_level="CRITICAL",
    )


def _generate(api: TestClient, project: dict) -> dict:
    generated = api.post("/api/v1/patterns/generate", json=_request(project))
    assert generated.status_code == 200, generated.text
    return generated.json()


def test_api_compares_measurements_style_and_real_pattern_geometry(tmp_path: Path) -> None:
    project = _project()
    with TestClient(create_app(_settings(tmp_path)), raise_server_exceptions=False) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        first = _generate(api, project)

        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        current["status"] = "draft"
        waist = current["body_measurements"]["values"]["waist"]
        waist["value"] += 20
        if waist.get("original_input"):
            waist["original_input"]["value"] += (
                2 if waist["original_input"]["unit"] == "cm" else 20
            )
        current["garment_spec"]["parameters"]["skirt"]["length_from_waist_mm"] += 25
        replaced = api.put(
            f"/api/v1/projects/{project['project_id']}",
            headers={"If-Match": str(current["revision"])},
            json=current,
        )
        assert replaced.status_code == 200, replaced.text
        second = _generate(api, replaced.json())

        listed = api.get(f"/api/v1/projects/{project['project_id']}/generations")
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["items"]) == 2
        assert all(item["comparable"] for item in listed.json()["items"])
        assert next(item for item in listed.json()["items"] if item["is_current"])[
            "generation_id"
        ] == second["generation_id"]

        compared = api.get(
            f"/api/v1/projects/{project['project_id']}/generations/compare",
            params={
                "base_generation_id": first["generation_id"],
                "target_generation_id": second["generation_id"],
            },
        )
        assert compared.status_code == 200, compared.text
        document = compared.json()
        waist = next(
            item for item in document["measurements"] if item["field_id"] == "waist"
        )
        assert waist["label_ru"] == "Обхват талии"
        assert waist["delta"] == 20
        skirt = next(
            item for item in document["style"]
            if item["path"].endswith("skirt.length_from_waist_mm")
        )
        assert skirt["delta"] == 25
        assert document["totals"]["changed_pieces"] > 0
        assert document["pattern"]["changed_pieces"]
        assert document["no_changes"] is False

        same = api.get(
            f"/api/v1/projects/{project['project_id']}/generations/compare",
            params={
                "base_generation_id": first["generation_id"],
                "target_generation_id": first["generation_id"],
            },
        )
        assert same.status_code == 422
        assert same.json()["code"] == "GENERATION_COMPARE_SAME"


def test_comparison_is_confined_to_one_project_and_never_guesses_inputs(
    tmp_path: Path,
) -> None:
    first_project = _project("Первый проект")
    second_project = _project("Второй проект")
    with TestClient(create_app(_settings(tmp_path)), raise_server_exceptions=False) as api:
        assert api.post("/api/v1/projects", json=first_project).status_code == 201
        assert api.post("/api/v1/projects", json=second_project).status_code == 201
        first = _generate(api, first_project)
        second = _generate(api, second_project)
        mixed = api.get(
            f"/api/v1/projects/{first_project['project_id']}/generations/compare",
            params={
                "base_generation_id": first["generation_id"],
                "target_generation_id": second["generation_id"],
            },
        )
        assert mixed.status_code == 409
        assert mixed.json()["code"] == "GENERATION_PROJECT_MISMATCH"

        with sqlite3.connect(tmp_path / "kroika.db") as connection:
            connection.execute(
                "DELETE FROM generation_input_snapshots WHERE generation_id = ?",
                (first["generation_id"],),
            )
        listed = api.get(
            f"/api/v1/projects/{first_project['project_id']}/generations"
        ).json()
        assert listed["items"][0]["comparable"] is False


def test_topology_and_warning_changes_are_reported_without_input_noise() -> None:
    request = _example("example-engine-request.json")
    request["input_hash"] = compute_input_hash(request)
    base = GeometryPatternEngine().generate(request)
    target = deepcopy(base)
    target["generation_id"] = str(uuid4())
    target["pattern"]["pieces"].pop()
    target["validation_report"]["issues"].append({
        "code": "STAGE26_TEST_WARNING",
        "severity": "warning",
        "message_ru": "Новая проверка для сравнения.",
        "json_pointer": "/pattern/pieces",
    })

    compared = compare_generations(
        base,
        target,
        request,
        request,
        current_generation_id=target["generation_id"],
    )
    assert compared["measurements"] == []
    assert compared["style"] == []
    assert len(compared["pattern"]["removed_pieces"]) == 1
    assert compared["validation"]["added_issues"][0]["code"] == "STAGE26_TEST_WARNING"
    assert compared["totals"]["validation_changes"] == 1


def test_missing_snapshot_table_is_recreated_and_backfilled_from_revisions(
    tmp_path: Path,
) -> None:
    project = _project()
    settings = _settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        generated = _generate(api, project)
    with sqlite3.connect(tmp_path / "kroika.db") as connection:
        connection.execute("DROP TABLE generation_input_snapshots")

    with TestClient(create_app(settings), raise_server_exceptions=False) as api:
        listed = api.get(f"/api/v1/projects/{project['project_id']}/generations")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["generation_id"] == generated["generation_id"]
        assert listed.json()["items"][0]["comparable"] is True


def test_stage26_contract_and_current_only_gate_are_wired(tmp_path: Path) -> None:
    requirements = (ROOT / "requirements-stage26.txt").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    verify_all = (ROOT / "scripts/verify_all.py").read_text(encoding="utf-8")
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    backend = (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")

    assert "-r requirements-stage25.txt" in requirements
    assert 'ROOT / "requirements-stage26.txt"' in launcher
    assert '"requirements-stage26.txt"' in launcher
    assert_current_only_workflow(ROOT, workflow)
    assert "verify_stage26.py" in verify_all
    assert package["scripts"]["test:stage26"].endswith(
        "Stage26GenerationComparison.test.tsx"
    )
    assert package["version"] == APP_VERSION == assert_current_versions(ROOT, 26)
    assert f'version = "{APP_VERSION}"' in backend

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

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
                str(ROOT / "backend" / "src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.contract_io import ContractValidationError, validate_document  # noqa: E402
from kroika_contracts.measurements import (  # noqa: E402
    MEASUREMENTS,
    catalogue,
    measurement_issues,
    required_ids,
    validate_measurement_profile,
)


def example_project() -> dict:
    return json.loads(
        (ROOT / "examples" / "v1" / "example-dress-project.json").read_text(encoding="utf-8")
    )


def example_profile() -> dict:
    return deepcopy(example_project()["body_measurements"])


def fixed_profiles() -> list[dict]:
    document = json.loads(
        (ROOT / "references" / "stage5" / "measurement-profiles.json").read_text(
            encoding="utf-8"
        )
    )
    return document["profiles"]


@pytest.fixture
def app(tmp_path: Path):
    return create_app(Settings(database_path=tmp_path / "stage5.db", log_level="CRITICAL"))


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_catalogue_has_unique_complete_metadata_and_context_sets():
    ids = [item.id for item in MEASUREMENTS]
    assert len(ids) >= 35
    assert len(ids) == len(set(ids))
    assert all(item.minimum < item.maximum for item in MEASUREMENTS)
    assert all(len(item.instruction_ru) >= 40 for item in MEASUREMENTS)
    assert all(item.unit == ("deg" if item.kind == "angle" else "mm") for item in MEASUREMENTS)

    sleeveless = catalogue("dress", "sleeveless")
    long_sleeve = catalogue("dress", "long")
    assert "upper_arm_circumference" not in {
        item["id"] for item in sleeveless["measurements"]
    }
    long_by_id = {item["id"]: item for item in long_sleeve["measurements"]}
    assert long_by_id["upper_arm_circumference"]["required"] is True
    assert set(required_ids("dress", "sleeveless")) < set(required_ids("dress", "long"))


@pytest.mark.parametrize("profile", fixed_profiles(), ids=lambda item: item["name"])
def test_fixed_synthetic_profiles_cover_valid_ranges(profile: dict):
    validate_measurement_profile(profile, "dress", "sleeveless")
    assert not [
        item for item in measurement_issues(profile, "dress", "sleeveless")
        if item.severity == "blocking_error"
    ]


def test_catalog_api_contains_rules_but_no_personal_values(client: TestClient):
    response = client.get(
        "/api/v1/measurements/catalog?garment_type=dress&sleeve_type=sleeveless"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["normalized_unit"] == "mm"
    assert body["display_units"] == ["cm", "mm"]
    assert body["source_options"] == ["user", "preset", "derived"]
    assert "profile_id" not in response.text
    assert all("instruction_ru" in item and "required" in item for item in body["measurements"])


def test_blank_draft_stays_empty_and_is_reported_incomplete(client: TestClient):
    profile = {
        "schema_version": "1.0.0",
        "profile_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "name": "Пустой профиль",
        "status": "draft",
        "normalized_unit": "mm",
        "values": {},
        "angles_deg": {},
        "angle_provenance": {},
    }
    response = client.post(
        "/api/v1/measurements/validate?garment_type=dress&sleeve_type=sleeveless",
        json=profile,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "incomplete"
    assert response.json()["completed_count"] == 0
    assert profile["values"] == {}
    assert profile["angles_deg"] == {}


def test_range_normalization_and_derived_provenance_fail_closed(client: TestClient):
    profile = example_profile()
    profile["status"] = "draft"
    profile["values"]["bust"] = {
        "value": 590, "unit": "mm", "source": "user",
        "original_input": {"value": 59, "unit": "cm"},
    }
    response = client.post("/api/v1/measurement-profiles", json=profile)
    assert response.status_code == 422
    assert response.json()["issues"][0]["code"] == "MEASUREMENT_OUT_OF_RANGE"
    assert "590" not in response.text

    normalized = example_profile()
    normalized["values"]["bust"]["original_input"] = {"value": 93, "unit": "cm"}
    with pytest.raises(Exception, match="NORMALIZATION_MISMATCH"):
        validate_measurement_profile(normalized)

    derived = example_profile()
    derived["values"]["bust"] = {"value": 920, "unit": "mm", "source": "derived"}
    with pytest.raises(ContractValidationError):
        validate_document("body-measurements", derived)


def test_ready_long_sleeve_profile_requires_sleeve_measurements(client: TestClient):
    profile = example_profile()
    response = client.post(
        "/api/v1/measurements/validate?garment_type=dress&sleeve_type=long",
        json=profile,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid"
    missing = {item["json_pointer"] for item in body["issues"]}
    assert "/body_measurements/values/upper_arm_circumference" in missing
    assert "/body_measurements/values/sleeve_length" in missing


def test_cross_measurement_checks_are_clear_and_non_evaluative():
    profile = example_profile()
    profile["values"]["elbow_length"] = {"value": 650, "unit": "mm", "source": "user"}
    profile["values"]["sleeve_length"] = {"value": 600, "unit": "mm", "source": "user"}
    issues = measurement_issues(profile)
    assert {item.code for item in issues} >= {"MEASUREMENT_OUT_OF_RANGE", "MEASUREMENT_LENGTH_ORDER"}
    assert all("фигура" not in item.message_ru.lower() for item in issues)


def test_profiles_persist_without_exposing_values_in_list(client: TestClient, app):
    profile = example_profile()
    created = client.post("/api/v1/measurement-profiles", json=profile)
    assert created.status_code == 201
    assert created.json()["revision"] == 1
    assert created.json()["profile"] == profile

    listed = client.get("/api/v1/measurement-profiles")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["profile_id"] == profile["profile_id"]
    assert "values" not in listed.text

    duplicate = client.post("/api/v1/measurement-profiles", json=profile)
    assert duplicate.status_code == 409
    changed = deepcopy(profile)
    changed["name"] = "Обновлённые мерки"
    updated = client.put(
        f"/api/v1/measurement-profiles/{profile['profile_id']}",
        headers={"If-Match": "1"}, json=changed,
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["profile"]["name"] == "Обновлённые мерки"
    stale = client.put(
        f"/api/v1/measurement-profiles/{profile['profile_id']}",
        headers={"If-Match": "1"}, json=profile,
    )
    assert stale.status_code == 409

    reopened = create_app(Settings(database_path=app.state.settings.database_path, log_level="CRITICAL"))
    with TestClient(reopened) as second_client:
        saved = second_client.get(f"/api/v1/measurement-profiles/{profile['profile_id']}")
        assert saved.json()["profile"]["name"] == "Обновлённые мерки"


def test_project_save_preserves_mm_original_input_and_source(client: TestClient):
    project = example_project()
    assert client.post("/api/v1/projects", json=project).status_code == 201
    changed = deepcopy(project)
    changed["status"] = "draft"
    changed["body_measurements"]["values"]["bust"] = {
        "value": 930, "unit": "mm", "source": "user",
        "original_input": {"value": 93, "unit": "cm"},
    }
    response = client.put(
        f"/api/v1/projects/{project['project_id']}", headers={"If-Match": "1"}, json=changed,
    )
    assert response.status_code == 200
    saved = response.json()["body_measurements"]["values"]["bust"]
    assert saved == {
        "value": 930, "unit": "mm", "source": "user",
        "original_input": {"value": 93, "unit": "cm"},
    }


def test_measurement_change_requires_project_to_return_to_draft(client: TestClient):
    project = example_project()
    assert client.post("/api/v1/projects", json=project).status_code == 201
    changed = deepcopy(project)
    changed["body_measurements"]["values"]["bust"] = {
        "value": 930, "unit": "mm", "source": "user",
        "original_input": {"value": 93, "unit": "cm"},
    }
    rejected = client.put(
        f"/api/v1/projects/{project['project_id']}", headers={"If-Match": "1"}, json=changed,
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "PROJECT_MEASUREMENTS_CHANGED_WITH_ACTIVE_STATUS"
    assert client.get(f"/api/v1/projects/{project['project_id']}").json()["revision"] == 1


def test_local_and_docker_bootstrap_install_latest_stage_requirements():
    local_launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert '"requirements-stage5.txt"' in local_launcher
    assert '"-r", str(ROOT / "requirements-stage5.txt")' in local_launcher
    assert "COPY requirements-stage3.txt requirements-stage4.txt requirements-stage5.txt" in dockerfile
    assert "-r requirements-stage5.txt" in dockerfile

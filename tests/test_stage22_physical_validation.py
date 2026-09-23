from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.repository import SQLiteRepository  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _project(name: str = "Физическая приёмка") -> dict:
    project = _example("example-dress-project.json")
    project.update({
        "project_id": str(uuid4()),
        "revision": 1,
        "name": name,
        "created_at": "2026-09-23T18:00:00Z",
        "updated_at": "2026-09-23T18:00:00Z",
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


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        log_level="CRITICAL",
    )), raise_server_exceptions=False)


def _generate(api: TestClient, project: dict) -> str:
    created = api.post("/api/v1/projects", json=project)
    assert created.status_code == 201, created.text
    generated = api.post("/api/v1/patterns/generate", json=_request(project))
    assert generated.status_code == 200, generated.text
    return generated.json()["generation_id"]


def _record(api: TestClient, generation_id: str, document: dict):
    return api.post(
        f"/api/v1/patterns/{generation_id}/physical-validation", json=document
    )


def test_validation_journal_is_append_only_and_fail_closed(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        generation_id = _generate(api, _project())
        initial = api.get(
            f"/api/v1/patterns/{generation_id}/physical-validation"
        ).json()
        assert [item["status"] for item in initial["gates"]] == [
            "pending", "pending", "pending",
        ]
        assert initial["production_allowed"] is False
        assert initial["records"] == []

        paper = _record(api, generation_id, {
            "gate": "paper",
            "reviewer_name": "Анна",
            "printer_name": "HP LaserJet M404",
            "square_width_mm": 50.4,
            "square_height_mm": 49.2,
            "control_line_mm": 200.8,
            "notes": "Листы совместились по меткам.",
        })
        assert paper.status_code == 201, paper.text
        assert paper.json()["gates"][0]["status"] == "pending"
        assert paper.json()["gates"][0]["passed_observations"] == 1
        assert paper.json()["gates"][0]["required_observations"] == 2
        assert paper.json()["records"][0]["outcome"] == "passed"
        assert paper.json()["production_allowed"] is False

        second_paper = _record(api, generation_id, {
            "gate": "paper",
            "reviewer_name": "Анна",
            "printer_name": "Canon i-SENSYS LBP223",
            "square_width_mm": 50,
            "square_height_mm": 50.1,
            "control_line_mm": 199.7,
            "notes": "Второй принтер, масштаб подтверждён.",
        })
        assert second_paper.status_code == 201, second_paper.text
        assert second_paper.json()["gates"][0]["status"] == "passed"

        expert = _record(api, generation_id, {
            "gate": "expert", "outcome": "passed", "reviewer_name": "Конструктор",
            "notes": "Баланс и сопряжения проверены.",
        })
        assert expert.status_code == 201, expert.text
        for figure_label in (
            "Профиль 1 · макет 1",
            " профиль 1 · МАКЕТ 1 ",
            "Профиль 2 · макет 2",
            "Профиль 3 · макет 3",
        ):
            toile = _record(api, generation_id, {
                "gate": "toile", "outcome": "passed", "reviewer_name": "Закройщик",
                "figure_label": figure_label,
                "notes": "Макет сел без блокирующих дефектов.",
            })
            assert toile.status_code == 201, toile.text
        assert toile.status_code == 201, toile.text
        accepted = toile.json()
        assert accepted["production_allowed"] is True
        assert [item["status"] for item in accepted["gates"]] == [
            "passed", "passed", "passed",
        ]
        assert accepted["gates"][2]["passed_observations"] == 3
        assert len(accepted["records"]) == 7

        svg = api.get(f"/api/v1/patterns/{generation_id}/export/print.svg")
        assert svg.headers["x-kroika-export-mode"] == "production"
        assert svg.headers["x-kroika-production-ready"] == "true"
        assert "production-ready=true" in svg.text
        assert 'id="control-line-200mm"' in svg.text
        assert "ЭКСПЕРИМЕНТАЛЬНО" not in svg.text
        pdf = api.post(f"/api/v1/patterns/{generation_id}/export/a4-pdf")
        assert pdf.status_code == 200
        assert pdf.headers["x-kroika-production-ready"] == "true"
        assert "Контрольная линия 200 мм" in PdfReader(
            BytesIO(pdf.content)
        ).pages[0].extract_text()

        failed_repeat = _record(api, generation_id, {
            "gate": "expert", "outcome": "failed", "reviewer_name": "Конструктор",
            "notes": "После повторной проверки требуется исправить баланс.",
        })
        assert failed_repeat.status_code == 201, failed_repeat.text
        revoked = failed_repeat.json()
        assert revoked["production_allowed"] is False
        assert revoked["gates"][1]["status"] == "failed"
        assert len(revoked["records"]) == 8
        assert len({item["record_id"] for item in revoked["records"]}) == 8
        diagnostic = api.get(f"/api/v1/patterns/{generation_id}/export/print.svg")
        assert diagnostic.headers["x-kroika-export-mode"] == "diagnostic"
        assert diagnostic.headers["x-kroika-production-ready"] == "false"
        assert api.delete(f"/api/v1/projects/{accepted['project_id']}").status_code == 204
        with sqlite3.connect(tmp_path / "kroika.db") as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM physical_validation_records"
            ).fetchone()[0] == 0


def test_paper_result_is_derived_and_bad_or_incomplete_records_are_rejected(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as api:
        generation_id = _generate(api, _project())
        outside_tolerance = _record(api, generation_id, {
            "gate": "paper",
            "reviewer_name": "Анна",
            "printer_name": "Office printer",
            "square_width_mm": 48.8,
            "square_height_mm": 50,
            "control_line_mm": 200,
            "notes": "Масштаб по ширине ушёл.",
        })
        assert outside_tolerance.status_code == 201
        assert outside_tolerance.json()["gates"][0]["status"] == "failed"

        corrected = _record(api, generation_id, {
            "gate": "paper", "reviewer_name": "Анна",
            "printer_name": "Office printer", "square_width_mm": 50,
            "square_height_mm": 50, "control_line_mm": 200,
        })
        assert corrected.status_code == 201
        assert corrected.json()["gates"][0]["status"] == "pending"
        assert corrected.json()["gates"][0]["passed_observations"] == 1
        duplicate = _record(api, generation_id, {
            "gate": "paper", "reviewer_name": "Анна",
            "printer_name": " office PRINTER ", "square_width_mm": 50,
            "square_height_mm": 50, "control_line_mm": 200,
        })
        assert duplicate.status_code == 201
        assert duplicate.json()["gates"][0]["passed_observations"] == 1

        supplied_outcome = _record(api, generation_id, {
            "gate": "paper", "outcome": "passed", "reviewer_name": "Анна",
            "printer_name": "Office printer", "square_width_mm": 50,
            "square_height_mm": 50, "control_line_mm": 200,
        })
        assert supplied_outcome.status_code == 422
        missing_measurements = _record(api, generation_id, {
            "gate": "paper", "reviewer_name": "Анна", "printer_name": "Office printer",
        })
        assert missing_measurements.status_code == 422
        failed_without_notes = _record(api, generation_id, {
            "gate": "expert", "outcome": "failed", "reviewer_name": "Конструктор",
        })
        assert failed_without_notes.status_code == 422
        toile_without_profile = _record(api, generation_id, {
            "gate": "toile", "outcome": "passed", "reviewer_name": "Закройщик",
        })
        assert toile_without_profile.status_code == 422


def test_physical_approval_never_leaks_to_another_generation(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        first_id = _generate(api, _project("Первая версия"))
        second_id = _generate(api, _project("Вторая версия"))
        for document in (
            {
                "gate": "paper", "reviewer_name": "Анна", "printer_name": "HP M404",
                "square_width_mm": 50, "square_height_mm": 50,
                "control_line_mm": 200,
            },
            {
                "gate": "paper", "reviewer_name": "Анна",
                "printer_name": "Canon LBP223", "square_width_mm": 50,
                "square_height_mm": 50, "control_line_mm": 200,
            },
            {
                "gate": "expert", "outcome": "passed", "reviewer_name": "Конструктор",
                "notes": "Проверено.",
            },
            {
                "gate": "toile", "outcome": "passed", "reviewer_name": "Закройщик",
                "figure_label": "Профиль 1", "notes": "Проверено.",
            },
            {
                "gate": "toile", "outcome": "passed", "reviewer_name": "Закройщик",
                "figure_label": "Профиль 2", "notes": "Проверено.",
            },
            {
                "gate": "toile", "outcome": "passed", "reviewer_name": "Закройщик",
                "figure_label": "Профиль 3", "notes": "Проверено.",
            },
        ):
            assert _record(api, first_id, document).status_code == 201

        assert api.get(
            f"/api/v1/patterns/{first_id}/physical-validation"
        ).json()["production_allowed"] is True
        second = api.get(f"/api/v1/patterns/{second_id}/physical-validation").json()
        assert second["production_allowed"] is False
        assert second["records"] == []
        assert {item["status"] for item in second["gates"]} == {"pending"}


def test_stage22_contract_and_current_only_gate_are_wired(tmp_path: Path) -> None:
    requirements = (ROOT / "requirements-stage22.txt").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(
        encoding="utf-8"
    )
    verify_all = (ROOT / "scripts" / "verify_all.py").read_text(encoding="utf-8")
    assert "-r requirements-stage21.txt" in requirements
    assert 'ROOT / "requirements-stage22.txt"' in launcher
    assert '"requirements-stage22.txt"' in launcher
    assert "python scripts/verify_stage22.py" in workflow
    assert "verify_stage22.py" in verify_all

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


def test_stage22_migrates_a_version_one_database_without_losing_projects(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"
    repository = SQLiteRepository(database)
    repository.initialize()
    project = _project("Сохранённый проект")
    repository.create_project(project)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE physical_validation_records")
        connection.execute("PRAGMA user_version = 1")

    migrated = SQLiteRepository(database)
    migrated.initialize()
    assert migrated.get_project(project["project_id"]) == project
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "physical_validation_records" in tables

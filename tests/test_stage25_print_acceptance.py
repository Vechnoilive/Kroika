from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
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

from kroika_backend.app import APP_VERSION, create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402
from tests.wiring import assert_current_only_workflow, assert_current_versions  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _project(name: str = "Печатная приёмка") -> dict:
    project = _example("example-dress-project.json")
    project.update({
        "project_id": str(uuid4()),
        "revision": 1,
        "name": name,
        "created_at": "2026-09-23T20:00:00Z",
        "updated_at": "2026-09-23T20:00:00Z",
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
        "pattern_method",
        "body_measurements",
        "garment_spec",
        "fit_settings",
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


def _upload_evidence(api: TestClient) -> str:
    image = (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
    uploaded = api.post("/api/v1/images", json={
        "file_name": "paper-proof.png",
        "media_type": "image/png",
        "data_base64": base64.b64encode(image).decode("ascii"),
    })
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()["image_ref"]


def test_scale_check_and_print_plan_match_the_full_pdf(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        generation_id = _generate(api, _project())

        plan_response = api.get(f"/api/v1/patterns/{generation_id}/print-plan")
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()
        assert plan["page_format"] == "A4"
        assert plan["scale"] == 1
        assert plan["total_pdf_pages"] == plan["pattern_sheet_count"] + 1
        assert plan["columns"] * plan["rows"] == plan["pattern_sheet_count"]
        assert plan["production_allowed"] is False

        scale_check = api.post(
            f"/api/v1/patterns/{generation_id}/export/scale-check-pdf"
        )
        assert scale_check.status_code == 200, scale_check.text
        scale_reader = PdfReader(BytesIO(scale_check.content))
        assert len(scale_reader.pages) == 1
        assert scale_check.headers["x-kroika-total-page-count"] == "1"
        assert scale_check.headers["x-kroika-sheet-count"] == str(
            plan["pattern_sheet_count"]
        )
        scale_text = scale_reader.pages[0].extract_text()
        assert "50 x 50 mm" in scale_text
        assert "Контрольная линия 200 мм" in scale_text

        full_pdf = api.post(f"/api/v1/patterns/{generation_id}/export/a4-pdf")
        assert full_pdf.status_code == 200, full_pdf.text
        full_reader = PdfReader(BytesIO(full_pdf.content))
        assert len(full_reader.pages) == plan["total_pdf_pages"]
        assert full_pdf.headers["x-kroika-sheet-count"] == str(
            plan["pattern_sheet_count"]
        )
        assert full_pdf.headers["x-kroika-total-page-count"] == str(
            plan["total_pdf_pages"]
        )


def test_evidence_stays_local_is_protected_and_appears_in_report(tmp_path: Path) -> None:
    project = _project("Юбка с проверенной печатью")
    with _client(tmp_path) as api:
        generation_id = _generate(api, project)
        image_ref = _upload_evidence(api)

        recorded = api.post(
            f"/api/v1/patterns/{generation_id}/physical-validation",
            json={
                "gate": "paper",
                "reviewer_name": "Анна",
                "printer_name": "HP LaserJet M404",
                "square_width_mm": 50,
                "square_height_mm": 50,
                "control_line_mm": 200,
                "notes": "Пробная сборка совпала по меткам.",
                "evidence_image_refs": [image_ref],
            },
        )
        assert recorded.status_code == 201, recorded.text
        assert recorded.json()["records"][0]["evidence_image_refs"] == [image_ref]

        local_image = api.get(f"/api/v1/images/{image_ref}")
        assert local_image.status_code == 200
        assert local_image.headers["content-type"] == "image/png"
        assert local_image.headers["cache-control"] == "no-store"
        assert local_image.content.startswith(b"\x89PNG")
        protected = api.delete(f"/api/v1/images/{image_ref}")
        assert protected.status_code == 409
        assert protected.json()["code"] == "IMAGE_IN_USE"

        report = api.get(
            f"/api/v1/patterns/{generation_id}/physical-validation/report.pdf"
        )
        assert report.status_code == 200, report.text
        assert report.content.startswith(b"%PDF")
        report_text = "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(report.content)).pages
        )
        assert "Отчёт физической приёмки" in report_text
        assert project["name"] in report_text
        assert "Фото-доказательства: 1" in report_text
        assert generation_id in report_text

        removed = api.delete(f"/api/v1/projects/{project['project_id']}")
        assert removed.status_code == 204
        assert api.get(f"/api/v1/images/{image_ref}").status_code == 422
        assert not any((tmp_path / "images").glob(f"{image_ref}.*"))


def test_unknown_evidence_is_rejected_without_partial_journal_record(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        generation_id = _generate(api, _project())
        missing_ref = f"img_{'0' * 32}"
        rejected = api.post(
            f"/api/v1/patterns/{generation_id}/physical-validation",
            json={
                "gate": "expert",
                "outcome": "passed",
                "reviewer_name": "Конструктор",
                "notes": "Проверено.",
                "evidence_image_refs": [missing_ref],
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "INVALID_IMAGE"
        summary = api.get(
            f"/api/v1/patterns/{generation_id}/physical-validation"
        ).json()
        assert summary["records"] == []


def test_stage25_contract_and_current_only_gate_are_wired(tmp_path: Path) -> None:
    requirements = (ROOT / "requirements-stage25.txt").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    verify_all = (ROOT / "scripts/verify_all.py").read_text(encoding="utf-8")
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    backend = (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")

    assert "-r requirements-stage24.txt" in requirements
    assert 'ROOT / "requirements-stage25.txt"' in launcher
    assert '"requirements-stage25.txt"' in launcher
    assert_current_only_workflow(ROOT, workflow)
    assert "verify_stage25.py" in verify_all
    assert package["scripts"]["test:stage25"].endswith("Stage25PrintAcceptance.test.tsx")
    assert package["version"] == APP_VERSION == assert_current_versions(ROOT, 25)
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

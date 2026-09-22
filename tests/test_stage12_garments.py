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


def _json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


CANONICAL_EXTRA_MEASUREMENTS = {
    "neck_circumference": 380,
    "upper_arm_circumference": 300,
    "wrist_circumference": 160,
    "hand_circumference": 210,
    "sleeve_length": 580,
    "elbow_circumference": 260,
    "elbow_length": 330,
}

VARIANTS = {
    "skirt": {
        "preset": "woven_skirt_trial",
        "sleeve": {"type": "sleeveless", "length_mm": None},
        "closure": {"type": "zipper", "location": "center_back", "length_mm": 550},
        "finishing": {
            "neckline_facing": False, "armhole_facing": False, "waistband": True,
            "front_placket": False, "collar": False,
        },
        "ease": {"bust": 0, "waist": 20, "hips": 40, "upper_arm": 0},
    },
    "top": {
        "preset": "woven_top_trial",
        "sleeve": {"type": "sleeveless", "length_mm": None},
        "closure": {"type": "zipper", "location": "center_back", "length_mm": 550},
        "finishing": {
            "neckline_facing": True, "armhole_facing": True, "waistband": False,
            "front_placket": False, "collar": False,
        },
        "ease": {"bust": 50, "waist": 40, "hips": 50, "upper_arm": 0},
    },
    "blouse": {
        "preset": "woven_blouse_trial",
        "sleeve": {"type": "long", "length_mm": 580},
        "closure": {"type": "zipper", "location": "center_back", "length_mm": 550},
        "finishing": {
            "neckline_facing": True, "armhole_facing": False, "waistband": False,
            "front_placket": False, "collar": False,
        },
        "ease": {"bust": 80, "waist": 80, "hips": 80, "upper_arm": 60},
    },
    "shirt": {
        "preset": "woven_shirt_trial",
        "sleeve": {"type": "long", "length_mm": 580},
        "closure": {"type": "buttons", "location": "center_front", "length_mm": 550},
        "finishing": {
            "neckline_facing": False, "armhole_facing": False, "waistband": False,
            "front_placket": True, "collar": True,
        },
        "ease": {"bust": 100, "waist": 100, "hips": 100, "upper_arm": 70},
    },
    "vest": {
        "preset": "woven_vest_trial",
        "sleeve": {"type": "sleeveless", "length_mm": None},
        "closure": {"type": "buttons", "location": "center_front", "length_mm": 550},
        "finishing": {
            "neckline_facing": True, "armhole_facing": True, "waistband": False,
            "front_placket": True, "collar": False,
        },
        "ease": {"bust": 60, "waist": 50, "hips": 60, "upper_arm": 0},
    },
}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        log_level="CRITICAL",
    )), raise_server_exceptions=False)


def _project(garment_type: str) -> dict:
    project = _json("examples/v1/example-dress-project.json")
    project.update({
        "project_id": str(uuid4()), "revision": 1, "name": f"Этап 12 · {garment_type}",
        "status": "inputs_confirmed", "style_analysis_provider": None,
        "style_analysis": None,
    })
    project["body_measurements"]["profile_id"] = str(uuid4())
    project["garment_spec"]["garment_id"] = str(uuid4())
    project["fit_settings"]["settings_id"] = str(uuid4())
    project["fabric_properties"]["fabric_id"] = str(uuid4())
    for name, value in CANONICAL_EXTRA_MEASUREMENTS.items():
        project["body_measurements"]["values"][name] = {
            "value": value, "unit": "mm", "source": "user",
        }
    variant = VARIANTS[garment_type]
    parameters = project["garment_spec"]["parameters"]
    project["garment_spec"]["garment_type"] = garment_type
    parameters["sleeve"] = deepcopy(variant["sleeve"])
    parameters["closure"] = deepcopy(variant["closure"])
    parameters["finishing"] = deepcopy(variant["finishing"])
    parameters["upper"] = {"length_below_waist_mm": 100 if garment_type == "top" else 120}
    project["fit_settings"]["preset"]["id"] = variant["preset"]
    project["fit_settings"]["wearing_ease_mm"] = deepcopy(variant["ease"])
    if garment_type == "skirt":
        names = {"waist", "hips", "back_waist_arc", "back_hip_arc", "hip_depth"}
        project["body_measurements"]["values"] = {
            name: value for name, value in project["body_measurements"]["values"].items()
            if name in names
        }
        project["body_measurements"]["angles_deg"] = {
            "hip_inclination": project["body_measurements"]["angles_deg"]["hip_inclination"]
        }
    return project


def _request(project: dict) -> dict:
    request = {
        "schema_version": "1.0.0", "request_id": str(uuid4()),
        "project_id": project["project_id"], "input_hash": "0" * 64,
    }
    for name in (
        "pattern_method", "body_measurements", "garment_spec", "fit_settings",
        "fabric_properties",
    ):
        request[name] = deepcopy(project[name])
    request["input_hash"] = compute_input_hash(request)
    return request


def test_catalogue_and_measurement_scope_are_explicit(tmp_path: Path):
    reference = _json("references/stage12/garment-controls.json")
    with _client(tmp_path) as api:
        response = api.get("/api/v1/garments/catalog")
        assert response.status_code == 200
        items = {item["garment_type"]: item for item in response.json()["items"]}
        assert {"dress", "sundress", *VARIANTS} <= set(items)
        for item in items.values():
            assert item["formula_status"] == "implemented"
            assert item["reference_status"] == "automated_passed"
            assert item["invariant_status"] == "automated_passed"
            assert item["paper_status"] == item["expert_status"] == item["toile_status"] == "pending"
            assert item["production_allowed"] is False

        skirt = api.get(
            "/api/v1/measurements/catalog?garment_type=skirt&sleeve_type=sleeveless"
        ).json()
        required = [item["id"] for item in skirt["measurements"] if item["required"]]
        assert required == reference["garments"]["skirt"]["required_measurements"]
        assert "bust" not in {item["id"] for item in skirt["measurements"]}


def test_five_stage12_garments_match_automated_references(tmp_path: Path):
    reference = _json("references/stage12/garment-controls.json")["garments"]
    with _client(tmp_path) as api:
        for garment_type in VARIANTS:
            project = _project(garment_type)
            created = api.post("/api/v1/projects", json=project)
            assert created.status_code == 201, created.text
            response = api.post("/api/v1/patterns/generate", json=_request(project))
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["status"] == "succeeded"
            assert [item["id"] for item in result["pattern"]["pieces"]] == reference[garment_type]["piece_ids"]
            assert len(result["pattern"]["seam_pairs"]) == reference[garment_type]["seam_pair_count"]
            formula_check = next(
                item for item in result["validation_report"]["checks"]
                if item["id"] == "engine.pattern_blocks.formulas"
            )
            assert formula_check["measured_value"] == reference[garment_type]["formula_count"]
            assert result["validation_report"]["production_export_allowed"] is False
            assert "GARMENT_ACCEPTANCE_PENDING" in {
                item["code"] for item in result["validation_report"]["issues"]
            }


def test_unlisted_component_combination_fails_closed(tmp_path: Path):
    project = _project("shirt")
    project["garment_spec"]["parameters"]["finishing"]["collar"] = False
    with _client(tmp_path) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        response = api.post("/api/v1/patterns/generate", json=_request(project))
        assert response.status_code == 422
        assert any(
            issue["code"] == "GARMENT_VARIANT_NOT_IMPLEMENTED"
            for issue in response.json()["issues"]
        )


def test_stage12_contract_and_current_only_ci_are_wired(tmp_path: Path):
    launcher = (ROOT / "scripts/start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage12.txt"' in launcher
    current_stage = max(
        int(path.stem.removeprefix("verify_stage"))
        for path in (ROOT / "scripts").glob("verify_stage*.py")
    )
    assert f"python scripts/verify_stage{current_stage}.py" in workflow
    assert "verify_all.py" not in workflow
    assert "verify_stage11.py" not in workflow

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

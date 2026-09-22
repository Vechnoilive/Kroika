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


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(
        database_path=tmp_path / "kroika.db",
        image_storage_path=tmp_path / "images",
        log_level="CRITICAL",
    )), raise_server_exceptions=False)


def _project() -> dict:
    project = _json("examples/v1/example-dress-project.json")
    project.update({
        "project_id": str(uuid4()), "revision": 1,
        "name": "Этап 13 · лёгкий жакет", "status": "inputs_confirmed",
        "style_analysis_provider": None, "style_analysis": None,
        "pattern_method": {
            "id": "kroika-light-jacket", "version": "0.1.0",
            "validation_status": "experimental",
        },
    })
    project["body_measurements"]["profile_id"] = str(uuid4())
    project["garment_spec"]["garment_id"] = str(uuid4())
    project["fit_settings"]["settings_id"] = str(uuid4())
    project["fabric_properties"]["fabric_id"] = str(uuid4())
    for name, value in {
        "neck_circumference": 380,
        "upper_arm_circumference": 300,
        "wrist_circumference": 160,
        "hand_circumference": 210,
        "sleeve_length": 580,
        "elbow_circumference": 260,
        "elbow_length": 330,
        "front_diagonal_shoulder_height": 430,
        "back_diagonal_shoulder_height": 420,
    }.items():
        project["body_measurements"]["values"][name] = {
            "value": value, "unit": "mm", "source": "user",
        }
    parameters = project["garment_spec"]["parameters"]
    project["garment_spec"]["garment_type"] = "jacket"
    parameters.update({
        "bodice_fit": "semi_fitted",
        "shaping": "princess_seams",
        "sleeve": {"type": "long", "length_mm": 580},
        "upper": {"length_below_waist_mm": 240},
        "closure": {"type": "buttons", "location": "center_front", "length_mm": 450},
        "finishing": {
            "neckline_facing": False, "armhole_facing": False,
            "waistband": False, "front_placket": True, "collar": True,
            "front_facing": True, "lining": True, "pockets": True, "vent": True,
        },
        "jacket": {
            "variant": "light_single_breasted", "front_extension_mm": 35,
            "lapel_width_mm": 70, "roll_line_from_waist_mm": 180,
            "collar_stand_mm": 25, "collar_fall_mm": 55,
            "underlayer_allowance_mm": 10, "vent_length_mm": 180,
            "pocket_width_mm": 160, "pocket_depth_mm": 180,
            "button_count": 2, "pocket_type": "patch",
            "sleeve_construction": "one_piece", "lining": "full",
        },
    })
    project["fit_settings"]["preset"] = {
        "id": "woven_light_jacket_trial", "version": "0.1.0",
    }
    project["fit_settings"]["wearing_ease_mm"] = {
        "bust": 110, "waist": 130, "hips": 110, "upper_arm": 90,
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


def test_jacket_has_separate_method_ease_and_measurement_scope(tmp_path: Path):
    reference = _json("references/stage13/light-jacket-controls.json")
    with _client(tmp_path) as api:
        items = {item["garment_type"]: item for item in api.get("/api/v1/garments/catalog").json()["items"]}
        jacket = items["jacket"]
        assert jacket["paper_status"] == jacket["expert_status"] == jacket["toile_status"] == "pending"
        assert jacket["production_allowed"] is False

        catalog = api.get(
            "/api/v1/measurements/catalog?garment_type=jacket&sleeve_type=long"
        ).json()
        required = {item["id"] for item in catalog["measurements"] if item["required"]}
        assert {
            "bust", "waist", "hips", "neck_circumference", "armscye_depth",
            "front_diagonal_shoulder_height", "back_diagonal_shoulder_height",
            "upper_arm_circumference", "wrist_circumference", "hand_circumference",
            "sleeve_length", "elbow_circumference", "elbow_length",
        } <= required
        project = _project()
        assert project["pattern_method"] == {
            **reference["method"], "validation_status": "experimental",
        }
        assert project["fit_settings"]["wearing_ease_mm"] == reference["wearing_ease_mm"]


def test_light_jacket_builds_complete_paired_diagnostic_set(tmp_path: Path):
    reference = _json("references/stage13/light-jacket-controls.json")
    project = _project()
    with _client(tmp_path) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        response = api.post("/api/v1/patterns/generate", json=_request(project))
        assert response.status_code == 200, response.text
        result = response.json()
    assert result["status"] == "succeeded"
    assert tuple(map(int, result["engine_version"].split("."))) >= (0, 7, 0)
    assert [piece["id"] for piece in result["pattern"]["pieces"]] == reference["piece_ids"]
    assert len(result["pattern"]["seam_pairs"]) == reference["seam_pair_count"]
    assert all(piece["cutting_contour"] for piece in result["pattern"]["pieces"])
    assert result["pattern"]["print_layout"]["scale"] == 1

    pieces = {piece["id"]: piece for piece in result["pattern"]["pieces"]}
    front_paths = {path["id"] for path in pieces["jacket_front_center"]["internal_paths"]}
    front_segments = {
        segment["id"]
        for piece_id in ("jacket_front_center", "jacket_side_front")
        for segment in pieces[piece_id]["seam_contour"]["segments"]
    }
    back_paths = {path["id"] for path in pieces["back_bodice"]["internal_paths"]}
    assert {"jacket_roll_line", "jacket_button_line"} <= front_paths
    assert {"jacket_center_princess", "jacket_side_princess"} <= front_segments
    assert "back_center_vent" in back_paths
    pairs = {pair["id"] for pair in result["pattern"]["seam_pairs"]}
    assert {
        "jacket_princess_join", "jacket_front_sleeve_side_join",
        "jacket_front_sleeve_center_join", "jacket_back_sleeve_join",
        "jacket_front_collar_join", "jacket_back_collar_join",
        "jacket_front_edge_facing", "jacket_facing_lining",
        "jacket_lining_princess", "jacket_lining_front_sleeve_side",
        "jacket_lining_front_sleeve_center", "jacket_lining_back_sleeve",
    } <= pairs
    jacket_check = next(
        item for item in result["validation_report"]["checks"]
        if item["id"] == "engine.jacket.interfaces"
    )
    assert jacket_check["status"] == "passed"
    assert result["validation_report"]["production_export_allowed"] is False


def test_jacket_fails_closed_for_wrong_method_or_missing_lining(tmp_path: Path):
    for mutate in ("method", "lining"):
        project = _project()
        if mutate == "method":
            project["pattern_method"]["id"] = "kroika-gc-woven"
        else:
            project["garment_spec"]["parameters"]["finishing"]["lining"] = False
        with _client(tmp_path / mutate) as api:
            assert api.post("/api/v1/projects", json=project).status_code == 201
            response = api.post("/api/v1/patterns/generate", json=_request(project))
            assert response.status_code == 422
            assert response.json()["code"] == "SEMANTIC_VALIDATION_FAILED"
            assert {
                issue["code"] for issue in response.json()["issues"]
            } & {"METHOD_NOT_AVAILABLE", "GARMENT_VARIANT_NOT_IMPLEMENTED"}


def test_stage13_contract_and_current_only_ci_are_wired(tmp_path: Path):
    launcher = (ROOT / "scripts/start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage13.txt"' in launcher
    current_stage = max(
        int(path.stem.removeprefix("verify_stage"))
        for path in (ROOT / "scripts").glob("verify_stage*.py")
    )
    assert f"python scripts/verify_stage{current_stage}.py" in workflow
    assert "verify_all.py" not in workflow
    assert "verify_stage12.py" not in workflow

    spec, base_uri = read_from_filename(str(ROOT / "schemas/openapi.v1.yaml"))
    validate(spec, base_uri=base_uri)
    app = create_app(Settings(
        database_path=tmp_path / "contract.db",
        image_storage_path=tmp_path / "contract-images",
        log_level="CRITICAL",
    ))
    documented = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item if method in {"get", "post", "put", "patch", "delete"}
    }
    runtime = {
        (method, route.path)
        for route in app.routes for method in (route.methods or set())
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert runtime == documented

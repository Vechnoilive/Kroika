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


def _project(garment_type: str = "trousers") -> dict:
    project = _json("examples/v1/example-dress-project.json")
    project.update({
        "project_id": str(uuid4()), "revision": 1,
        "name": f"Этап 14 · {garment_type}", "status": "inputs_confirmed",
        "style_analysis_provider": None, "style_analysis": None,
        "pattern_method": {
            "id": "kroika-woven-trousers", "version": "0.1.0",
            "validation_status": "experimental",
        },
    })
    project["body_measurements"]["profile_id"] = str(uuid4())
    project["garment_spec"]["garment_id"] = str(uuid4())
    project["fit_settings"]["settings_id"] = str(uuid4())
    project["fabric_properties"]["fabric_id"] = str(uuid4())
    for name, value in {
        "sitting_height": 270, "crotch_length": 720,
        "outside_leg_length": 1040, "inseam_length": 780,
        "thigh_circumference": 590, "knee_circumference": 400,
        "trouser_hem_circumference": 380, "knee_height": 560,
    }.items():
        project["body_measurements"]["values"][name] = {
            "value": value, "unit": "mm", "source": "user",
        }
    parameters = project["garment_spec"]["parameters"]
    project["garment_spec"]["garment_type"] = garment_type
    trousers = garment_type == "trousers"
    parameters.update({
        "bodice_fit": "semi_fitted", "shaping": "darts",
        "sleeve": {"type": "sleeveless", "length_mm": None},
        "closure": {
            "type": "zipper", "location": "center_front",
            "length_mm": 180 if trousers else 150,
        },
        "finishing": {
            "neckline_facing": False, "armhole_facing": False,
            "waistband": True, "front_placket": False, "collar": False,
            "front_facing": False, "lining": False, "pockets": True,
            "vent": False, "fly_front": True,
        },
        "trousers": {
            "variant": "straight_trousers" if trousers else "tailored_shorts",
            "waist_position": "natural", "length_mm": 1000 if trousers else 500,
            "leg_shape": "straight", "rise_ease_mm": 20,
            "waistband_width_mm": 40, "fly_length_mm": 180 if trousers else 150,
            "pocket_opening_mm": 160, "pocket_type": "slash", "pleat_count": 0,
        },
    })
    project["fit_settings"]["preset"] = {
        "id": "woven_straight_trousers_trial" if trousers else "woven_tailored_shorts_trial",
        "version": "0.1.0",
    }
    project["fit_settings"]["wearing_ease_mm"] = {
        "bust": 0, "waist": 20, "hips": 50, "upper_arm": 0,
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


def test_lower_catalogue_measurements_and_jumpsuit_gate_are_explicit(tmp_path: Path):
    reference = _json("references/stage14/lower-garment-controls.json")
    with _client(tmp_path) as api:
        items = {
            item["garment_type"]: item
            for item in api.get("/api/v1/garments/catalog").json()["items"]
        }
        assert {"trousers", "shorts"} <= set(items)
        assert "jumpsuit" not in items
        assert all(items[k]["production_allowed"] is False for k in ("trousers", "shorts"))
        catalog = api.get(
            "/api/v1/measurements/catalog?garment_type=trousers&sleeve_type=sleeveless"
        ).json()
        required = {item["id"] for item in catalog["measurements"] if item["required"]}
        assert {
            "waist", "hips", "sitting_height", "crotch_length",
            "outside_leg_length", "inseam_length", "thigh_circumference",
            "knee_circumference", "trouser_hem_circumference", "knee_height",
        } <= required
    assert reference["jumpsuit_dependency"] == "blocked_until_upper_and_lower_toile_verified"


def test_trousers_and_shorts_build_complete_balanced_sets(tmp_path: Path):
    reference = _json("references/stage14/lower-garment-controls.json")
    for garment_type in ("trousers", "shorts"):
        project = _project(garment_type)
        with _client(tmp_path / garment_type) as api:
            assert api.post("/api/v1/projects", json=project).status_code == 201
            response = api.post("/api/v1/patterns/generate", json=_request(project))
            assert response.status_code == 200, response.text
            result = response.json()
        assert result["status"] == "succeeded"
        assert result["engine_version"] == "0.8.0"
        assert [piece["id"] for piece in result["pattern"]["pieces"]] == reference["piece_ids"]
        assert len(result["pattern"]["seam_pairs"]) == reference["seam_pair_count"]
        assert all(piece["cutting_contour"] for piece in result["pattern"]["pieces"])
        pieces = {piece["id"]: piece for piece in result["pattern"]["pieces"]}
        front_paths = {path["id"] for path in pieces["front_trouser"]["internal_paths"]}
        back_paths = {path["id"] for path in pieces["back_trouser"]["internal_paths"]}
        assert {"front_hip_line", "front_leg_balance", "front_crease_line",
                "front_waist_dart", "front_slash_pocket_opening", "front_fly_line"} <= front_paths
        assert {"back_hip_line", "back_leg_balance", "back_crease_line",
                "back_waist_dart"} <= back_paths
        pairs = {pair["id"] for pair in result["pattern"]["seam_pairs"]}
        assert {
            "trouser_side_upper_join", "trouser_side_lower_join",
            "trouser_inseam_upper_join", "trouser_inseam_lower_join",
            "trouser_front_crotch_join", "trouser_back_crotch_join",
            "trouser_front_waist_join", "trouser_back_waist_join",
            "trouser_pocket_join", "trouser_fly_facing_join",
        } <= pairs
        check = next(item for item in result["validation_report"]["checks"]
                     if item["id"] == "engine.trousers.balance")
        assert check["status"] == "passed"
        assert result["validation_report"]["production_export_allowed"] is False


def test_lower_module_fails_closed_for_wrong_method_variant_and_rise(tmp_path: Path):
    for mutation in ("method", "variant", "rise"):
        project = _project()
        if mutation == "method":
            project["pattern_method"]["id"] = "kroika-gc-woven"
        elif mutation == "variant":
            project["garment_spec"]["parameters"]["trousers"]["variant"] = "tailored_shorts"
        else:
            project["body_measurements"]["values"]["sitting_height"]["value"] = 400
        with _client(tmp_path / mutation) as api:
            assert api.post("/api/v1/projects", json=project).status_code == 201
            response = api.post("/api/v1/patterns/generate", json=_request(project))
        assert response.status_code in {200, 422}
        if mutation in {"method", "variant"}:
            assert response.status_code == 422
            assert response.json()["code"] == "SEMANTIC_VALIDATION_FAILED"
        else:
            assert response.json()["status"] == "rejected"
            assert any(
                issue["code"] == "TROUSER_RISE_MEASUREMENTS_CONFLICT"
                for issue in response.json()["validation_report"]["issues"]
            )


def test_stage14_contract_and_current_only_ci_are_wired(tmp_path: Path):
    launcher = (ROOT / "scripts/start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage14.txt"' in launcher
    assert "python scripts/verify_stage14.py" in workflow
    assert "verify_all.py" not in workflow
    assert "verify_stage13.py" not in workflow

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

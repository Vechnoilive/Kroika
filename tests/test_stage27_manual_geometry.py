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
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import APP_VERSION, create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _project() -> dict:
    project = _example("example-dress-project.json")
    project.update({
        "project_id": str(uuid4()),
        "revision": 1,
        "name": "Ручная геометрия",
        "created_at": "2026-09-24T07:00:00Z",
        "updated_at": "2026-09-24T07:00:00Z",
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


def _generated(api: TestClient) -> tuple[dict, dict]:
    project = _project()
    assert api.post("/api/v1/projects", json=project).status_code == 201
    response = api.post("/api/v1/patterns/generate", json=_request(project))
    assert response.status_code == 200, response.text
    return project, response.json()


def _safe_edit(generation: dict, distance: float = 1.0) -> dict:
    pattern = generation["pattern"]
    paired = {
        (str(pair[side]), str(segment_id))
        for pair in pattern["seam_pairs"]
        for side, segments in (
            ("first_piece_id", "first_segment_ids"),
            ("second_piece_id", "second_segment_ids"),
        )
        for segment_id in pair[segments]
    }
    for piece in pattern["pieces"]:
        folds = {
            item["segment_id"] for item in piece["edge_allowances"]
            if item["edge_type"] == "fold"
        }
        segments = piece["seam_contour"]["segments"]
        for index, segment in enumerate(segments):
            following = segments[(index + 1) % len(segments)]
            if (
                segment["id"] not in folds
                and following["id"] not in folds
                and (piece["id"], segment["id"]) not in paired
                and (piece["id"], following["id"]) not in paired
            ):
                return {
                    "piece_id": piece["id"],
                    "segment_id": segment["id"],
                    "handle": "end",
                    "x_mm": segment["end"][0] + distance,
                    "y_mm": segment["end"][1],
                }
    raise AssertionError("Reference generation has no safe manual vertex")


def test_manual_edit_creates_audited_immutable_generation(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        project, base = _generated(api)
        before_project = api.get(f"/api/v1/projects/{project['project_id']}").json()
        edit = _safe_edit(base)
        response = api.post(
            f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={"If-Match": str(before_project["revision"])},
            json={"note": "Уточнена линия после примерки макета", "edits": [edit]},
        )
        assert response.status_code == 200, response.text
        edited = response.json()
        assert edited["generation_id"] != base["generation_id"]
        assert edited["engine_version"] == "0.13.0"
        assert edited["pattern"]["manual_adjustments"]["base_generation_id"] == base[
            "generation_id"
        ]
        assert edited["pattern"]["manual_adjustments"]["edits"][0]["after"] == [
            edit["x_mm"], edit["y_mm"]
        ]
        assert edited["validation_report"]["production_export_allowed"] is False
        assert any(
            issue["code"] == "MANUAL_GEOMETRY_REVIEW_REQUIRED"
            for issue in edited["validation_report"]["issues"]
        )
        changed_piece = next(
            item for item in edited["pattern"]["pieces"] if item["id"] == edit["piece_id"]
        )
        assert changed_piece["cutting_contour"] is not None

        stored_base = api.get(
            f"/api/v1/patterns/{base['generation_id']}/validation"
        )
        assert stored_base.status_code == 200
        after_project = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert after_project["revision"] == before_project["revision"] + 1
        assert after_project["latest_generation"]["generation_id"] == edited["generation_id"]
        assert len(after_project["generation_history"]) == 2

        compared = api.get(
            f"/api/v1/projects/{project['project_id']}/generations/compare",
            params={
                "base_generation_id": base["generation_id"],
                "target_generation_id": edited["generation_id"],
            },
        )
        assert compared.status_code == 200, compared.text
        assert compared.json()["totals"]["changed_pieces"] >= 1


def test_editor_rejects_large_moves_and_protected_fold_edges(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        project, base = _generated(api)
        revision = api.get(f"/api/v1/projects/{project['project_id']}").json()["revision"]
        too_far = _safe_edit(base, distance=51)
        response = api.post(
            f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={"If-Match": str(revision)},
            json={"edits": [too_far]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "MANUAL_MOVE_TOO_LARGE"

        fold_edit = None
        for piece in base["pattern"]["pieces"]:
            fold_ids = {
                item["segment_id"] for item in piece["edge_allowances"]
                if item["edge_type"] == "fold"
            }
            if fold_ids:
                segment = next(
                    item for item in piece["seam_contour"]["segments"]
                    if item["id"] in fold_ids
                )
                fold_edit = {
                    "piece_id": piece["id"], "segment_id": segment["id"],
                    "handle": "end", "x_mm": segment["end"][0] + 1,
                    "y_mm": segment["end"][1],
                }
                break
        assert fold_edit is not None
        response = api.post(
            f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={"If-Match": str(revision)},
            json={"edits": [fold_edit]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "MANUAL_FOLD_EDGE_LOCKED"

        pair = base["pattern"]["seam_pairs"][0]
        piece = next(
            item for item in base["pattern"]["pieces"]
            if item["id"] == pair["first_piece_id"]
        )
        segment = next(
            item for item in piece["seam_contour"]["segments"]
            if item["id"] == pair["first_segment_ids"][0]
        )
        mismatch = {
            "piece_id": piece["id"], "segment_id": segment["id"], "handle": "end",
            "x_mm": segment["end"][0] + 3, "y_mm": segment["end"][1],
        }
        response = api.post(
            f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={"If-Match": str(revision)},
            json={"edits": [mismatch]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "MANUAL_SEAM_PAIR_MISMATCH"


def test_editor_blocks_stale_versions_and_missing_snapshots(tmp_path: Path) -> None:
    with _client(tmp_path) as api:
        project, base = _generated(api)
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        edit = _safe_edit(base)
        saved = api.post(
            f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={"If-Match": str(current["revision"])},
            json={"edits": [edit]},
        )
        assert saved.status_code == 200, saved.text
        latest_revision = api.get(
            f"/api/v1/projects/{project['project_id']}"
        ).json()["revision"]
        stale = api.post(
            f"/api/v1/patterns/{base['generation_id']}/manual-edit",
            headers={"If-Match": str(latest_revision)},
            json={"edits": [_safe_edit(base, distance=2)]},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "MANUAL_BASE_NOT_CURRENT"

        repository = api.app.state.repository
        with repository._connect() as connection:  # noqa: SLF001 - migration boundary test.
            connection.execute(
                "DELETE FROM generation_input_snapshots WHERE generation_id = ?",
                (saved.json()["generation_id"],),
            )
        no_snapshot = api.post(
            f"/api/v1/patterns/{saved.json()['generation_id']}/manual-edit",
            headers={"If-Match": str(latest_revision)},
            json={"edits": [_safe_edit(saved.json())]},
        )
        assert no_snapshot.status_code == 409
        assert no_snapshot.json()["code"] == "MANUAL_INPUT_SNAPSHOT_MISSING"


def test_stage27_openapi_version_and_gate_wiring(tmp_path: Path) -> None:
    specification, base_uri = read_from_filename(str(ROOT / "schemas" / "openapi.v1.yaml"))
    validate(specification, base_uri=base_uri)
    runtime_paths = set(create_app(Settings(
        database_path=tmp_path / "contract.db",
        image_storage_path=tmp_path / "contract-images",
        log_level="CRITICAL",
    )).openapi()["paths"])
    assert runtime_paths == set(specification["paths"])
    assert APP_VERSION == "0.27.0"
    assert "/api/v1/patterns/{generation_id}/manual-edit" in runtime_paths
    assert "test:stage27" in json.loads(
        (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )["scripts"]
    assert "verify_stage27.py" in (ROOT / "scripts" / "verify_all.py").read_text(
        encoding="utf-8"
    )

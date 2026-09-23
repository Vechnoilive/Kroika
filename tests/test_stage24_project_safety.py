from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def test_project_can_be_renamed_and_deleted_with_its_revision_history(tmp_path: Path) -> None:
    database = tmp_path / "kroika.db"
    settings = Settings(
        database_path=database,
        image_storage_path=tmp_path / "images",
        log_level="CRITICAL",
    )
    project = _example("example-dress-project.json")
    with TestClient(create_app(settings), raise_server_exceptions=False) as api:
        created = api.post("/api/v1/projects", json=project)
        assert created.status_code == 201, created.text

        renamed = created.json()
        renamed["name"] = "Новое название"
        response = api.put(
            f"/api/v1/projects/{project['project_id']}",
            headers={"If-Match": "1"},
            json=renamed,
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Новое название"
        assert response.json()["revision"] == 2
        assert api.get("/api/v1/projects").json()["items"][0]["name"] == "Новое название"

        removed = api.delete(f"/api/v1/projects/{project['project_id']}")
        assert removed.status_code == 204
        missing = api.get(f"/api/v1/projects/{project['project_id']}")
        assert missing.status_code == 404
        assert missing.json()["code"] == "PROJECT_NOT_FOUND"

    with sqlite3.connect(database) as connection:
        revisions = connection.execute(
            "SELECT COUNT(*) FROM project_revisions WHERE project_id = ?",
            (project["project_id"],),
        ).fetchone()[0]
    assert revisions == 0


def test_stage24_isolated_gate_is_wired() -> None:
    requirements = (ROOT / "requirements-stage24.txt").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    verify_all = (ROOT / "scripts" / "verify_all.py").read_text(encoding="utf-8")
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert "-r requirements-stage23.txt" in requirements
    assert 'ROOT / "requirements-stage24.txt"' in launcher
    assert '"requirements-stage24.txt"' in launcher
    assert "python scripts/verify_stage24.py" in workflow
    assert "verify_stage24.py" in verify_all
    assert "test:stage24" in package["scripts"]
    assert package["version"] == "0.24.0"

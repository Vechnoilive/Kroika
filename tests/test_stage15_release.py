from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.backup import (  # noqa: E402
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.repository import SQLiteRepository  # noqa: E402
from kroika_pattern_engine import (  # noqa: E402
    GeometryPatternEngine,
    garment_acceptance,
    release_gate,
    render_pattern_pdf,
    render_pattern_svg,
)
from kroika_pattern_engine.garment_catalogue import GARMENT_CATALOGUE  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_path": tmp_path / "data" / "kroika.db",
        "image_storage_path": tmp_path / "data" / "images",
        "log_level": "CRITICAL",
    }
    values.update(overrides)
    return Settings(**values)


def test_release_gate_is_derived_and_requires_every_physical_gate(monkeypatch):
    current = release_gate()
    assert current["stage"] == 15
    assert current["status"] == "blocked"
    assert current["production_ready"] is False
    assert current["ready_garments"] == []
    assert len(current["blocked_garments"]) == len(GARMENT_CATALOGUE) == 10
    assert all(
        set(item["missing_gates"]) == {"paper", "expert", "toile"}
        for item in current["blocked_garments"]
    )

    accepted = deepcopy(GARMENT_CATALOGUE["dress"])
    accepted.update(
        paper_status="passed", expert_status="passed", toile_status="passed",
        production_allowed=False,
    )
    monkeypatch.setitem(GARMENT_CATALOGUE, "dress", accepted)
    assert garment_acceptance("dress")["production_allowed"] is True
    accepted["toile_status"] = "pending"
    monkeypatch.setitem(GARMENT_CATALOGUE, "dress", accepted)
    assert garment_acceptance("dress")["production_allowed"] is False


def test_release_api_security_headers_and_disabled_provider_are_fail_closed(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/release/status")
        assert response.status_code == 200
        assert response.json()["production_ready"] is False
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "camera=()" in response.headers["permissions-policy"]

        disabled = client.post(
            "/api/v1/garments/analyze-image?provider=gemini",
            json=_example("example-ai-request.json"),
        )
        assert disabled.status_code == 503
        assert disabled.json()["code"] == "PROVIDER_UNAVAILABLE"


def test_private_data_can_be_deleted_without_leaving_orphan_images(tmp_path: Path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    image_bytes = (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
    with TestClient(app, raise_server_exceptions=False) as client:
        uploaded = client.post("/api/v1/images", json={
            "file_name": "sketch.png",
            "media_type": "image/png",
            "data_base64": base64.b64encode(image_bytes).decode("ascii"),
        })
        assert uploaded.status_code == 201, uploaded.text
        image_ref = uploaded.json()["image_ref"]
        image_path = settings.image_storage_path / f"{image_ref}.png"
        assert image_path.is_file()

        project = _example("example-dress-project.json")
        project["image_refs"] = [image_ref]
        assert client.post("/api/v1/projects", json=project).status_code == 201
        assert client.delete(f"/api/v1/images/{image_ref}").status_code == 409

        without_image = deepcopy(project)
        without_image["image_refs"] = []
        replaced = client.put(
            f"/api/v1/projects/{project['project_id']}",
            headers={"If-Match": "1"},
            json=without_image,
        )
        assert replaced.status_code == 200, replaced.text
        assert client.delete(f"/api/v1/images/{image_ref}").status_code == 409
        assert client.delete(f"/api/v1/projects/{project['project_id']}").status_code == 204
        assert not image_path.exists()
        assert client.get(f"/api/v1/projects/{project['project_id']}").status_code == 404

        profile = project["body_measurements"]
        assert client.post("/api/v1/measurement-profiles", json=profile).status_code == 201
        assert client.delete(
            f"/api/v1/measurement-profiles/{profile['profile_id']}"
        ).status_code == 204
        assert client.get(
            f"/api/v1/measurement-profiles/{profile['profile_id']}"
        ).status_code == 404


def test_backup_round_trip_checksums_database_and_images(tmp_path: Path):
    database = tmp_path / "source" / "kroika.db"
    images = tmp_path / "source" / "images"
    repository = SQLiteRepository(database)
    repository.initialize()
    project = _example("example-dress-project.json")
    repository.create_project(project)
    images.mkdir(parents=True)
    image = images / ("img_" + "a" * 32 + ".jpg")
    image.write_bytes(b"\xff\xd8\xffbackup-image")

    backup = tmp_path / "backup-001"
    manifest = create_backup(database, images, backup)
    assert manifest == verify_backup(backup)
    assert {item["path"] for item in manifest["files"]} == {
        "kroika.db", f"images/{image.name}",
    }

    restored_database = tmp_path / "restored" / "kroika.db"
    restored_images = tmp_path / "restored" / "images"
    restore_backup(backup, restored_database, restored_images)
    restored = SQLiteRepository(restored_database)
    restored.initialize()
    assert restored.get_project(project["project_id"]) == project
    assert (restored_images / image.name).read_bytes() == image.read_bytes()

    (backup / "kroika.db").write_bytes(b"tampered")
    with pytest.raises(BackupError, match="Контрольная сумма"):
        verify_backup(backup)


def test_restore_refuses_overwrite_without_explicit_permission(tmp_path: Path):
    source_database = tmp_path / "source" / "kroika.db"
    source_images = tmp_path / "source" / "images"
    SQLiteRepository(source_database).initialize()
    backup = tmp_path / "backup"
    create_backup(source_database, source_images, backup)

    target_database = tmp_path / "target" / "kroika.db"
    target_images = tmp_path / "target" / "images"
    SQLiteRepository(target_database).initialize()
    with pytest.raises(BackupError, match="не пусто"):
        restore_backup(backup, target_database, target_images)


def test_database_refuses_unknown_future_schema(tmp_path: Path):
    database = tmp_path / "future.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="более новой версией"):
        SQLiteRepository(database).initialize()


def test_production_container_excludes_release_audit_tooling():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    runtime = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")
    assert "-r requirements-runtime.txt" in dockerfile
    assert "requirements-stage15.txt" not in dockerfile
    assert "-r requirements-stage14.txt" in runtime
    assert "Pillow==12.3.0" in runtime


def test_reference_generation_svg_and_pdf_stay_inside_release_budgets():
    request = _example("example-engine-request.json")
    started = perf_counter()
    result = GeometryPatternEngine().generate(request)
    generation_seconds = perf_counter() - started
    assert result["status"] == "succeeded"
    assert generation_seconds < 15.0

    started = perf_counter()
    svg = render_pattern_svg(result["pattern"])
    svg_seconds = perf_counter() - started
    ElementTree.fromstring(svg)
    assert svg_seconds < 3.0

    started = perf_counter()
    pdf = render_pattern_pdf(result["pattern"])
    pdf_seconds = perf_counter() - started
    reader = PdfReader(BytesIO(pdf.content))
    assert len(reader.pages) == pdf.page_count
    assert pdf_seconds < 5.0

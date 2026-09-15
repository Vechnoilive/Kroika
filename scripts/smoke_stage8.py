#!/usr/bin/env python3
"""Exercise the stage-8 garment generator through the real HTTP boundary."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.contract_io import validate_document  # noqa: E402


def load_example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


with TemporaryDirectory(prefix="kroika-stage8-") as directory:
    app = create_app(
        Settings(database_path=Path(directory) / "smoke.db", log_level="CRITICAL")
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        project = load_example("example-dress-project.json")
        assert client.post("/api/v1/projects", json=project).status_code == 201
        response = client.post(
            "/api/v1/patterns/generate",
            json=load_example("example-engine-request.json"),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        validate_document("pattern-engine-result", result)
        assert result["status"] == "succeeded"
        assert len(result["pattern"]["pieces"]) == 6
        assert len(result["pattern"]["seam_pairs"]) == 10
        preview = client.get(
            f"/api/v1/patterns/{result['generation_id']}/preview.svg"
        )
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"].startswith("image/svg+xml")
        assert preview.headers["x-content-type-options"] == "nosniff"
        ElementTree.fromstring(preview.text)
        blocked = client.post(
            f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf"
        )
        assert blocked.status_code == 409
        saved = client.get(f"/api/v1/projects/{project['project_id']}").json()
        assert saved["status"] == "generated"
        assert client.get("/health/ready").json()["pattern_engine"] == (
            "kroika-geometry:0.4.0"
        )

print("Smoke-test этапа 8 пройден: изделие, швы, SVG и блокировка PDF работают.")

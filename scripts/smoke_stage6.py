#!/usr/bin/env python3
"""Exercise the geometry diagnostic through the real FastAPI boundary."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

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


with TemporaryDirectory(prefix="kroika-stage6-") as directory:
    app = create_app(
        Settings(database_path=Path(directory) / "smoke.db", log_level="CRITICAL")
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        project = load_example("example-dress-project.json")
        assert client.post("/api/v1/projects", json=project).status_code == 201
        response = client.post(
            "/api/v1/patterns/generate", json=load_example("example-engine-request.json")
        )
        assert response.status_code == 200, response.text
        result = response.json()
        validate_document("pattern-engine-result", result)
        assert result["status"] == "succeeded"
        assert result["pattern"] is not None
        assert "EXPERT_BLOCK_REVIEW_REQUIRED" in {
            issue["code"] for issue in result["validation_report"]["issues"]
        }
        assert result["validation_report"]["checks"][0]["status"] == "passed"
        engine = app.state.pattern_engine
        assert client.get("/health/ready").json()["pattern_engine"] == (
            f"{engine.engine_id}:{engine.engine_version}"
        )

print("Smoke-test этапа 6 пройден: API повторно проверяет ядро внутри собранного изделия.")

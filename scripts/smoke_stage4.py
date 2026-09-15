#!/usr/bin/env python3
"""In-process smoke test for a clean stage-4 application."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
                str(ROOT / "backend" / "src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def main() -> int:
    with TemporaryDirectory(prefix="kroika-smoke-") as directory:
        app = create_app(Settings(database_path=Path(directory) / "kroika.db"))
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.get("/health/live").status_code == 200
            ready = client.get("/health/ready")
            assert ready.status_code == 200 and ready.json()["database"] == "ok"

            project = _example("example-dress-project.json")
            created = client.post("/api/v1/projects", json=project)
            assert created.status_code == 201, created.text
            assert client.get(f"/api/v1/projects/{project['project_id']}").status_code == 200

            ai_request = _example("example-ai-request.json")
            analysis = client.post("/api/v1/garments/analyze-image", json=ai_request)
            assert analysis.status_code == 200, analysis.text
            assert analysis.json()["status"] == "needs_confirmation"

            engine_request = _example("example-engine-request.json")
            first = client.post("/api/v1/patterns/generate", json=engine_request)
            second = client.post("/api/v1/patterns/generate", json=deepcopy(engine_request))
            assert first.status_code == 200, first.text
            assert first.json() == second.json()
            assert first.json()["status"] == "succeeded"
            generation_id = first.json()["generation_id"]
            assert client.get(f"/api/v1/patterns/{generation_id}/validation").status_code == 200
            assert client.get(f"/api/v1/patterns/{generation_id}/preview.svg").status_code == 200
            assert client.post(f"/api/v1/patterns/{generation_id}/export/a4-pdf").status_code == 409

    print("Smoke-test этапа 4 пройден: health, SQLite, mock, проекты и движок работают.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Exercise provider discovery, local upload, failure and offline fallback over HTTP."""

from __future__ import annotations

import base64
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


with TemporaryDirectory(prefix="kroika-stage10-") as directory:
    root = Path(directory)
    app = create_app(Settings(
        database_path=root / "smoke.db",
        image_storage_path=root / "images",
        ai_provider="qwen",
        log_level="CRITICAL",
    ))
    with TestClient(app, raise_server_exceptions=False) as client:
        status = client.get("/api/v1/ai/providers")
        assert status.status_code == 200, status.text
        assert len(status.json()["items"]) == 3
        png = (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
        upload = client.post("/api/v1/images", json={
            "file_name": "garment.png", "media_type": "image/png",
            "data_base64": base64.b64encode(png).decode(),
        })
        assert upload.status_code == 201, upload.text
        request = json.loads((ROOT / "examples/v1/example-ai-request.json").read_text())
        request["image_refs"] = [upload.json()["image_ref"]]
        external = client.post("/api/v1/garments/analyze-image?provider=qwen", json=request)
        assert external.status_code == 503, external.text
        offline = client.post("/api/v1/garments/analyze-image?provider=mock", json=request)
        assert offline.status_code == 200, offline.text
        assert offline.json()["targeted_questions"]

print("Smoke-test этапа 10 пройден: выбор, загрузка, честный отказ и mock fallback работают.")

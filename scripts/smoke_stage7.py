#!/usr/bin/env python3
"""Exercise stage-7 blocks through pure geometry and the real FastAPI boundary."""

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
from kroika_pattern_engine.blocks import build_base_blocks  # noqa: E402


def load_example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


request = load_example("example-engine-request.json")
blocks = build_base_blocks(request)
validate_document("pattern-data", blocks.to_pattern_data())
assert len(blocks.pieces) == 4
assert max(
    abs(value)
    for name, value in blocks.controls.items()
    if name.endswith("_residual_mm") and name != "skirt_side_length_residual_mm"
) < 0.001

with TemporaryDirectory(prefix="kroika-stage7-") as directory:
    app = create_app(
        Settings(database_path=Path(directory) / "smoke.db", log_level="CRITICAL")
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        project = load_example("example-dress-project.json")
        assert client.post("/api/v1/projects", json=project).status_code == 201
        response = client.post("/api/v1/patterns/generate", json=request)
        assert response.status_code == 200, response.text
        result = response.json()
        validate_document("pattern-engine-result", result)
        assert result["status"] == "succeeded"
        assert result["pattern"] is not None
        codes = {item["code"] for item in result["validation_report"]["issues"]}
        assert "EXPERT_BLOCK_REVIEW_REQUIRED" in codes
        checks = {item["id"]: item for item in result["validation_report"]["checks"]}
        assert checks["engine.pattern_blocks.geometry"]["status"] == "passed"
        assert client.get("/health/ready").json()["pattern_engine"] == (
            "kroika-geometry:0.5.0"
        )

print("Smoke-test этапа 7 пройден: базовые блоки валидны и используются сборкой этапа 8.")

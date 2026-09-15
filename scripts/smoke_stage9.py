#!/usr/bin/env python3
"""Exercise stage-9 generation and both diagnostic print exports over HTTP."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"), str(ROOT / "backend" / "src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_contracts.contract_io import validate_document  # noqa: E402


def example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


with TemporaryDirectory(prefix="kroika-stage9-") as directory:
    app = create_app(Settings(database_path=Path(directory) / "smoke.db", log_level="CRITICAL"))
    with TestClient(app, raise_server_exceptions=False) as client:
        project = example("example-dress-project.json")
        assert client.post("/api/v1/projects", json=project).status_code == 201
        generated = client.post("/api/v1/patterns/generate", json=example("example-engine-request.json"))
        assert generated.status_code == 200, generated.text
        result = generated.json()
        validate_document("pattern-engine-result", result)
        assert result["status"] == "succeeded"
        assert result["validation_report"]["production_export_allowed"] is False

        preview = client.get(f"/api/v1/patterns/{result['generation_id']}/preview.svg")
        assert preview.status_code == 200, preview.text
        ElementTree.fromstring(preview.text)
        assert 'class="cutting"' in preview.text

        printable_svg = client.get(f"/api/v1/patterns/{result['generation_id']}/export/print.svg")
        assert printable_svg.status_code == 200, printable_svg.text
        assert printable_svg.headers["x-kroika-export-mode"] == "diagnostic"
        assert printable_svg.headers["x-kroika-production-ready"] == "false"
        assert "attachment" in printable_svg.headers["content-disposition"]

        pdf = client.post(f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf")
        assert pdf.status_code == 200, pdf.text
        assert pdf.content.startswith(b"%PDF")
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.headers["x-kroika-export-mode"] == "diagnostic"
        assert pdf.headers["x-kroika-production-ready"] == "false"
        reader = PdfReader(BytesIO(pdf.content))
        assert len(reader.pages) == int(pdf.headers["x-kroika-sheet-count"]) + 1
        assert "50 x 50 mm" in reader.pages[0].extract_text()

        saved = client.get(f"/api/v1/projects/{project['project_id']}").json()
        assert saved["status"] == "generated"
        assert client.get("/health/ready").json()["pattern_engine"] == "kroika-geometry:0.5.0"

print("Smoke-test этапа 9 пройден: линии среза, SVG и диагностический PDF A4 1:1 работают.")

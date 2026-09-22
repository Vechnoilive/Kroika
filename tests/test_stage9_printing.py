from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import math
from pathlib import Path
import sqlite3
import sys
from xml.etree import ElementTree

from openapi_spec_validator import validate as validate_openapi
from openapi_spec_validator.readers import read_from_filename
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.semantic import validate_validation_report  # noqa: E402
from kroika_backend.repository import SQLiteRepository  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_pdf, render_pattern_svg  # noqa: E402
from kroika_pattern_engine.allowances import edge_type_for_segment  # noqa: E402
from kroika_pattern_engine.geometry import contour_from_data, validate_simple_contour  # noqa: E402
from kroika_pattern_engine.print_layout import layout_pattern, make_tile_plan  # noqa: E402


def _request() -> dict:
    return json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(encoding="utf-8")
    )


def _result() -> dict:
    fixed = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    return GeometryPatternEngine(clock=lambda: fixed).generate(_request())


def test_stage9_builds_audited_allowances_cutting_contours_and_matching_notches():
    request = _request()
    result = _result()
    validate_document("pattern-engine-result", result)
    validate_validation_report(result["validation_report"])
    assert result["status"] == "succeeded"
    assert result["engine_version"] == GeometryPatternEngine.engine_version
    assert result["validation_report"]["diagnostic_export_allowed"] is True
    assert result["validation_report"]["production_export_allowed"] is False
    assert "PHYSICAL_PRINT_TEST_REQUIRED" in {
        issue["code"] for issue in result["validation_report"]["issues"]
    }

    pattern = result["pattern"]
    assert pattern["print_layout"] == {
        "page_format": "A4",
        "page_width_mm": 210,
        "page_height_mm": 297,
        "margin_mm": 10,
        "overlap_mm": 10,
        "scale": 1,
        "control_square_mm": 50,
    }
    configured = request["fit_settings"]["seam_allowances_mm"]
    pieces = {piece["id"]: piece for piece in pattern["pieces"]}
    for piece in pieces.values():
        seam = contour_from_data(piece["seam_contour"])
        cutting = contour_from_data(piece["cutting_contour"])
        validate_simple_contour(seam)
        validate_simple_contour(cutting, flatness_mm=0.05)
        assert cutting.area_mm2 > seam.area_mm2
        assert all(math.isfinite(value) for segment in cutting.segments for value in (
            segment.start.x_mm,
            segment.start.y_mm,
            segment.end.x_mm,
            segment.end.y_mm,
        ))
        allowances = {item["segment_id"]: item for item in piece["edge_allowances"]}
        assert set(allowances) == {segment.id for segment in seam.segments}
        for segment in seam.segments:
            edge_type = edge_type_for_segment(piece, segment.id)
            assert allowances[segment.id] == {
                "segment_id": segment.id,
                "edge_type": edge_type,
                "allowance_mm": configured[edge_type],
            }
        if piece["cut_on_fold"]:
            assert any(
                item["edge_type"] == "fold" and item["allowance_mm"] == 0
                for item in piece["edge_allowances"]
            )
        assert piece["grainline"]["start"] != piece["grainline"]["end"]
        assert piece["annotations"]

    for pair in pattern["seam_pairs"]:
        matches = [
            (piece["id"], notch)
            for piece in pieces.values()
            for notch in piece["notches"]
            if notch["match_id"] == pair["id"]
        ]
        assert {piece_id for piece_id, _ in matches} == {
            pair["first_piece_id"],
            pair["second_piece_id"],
        }
        assert len(matches) == 2
        for piece_id, notch in matches:
            source = next(
                segment
                for segment in pieces[piece_id]["seam_contour"]["segments"]
                if segment["id"] == notch["segment_id"]
            )
            from kroika_pattern_engine.geometry import curve_from_data

            assert 0 < notch["distance_from_start_mm"] < curve_from_data(source).length_mm


def test_svg_is_one_safe_unified_millimetre_sheet_with_all_print_marks():
    svg = render_pattern_svg(_result()["pattern"])
    root = ElementTree.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["width"].endswith("mm")
    assert root.attrib["height"].endswith("mm")
    assert svg.count('class="cutting"') == 6
    assert svg.count('class="seam"') == 6
    assert 'id="control-square-50mm"' in svg
    assert 'width="50" height="50"' in svg
    assert 'class="fold"' in svg
    assert 'class="grain"' in svg
    assert 'class="notch"' in svg
    assert "ЭКСПЕРИМЕНТАЛЬНО" in svg
    assert "<script" not in svg.lower()
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in svg


def test_pdf_has_a4_map_exact_scale_tiles_overlap_and_cyrillic_text():
    pattern = _result()["pattern"]
    rendered = render_pattern_pdf(pattern)
    reader = PdfReader(BytesIO(rendered.content))
    assert rendered.content.startswith(b"%PDF")
    assert reader.is_encrypted is False
    assert len(reader.pages) == rendered.page_count == rendered.tile_count + 1
    assert rendered.columns >= 1 and rendered.rows >= 1
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.2756) < 0.02
        assert abs(float(page.mediabox.height) - 841.8898) < 0.02
    map_text = reader.pages[0].extract_text()
    assert "50 x 50 mm" in map_text
    assert "Actual size / 100%" in map_text
    assert "не раскраивайте ткань" in map_text
    assert "A1" in map_text
    tile_text = reader.pages[1].extract_text()
    assert "лист A1" in tile_text
    assert "ЭКСПЕРИМЕНТАЛЬНО" in tile_text

    layout = layout_pattern(pattern)
    plan = make_tile_plan(layout, pattern["print_layout"])
    assert plan.printable_width_mm - plan.stride_x_mm == plan.overlap_mm == 10
    assert plan.printable_height_mm - plan.stride_y_mm == plan.overlap_mm == 10
    assert plan.tiles[-1].origin_x_mm + plan.printable_width_mm >= layout.width_mm
    assert plan.tiles[-1].origin_y_mm + plan.printable_height_mm >= layout.height_mm


def test_missing_by_edge_allowances_fail_closed_without_production_export():
    request = deepcopy(_request())
    request["fit_settings"]["seam_allowance_mode"] = "none"
    result = GeometryPatternEngine().generate(request)
    assert result["status"] == "rejected"
    assert result["pattern"] is None
    assert result["validation_report"]["production_export_allowed"] is False
    assert result["validation_report"]["issues"][0]["code"] == "SEAM_ALLOWANCE_MODE_REQUIRED"


def test_stage9_runtime_contract_remains_wired():
    requirements = (ROOT / "requirements-stage9.txt").read_text(encoding="utf-8")
    current_requirements = (ROOT / "requirements-stage10.txt").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    current_stage = max(
        int(path.stem.removeprefix("verify_stage"))
        for path in (ROOT / "scripts").glob("verify_stage*.py")
    )
    assert "reportlab==4.4.9" in requirements
    assert "pypdf==6.19.0" in requirements
    assert '"requirements-stage9.txt"' in launcher
    assert "-r requirements-stage9.txt" in current_requirements
    assert "fonts-dejavu-core" in dockerfile
    assert f"python scripts/verify_stage{current_stage}.py" in workflow
    assert "verify_all.py" not in workflow
    spec, base_uri = read_from_filename(str(ROOT / "schemas" / "openapi.v1.yaml"))
    validate_openapi(spec, base_uri=base_uri)
    operations = [
        operation["operationId"]
        for path in spec["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operations) == len(set(operations))


def test_old_generation_cache_is_migrated_and_new_engine_result_can_coexist(tmp_path: Path):
    database = tmp_path / "legacy.db"
    project = json.loads(
        (ROOT / "examples" / "v1" / "example-dress-project.json").read_text(encoding="utf-8")
    )
    legacy = json.loads(
        (ROOT / "examples" / "v1" / "example-engine-result.json").read_text(encoding="utf-8")
    )
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE generations (
                generation_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (project_id, input_hash)
            );
        """)
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?)",
            (project["project_id"], project["revision"], json.dumps(project), project["updated_at"]),
        )
        connection.execute(
            "INSERT INTO generations VALUES (?, ?, ?, ?, ?)",
            (
                legacy["generation_id"],
                legacy["project_id"],
                legacy["input_hash"],
                json.dumps(legacy),
                legacy["created_at"],
            ),
        )
    repository = SQLiteRepository(database)
    repository.initialize()
    assert repository.get_generation_by_hash(
        legacy["project_id"], legacy["input_hash"], legacy["engine_version"]
    ) == legacy
    assert repository.get_generation_by_hash(
        legacy["project_id"], legacy["input_hash"], GeometryPatternEngine.engine_version
    ) is None
    current = _result()
    repository.record_generation(current)
    assert repository.get_generation_by_hash(
        current["project_id"], current["input_hash"], GeometryPatternEngine.engine_version
    )["generation_id"] == current["generation_id"]

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402
from kroika_contracts.semantic import (  # noqa: E402
    SemanticContractError,
    validate_engine_request,
    validate_validation_report,
)
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg  # noqa: E402
from kroika_pattern_engine.geometry import (  # noqa: E402
    Point,
    contour_from_data,
    curve_from_data,
    validate_simple_contour,
)


def load_request() -> dict:
    return json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(
            encoding="utf-8"
        )
    )


def variant_request(garment_type: str, fit: str) -> dict:
    request = load_request()
    request["garment_spec"]["garment_type"] = garment_type
    request["garment_spec"]["parameters"]["bodice_fit"] = fit
    request["fit_settings"]["preset"]["id"] = f"woven_{fit}_trial"
    if fit == "fitted":
        request["fit_settings"]["wearing_ease_mm"].update(
            {"bust": 40, "waist": 20, "hips": 40}
        )
    request["input_hash"] = compute_input_hash(request)
    return request


@pytest.mark.parametrize("garment_type", ["dress", "sundress"])
@pytest.mark.parametrize("fit", ["fitted", "semi_fitted"])
def test_supported_variant_matrix_builds_valid_complete_geometry(
    garment_type: str, fit: str
):
    request = variant_request(garment_type, fit)
    validate_engine_request(request)
    fixed = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    result = GeometryPatternEngine(clock=lambda: fixed).generate(request)

    validate_document("pattern-engine-result", result)
    validate_validation_report(result["validation_report"])
    assert result["engine_version"] == GeometryPatternEngine.engine_version
    assert result["status"] == "succeeded"
    assert result["validation_report"]["status"] == "warnings"
    assert result["validation_report"]["diagnostic_export_allowed"] is True
    assert result["validation_report"]["production_export_allowed"] is False
    ease_check = next(
        check
        for check in result["validation_report"]["checks"]
        if check["id"] == "engine.garment_assembly.ease"
    )
    assert ease_check["status"] == "passed"
    assert ease_check["measured_value"] <= ease_check["limit_value"] == 5.0

    pattern = result["pattern"]
    assert pattern is not None
    assert len(pattern["pieces"]) == 6
    assert len(pattern["seam_pairs"]) == 10
    assert {piece["id"] for piece in pattern["pieces"]} == {
        "front_bodice",
        "back_bodice",
        "front_skirt",
        "back_skirt",
        "front_facing",
        "back_facing",
    }
    for piece in pattern["pieces"]:
        validate_simple_contour(contour_from_data(piece["seam_contour"]))
        validate_simple_contour(contour_from_data(piece["cutting_contour"]))
        assert piece["grainline"]["start"] != piece["grainline"]["end"]
        assert piece["annotations"]

    pieces = {piece["id"]: piece for piece in pattern["pieces"]}
    for pair in pattern["seam_pairs"]:
        first_segments = {
            segment["id"]: segment
            for segment in pieces[pair["first_piece_id"]]["seam_contour"]["segments"]
        }
        second_segments = {
            segment["id"]: segment
            for segment in pieces[pair["second_piece_id"]]["seam_contour"]["segments"]
        }
        first = sum(
            curve_from_data(first_segments[segment_id]).length_mm
            for segment_id in pair["first_segment_ids"]
        )
        second = sum(
            curve_from_data(second_segments[segment_id]).length_mm
            for segment_id in pair["second_segment_ids"]
        )
        first -= pair["first_length_reduction_mm"]
        second -= pair["second_length_reduction_mm"]
        residual = abs(abs(first - second) - pair["allowed_ease_mm"])
        assert residual <= pair["tolerance_mm"]
        assert pair["allowed_ease_mm"] <= 5.0

    front_bodice = pieces["front_bodice"]
    front_side = curve_from_data(next(
        segment
        for segment in front_bodice["seam_contour"]["segments"]
        if segment["id"] == "front_side"
    ))
    side_dart = next(
        path for path in front_bodice["internal_paths"] if path["id"] == "front_side_dart"
    )
    dart_legs = [curve_from_data(segment) for segment in side_dart["segments"]]
    assert abs(dart_legs[0].length_mm - dart_legs[1].length_mm) <= 1e-6
    assert front_side.point_at(0.0).y_mm < side_dart["segments"][0]["start"][1]
    for dart_point in (
        side_dart["segments"][0]["start"],
        side_dart["segments"][-1]["end"],
    ):
        lower_t, upper_t = 0.0, 1.0
        for _ in range(64):
            middle_t = (lower_t + upper_t) / 2.0
            if front_side.point_at(middle_t).y_mm < dart_point[1]:
                lower_t = middle_t
            else:
                upper_t = middle_t
        assert front_side.point_at((lower_t + upper_t) / 2.0).distance_to(
            Point(*dart_point)
        ) <= 1e-6

    svg = render_pattern_svg(pattern)
    root = ElementTree.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["role"] == "img"
    assert svg.count('class="cutting"') == 6
    assert svg.count('class="seam"') == 6
    assert "50 × 50 мм" in svg
    assert "<script" not in svg.lower()


def test_svg_escapes_annotation_and_labels():
    result = GeometryPatternEngine().generate(variant_request("dress", "semi_fitted"))
    pattern = deepcopy(result["pattern"])
    pattern["pieces"][0]["name_ru"] = '<script>alert("x")</script>'
    svg = render_pattern_svg(pattern)
    ElementTree.fromstring(svg)
    assert "<script" not in svg.lower()
    assert "&lt;script&gt;" in svg


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("garment_spec", "parameters", "neckline", "type"), "v"),
        (("garment_spec", "parameters", "sleeve"), {"type": "long", "length_mm": 600}),
        (("garment_spec", "parameters", "skirt", "type"), "straight"),
        (("fit_settings", "preset", "id"), "wrong_preset"),
    ],
)
def test_unsupported_combinations_are_blocked_before_geometry(path, value):
    request = variant_request("dress", "semi_fitted")
    target = request
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as caught:
        validate_engine_request(request)
    assert "GARMENT_VARIANT_NOT_IMPLEMENTED" in {
        issue.code for issue in caught.value.issues
    }


def test_stage8_bootstrap_and_documentation_are_wired():
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-stage8.txt").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify_all.py").read_text(encoding="utf-8")
    documentation = (ROOT / "docs" / "GARMENT_GENERATOR.md").read_text(encoding="utf-8")
    assert '"requirements-stage8.txt"' in launcher
    assert "-r requirements-runtime.txt" in dockerfile
    assert "-r requirements-stage7.txt" in requirements
    assert "verify_stage8.py" in verifier
    for term in ("10", "SVG", "сарафан", "production_export_allowed=false"):
        assert term in documentation

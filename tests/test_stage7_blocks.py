from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from hypothesis import given, settings, strategies as st
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine  # noqa: E402
from kroika_pattern_engine.blocks import (  # noqa: E402
    BlockConstructionError,
    build_base_blocks,
    build_one_piece_sleeve,
    calculate_block_values,
)
from kroika_pattern_engine.geometry import contour_from_data, validate_simple_contour  # noqa: E402


def load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


CASES = load_json("references/stage2/control-examples.json")["cases"]
MANUAL = load_json("references/stage7/block-controls.json")["cases"]


def request_for_case(case: dict, *, scale: float = 1.0) -> dict:
    request = load_json("examples/v1/example-engine-request.json")
    linear = {
        key: value * scale
        for key, value in case["inputs"].items()
        if not key.endswith("_deg")
    }
    request["body_measurements"]["values"] = {
        key: {"value": value, "unit": "mm", "source": "preset"}
        for key, value in linear.items()
    }
    shoulder_lengths = {"S": 120.0, "M": 130.0, "L": 140.0}
    request["body_measurements"]["values"]["shoulder_length"] = {
        "value": shoulder_lengths[case["id"]] * scale,
        "unit": "mm",
        "source": "preset",
    }
    request["body_measurements"]["angles_deg"] = {
        "shoulder_slope": case["inputs"]["shoulder_slope_deg"],
        "hip_inclination": case["inputs"]["hip_inclination_deg"],
    }
    for group in ("wearing_ease_mm", "design_ease_mm"):
        request["fit_settings"][group] = {
            "bust": 0,
            "waist": 0,
            "hips": 0,
            "upper_arm": 0,
        }
    request["garment_spec"]["parameters"]["neckline"]["front_depth_mm"] = 90 * scale
    request["garment_spec"]["parameters"]["neckline"]["back_depth_mm"] = 25 * scale
    request["garment_spec"]["parameters"]["skirt"]["length_from_waist_mm"] = 550 * scale
    request["garment_spec"]["parameters"]["skirt"]["hem_expansion_each_side_mm"] = 40 * scale
    return request


def segment(piece, segment_id: str):
    return next(item for item in piece.seam_contour.segments if item.id == segment_id)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["id"])
def test_f01_f41_match_fixed_stage2_arithmetic(case: dict):
    actual = calculate_block_values(case["inputs"])
    assert set(actual) == set(case["expected"])
    for name, expected in case["expected"].items():
        assert actual[name] == pytest.approx(expected, abs=1e-9)


def test_confirmed_ease_is_added_once_and_keeps_the_recorded_split():
    request = load_json("examples/v1/example-engine-request.json")
    request["body_measurements"]["values"]["shoulder_length"] = {
        "value": 130,
        "unit": "mm",
        "source": "user",
    }
    blocks = build_base_blocks(request)
    assert blocks.formula_inputs["bust"] == 980
    assert blocks.formula_inputs["back_bust_arc"] == 470
    assert blocks.formula_values["front_width"] == 255
    assert blocks.formula_values["back_width"] == 235
    assert 2 * (
        blocks.formula_values["front_width"] + blocks.formula_values["back_width"]
    ) == 980


@pytest.mark.parametrize(
    ("case", "manual"),
    list(zip(CASES, MANUAL, strict=True)),
    ids=[item["id"] for item in CASES],
)
def test_four_blocks_match_independent_control_dimensions(case: dict, manual: dict):
    blocks = build_base_blocks(request_for_case(case))
    assert manual["id"] == case["id"]
    expected = manual["expected_mm"]
    assert segment(blocks.front_bodice, "front_waist").length_mm == pytest.approx(
        expected["front_bodice_raw_waist"], abs=1e-9
    )
    assert segment(blocks.back_bodice, "back_waist").length_mm == pytest.approx(
        expected["back_bodice_raw_waist"], abs=1e-9
    )
    assert segment(blocks.front_skirt, "front_skirt_waist").length_mm == pytest.approx(
        expected["front_skirt_raw_waist"], abs=1e-9
    )
    assert segment(blocks.back_skirt, "back_skirt_waist").length_mm == pytest.approx(
        expected["back_skirt_raw_waist"], abs=1e-9
    )
    assert segment(blocks.front_bodice, "front_side").end.y_mm == pytest.approx(
        expected["front_underarm_height"], abs=1e-9
    )
    assert segment(blocks.back_bodice, "back_side").end.y_mm == pytest.approx(
        expected["back_underarm_height"], abs=1e-9
    )


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["id"])
def test_base_contours_are_simple_and_pattern_contract_compatible(case: dict):
    blocks = build_base_blocks(request_for_case(case))
    pattern = blocks.to_pattern_data()
    validate_document("pattern-data", pattern)
    assert [piece["id"] for piece in pattern["pieces"]] == [
        "front_bodice",
        "back_bodice",
        "front_skirt",
        "back_skirt",
    ]
    assert pattern["seam_pairs"] == []
    for piece in pattern["pieces"]:
        validate_simple_contour(contour_from_data(piece["seam_contour"]))
        assert piece["cutting_contour"] is None
        assert piece["internal_paths"]
        assert "Экспериментальный" in piece["annotations"][0]["text_ru"]


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["id"])
def test_darts_waist_shoulder_and_side_projection_conserve_targets(case: dict):
    blocks = build_base_blocks(request_for_case(case))
    for name, value in blocks.controls.items():
        if name.endswith("_residual_mm") and name != "skirt_side_length_residual_mm":
            assert abs(value) <= 1e-9, (name, value)
    assert blocks.controls["formula_count"] == 41
    assert blocks.controls["front_armhole_length_mm"] > 0
    assert blocks.controls["back_armhole_length_mm"] > 0
    assert {path.id for path in blocks.front_bodice.internal_paths} >= {
        "front_waist_dart",
        "front_side_dart",
        "front_bust_line",
    }
    assert len([path for path in blocks.back_bodice.internal_paths if "dart" in path.id]) == 2


@settings(max_examples=60, deadline=None)
@given(scale=st.floats(min_value=0.8, max_value=1.2, allow_nan=False, allow_infinity=False))
def test_scaled_reference_family_remains_finite_connected_and_simple(scale: float):
    blocks = build_base_blocks(request_for_case(CASES[1], scale=scale))
    # build_base_blocks already validates every contour; avoid doubling the
    # expensive flattened-intersection pass in each property example.
    for piece in blocks.pieces:
        assert piece.seam_contour.area_mm2 > 0
    assert max(
        abs(value)
        for name, value in blocks.controls.items()
        if name.endswith("_residual_mm") and name != "skirt_side_length_residual_mm"
    ) < 1e-8


def test_missing_geometry_measurement_and_invalid_domain_fail_explicitly():
    request = request_for_case(CASES[1])
    del request["body_measurements"]["values"]["shoulder_length"]
    with pytest.raises(BlockConstructionError) as missing:
        build_base_blocks(request)
    assert missing.value.code == "BLOCK_MEASUREMENT_REQUIRED"
    assert missing.value.json_pointer.endswith("/shoulder_length")

    invalid = dict(CASES[1]["inputs"], waist=1400)
    with pytest.raises(BlockConstructionError) as domain:
        calculate_block_values(invalid)
    assert domain.value.code == "BLOCK_FORMULA_OUTSIDE_DOMAIN"


def test_one_piece_sleeve_cap_is_solved_to_the_built_armhole_length():
    blocks = build_base_blocks(request_for_case(CASES[1]))
    sleeve = build_one_piece_sleeve(
        front_armhole_length_mm=blocks.controls["front_armhole_length_mm"],
        back_armhole_length_mm=blocks.controls["back_armhole_length_mm"],
        upper_arm_circumference_mm=300,
        upper_arm_ease_mm=40,
        sleeve_length_mm=600,
        wrist_circumference_mm=160,
        hand_circumference_mm=200,
        sleeve_balance_mm=blocks.formula_values["sleeve_balance"],
    )
    assert sleeve.actual_cap_length_mm == pytest.approx(
        sleeve.target_cap_length_mm, abs=1e-7
    )
    assert 0 < sleeve.cap_height_mm < sleeve.target_cap_length_mm
    validate_simple_contour(sleeve.piece.seam_contour)
    validate_document(
        "pattern-data",
        {
            "schema_version": "1.0.0",
            "unit": "mm",
            "pieces": [sleeve.piece.to_pattern_data()],
            "seam_pairs": [],
        },
    )


def test_engine_reuses_validated_blocks_inside_stage8_assembly():
    request = request_for_case(CASES[1])
    fixed = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    result = GeometryPatternEngine(clock=lambda: fixed).generate(request)
    validate_document("pattern-engine-result", result)
    assert result["engine_version"] == "0.4.0"
    assert result["status"] == "succeeded"
    assert result["pattern"] is not None
    report = result["validation_report"]
    assert report["production_export_allowed"] is False
    assert {item["code"] for item in report["issues"]} == {
        "EXPERT_BLOCK_REVIEW_REQUIRED",
        "SEAM_TRUEING_REVIEW_REQUIRED",
        "CUTTING_CONTOUR_NOT_AVAILABLE",
    }
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["engine.pattern_blocks.formulas"]["status"] == "passed"
    assert by_id["engine.pattern_blocks.geometry"]["status"] == "passed"
    assert by_id["engine.pattern_blocks.controls"]["measured_value"] <= 0.001
    assert by_id["engine.garment_assembly"]["status"] == "passed"


def test_stage7_is_latest_bootstrap_and_documented_layer():
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-stage7.txt").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify_all.py").read_text(encoding="utf-8")
    documentation = (ROOT / "docs" / "BASE_BLOCKS.md").read_text(encoding="utf-8")
    assert '"requirements-stage7.txt"' in launcher
    assert "-r requirements-stage8.txt" in dockerfile
    assert "-r requirements-stage6.txt" in requirements
    assert "verify_stage7.py" in verifier
    for term in ("F01–F41", "вытач", "пройм", "GARMENT_ASSEMBLY_STAGE_NOT_READY"):
        assert term in documentation

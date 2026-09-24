from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src")]

from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.hashing import canonical_generation_payload, compute_input_hash  # noqa: E402
from kroika_contracts.semantic import SemanticContractError, validate_engine_request  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine  # noqa: E402
from kroika_pattern_engine.geometry import contour_from_data  # noqa: E402
from kroika_pattern_engine.modeling import (  # noqa: E402
    apply_modeling_transformations,
    adjusted_hem_width_mm,
    equal_panel_boundaries_mm,
    flounce_radii_mm,
    gathered_cut_length_mm,
    pleat_allowance_mm,
    transferred_dart_intake_mm,
    yoke_split_depths_mm,
)
from tests.wiring import assert_current_only_workflow  # noqa: E402


def _example_request() -> dict:
    return json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(
            encoding="utf-8"
        )
    )


def _element(
    source_id: str,
    element_type: str,
    variant: str,
    location: str,
    construction: str,
    module_id: str,
    dimensions: dict[str, float | None],
    *,
    count: int | None = 1,
) -> dict:
    return {
        "source_element_id": source_id,
        "type": element_type,
        "variant": variant,
        "description_ru": f"Модельная операция {source_id}.",
        "location": location,
        "construction": construction,
        "count": count,
        "symmetry": "symmetric",
        "confidence": 0.95,
        "evidence_ru": "Подтверждено пользователем по фотографии.",
        "requires_confirmation": False,
        "included": True,
        "confirmed_by_user": True,
        "dimensions_mm": dimensions,
        "support_status": "supported",
        "module_id": module_id,
    }


def _intent(elements: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "source": "manual",
        "status": "ready",
        "review_status": "confirmed",
        "reviewed_at": "2026-09-23T12:00:00Z",
        "elements": elements,
        "layers": [{
            "source_layer_id": "main_fabric",
            "role": "main",
            "coverage": "full",
            "material_hint_ru": "Основная ткань.",
            "opacity": "opaque",
            "drape": "medium",
            "confidence": 0.95,
            "requires_confirmation": False,
            "included": True,
            "confirmed_by_user": True,
            "support_status": "supported",
            "module_id": "main_fabric_layer",
        }],
        "proportions": {
            "waist_position": "natural",
            "volume": "regular",
            "hem_shape": "straight",
            "asymmetry": "no",
            "confidence": 0.95,
            "confirmed_by_user": True,
            "support_status": "supported",
            "module_id": "bounded_visual_proportions",
        },
        "pending_questions": [],
        "question_answers": [],
    }


def _ready_request(*elements: dict) -> dict:
    request = _example_request()
    request["garment_spec"]["design_intent"] = _intent(list(elements))
    request["input_hash"] = compute_input_hash(request)
    validate_engine_request(request)
    return request


def _dimensions(**values: float | None) -> dict[str, float | None]:
    result = {"width": None, "length": None, "depth": None, "spacing": None}
    result.update(values)
    return result


def test_stage18_reference_formulas_and_invariants():
    reference = json.loads(
        (ROOT / "references" / "stage18" / "modeling-controls.json").read_text(
            encoding="utf-8"
        )
    )["references"]
    assert pleat_allowance_mm("knife", 20) == reference["knife_pleat_allowance"]
    assert pleat_allowance_mm("box", 20) == reference["box_pleat_allowance"]
    assert gathered_cut_length_mm(400, 120) == reference["gathered_cut_length"]
    assert flounce_radii_mm(math.pi * 100, 80) == pytest.approx((
        reference["flounce_inner_radius"], reference["flounce_outer_radius"],
    ))
    assert yoke_split_depths_mm(600, 120) == (
        reference["yoke_depth"], reference["yoke_remainder"],
    )
    assert equal_panel_boundaries_mm(400, 4) == tuple(reference["panel_boundaries"])
    assert transferred_dart_intake_mm(24, 0.75) == pytest.approx((
        reference["transferred_dart_intake"], reference["retained_dart_intake"],
    ))
    assert adjusted_hem_width_mm(180, -50) == reference["adjusted_hem_half_width"]
    with pytest.raises(ValueError):
        adjusted_hem_width_mm(80, -60)
    upper_request = _example_request()
    upper_request["garment_spec"]["garment_type"] = "top"
    no_phantom_hem = apply_modeling_transformations(
        {"schema_version": "1.0.0", "unit": "mm", "pieces": [], "seam_pairs": []},
        upper_request,
    )
    assert no_phantom_hem.applied_count == 0


def test_center_pleat_and_belt_change_real_geometry_and_audit_hash():
    pleat = _element(
        "front_center_box", "pleat", "box", "skirt_front", "integrated",
        "center_pleat_v1", _dimensions(depth=20, length=260),
    )
    belt = _element(
        "waist_belt", "belt", "straight", "waist", "separate_piece",
        "straight_belt_v1", _dimensions(width=45, length=1400),
    )
    request = _ready_request(pleat, belt)
    assert canonical_generation_payload(request)["hash_contract_version"] == "1.1.0"
    legacy_request = _example_request()
    assert canonical_generation_payload(legacy_request)["hash_contract_version"] == "1.0.0"
    assert compute_input_hash(legacy_request) == legacy_request["input_hash"]
    reordered = _ready_request(belt, pleat)
    assert reordered["input_hash"] == request["input_hash"]
    changed = deepcopy(request)
    changed["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["depth"] = 25
    changed["input_hash"] = compute_input_hash(changed)
    assert changed["input_hash"] != request["input_hash"]

    result = GeometryPatternEngine().generate(request)
    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    operations = {item["kind"]: item for item in pattern["modeling_operations"]}
    assert operations["pleat"]["parameters_mm"]["added_width"] == 80
    assert operations["belt"]["parameters_mm"] == {
        "finished_width": 45.0,
        "finished_length": 1400.0,
    }
    pieces = {piece["id"]: piece for piece in pattern["pieces"]}
    assert "waist_belt_belt" in pieces
    front = contour_from_data(pieces["front_skirt"]["seam_contour"])
    assert front.bounding_box.min_x_mm == 0
    assert any(segment.id == "front_center_box_center_extension_waist"
               for segment in front.segments)
    assert {path["id"] for path in pieces["front_skirt"]["internal_paths"]} >= {
        "front_center_box_fold_1", "front_center_box_fold_2",
        "front_center_box_fold_3", "front_center_box_fold_4",
    }


def test_circular_flounce_adds_joined_cuttable_pieces():
    flounce = _element(
        "hem_flounce", "flounce", "circular", "hem", "separate_piece",
        "circular_hem_flounce_v1", _dimensions(depth=90),
    )
    pleat = _element(
        "front_hem_pleat", "pleat", "knife", "skirt_front", "integrated",
        "center_pleat_v1", _dimensions(depth=15),
    )
    # Deliberately put the flounce first: compilation order must still widen the hem before joining.
    result = GeometryPatternEngine().generate(_ready_request(flounce, pleat))
    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    pieces = {piece["id"]: piece for piece in pattern["pieces"]}
    assert {"front_skirt_flounce", "back_skirt_flounce"} <= set(pieces)
    assert pieces["front_skirt_flounce"]["cutting_contour"] is not None
    front_join_allowances = {
        item["edge_type"]
        for item in pieces["front_skirt"]["edge_allowances"]
        if "flounce_join" in item["segment_id"]
    }
    assert front_join_allowances == {"normal"}
    pairs = {pair["id"] for pair in pattern["seam_pairs"]}
    assert {
        "front_skirt_flounce_join", "back_skirt_flounce_join",
        "flounce_side_left_join", "flounce_side_right_join",
    } <= pairs
    operation = next(item for item in pattern["modeling_operations"] if item["kind"] == "flounce")
    assert operation["formula_id"] == "M18-F01"
    assert operation["invariant_residual_mm"] <= 1e-6


def test_gather_adds_cut_width_but_preserves_the_joining_length():
    gather = _element(
        "front_waist_gather", "gather", "gathered", "skirt_front", "integrated",
        "waist_gather_allowance_v1", _dimensions(width=120, length=200),
    )
    result = GeometryPatternEngine().generate(_ready_request(gather))
    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    operation = next(item for item in pattern["modeling_operations"] if item["kind"] == "gather")
    assert operation["parameters_mm"]["added_width"] == 120
    front = next(piece for piece in pattern["pieces"] if piece["id"] == "front_skirt")
    assert "front_waist_gather_gather_line" in {path["id"] for path in front["internal_paths"]}
    waist_pair = next(
        pair for pair in pattern["seam_pairs"]
        if pair["first_piece_id"] == "front_bodice" and pair["second_piece_id"] == "front_skirt"
    )
    assert waist_pair["second_length_reduction_mm"] >= 120
    check = next(
        item for item in result["validation_report"]["checks"]
        if item["id"] == "engine.modeling.interfaces"
    )
    assert check["status"] == "passed"
    assert check["measured_value"] <= check["limit_value"]


def test_adjustable_waistband_and_negative_hem_are_applied_to_skirt():
    request = _example_request()
    request["garment_spec"]["garment_type"] = "skirt"
    request["garment_spec"]["parameters"]["skirt"]["hem_expansion_each_side_mm"] = -40
    request["garment_spec"]["parameters"]["finishing"] = {
        "neckline_facing": False,
        "armhole_facing": False,
        "waistband": True,
        "front_placket": False,
        "collar": False,
    }
    request["fit_settings"]["preset"]["id"] = "woven_skirt_trial"
    request["fit_settings"]["wearing_ease_mm"] = {
        "bust": 0, "waist": 20, "hips": 40, "upper_arm": 0,
    }
    waistband = _element(
        "wide_waistband", "waistband", "straight", "waist", "separate_piece",
        "adjustable_straight_waistband_v1", _dimensions(width=70), count=1,
    )
    request["garment_spec"]["design_intent"] = _intent([waistband])
    request["input_hash"] = compute_input_hash(request)
    validate_engine_request(request)

    result = GeometryPatternEngine().generate(request)
    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pieces = {piece["id"]: piece for piece in result["pattern"]["pieces"]}
    for piece_id in ("front_waistband", "back_waistband"):
        assert contour_from_data(pieces[piece_id]["seam_contour"]).bounding_box.height_mm == 70
    kinds = {item["kind"] for item in result["pattern"]["modeling_operations"]}
    assert {"waistband", "hem_adjustment"} <= kinds


def test_stage18_modules_fail_closed_when_declared_shape_does_not_match():
    invalid = _element(
        "bad_flounce", "flounce", "circular", "hem", "separate_piece",
        "circular_hem_flounce_v1", _dimensions(width=100),
    )
    request = _example_request()
    request["garment_spec"]["design_intent"] = _intent([invalid])
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as failure:
        validate_engine_request(request)
    assert "DESIGN_MODEL_MODULE_MISMATCH" in {item.code for item in failure.value.issues}

    duplicate = _element(
        "duplicate_model", "belt", "straight", "waist", "separate_piece",
        "straight_belt_v1", _dimensions(width=40, length=1200),
    )
    request["garment_spec"]["design_intent"] = _intent([duplicate, deepcopy(duplicate)])
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as duplicate_failure:
        validate_engine_request(request)
    assert "DESIGN_SOURCE_ID_DUPLICATE" in {
        item.code for item in duplicate_failure.value.issues
    }


def test_stage18_local_launcher_and_ci_use_only_the_current_gate():
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage18.txt"' in launcher
    assert_current_only_workflow(ROOT, workflow)

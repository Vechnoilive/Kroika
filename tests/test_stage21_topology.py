from __future__ import annotations

from copy import deepcopy
import json
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
from tests.wiring import assert_current_only_workflow  # noqa: E402


def _dimensions(**values: float | None) -> dict[str, float | None]:
    result = {"width": None, "length": None, "depth": None, "spacing": None}
    result.update(values)
    return result


def _element(
    source_id: str,
    element_type: str,
    variant: str,
    location: str,
    construction: str,
    count: int,
    symmetry: str,
    module_id: str,
    dimensions: dict[str, float | None],
) -> dict:
    return {
        "source_element_id": source_id,
        "type": element_type,
        "variant": variant,
        "description_ru": f"Топологическая операция {source_id}.",
        "location": location,
        "construction": construction,
        "count": count,
        "symmetry": symmetry,
        "confidence": 1.0,
        "evidence_ru": "Подтверждено пользователем по фотографии.",
        "requires_confirmation": False,
        "included": True,
        "confirmed_by_user": True,
        "dimensions_mm": dimensions,
        "support_status": "supported",
        "module_id": module_id,
    }


def _intent(*elements: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "coverage_schema_version": "1.0.0",
        "source": "manual",
        "status": "ready",
        "review_status": "confirmed",
        "reviewed_at": "2026-09-23T18:00:00Z",
        "elements": list(elements),
        "layers": [{
            "source_layer_id": "main_fabric",
            "role": "main",
            "coverage": "full",
            "material_hint_ru": "Основная ткань.",
            "opacity": "opaque",
            "drape": "medium",
            "confidence": 1.0,
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
            "confidence": 1.0,
            "confirmed_by_user": True,
            "support_status": "supported",
            "module_id": "bounded_visual_proportions",
        },
        "pending_questions": [],
        "question_answers": [],
    }


def _request(*elements: dict) -> dict:
    request = json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(
            encoding="utf-8"
        )
    )
    request["garment_spec"]["design_intent"] = _intent(*elements)
    request["input_hash"] = compute_input_hash(request)
    validate_engine_request(request)
    return request


def _yoke() -> dict:
    return _element(
        "photo_skirt_yoke", "yoke", "straight", "waist", "separate_piece", 2,
        "symmetric", "paired_straight_skirt_yoke_v1", _dimensions(depth=120),
    )


def _panels(count: int = 3) -> dict:
    return _element(
        "photo_skirt_panels", "panel", "straight", "full_garment",
        "separate_piece", count, "symmetric", "paired_equal_skirt_panels_v1",
        _dimensions(),
    )


def _dart_transfer(width: float = 10) -> dict:
    return _element(
        "photo_dart_transfer", "dart", "shaped", "bodice_front", "integrated", 2,
        "symmetric", "front_waist_to_side_dart_v1", _dimensions(width=width),
    )


def _operation(result: dict, kind: str) -> dict:
    return next(
        item for item in result["pattern"]["topology_operations"]
        if item["kind"] == kind
    )


def test_yoke_creates_separate_cuttable_pieces_and_exact_joins() -> None:
    result = GeometryPatternEngine().generate(_request(_yoke()))

    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    pieces = {item["id"]: item for item in pattern["pieces"]}
    assert {"front_skirt_yoke", "back_skirt_yoke", "front_skirt", "back_skirt"} <= pieces.keys()
    assert all(
        pieces[piece_id]["cutting_contour"] is not None
        for piece_id in ("front_skirt_yoke", "back_skirt_yoke", "front_skirt", "back_skirt")
    )
    assert {
        "front_skirt_yoke_join", "back_skirt_yoke_join",
        "skirt_yoke_side_join", "skirt_lower_side_join",
    } <= {item["id"] for item in pattern["seam_pairs"]}
    assert _operation(result, "yoke")["parameters_mm"] == {"depth": 120.0}
    check = next(
        item for item in result["validation_report"]["checks"]
        if item["id"] == "engine.topology.interfaces"
    )
    assert check["status"] == "passed"
    assert check["measured_value"] <= 1.0


def test_equal_panels_replace_skirt_halves_and_keep_every_interface_auditable() -> None:
    result = GeometryPatternEngine().generate(_request(_panels(3)))

    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    pieces = {item["id"]: item for item in pattern["pieces"]}
    panel_ids = {
        f"{side}_skirt_panel_{number}"
        for side in ("front", "back") for number in range(1, 4)
    }
    assert panel_ids <= pieces.keys()
    assert {"front_skirt", "back_skirt"}.isdisjoint(pieces)
    assert all(pieces[piece_id]["cutting_contour"] is not None for piece_id in panel_ids)
    pair_ids = {item["id"] for item in pattern["seam_pairs"]}
    assert {
        "front_panel_join_1", "front_panel_join_2",
        "back_panel_join_1", "back_panel_join_2", "skirt_side_join",
    } <= pair_ids
    assert len([item for item in pair_ids if item.startswith("front_waist_panel_join_")]) == 3
    operation = _operation(result, "panels")
    assert set(operation["target_piece_ids"]) == panel_ids
    coverage = next(
        item for item in pattern["design_coverage"]["modules"]
        if item["module_id"] == "paired_equal_skirt_panels_v1"
    )
    assert set(coverage["evidence"]["piece_ids"]) == panel_ids


def test_partial_dart_transfer_moves_intake_without_changing_joined_lengths() -> None:
    baseline = GeometryPatternEngine().generate(_request())["pattern"]
    result = GeometryPatternEngine().generate(_request(_dart_transfer(10)))

    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    before_pairs = {item["id"]: item for item in baseline["seam_pairs"]}
    after_pairs = {item["id"]: item for item in pattern["seam_pairs"]}
    assert after_pairs["front_waist_join"]["first_length_reduction_mm"] == pytest.approx(
        before_pairs["front_waist_join"]["first_length_reduction_mm"] - 10
    )
    assert after_pairs["bodice_side_join"]["first_length_reduction_mm"] == pytest.approx(
        before_pairs["bodice_side_join"]["first_length_reduction_mm"] + 10
    )
    before_front = next(item for item in baseline["pieces"] if item["id"] == "front_bodice")
    after_front = next(item for item in pattern["pieces"] if item["id"] == "front_bodice")
    before_waist = next(
        item for item in contour_from_data(before_front["seam_contour"]).segments
        if item.id == "front_waist"
    )
    after_waist = next(
        item for item in contour_from_data(after_front["seam_contour"]).segments
        if item.id == "front_waist"
    )
    assert before_waist.length_mm - after_waist.length_mm == pytest.approx(10)
    assert _operation(result, "dart_transfer")["invariant_residual_mm"] <= 1.0


def test_topology_hash_v14_is_order_independent_and_changes_with_parameters() -> None:
    request = _request(_dart_transfer(10), _yoke())
    payload = canonical_generation_payload(request)
    assert payload["hash_contract_version"] == "1.4.0"
    assert [item["module_id"] for item in payload["garment_spec"]["topology_elements"]] == [
        "front_waist_to_side_dart_v1", "paired_straight_skirt_yoke_v1",
    ]
    reordered = deepcopy(request)
    reordered["garment_spec"]["design_intent"]["elements"].reverse()
    assert compute_input_hash(reordered) == request["input_hash"]

    changed = deepcopy(request)
    changed["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["width"] = 12
    assert compute_input_hash(changed) != request["input_hash"]

    legacy = _request()
    assert canonical_generation_payload(legacy)["hash_contract_version"] == "1.3.0"


def test_topology_contract_rejects_mismatches_and_pipeline_conflicts() -> None:
    invalid = _yoke()
    invalid["count"] = 1
    request = json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(
            encoding="utf-8"
        )
    )
    request["garment_spec"]["design_intent"] = _intent(invalid)
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as mismatch:
        validate_engine_request(request)
    assert "DESIGN_TOPOLOGY_MODULE_MISMATCH" in {
        issue.code for issue in mismatch.value.issues
    }

    request["garment_spec"]["design_intent"] = _intent(_yoke(), _panels())
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as conflict:
        validate_engine_request(request)
    assert "DESIGN_TOPOLOGY_TARGET_CONFLICT" in {
        issue.code for issue in conflict.value.issues
    }


def test_stage21_local_launcher_and_ci_use_only_the_current_gate() -> None:
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage21.txt"' in launcher
    assert_current_only_workflow(ROOT, workflow)

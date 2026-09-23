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
from kroika_pattern_engine.composites import (  # noqa: E402
    collar_dimensions_mm,
    cuff_dimensions_mm,
    pocket_dimensions_mm,
)
from kroika_pattern_engine.geometry import contour_from_data  # noqa: E402


EXTRA_MEASUREMENTS = {
    "neck_circumference": 380,
    "upper_arm_circumference": 300,
    "wrist_circumference": 160,
    "hand_circumference": 210,
    "sleeve_length": 580,
    "elbow_circumference": 260,
    "elbow_length": 330,
}


def _example_request() -> dict:
    return json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(
            encoding="utf-8"
        )
    )


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
    module_id: str,
    dimensions: dict[str, float | None],
) -> dict:
    return {
        "source_element_id": source_id,
        "type": element_type,
        "variant": variant,
        "description_ru": f"Составная деталь {source_id}.",
        "location": location,
        "construction": construction,
        "count": count,
        "symmetry": "symmetric",
        "confidence": 0.98,
        "evidence_ru": "Подтверждено пользователем по фотографии.",
        "requires_confirmation": False,
        "included": True,
        "confirmed_by_user": True,
        "dimensions_mm": dimensions,
        "support_status": "supported",
        "module_id": module_id,
    }


def _layer(
    source_id: str, role: str, coverage: str, opacity: str, module_id: str,
) -> dict:
    return {
        "source_layer_id": source_id,
        "role": role,
        "coverage": coverage,
        "material_hint_ru": f"Материал слоя {source_id}.",
        "opacity": opacity,
        "drape": "fluid",
        "confidence": 0.98,
        "requires_confirmation": False,
        "included": True,
        "confirmed_by_user": True,
        "support_status": "supported",
        "module_id": module_id,
    }


def _main_layer() -> dict:
    return {
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
    }


def _intent(elements: list[dict], layers: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0.0",
        "source": "manual",
        "status": "ready",
        "review_status": "confirmed",
        "reviewed_at": "2026-09-23T15:00:00Z",
        "elements": elements,
        "layers": [_main_layer(), *(layers or [])],
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


def _ready_request(*elements: dict, layers: list[dict] | None = None) -> dict:
    request = _example_request()
    request["garment_spec"]["design_intent"] = _intent(list(elements), layers)
    request["input_hash"] = compute_input_hash(request)
    validate_engine_request(request)
    return request


def _blouse_request(*elements: dict) -> dict:
    request = _example_request()
    for name, value in EXTRA_MEASUREMENTS.items():
        request["body_measurements"]["values"][name] = {
            "value": value, "unit": "mm", "source": "user",
        }
    spec = request["garment_spec"]
    spec["garment_type"] = "blouse"
    spec["parameters"]["sleeve"] = {"type": "long", "length_mm": 580}
    spec["parameters"]["closure"] = {
        "type": "zipper", "location": "center_back", "length_mm": 550,
    }
    spec["parameters"]["finishing"] = {
        "neckline_facing": True,
        "armhole_facing": False,
        "waistband": False,
        "front_placket": False,
        "collar": False,
    }
    spec["parameters"]["upper"] = {"length_below_waist_mm": 120}
    spec["design_intent"] = _intent(list(elements))
    request["fit_settings"]["preset"]["id"] = "woven_blouse_trial"
    request["fit_settings"]["wearing_ease_mm"] = {
        "bust": 80, "waist": 80, "hips": 80, "upper_arm": 60,
    }
    request["input_hash"] = compute_input_hash(request)
    validate_engine_request(request)
    return request


def test_stage19_reference_dimensions_are_bounded():
    assert cuff_dimensions_mm(210, 55) == (210, 55)
    assert collar_dimensions_mm(105, 75, 40) == (105, 75, 40)
    assert pocket_dimensions_mm(140, 170) == (140, 170)
    with pytest.raises(Exception):
        cuff_dimensions_mm(210, 10)
    with pytest.raises(Exception):
        pocket_dimensions_mm(400, 170)


def test_cuff_and_stand_collar_create_cuttable_pieces_and_exact_joins():
    cuff = _element(
        "sleeve_cuff", "cuff", "straight", "sleeve", "separate_piece", 2,
        "sleeve_cuff_band_v1", _dimensions(width=55),
    )
    cuff_result = GeometryPatternEngine().generate(_blouse_request(cuff))
    assert cuff_result["status"] == "succeeded"
    validate_document("pattern-engine-result", cuff_result)
    cuff_pattern = cuff_result["pattern"]
    cuff_pieces = {piece["id"]: piece for piece in cuff_pattern["pieces"]}
    assert cuff_pieces["sleeve_cuff_cuff"]["cutting_contour"] is not None
    sleeve_allowances = {
        item["edge_type"]
        for item in cuff_pieces["base_sleeve"]["edge_allowances"]
        if item["segment_id"] == "sleeve_cuff_cuff_join"
    }
    assert sleeve_allowances == {"normal"}
    cuff_operation = cuff_pattern["composite_operations"][0]
    assert cuff_operation["kind"] == "cuff"
    assert cuff_operation["invariant_residual_mm"] <= 1e-6

    collar = _element(
        "photo_stand", "collar", "stand", "neckline", "separate_piece", 1,
        "stand_collar_v1", _dimensions(width=40),
    )
    collar_result = GeometryPatternEngine().generate(_ready_request(collar))
    assert collar_result["status"] == "succeeded"
    validate_document("pattern-engine-result", collar_result)
    collar_pattern = collar_result["pattern"]
    collar_pieces = {piece["id"]: piece for piece in collar_pattern["pieces"]}
    collar_box = contour_from_data(
        collar_pieces["photo_stand_stand_collar"]["seam_contour"]
    ).bounding_box
    assert collar_box.height_mm == 40
    collar_pairs = {pair["id"] for pair in collar_pattern["seam_pairs"]}
    assert {
        "photo_stand_front_collar_attachment",
        "photo_stand_back_collar_attachment",
    } <= collar_pairs


def test_patch_pocket_adds_piece_and_surface_placement_path():
    pocket = _element(
        "front_pockets", "pocket", "patch", "skirt_front", "applied", 2,
        "paired_patch_pocket_v1", _dimensions(width=140, depth=170),
    )
    result = GeometryPatternEngine().generate(_ready_request(pocket))
    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pieces = {piece["id"]: piece for piece in result["pattern"]["pieces"]}
    assert pieces["front_pockets_patch_pocket"]["cut_quantity"] == 2
    assert "front_pockets_placement" in {
        path["id"] for path in pieces["front_skirt"]["internal_paths"]
    }
    operation = result["pattern"]["composite_operations"][0]
    assert operation["interface_ids"] == ["front_pockets_placement"]


def test_lining_and_overlay_are_separate_layer_pieces_with_audited_interfaces():
    flounce = _element(
        "layered_flounce", "flounce", "circular", "hem", "separate_piece", 1,
        "circular_hem_flounce_v1", _dimensions(depth=80),
    )
    lining = _layer(
        "skirt_lining", "lining", "skirt", "opaque", "skirt_full_lining_v1"
    )
    overlay = _layer(
        "sheer_overlay", "overlay", "skirt", "semi_transparent",
        "skirt_overlay_layer_v1",
    )
    result = GeometryPatternEngine().generate(
        _ready_request(flounce, layers=[overlay, lining])
    )
    assert result["status"] == "succeeded"
    validate_document("pattern-engine-result", result)
    pattern = result["pattern"]
    pieces = {piece["id"]: piece for piece in pattern["pieces"]}
    assert {
        "lining_front_skirt", "lining_back_skirt",
        "overlay_front_skirt", "overlay_back_skirt",
        "overlay_front_skirt_flounce", "overlay_back_skirt_flounce",
    } <= set(pieces)
    assert all(pieces[piece_id]["cutting_contour"] is not None for piece_id in (
        "lining_front_skirt", "lining_back_skirt",
        "overlay_front_skirt", "overlay_back_skirt",
    ))
    pair_ids = {pair["id"] for pair in pattern["seam_pairs"]}
    assert {
        "lining_skirt_side_join",
        "lining_front_skirt_waist_attachment",
        "overlay_skirt_side_join",
        "overlay_back_skirt_waist_attachment",
        "overlay_front_skirt_flounce_join",
        "overlay_back_skirt_flounce_join",
    } <= pair_ids
    operations = {item["kind"]: item for item in pattern["composite_operations"]}
    assert operations["lining"]["invariant_residual_mm"] <= 1e-6
    assert operations["overlay"]["invariant_residual_mm"] <= 1e-6


def test_stage19_hash_is_order_independent_and_preserves_legacy_contract():
    pocket = _element(
        "hash_pockets", "pocket", "patch", "skirt_front", "applied", 2,
        "paired_patch_pocket_v1", _dimensions(width=130, depth=160),
    )
    overlay = _layer(
        "hash_overlay", "overlay", "skirt", "transparent", "skirt_overlay_layer_v1"
    )
    request = _ready_request(pocket, layers=[overlay])
    payload = canonical_generation_payload(request)
    assert payload["hash_contract_version"] == "1.2.0"
    assert payload["garment_spec"]["composite_elements"][0]["module_id"] == (
        "paired_patch_pocket_v1"
    )
    assert payload["garment_spec"]["composite_layers"][0]["module_id"] == (
        "skirt_overlay_layer_v1"
    )
    legacy = _example_request()
    assert canonical_generation_payload(legacy)["hash_contract_version"] == "1.0.0"
    assert compute_input_hash(legacy) == legacy["input_hash"]

    changed = deepcopy(request)
    changed["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["width"] = 150
    changed["input_hash"] = compute_input_hash(changed)
    assert changed["input_hash"] != request["input_hash"]

    reordered = deepcopy(request)
    reordered["garment_spec"]["design_intent"]["layers"].reverse()
    reordered["input_hash"] = compute_input_hash(reordered)
    assert reordered["input_hash"] == request["input_hash"]


def test_stage19_modules_fail_closed_for_mismatches_and_conflicts():
    invalid = _element(
        "bad_cuff", "cuff", "straight", "sleeve", "separate_piece", 1,
        "sleeve_cuff_band_v1", _dimensions(width=55),
    )
    request = _blouse_request()
    request["garment_spec"]["design_intent"] = _intent([invalid])
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as mismatch:
        validate_engine_request(request)
    assert "DESIGN_COMPOSITE_MODULE_MISMATCH" in {
        item.code for item in mismatch.value.issues
    }

    cuff = _element(
        "first_cuff", "cuff", "straight", "sleeve", "separate_piece", 2,
        "sleeve_cuff_band_v1", _dimensions(width=50),
    )
    duplicate = deepcopy(cuff)
    duplicate["source_element_id"] = "second_cuff"
    request["garment_spec"]["design_intent"] = _intent([cuff, duplicate])
    request["input_hash"] = compute_input_hash(request)
    with pytest.raises(SemanticContractError) as conflict:
        validate_engine_request(request)
    assert "DESIGN_COMPOSITE_TARGET_CONFLICT" in {
        item.code for item in conflict.value.issues
    }


def test_stage19_local_launcher_and_ci_use_only_the_current_gate():
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    assert '"requirements-stage19.txt"' in launcher
    assert "python scripts/verify_stage19.py" in workflow
    assert "verify_all.py" not in workflow
    assert "verify_stage18.py" not in workflow

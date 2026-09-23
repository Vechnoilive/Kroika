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


def _example_request() -> dict:
    request = json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(
            encoding="utf-8"
        )
    )
    request["garment_spec"]["design_intent"] = _intent()
    request["input_hash"] = compute_input_hash(request)
    return request


def _element(
    source_id: str,
    element_type: str,
    variant: str,
    location: str,
    construction: str,
    module_id: str | None,
    *,
    included: bool = True,
    dimensions: dict[str, float | None] | None = None,
) -> dict:
    return {
        "source_element_id": source_id,
        "type": element_type,
        "variant": variant,
        "description_ru": f"Деталь {source_id}.",
        "location": location,
        "construction": construction,
        "count": 1,
        "symmetry": "symmetric",
        "confidence": 0.98,
        "evidence_ru": "Подтверждено по исходному виду.",
        "requires_confirmation": False,
        "included": included,
        "confirmed_by_user": True,
        "dimensions_mm": dimensions or {
            "width": None, "length": None, "depth": None, "spacing": None,
        },
        "support_status": "supported" if included else "excluded",
        "module_id": module_id if included else None,
    }


def _layer(source_id: str, role: str, module_id: str) -> dict:
    return {
        "source_layer_id": source_id,
        "role": role,
        "coverage": "full",
        "material_hint_ru": "Основная ткань.",
        "opacity": "opaque",
        "drape": "medium",
        "confidence": 1.0,
        "requires_confirmation": False,
        "included": True,
        "confirmed_by_user": True,
        "support_status": "supported",
        "module_id": module_id,
    }


def _intent() -> dict:
    return {
        "schema_version": "1.0.0",
        "coverage_schema_version": "1.0.0",
        "source": "ai",
        "status": "ready",
        "review_status": "confirmed",
        "reviewed_at": "2026-09-23T10:00:00Z",
        "elements": [
            _element(
                "back_zip", "closure", "zipper", "bodice_back", "integrated",
                "bounded_closure",
            ),
            _element(
                "waist_belt", "belt", "straight", "waist", "separate_piece",
                "straight_belt_v1",
                dimensions={"width": 40, "length": 1100, "depth": None, "spacing": None},
            ),
            _element(
                "photo_peplum", "peplum", "other", "waist", "separate_piece", None,
                included=False,
            ),
        ],
        "layers": [_layer("main_fabric", "main", "main_fabric_layer")],
        "proportions": {
            "waist_position": "natural",
            "volume": "regular",
            "hem_shape": "straight",
            "asymmetry": "no",
            "confidence": 0.97,
            "confirmed_by_user": True,
            "support_status": "supported",
            "module_id": "bounded_visual_proportions",
        },
        "pending_questions": [],
        "question_answers": [],
    }


def test_engine_links_confirmed_plan_to_real_geometry() -> None:
    request = _example_request()
    validate_engine_request(request)

    result = GeometryPatternEngine().generate(request)
    validate_document("pattern-engine-result", result)

    assert result["status"] == "succeeded"
    pattern = result["pattern"]
    assert pattern is not None
    modules = {
        item["module_id"]: item for item in pattern["design_coverage"]["modules"]
    }
    required = {
        "bounded_closure", "straight_belt_v1", "main_fabric_layer",
        "bounded_visual_proportions",
    }
    assert required <= modules.keys()
    assert modules["straight_belt_v1"]["source_ids"] == ["waist_belt"]
    assert modules["straight_belt_v1"]["evidence"]["operation_ids"] == [
        "model_waist_belt_belt"
    ]
    assert "waist_belt_belt" in modules["straight_belt_v1"]["evidence"]["piece_ids"]
    assert pattern["design_coverage"]["physical_validation_required"] is True
    assert any(
        check["id"] == "engine.design_coverage" and check["status"] == "passed"
        for check in result["validation_report"]["checks"]
    )


def test_every_coverage_reference_exists_in_pattern_audit_data() -> None:
    result = GeometryPatternEngine().generate(_example_request())
    pattern = result["pattern"]
    assert pattern is not None
    piece_ids = {item["id"] for item in pattern["pieces"]}
    pair_ids = {item["id"] for item in pattern["seam_pairs"]}
    path_ids = set()
    segment_ids = set()
    for piece in pattern["pieces"]:
        paths = [piece["seam_contour"], *piece["internal_paths"]]
        if piece["cutting_contour"] is not None:
            paths.append(piece["cutting_contour"])
        for path in paths:
            path_ids.add(path["id"])
            segment_ids.update(segment["id"] for segment in path["segments"])
    operation_ids = {
        operation["operation_id"]
        for key in ("modeling_operations", "composite_operations")
        for operation in pattern.get(key, [])
    }
    for module in pattern["design_coverage"]["modules"]:
        evidence = module["evidence"]
        assert set(evidence["piece_ids"]) <= piece_ids
        assert set(evidence["seam_pair_ids"]) <= pair_ids
        assert set(evidence["path_ids"]) <= path_ids
        assert set(evidence["segment_ids"]) <= segment_ids
        assert set(evidence["operation_ids"]) <= operation_ids


def test_missing_geometry_evidence_rejects_generation() -> None:
    request = _example_request()
    request["garment_spec"]["design_intent"]["layers"].append(
        _layer("impossible_lining", "lining", "jacket_full_lining")
    )

    result = GeometryPatternEngine().generate(request)

    assert result["status"] == "rejected"
    assert result["pattern"] is None
    assert result["validation_report"]["issues"][0]["code"] == (
        "DESIGN_COVERAGE_EVIDENCE_MISSING"
    )
    assert result["validation_report"]["issues"][0]["json_pointer"] == (
        "/garment_spec/design_intent"
    )
    assert result["validation_report"]["checks"][-1]["id"] == "engine.design_coverage"


def test_coverage_contract_has_order_independent_hash_v13() -> None:
    request = _example_request()
    first_payload = canonical_generation_payload(request)
    first_hash = compute_input_hash(request)
    assert first_payload["hash_contract_version"] == "1.3.0"
    assert first_payload["garment_spec"]["coverage_contract"] == {
        "schema_version": "1.0.0",
        "required_module_ids": [
            "bounded_closure", "bounded_visual_proportions", "main_fabric_layer",
            "straight_belt_v1",
        ],
    }

    reordered = deepcopy(request)
    reordered["garment_spec"]["design_intent"]["elements"].reverse()
    assert compute_input_hash(reordered) == first_hash

    changed = deepcopy(request)
    changed["garment_spec"]["design_intent"]["elements"].append(
        _element(
            "bodice_darts", "dart", "standard", "bodice_front", "integrated",
            "base_dart_shaping",
        )
    )
    assert compute_input_hash(changed) != first_hash


def test_fixed_module_cannot_claim_geometry_from_another_location() -> None:
    request = _example_request()
    request["garment_spec"]["design_intent"]["elements"][0]["location"] = "shoulder"
    request["input_hash"] = compute_input_hash(request)

    with pytest.raises(SemanticContractError) as caught:
        validate_engine_request(request)

    assert "DESIGN_COVERAGE_MODULE_MISMATCH" in {
        issue.code for issue in caught.value.issues
    }

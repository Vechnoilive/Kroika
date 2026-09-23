from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]

from kroika_backend.mock_provider import MockVisionProvider  # noqa: E402
from kroika_backend.vision_prompt import analysis_instruction, provider_analysis_schema  # noqa: E402
from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.semantic import (  # noqa: E402
    SemanticContractError,
    validate_ai_analysis,
    validate_engine_request,
    validate_project,
)


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _main_layer() -> dict:
    return {
        "source_layer_id": "main_fabric",
        "role": "main",
        "coverage": "full",
        "material_hint_ru": "Основная ткань.",
        "opacity": "opaque",
        "drape": "medium",
        "confidence": 0.9,
        "requires_confirmation": False,
        "support_status": "supported",
        "module_id": "main_fabric_layer",
    }


def _intent(status: str, element_status: str = "supported") -> dict:
    module_id = "base_dart_shaping" if element_status == "supported" else None
    return {
        "schema_version": "1.0.0",
        "source": "ai",
        "status": status,
        "elements": [{
            "source_element_id": "front_darts",
            "type": "dart",
            "variant": "standard",
            "description_ru": "Вытачки переда.",
            "location": "bodice_front",
            "construction": "integrated",
            "count": 2,
            "symmetry": "symmetric",
            "confidence": 0.8,
            "evidence_ru": "Видны две линии.",
            "requires_confirmation": False,
            "support_status": element_status,
            "module_id": module_id,
        }],
        "layers": [_main_layer()],
        "proportions": {
            "waist_position": "natural",
            "volume": "regular",
            "hem_shape": "straight",
            "asymmetry": "no",
            "confidence": 0.8,
            "support_status": "supported",
            "module_id": "bounded_visual_proportions",
        },
        "pending_questions": [],
    }


def test_new_provider_contract_requires_full_design_feature_plan():
    canonical = _example("example-ai-response.json")
    validate_document("ai-style-analysis", canonical)
    validate_ai_analysis(canonical)

    provider_schema = provider_analysis_schema()
    assert "design_features" in provider_schema["required"]
    kinds = provider_schema["properties"]["design_features"]["properties"][
        "elements"
    ]["items"]["properties"]["type"]["enum"]
    assert {"pleat", "flounce", "overlay", "sash", "drape"} <= set(kinds)

    legacy = deepcopy(canonical)
    legacy.pop("design_features")
    validate_document("ai-style-analysis", legacy)
    legacy_project = _example("example-dress-project.json")
    legacy_project["style_analysis_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    legacy_project["style_analysis_provider"] = "mock"
    legacy_project["style_analysis"] = legacy
    validate_project(legacy_project)
    instruction = analysis_instruction(["dress"], {"skirt": ["a_line"]})
    assert "design_features обязателен" in instruction
    assert "накладные" in instruction


def test_mock_analysis_exposes_a_valid_traceable_design_plan():
    response = asyncio.run(MockVisionProvider().analyze_style({
        "image_refs": ["img_demo_front_12345678"],
    }))
    validate_ai_analysis(response)
    assert response["design_features"]["elements"][0]["type"] == "dart"
    assert response["design_features"]["layers"][0]["role"] == "main"
    assert response["design_features"]["elements"][0]["evidence_ru"]


def test_design_analysis_rejects_ambiguous_or_untraceable_components():
    duplicate = _example("example-ai-response.json")
    duplicate["design_features"]["elements"].append(
        deepcopy(duplicate["design_features"]["elements"][0])
    )
    with pytest.raises(SemanticContractError) as failure:
        validate_ai_analysis(duplicate)
    assert "AI_DESIGN_ELEMENT_ID_DUPLICATE" in str(failure.value)

    no_main = _example("example-ai-response.json")
    no_main["design_features"]["layers"][0]["role"] = "overlay"
    with pytest.raises(SemanticContractError) as failure:
        validate_ai_analysis(no_main)
    assert "AI_DESIGN_MAIN_LAYER_COUNT" in str(failure.value)

    unanswered = _example("example-ai-response.json")
    unanswered["design_features"]["elements"][0]["requires_confirmation"] = True
    unanswered["targeted_questions"] = []
    with pytest.raises(SemanticContractError) as failure:
        validate_ai_analysis(unanswered)
    assert "AI_DESIGN_QUESTION_MISSING" in str(failure.value)


def test_engine_accepts_compiled_intent_and_blocks_silently_dropped_details():
    ready = _example("example-engine-request.json")
    ready["garment_spec"]["design_intent"] = _intent("ready")
    validate_document("pattern-engine-request", ready)
    validate_engine_request(ready)

    partial = _example("example-engine-request.json")
    partial["garment_spec"]["design_intent"] = _intent("partial", "planned")
    validate_document("pattern-engine-request", partial)
    with pytest.raises(SemanticContractError) as failure:
        validate_engine_request(partial)
    issue_codes = {item.code for item in failure.value.issues}
    assert "GARMENT_DESIGN_NOT_COMPILED" in issue_codes

    inconsistent = _example("example-engine-request.json")
    inconsistent["garment_spec"]["design_intent"] = _intent("ready", "planned")
    with pytest.raises(SemanticContractError) as failure:
        validate_engine_request(inconsistent)
    issue_codes = {item.code for item in failure.value.issues}
    assert {"DESIGN_INTENT_STATUS_MISMATCH", "GARMENT_DESIGN_NOT_COMPILED"} <= issue_codes

from __future__ import annotations

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

from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.semantic import (  # noqa: E402
    SemanticContractError,
    validate_engine_request,
    validate_project,
)


def _example(name: str) -> dict:
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def _element(*, support: str = "supported", included: bool = True) -> dict:
    return {
        "source_element_id": "front_darts",
        "type": "dart",
        "variant": "standard",
        "description_ru": "Вытачки переда.",
        "location": "bodice_front",
        "construction": "integrated",
        "count": 2,
        "symmetry": "symmetric",
        "confidence": 0.9,
        "evidence_ru": "Видны две линии вытачек.",
        "requires_confirmation": False,
        "included": included,
        "confirmed_by_user": True,
        "dimensions_mm": {"width": None, "length": None, "depth": None, "spacing": None},
        "support_status": support,
        "module_id": "base_dart_shaping" if support == "supported" else None,
    }


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
        "included": True,
        "confirmed_by_user": True,
        "support_status": "supported",
        "module_id": "main_fabric_layer",
    }


def _intent(*, status: str = "ready", element_status: str = "supported") -> dict:
    return {
        "schema_version": "1.0.0",
        "source": "ai",
        "status": status,
        "review_status": "confirmed",
        "reviewed_at": "2026-09-22T20:00:00Z",
        "elements": [_element(support=element_status)],
        "layers": [_main_layer()],
        "proportions": {
            "waist_position": "natural",
            "volume": "regular",
            "hem_shape": "straight",
            "asymmetry": "no",
            "confidence": 0.9,
            "confirmed_by_user": True,
            "support_status": "supported",
            "module_id": "bounded_visual_proportions",
        },
        "pending_questions": ["Есть ли скрытая складка?"],
        "question_answers": [{
            "question": "Есть ли скрытая складка?",
            "answer_ru": "Нет, это тень на фотографии.",
        }],
    }


def test_review_contract_stores_human_decisions_and_dimensions():
    intent = _intent(status="partial", element_status="planned")
    intent["elements"][0]["dimensions_mm"]["length"] = 180
    validate_document("garment-design-intent", intent)

    element = intent["elements"][0]
    assert element["confirmed_by_user"] is True
    assert element["dimensions_mm"]["length"] == 180
    assert intent["question_answers"][0]["answer_ru"]


def test_unconfirmed_review_can_be_saved_as_draft_but_not_confirmed():
    project = _example("example-dress-project.json")
    intent = _intent(status="needs_confirmation")
    intent["review_status"] = "proposed"
    intent["reviewed_at"] = None
    intent["elements"][0]["confirmed_by_user"] = False
    intent["elements"][0]["support_status"] = "needs_confirmation"
    intent["elements"][0]["module_id"] = None
    intent["question_answers"][0]["answer_ru"] = ""
    project["garment_spec"]["design_intent"] = intent
    project["garment_spec"]["selection_status"] = "proposed"
    project["garment_spec"]["confirmed_at"] = None
    validate_project(project)

    project["garment_spec"]["selection_status"] = "confirmed"
    project["garment_spec"]["confirmed_at"] = "2026-09-22T20:00:00Z"
    with pytest.raises(SemanticContractError) as failure:
        validate_project(project)
    codes = {item.code for item in failure.value.issues}
    assert {"DESIGN_REVIEW_NOT_CONFIRMED", "GARMENT_DESIGN_NOT_COMPILED"} <= codes


def test_excluded_detail_is_traceable_and_does_not_block_ready_engine_request():
    request = _example("example-engine-request.json")
    intent = _intent()
    excluded = _element(support="excluded", included=False)
    excluded["source_element_id"] = "mistaken_flounce"
    excluded["type"] = "flounce"
    excluded["variant"] = "circular"
    excluded["description_ru"] = "Предположительный волан оказался тенью."
    intent["elements"].append(excluded)
    request["garment_spec"]["design_intent"] = intent

    validate_document("pattern-engine-request", request)
    validate_engine_request(request)


def test_reviewed_planned_detail_remains_fail_closed_and_legacy_intent_still_works():
    request = _example("example-engine-request.json")
    request["garment_spec"]["design_intent"] = _intent(
        status="partial", element_status="planned",
    )
    with pytest.raises(SemanticContractError) as failure:
        validate_engine_request(request)
    assert "GARMENT_DESIGN_NOT_COMPILED" in {
        item.code for item in failure.value.issues
    }

    legacy = deepcopy(_intent())
    legacy.pop("review_status")
    legacy.pop("reviewed_at")
    legacy.pop("question_answers")
    for item in [*legacy["elements"], *legacy["layers"]]:
        item.pop("included")
        item.pop("confirmed_by_user")
        item.pop("dimensions_mm", None)
    legacy["proportions"].pop("confirmed_by_user")
    request["garment_spec"]["design_intent"] = legacy
    validate_engine_request(request)

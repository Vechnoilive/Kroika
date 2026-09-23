"""Deterministic offline replacement for Qwen used during local development."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


_DEMO_ANALYSIS: dict[str, Any] = {
    "schema_version": "1.0.0",
    "status": "needs_confirmation",
    "garment_category": "dress",
    "source_image_views": ["front"],
    "silhouette": {
        "fit": "semi_fitted", "waist_seam": "present",
        "symmetry": "symmetric", "confidence": 0.91,
    },
    "neckline": {"front": "round", "back": "unknown", "collar": "none", "confidence": 0.94},
    "sleeves": {
        "present": False, "length": "sleeveless", "type": "unknown",
        "cuff": "none", "confidence": 0.98,
    },
    "bodice": {
        "visible_darts": ["bust", "waist_front"], "princess_seams": "none",
        "yoke": "none", "confidence": 0.78,
    },
    "tailoring": {
        "front_structure": "single_panel", "breasting": "none", "lapel": "none",
        "collar": "none", "vents": [], "pockets": [], "lining": "unknown",
        "confidence": 0.54,
    },
    "lower_part": {"type": "a_line", "length_category": "midi", "slit": "unknown", "confidence": 0.87},
    "trousers": {
        "rise": "unknown", "fit": "unknown", "length": "unknown",
        "waistband": "unknown", "pleats": "unknown", "confidence": 0,
    },
    "closure": {"type": "unknown", "location": "unknown", "confidence": 0},
    "details": {
        "pockets": [], "pleats": [], "gathers": [],
        "visible_seams": ["waist"], "lining_visible": "unknown",
    },
    "fabric_hypothesis": {
        "structure": "woven", "stretch": "unknown", "weight": "medium",
        "drape": "medium", "must_confirm": True,
    },
    "observations": [{
        "feature": "waist_seam", "value": "present", "confidence": 0.91,
        "evidence": "На демонстрационном виде заметна линия соединения лифа и юбки.",
    }],
    "uncertainties": ["Mock не анализирует настоящий файл и не видит спинку изделия."],
    "targeted_questions": [
        "Какая застёжка предусмотрена на спинке?",
        "Есть ли сзади талиевые вытачки?",
    ],
    "unsupported_features": [],
    "design_features": {
        "elements": [{
            "element_id": "front_darts",
            "type": "dart",
            "variant": "standard",
            "description_ru": "Нагрудные и талиевые вытачки переда.",
            "location": "bodice_front",
            "construction": "integrated",
            "count": 2,
            "symmetry": "symmetric",
            "confidence": 0.78,
            "evidence_ru": "На демонстрационном виде показаны линии вытачек переда.",
            "requires_confirmation": False,
        }],
        "layers": [{
            "layer_id": "main_fabric",
            "role": "main",
            "coverage": "full",
            "material_hint_ru": "Основная ткань средней плотности.",
            "opacity": "opaque",
            "drape": "medium",
            "confidence": 0.72,
            "requires_confirmation": False,
        }],
        "proportions": {
            "waist_position": "natural",
            "volume": "regular",
            "hem_shape": "straight",
            "asymmetry": "no",
            "confidence": 0.84,
        },
    },
}


class MockVisionProvider:
    provider_id = "mock"
    model = "offline fixture"

    async def analyze_style(self, request: Mapping[str, Any]) -> dict[str, Any]:
        # Deliberately read only fields permitted by AIAnalysisRequest.
        _ = tuple(request["image_refs"])
        return deepcopy(_DEMO_ANALYSIS)

    async def check_connection(self) -> None:
        """The local fixture is always available and performs no network call."""


# Backwards-compatible name for integrations created before stage 10.
MockAIProvider = MockVisionProvider

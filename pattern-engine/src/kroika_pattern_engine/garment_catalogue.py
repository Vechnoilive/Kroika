"""Garment scope and independently auditable release acceptance states."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_COMMON_PENDING = {
    "formula_status": "implemented",
    "reference_status": "automated_passed",
    "invariant_status": "automated_passed",
    "paper_status": "pending",
    "expert_status": "pending",
    "toile_status": "pending",
    "production_allowed": False,
}


GARMENT_CATALOGUE: dict[str, dict[str, Any]] = {
    "dress": {
        **_COMMON_PENDING,
        "garment_type": "dress",
        "name_ru": "Платье",
        "scope_ru": "Без рукавов, круглая горловина, отрезная А-юбка, молния сзади.",
    },
    "sundress": {
        **_COMMON_PENDING,
        "garment_type": "sundress",
        "name_ru": "Сарафан",
        "scope_ru": "Без рукавов, круглая горловина, отрезная А-юбка, молния сзади.",
    },
    "skirt": {
        **_COMMON_PENDING,
        "garment_type": "skirt",
        "name_ru": "Юбка",
        "scope_ru": "А-силуэт, талиевые вытачки, двухчастный прямой пояс, молния сзади.",
    },
    "top": {
        **_COMMON_PENDING,
        "garment_type": "top",
        "name_ru": "Топ",
        "scope_ru": "Полуприлегающий топ без рукавов, круглая горловина, обтачки, молния сзади.",
    },
    "blouse": {
        **_COMMON_PENDING,
        "garment_type": "blouse",
        "name_ru": "Блузка",
        "scope_ru": "Полуприлегающая основа, круглая горловина, одношовный длинный рукав, молния сзади.",
    },
    "shirt": {
        **_COMMON_PENDING,
        "garment_type": "shirt",
        "name_ru": "Рубашка",
        "scope_ru": "Свободная основа, длинный рукав, цельнокроеная планка, стойка и воротник.",
    },
    "vest": {
        **_COMMON_PENDING,
        "garment_type": "vest",
        "name_ru": "Жилет",
        "scope_ru": "Полуприлегающая основа без рукавов, передняя планка и цельные обтачки.",
    },
    "jacket": {
        **_COMMON_PENDING,
        "garment_type": "jacket",
        "name_ru": "Лёгкий жакет",
        "scope_ru": (
            "Однобортный жакет на две пуговицы: рельеф переда, лацкан, воротник, "
            "подборт, полная подкладка, накладные карманы, шлица и одношовный рукав."
        ),
    },
    "trousers": {
        **_COMMON_PENDING,
        "garment_type": "trousers",
        "name_ru": "Прямые брюки",
        "scope_ru": (
            "Естественная талия, прямые брючины, вытачки, прямой пояс, "
            "боковые карманы и передняя молния."
        ),
    },
    "shorts": {
        **_COMMON_PENDING,
        "garment_type": "shorts",
        "name_ru": "Классические шорты",
        "scope_ru": (
            "Естественная талия, прямой низ выше колена, вытачки, прямой пояс, "
            "боковые карманы и передняя молния."
        ),
    },
}


def garment_catalogue() -> list[dict[str, Any]]:
    """Return a defensive copy so HTTP consumers cannot mutate engine policy."""

    return [_with_release_policy(item) for item in GARMENT_CATALOGUE.values()]


def garment_acceptance(garment_type: str) -> dict[str, Any]:
    try:
        return _with_release_policy(GARMENT_CATALOGUE[garment_type])
    except KeyError as error:
        raise ValueError(f"Неизвестный тип изделия: {garment_type}") from error


def _with_release_policy(item: dict[str, Any]) -> dict[str, Any]:
    """Derive the production flag instead of trusting a manually edited boolean."""

    result = deepcopy(item)
    result["production_allowed"] = all((
        result["formula_status"] == "implemented",
        result["reference_status"] == "automated_passed",
        result["invariant_status"] == "automated_passed",
        result["paper_status"] == "passed",
        result["expert_status"] == "passed",
        result["toile_status"] == "passed",
    ))
    return result


def release_gate() -> dict[str, Any]:
    """Return the single fail-closed production policy used by API and tests."""

    items = garment_catalogue()
    ready = [item["garment_type"] for item in items if item["production_allowed"]]
    blocked = [{
        "garment_type": item["garment_type"],
        "missing_gates": [
            name for name, passed in (
                ("paper", item["paper_status"] == "passed"),
                ("expert", item["expert_status"] == "passed"),
                ("toile", item["toile_status"] == "passed"),
            ) if not passed
        ],
    } for item in items if not item["production_allowed"]]
    return {
        "stage": 15,
        "status": "ready" if not blocked else "blocked",
        "production_ready": not blocked,
        "policy": "paper + expert + toile verification are required per garment",
        "ready_garments": ready,
        "blocked_garments": blocked,
    }

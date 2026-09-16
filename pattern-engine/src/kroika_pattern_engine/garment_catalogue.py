"""Stage-12 garment scope and independently auditable acceptance states."""

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
}


def garment_catalogue() -> list[dict[str, Any]]:
    """Return a defensive copy so HTTP consumers cannot mutate engine policy."""

    return [deepcopy(item) for item in GARMENT_CATALOGUE.values()]


def garment_acceptance(garment_type: str) -> dict[str, Any]:
    try:
        return deepcopy(GARMENT_CATALOGUE[garment_type])
    except KeyError as error:
        raise ValueError(f"Неизвестный тип изделия: {garment_type}") from error

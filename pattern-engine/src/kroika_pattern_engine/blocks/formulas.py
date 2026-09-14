"""Stage-7 implementation of the pinned F01-F41 scalar registry.

The equations intentionally mirror references/stage2/formula-registry.json.
Geometry code consumes their named outputs; it must not silently substitute
average measurements or clamp an invalid dart.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .errors import BlockConstructionError

FORMULA_INPUT_KEYS = (
    "bust",
    "waist",
    "hips",
    "back_bust_arc",
    "back_waist_arc",
    "back_hip_arc",
    "shoulder_span",
    "back_neck_to_waist",
    "front_neck_to_waist_over_bust",
    "bust_path_height",
    "bust_vertical_height",
    "bust_span",
    "hip_depth",
    "armscye_depth",
    "shoulder_slope_deg",
    "hip_inclination_deg",
)

CONSTANTS: dict[str, float] = {
    "side_dart_depth_factor": 0.75,
    "front_dart_fraction": 2.0 / 3.0,
    "dart_tip_factor": 0.9,
    "back_dart_threshold": 40.0,
    "back_hip_factor": 1.05,
    "armhole_ease": 25.0,
    "sleeve_balance_reduction": 20.0,
}

FORMULA_IDS = tuple(f"F{index:02d}" for index in range(1, 42))


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlockConstructionError(
            "BLOCK_INPUT_NOT_NUMERIC",
            "Для построения нужны числовые значения мерок без текста.",
            field,
        )
    result = float(value)
    if not math.isfinite(result):
        raise BlockConstructionError(
            "BLOCK_INPUT_NOT_FINITE",
            "Мерка должна быть конечным числом.",
            field,
        )
    return result


def _positive(value: float, output: str, *, zero_allowed: bool = False) -> float:
    if value < 0.0 or (value == 0.0 and not zero_allowed):
        raise BlockConstructionError(
            "BLOCK_FORMULA_OUTSIDE_DOMAIN",
            f"Формула для «{output}» вышла за допустимую область; проверьте мерки.",
            f"/formula_outputs/{output}",
        )
    return value


def calculate_block_values(inputs: Mapping[str, Any]) -> dict[str, float]:
    """Evaluate F01-F41 in registry order with the stage-2 fail-closed domain."""

    missing = [key for key in FORMULA_INPUT_KEYS if key not in inputs]
    extra = [key for key in inputs if key not in FORMULA_INPUT_KEYS]
    if missing or extra:
        detail = "Не хватает: " + ", ".join(missing) if missing else "Лишние: " + ", ".join(extra)
        raise BlockConstructionError(
            "BLOCK_FORMULA_INPUT_SET",
            f"Набор входов формул должен быть точным. {detail}.",
            "/body_measurements",
        )

    v = {key: _number(inputs[key], f"/body_measurements/{key}") for key in FORMULA_INPUT_KEYS}
    for key in FORMULA_INPUT_KEYS[:14]:
        if v[key] <= 0.0:
            raise BlockConstructionError(
                "BLOCK_LENGTH_NOT_POSITIVE",
                "Все линейные мерки должны быть больше нуля.",
                f"/body_measurements/{key}",
            )
    for key in ("shoulder_slope_deg", "hip_inclination_deg"):
        if not 0.0 <= v[key] <= 40.0:
            raise BlockConstructionError(
                "BLOCK_ANGLE_OUTSIDE_DOMAIN",
                "Угол должен находиться в исследованной вычислительной области 0–40°.",
                f"/body_measurements/{key}",
            )
    for arc, circumference in (
        ("back_bust_arc", "bust"),
        ("back_waist_arc", "waist"),
        ("back_hip_arc", "hips"),
    ):
        if v[arc] >= v[circumference]:
            raise BlockConstructionError(
                "BLOCK_ARC_NOT_SMALLER",
                "Задняя дуга должна быть меньше соответствующего полного обхвата.",
                f"/body_measurements/{arc}",
            )

    c = CONSTANTS
    r: dict[str, float] = {}

    # F01-F08: normalized body dimensions.
    r["shoulder_tan"] = _positive(math.tan(math.radians(v["shoulder_slope_deg"])), "shoulder_tan", zero_allowed=True)
    r["hip_tan"] = _positive(math.tan(math.radians(v["hip_inclination_deg"] / 2.0)), "hip_tan", zero_allowed=True)
    r["front_width"] = _positive((v["bust"] - v["back_bust_arc"]) / 2.0, "front_width")
    r["back_width"] = _positive(v["back_bust_arc"] / 2.0, "back_width")
    r["front_waist"] = _positive((v["waist"] - v["back_waist_arc"]) / 2.0, "front_waist")
    r["back_waist"] = _positive(v["back_waist_arc"] / 2.0, "back_waist")
    r["bust_level"] = _positive((2.0 * v["bust_vertical_height"] + v["bust_path_height"]) / 3.0, "bust_level")
    r["bust_from_waist"] = _positive(v["back_neck_to_waist"] - r["bust_level"], "bust_from_waist")

    # F09-F17: front bodice and its two darts.
    r["front_adjustment"] = r["shoulder_tan"] * (r["front_width"] - v["shoulder_span"] / 2.0)
    r["back_adjustment"] = r["shoulder_tan"] * (r["back_width"] - v["shoulder_span"] / 2.0)
    r["front_max_length"] = _positive(v["front_neck_to_waist_over_bust"] - r["front_adjustment"], "front_max_length")
    r["back_length"] = _positive(v["back_neck_to_waist"] - r["back_adjustment"], "back_length")
    r["front_side_target"] = _positive(
        r["back_length"] - r["shoulder_tan"] * (r["front_width"] - r["back_width"]),
        "front_side_target",
    )
    r["side_dart_width"] = _positive(r["front_max_length"] - r["front_side_target"], "side_dart_width")
    r["side_dart_depth"] = _positive(
        c["side_dart_depth_factor"] * (r["front_width"] - v["bust_span"] / 2.0),
        "side_dart_depth",
    )
    r["front_waist_dart"] = _positive(
        (r["front_width"] - r["front_waist"]) * c["front_dart_fraction"],
        "front_waist_dart",
    )
    r["front_waist_dart_depth"] = _positive(c["dart_tip_factor"] * r["bust_from_waist"], "front_waist_dart_depth")

    # F18-F22: back bodice.
    r["back_reduction"] = _positive(r["back_width"] - r["back_waist"], "back_reduction", zero_allowed=True)
    r["back_side_take"] = _positive(
        0.0 if r["back_reduction"] < c["back_dart_threshold"] else r["back_reduction"] / 6.0,
        "back_side_take",
        zero_allowed=True,
    )
    r["back_each_dart"] = _positive(
        (r["back_reduction"] - r["back_side_take"]) / 2.0,
        "back_each_dart",
        zero_allowed=True,
    )
    r["back_dart_depth"] = _positive(r["back_length"] - r["bust_level"], "back_dart_depth")
    r["back_short_dart_depth"] = _positive(c["dart_tip_factor"] * r["back_dart_depth"], "back_short_dart_depth")

    # F23-F32: fitted skirt.
    r["skirt_front_hip"] = _positive((v["hips"] - v["back_hip_arc"]) / 2.0, "skirt_front_hip")
    r["skirt_back_hip"] = _positive(v["back_hip_arc"] / 2.0, "skirt_back_hip")
    r["skirt_back_depth"] = _positive(v["hip_depth"] * c["back_hip_factor"], "skirt_back_depth")
    r["skirt_front_side_take"] = _positive(
        min(r["hip_tan"] * v["hip_depth"], r["skirt_front_hip"] - r["front_waist"]),
        "skirt_front_side_take",
        zero_allowed=True,
    )
    r["skirt_back_side_take"] = _positive(
        min(r["hip_tan"] * r["skirt_back_depth"], r["skirt_back_hip"] - r["back_waist"]),
        "skirt_back_side_take",
        zero_allowed=True,
    )
    r["skirt_front_dart"] = _positive(
        r["skirt_front_hip"] - r["front_waist"] - r["skirt_front_side_take"],
        "skirt_front_dart",
        zero_allowed=True,
    )
    r["skirt_back_dart_total"] = _positive(
        r["skirt_back_hip"] - r["back_waist"] - r["skirt_back_side_take"],
        "skirt_back_dart_total",
        zero_allowed=True,
    )
    r["skirt_back_each_dart"] = _positive(r["skirt_back_dart_total"] / 2.0, "skirt_back_each_dart", zero_allowed=True)
    r["skirt_front_dart_depth"] = _positive(v["hip_depth"] * 0.8, "skirt_front_dart_depth")
    r["skirt_back_dart_depth"] = _positive(
        v["hip_depth"] * 0.85 - (v["hip_depth"] - r["skirt_back_depth"]),
        "skirt_back_dart_depth",
    )

    # F33-F41: construction controls.
    r["armhole_depth"] = _positive(v["armscye_depth"] + c["armhole_ease"], "armhole_depth")
    r["sleeve_balance"] = _positive(v["shoulder_span"] - c["sleeve_balance_reduction"], "sleeve_balance")
    r["waist_projection"] = _positive(2.0 * (r["front_waist"] + r["back_waist"]), "waist_projection")
    r["hip_projection"] = _positive(2.0 * (r["skirt_front_hip"] + r["skirt_back_hip"]), "hip_projection")
    r["skirt_front_waist"] = _positive(
        2.0 * (r["skirt_front_hip"] - r["skirt_front_side_take"] - r["skirt_front_dart"]),
        "skirt_front_waist",
    )
    r["skirt_back_waist"] = _positive(
        2.0 * (r["skirt_back_hip"] - r["skirt_back_side_take"] - r["skirt_back_dart_total"]),
        "skirt_back_waist",
    )
    r["back_hip_extension"] = _positive(r["skirt_back_depth"] - v["hip_depth"], "back_hip_extension")
    r["front_waist_dart_leg"] = _positive(
        math.hypot(r["front_waist_dart"] / 2.0, r["front_waist_dart_depth"]),
        "front_waist_dart_leg",
    )
    r["side_dart_leg"] = _positive(
        math.hypot(r["side_dart_width"] / 2.0, r["side_dart_depth"]),
        "side_dart_leg",
    )
    return r


def constructive_formula_inputs(request: Mapping[str, Any]) -> dict[str, float]:
    """Apply confirmed ease once, preserving the measured front/back split."""

    try:
        values = request["body_measurements"]["values"]
        angles = request["body_measurements"]["angles_deg"]
        fit = request["fit_settings"]
        wearing = fit["wearing_ease_mm"]
        design = fit["design_ease_mm"]
        distribution = fit["distribution"]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "BLOCK_REQUEST_STRUCTURE",
            "Запрос не содержит полного набора мерок и настроек посадки.",
            "/",
        ) from error

    raw: dict[str, float] = {}
    for key in FORMULA_INPUT_KEYS[:14]:
        try:
            raw[key] = _number(values[key]["value"], f"/body_measurements/values/{key}/value")
        except (KeyError, TypeError) as error:
            raise BlockConstructionError(
                "BLOCK_MEASUREMENT_REQUIRED",
                f"Для базового блока нужна мерка «{key}».",
                f"/body_measurements/values/{key}",
            ) from error
    for source, target in (("shoulder_slope", "shoulder_slope_deg"), ("hip_inclination", "hip_inclination_deg")):
        try:
            raw[target] = _number(angles[source], f"/body_measurements/angles_deg/{source}")
        except (KeyError, TypeError) as error:
            raise BlockConstructionError(
                "BLOCK_MEASUREMENT_REQUIRED",
                f"Для базового блока нужен угол «{source}».",
                f"/body_measurements/angles_deg/{source}",
            ) from error

    front_share = _number(distribution.get("front_share"), "/fit_settings/distribution/front_share")
    back_share = _number(distribution.get("back_share"), "/fit_settings/distribution/back_share")
    if front_share < 0.0 or back_share < 0.0 or abs(front_share + back_share - 1.0) > 1e-12:
        raise BlockConstructionError(
            "BLOCK_EASE_DISTRIBUTION",
            "Доли прибавки переда и спинки должны быть неотрицательны и давать в сумме 1.",
            "/fit_settings/distribution",
        )

    for circumference, back_arc in (
        ("bust", "back_bust_arc"),
        ("waist", "back_waist_arc"),
        ("hips", "back_hip_arc"),
    ):
        ease = _number(wearing[circumference], f"/fit_settings/wearing_ease_mm/{circumference}")
        ease += _number(design[circumference], f"/fit_settings/design_ease_mm/{circumference}")
        if ease < 0.0:
            raise BlockConstructionError(
                "BLOCK_NEGATIVE_EASE",
                "Отрицательная прибавка не поддерживается для текущей тканой основы.",
                f"/fit_settings/wearing_ease_mm/{circumference}",
            )
        raw[circumference] += ease
        raw[back_arc] += ease * back_share

    return raw


def calculate_request_values(request: Mapping[str, Any]) -> dict[str, float]:
    return calculate_block_values(constructive_formula_inputs(request))

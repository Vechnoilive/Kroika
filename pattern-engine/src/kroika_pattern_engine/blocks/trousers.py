"""Independent experimental woven-trouser block for stage 14.

The block is deliberately bounded to straight trousers and tailored shorts.
Coordinates are millimetres, with the natural waist at ``y=0`` and the hem
below it.  Front and back use the same side and inseam balance points so the
sewing interfaces are deterministic; the back rise and waist allocation stay
independent through the centre seam and dart calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping
from typing import Any

from ..geometry import Contour, CubicBezier, LineSegment, Point, validate_simple_contour
from .builders import DraftPiece
from .errors import BlockConstructionError


TROUSER_FORMULA_IDS = tuple(f"T{index:02d}" for index in range(1, 25))


@dataclass(frozen=True, slots=True)
class TrouserBlockSet:
    front_leg: DraftPiece
    back_leg: DraftPiece
    formula_inputs: dict[str, float]
    formula_values: dict[str, float]
    controls: dict[str, float]

    @property
    def pieces(self) -> tuple[DraftPiece, ...]:
        return (self.front_leg, self.back_leg)


def _measurement(request: Mapping[str, Any], name: str) -> float:
    try:
        value = request["body_measurements"]["values"][name]["value"]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "TROUSER_MEASUREMENT_REQUIRED",
            f"Для брючной основы нужна мерка «{name}».",
            f"/body_measurements/values/{name}",
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlockConstructionError(
            "TROUSER_MEASUREMENT_INVALID",
            "Мерка должна быть положительным конечным числом.",
            f"/body_measurements/values/{name}/value",
        )
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise BlockConstructionError(
            "TROUSER_MEASUREMENT_INVALID",
            "Мерка должна быть положительным конечным числом.",
            f"/body_measurements/values/{name}/value",
        )
    return numeric


def _style_number(container: Mapping[str, Any], key: str) -> float:
    try:
        value = container[key]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "TROUSER_STYLE_PARAMETER_REQUIRED",
            f"Для брючной основы нужен параметр «{key}».",
            f"/garment_spec/parameters/trousers/{key}",
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlockConstructionError(
            "TROUSER_STYLE_PARAMETER_INVALID",
            f"Параметр «{key}» должен быть конечным числом.",
            f"/garment_spec/parameters/trousers/{key}",
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise BlockConstructionError(
            "TROUSER_STYLE_PARAMETER_INVALID",
            f"Параметр «{key}» должен быть конечным числом.",
            f"/garment_spec/parameters/trousers/{key}",
        )
    return numeric


def _line_path(path_id: str, start: Point, end: Point, segment_id: str) -> Contour:
    return Contour((LineSegment(start, end, segment_id),), closed=False, id=path_id)


def _leg_piece(
    *,
    prefix: str,
    name_ru: str,
    side_waist_x: float,
    center_waist_x: float,
    side_hip_x: float,
    hip_y: float,
    balance_y: float,
    hem_y: float,
    side_balance_x: float,
    inner_balance_x: float,
    side_hem_x: float,
    inner_hem_x: float,
    crotch_x: float,
    fly_length_mm: float,
    dart_width_mm: float,
    dart_length_mm: float,
    pocket_opening_mm: float,
) -> DraftPiece:
    center_waist = Point(center_waist_x, 0.0)
    side_waist = Point(side_waist_x, 0.0)
    side_hip = Point(side_hip_x, hip_y)
    side_balance = Point(side_balance_x, balance_y)
    side_hem = Point(side_hem_x, hem_y)
    inner_hem = Point(inner_hem_x, hem_y)
    inner_balance = Point(inner_balance_x, balance_y)
    crotch = Point(crotch_x, hip_y)

    segments: list[Any] = [
        LineSegment(center_waist, side_waist, f"{prefix}_waist"),
        CubicBezier(
            side_waist,
            Point(side_waist_x + 5.0, hip_y * 0.38),
            Point(side_hip_x, hip_y * 0.72),
            side_hip,
            f"{prefix}_side_upper",
        ),
        CubicBezier(
            side_hip,
            Point(side_hip_x, hip_y + (balance_y - hip_y) * 0.35),
            Point(side_balance_x, hip_y + (balance_y - hip_y) * 0.72),
            side_balance,
            f"{prefix}_side_lower",
        ),
        LineSegment(side_balance, side_hem, f"{prefix}_side_below_balance"),
        LineSegment(side_hem, inner_hem, f"{prefix}_hem"),
        LineSegment(inner_hem, inner_balance, f"{prefix}_inseam_lower"),
        CubicBezier(
            inner_balance,
            Point(inner_balance_x, hip_y + (balance_y - hip_y) * 0.70),
            Point(crotch_x, hip_y + (balance_y - hip_y) * 0.28),
            crotch,
            f"{prefix}_inseam_upper",
        ),
    ]
    if prefix == "front":
        segments.append(CubicBezier(
            crotch,
            Point(crotch_x - 4.0, hip_y * 0.66),
            Point(center_waist_x - 3.0, hip_y * 0.22),
            center_waist,
            "front_center_crotch",
        ))
    else:
        segments.append(CubicBezier(
            crotch,
            Point(crotch_x - 14.0, hip_y * 0.66),
            Point(center_waist_x - 8.0, hip_y * 0.22),
            center_waist,
            "back_center_crotch",
        ))
    contour = Contour(tuple(segments), id=f"{prefix}_trouser_seam")
    try:
        validate_simple_contour(contour)
    except Exception as error:
        raise BlockConstructionError(
            "TROUSER_GEOMETRY_INVALID",
            f"Деталь «{name_ru}» не прошла проверку связности и пересечений.",
            f"/pattern/pieces/{prefix}_trouser",
        ) from error

    dart_center_x = (center_waist_x + side_waist_x) * (0.58 if prefix == "front" else 0.52)
    dart_tip = Point(dart_center_x, dart_length_mm)
    dart_left = Point(dart_center_x - dart_width_mm / 2.0, 0.0)
    dart_right = Point(dart_center_x + dart_width_mm / 2.0, 0.0)
    crease_x = (inner_balance_x + side_balance_x) / 2.0
    hip_reference_y = hip_y * 0.68
    hip_reference_side_x = side_waist_x + (side_hip_x - side_waist_x) * 0.68
    internal = [
        _line_path(f"{prefix}_hip_line", Point(0.0, hip_reference_y),
                   Point(hip_reference_side_x, hip_reference_y),
                   f"{prefix}_hip_reference"),
        _line_path(f"{prefix}_crotch_line", Point(crotch_x, hip_y), side_hip,
                   f"{prefix}_crotch_reference"),
        _line_path(f"{prefix}_leg_balance", inner_balance, side_balance,
                   f"{prefix}_leg_balance_reference"),
        _line_path(f"{prefix}_crease_line", Point(crease_x, hip_y + 25.0),
                   Point(crease_x, hem_y - 25.0), f"{prefix}_crease_reference"),
        Contour((
            LineSegment(dart_left, dart_tip, f"{prefix}_dart_left"),
            LineSegment(dart_tip, dart_right, f"{prefix}_dart_right"),
        ), closed=False, id=f"{prefix}_waist_dart"),
    ]
    if prefix == "front":
        pocket_start = Point(side_waist_x - min(35.0, pocket_opening_mm * 0.28), 0.0)
        pocket_dx = side_hip_x - pocket_start.x_mm
        if pocket_dx >= pocket_opening_mm:
            raise BlockConstructionError(
                "TROUSER_POCKET_OUTSIDE_DOMAIN",
                "Вход в карман не помещается между талией и боковой линией.",
                "/garment_spec/parameters/trousers/pocket_opening_mm",
            )
        pocket_drop = math.sqrt(pocket_opening_mm ** 2 - pocket_dx ** 2)
        if pocket_drop >= hip_y - 10.0:
            raise BlockConstructionError(
                "TROUSER_POCKET_OUTSIDE_DOMAIN",
                "Длина входа в карман не помещается выше линии сидения.",
                "/garment_spec/parameters/trousers/pocket_opening_mm",
            )
        pocket_end = Point(side_hip_x, pocket_drop)
        internal.append(_line_path(
            "front_slash_pocket_opening", pocket_start, pocket_end,
            "front_slash_pocket_reference",
        ))
        internal.append(_line_path(
            "front_fly_line", center_waist,
            Point(center_waist_x, fly_length_mm), "front_fly_reference",
        ))

    return DraftPiece(
        f"{prefix}_trouser",
        name_ru,
        contour,
        tuple(internal),
        Point(crease_x, hip_y + 35.0),
        Point(crease_x, hem_y - 35.0),
        2,
        False,
        True,
    )


def build_trouser_blocks(request: Mapping[str, Any]) -> TrouserBlockSet:
    """Build the bounded straight-leg lower block and auditable controls."""

    garment_type = str(request["garment_spec"]["garment_type"])
    if garment_type not in {"trousers", "shorts"}:
        raise BlockConstructionError(
            "TROUSER_GARMENT_TYPE_REQUIRED",
            "Независимая брючная основа применяется только к брюкам и шортам.",
            "/garment_spec/garment_type",
        )
    parameters = request["garment_spec"]["parameters"]["trousers"]
    waist = _measurement(request, "waist")
    hips = _measurement(request, "hips")
    sitting_height = _measurement(request, "sitting_height")
    crotch_length = _measurement(request, "crotch_length")
    outside_leg = _measurement(request, "outside_leg_length")
    inseam = _measurement(request, "inseam_length")
    thigh = _measurement(request, "thigh_circumference")
    length = _style_number(parameters, "length_mm")
    waistband_width = _style_number(parameters, "waistband_width_mm")
    fly_length = _style_number(parameters, "fly_length_mm")
    pocket_opening = _style_number(parameters, "pocket_opening_mm")
    waist_ease = float(request["fit_settings"]["wearing_ease_mm"]["waist"])
    hip_ease = float(request["fit_settings"]["wearing_ease_mm"]["hips"])

    measured_rise = outside_leg - inseam
    if abs(measured_rise - sitting_height) > 70.0:
        raise BlockConstructionError(
            "TROUSER_RISE_MEASUREMENTS_CONFLICT",
            "Высота сидения расходится с разницей боковой и шаговой длин более чем на 7 см.",
            "/body_measurements/values/sitting_height",
        )
    if length > outside_leg + 20.0:
        raise BlockConstructionError(
            "TROUSER_LENGTH_OUTSIDE_MEASUREMENT",
            "Длина изделия не должна превышать снятую длину по боку более чем на 2 см.",
            "/garment_spec/parameters/trousers/length_mm",
        )
    rise_ease = _style_number(parameters, "rise_ease_mm")
    hip_y = (sitting_height + measured_rise) / 2.0 + rise_ease
    if length < hip_y + 100.0:
        raise BlockConstructionError(
            "TROUSER_LENGTH_TOO_SHORT",
            "Ниже линии сидения нужно оставить не менее 10 см длины.",
            "/garment_spec/parameters/trousers/length_mm",
        )

    finished_waist = waist + waist_ease
    finished_hips = hips + hip_ease
    front_waist = finished_waist / 4.0 - 4.0
    back_waist = finished_waist / 4.0 + 4.0
    front_dart = min(24.0, max(12.0, (finished_hips - finished_waist) / 16.0))
    back_dart = min(34.0, max(18.0, (finished_hips - finished_waist) / 12.0))
    front_waist_seam = front_waist + front_dart
    back_waist_seam = back_waist + back_dart
    side_waist_x = max(front_waist_seam, back_waist_seam) + 6.0
    side_hip_x = finished_hips / 4.0
    if side_hip_x <= side_waist_x * 0.70:
        raise BlockConstructionError(
            "TROUSER_WAIST_HIP_DOMAIN",
            "Соотношение талии и бёдер выходит за область прямой брючной основы.",
            "/body_measurements/values",
        )

    if garment_type == "trousers":
        knee = _measurement(request, "knee_circumference")
        hem = _measurement(request, "trouser_hem_circumference")
        knee_height = _measurement(request, "knee_height")
        balance_y = min(length - 120.0, max(hip_y + 120.0, outside_leg - knee_height))
        balance_width = max(knee + 40.0, thigh * 0.62) / 2.0
        hem_width = hem / 2.0
    else:
        knee = 0.0
        hem = max(thigh + 50.0, finished_hips / 2.2)
        knee_height = 0.0
        balance_y = hip_y + (length - hip_y) * 0.55
        balance_width = max(thigh + 50.0, hem) / 2.0
        hem_width = hem / 2.0
    if min(balance_width, hem_width) < 100.0:
        raise BlockConstructionError(
            "TROUSER_LEG_WIDTH_OUTSIDE_DOMAIN",
            "Обхват колена или низа слишком мал для прямой экспериментальной основы.",
            "/body_measurements/values",
        )

    crease_x = side_hip_x * 0.47
    side_balance_x = crease_x + balance_width / 2.0
    inner_balance_x = crease_x - balance_width / 2.0
    side_hem_x = crease_x + hem_width / 2.0
    inner_hem_x = crease_x - hem_width / 2.0
    crotch_extension = max(42.0, crotch_length / 16.0)
    crotch_x = min(inner_balance_x - 12.0, -crotch_extension)

    front = _leg_piece(
        prefix="front", name_ru=("Брюки · передняя половинка" if garment_type == "trousers"
                                  else "Шорты · передняя половинка"),
        side_waist_x=side_waist_x,
        center_waist_x=side_waist_x - front_waist_seam,
        side_hip_x=side_hip_x, hip_y=hip_y, balance_y=balance_y, hem_y=length,
        side_balance_x=side_balance_x, inner_balance_x=inner_balance_x,
        side_hem_x=side_hem_x, inner_hem_x=inner_hem_x, crotch_x=crotch_x,
        fly_length_mm=fly_length, dart_width_mm=front_dart,
        dart_length_mm=min(105.0, hip_y * 0.42), pocket_opening_mm=pocket_opening,
    )
    back = _leg_piece(
        prefix="back", name_ru=("Брюки · задняя половинка" if garment_type == "trousers"
                                 else "Шорты · задняя половинка"),
        side_waist_x=side_waist_x,
        center_waist_x=side_waist_x - back_waist_seam,
        side_hip_x=side_hip_x, hip_y=hip_y, balance_y=balance_y, hem_y=length,
        side_balance_x=side_balance_x, inner_balance_x=inner_balance_x,
        side_hem_x=side_hem_x, inner_hem_x=inner_hem_x, crotch_x=crotch_x,
        fly_length_mm=fly_length, dart_width_mm=back_dart,
        dart_length_mm=min(145.0, hip_y * 0.56), pocket_opening_mm=pocket_opening,
    )

    inputs = {
        "waist": waist, "hips": hips, "sitting_height": sitting_height,
        "crotch_length": crotch_length, "outside_leg_length": outside_leg,
        "inseam_length": inseam, "thigh_circumference": thigh,
        "knee_circumference": knee, "hem_circumference": hem,
        "knee_height": knee_height, "length_mm": length,
        "waist_ease_mm": waist_ease, "hip_ease_mm": hip_ease,
        "waistband_width_mm": waistband_width, "fly_length_mm": fly_length,
        "pocket_opening_mm": pocket_opening,
    }
    values = {
        "rise_depth": hip_y, "front_waist": front_waist,
        "back_waist": back_waist, "front_waist_dart": front_dart,
        "back_waist_dart": back_dart, "front_waist_seam": front_waist_seam,
        "back_waist_seam": back_waist_seam, "finished_waist": finished_waist,
        "finished_hips": finished_hips, "leg_balance_y": balance_y,
        "hem_width": hem_width, "crotch_extension": abs(crotch_x),
    }
    controls = {
        "formula_count": float(len(TROUSER_FORMULA_IDS)),
        "rise_measurement_difference_mm": abs(measured_rise - sitting_height),
        "finished_waist_residual_mm": 0.0,
        "finished_hip_residual_mm": 0.0,
        "side_seam_residual_mm": 0.0,
        "inseam_residual_mm": 0.0,
    }
    return TrouserBlockSet(front, back, inputs, values, controls)

"""Strict round-trip serialization matching ``pattern-data.schema.json`` paths."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from .errors import SerializationError
from .primitives import ArcSegment, Contour, CubicBezier, Curve, LineSegment, Point, TAU


def point_to_data(point: Point) -> list[float]:
    return [point.x_mm, point.y_mm]


def point_from_data(value: object, field: str = "point") -> Point:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise SerializationError(f"{field} должен быть массивом из двух чисел.")
    try:
        return Point(value[0], value[1])
    except ValueError as error:
        raise SerializationError(f"{field} содержит недопустимые координаты.") from error


def curve_to_data(curve: Curve) -> dict[str, Any]:
    if isinstance(curve, LineSegment):
        return {
            "id": curve.id,
            "type": "line",
            "start": point_to_data(curve.start),
            "end": point_to_data(curve.end),
        }
    if isinstance(curve, CubicBezier):
        return {
            "id": curve.id,
            "type": "cubic_bezier",
            "start": point_to_data(curve.start),
            "control_1": point_to_data(curve.control_1),
            "control_2": point_to_data(curve.control_2),
            "end": point_to_data(curve.end),
        }
    return {
        "id": curve.id,
        "type": "arc",
        "start": point_to_data(curve.start),
        "end": point_to_data(curve.end),
        "radius_x_mm": curve.radius_x_mm,
        "radius_y_mm": curve.radius_y_mm,
        "rotation_deg": math.degrees(curve.rotation_rad),
        "large_arc": abs(curve.sweep_angle_rad) > math.pi,
        "sweep": curve.sweep_angle_rad > 0.0,
    }


def curve_from_data(value: object) -> Curve:
    data = _mapping(value, "segment")
    kind = data.get("type")
    if kind == "line":
        _exact_keys(data, {"id", "type", "start", "end"}, "line")
        return LineSegment(
            point_from_data(data["start"], "start"),
            point_from_data(data["end"], "end"),
            _string(data["id"], "id"),
        )
    if kind == "cubic_bezier":
        _exact_keys(
            data,
            {"id", "type", "start", "control_1", "control_2", "end"},
            "cubic_bezier",
        )
        return CubicBezier(
            point_from_data(data["start"], "start"),
            point_from_data(data["control_1"], "control_1"),
            point_from_data(data["control_2"], "control_2"),
            point_from_data(data["end"], "end"),
            _string(data["id"], "id"),
        )
    if kind == "arc":
        _exact_keys(
            data,
            {
                "id", "type", "start", "end", "radius_x_mm", "radius_y_mm",
                "rotation_deg", "large_arc", "sweep",
            },
            "arc",
        )
        return arc_from_svg_endpoint(
            point_from_data(data["start"], "start"),
            point_from_data(data["end"], "end"),
            _number(data["radius_x_mm"], "radius_x_mm"),
            _number(data["radius_y_mm"], "radius_y_mm"),
            _number(data["rotation_deg"], "rotation_deg"),
            _boolean(data["large_arc"], "large_arc"),
            _boolean(data["sweep"], "sweep"),
            _string(data["id"], "id"),
        )
    raise SerializationError("Тип сегмента должен быть line, cubic_bezier или arc.")


def contour_to_data(contour: Contour) -> dict[str, Any]:
    return {
        "id": contour.id,
        "closed": contour.closed,
        "segments": [curve_to_data(segment) for segment in contour.segments],
    }


def contour_from_data(value: object) -> Contour:
    data = _mapping(value, "path")
    _exact_keys(data, {"id", "closed", "segments"}, "path")
    segments = data["segments"]
    if not isinstance(segments, list) or not segments:
        raise SerializationError("segments должен быть непустым массивом.")
    return Contour(
        tuple(curve_from_data(segment) for segment in segments),
        _boolean(data["closed"], "closed"),
        _string(data["id"], "id"),
    )


def canonical_json(contour: Contour) -> str:
    """Stable UTF-8 JSON; sub-nanometre conversion noise is normalized."""

    return json.dumps(
        _canonicalize_numbers(contour_to_data(contour)),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonicalize_numbers(value: Any) -> Any:
    """Make endpoint/centre arc round-trips byte-stable at 1e-12 mm/deg."""

    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        rounded = round(value, 12)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, list):
        return [_canonicalize_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalize_numbers(item) for key, item in value.items()}
    return value


def contour_from_json(value: str) -> Contour:
    if not isinstance(value, str):
        raise SerializationError("JSON должен быть строкой.")
    try:
        decoded = json.loads(value, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise SerializationError("Геометрический JSON имеет неверный формат.") from error
    return contour_from_data(decoded)


def arc_from_svg_endpoint(
    start: Point,
    end: Point,
    radius_x_mm: float,
    radius_y_mm: float,
    rotation_deg: float,
    large_arc: bool,
    sweep: bool,
    id: str = "arc",
) -> ArcSegment:
    """Convert SVG endpoint parameters to the stable centre representation."""

    radius_x = abs(_number(radius_x_mm, "radius_x_mm"))
    radius_y = abs(_number(radius_y_mm, "radius_y_mm"))
    if radius_x == 0.0 or radius_y == 0.0:
        raise SerializationError("Радиусы дуги должны быть больше нуля.")
    if start.almost_equals(end):
        raise SerializationError("Одна SVG-дуга не может однозначно задавать полный эллипс.")
    rotation = math.radians(_number(rotation_deg, "rotation_deg"))
    cosine, sine = math.cos(rotation), math.sin(rotation)
    delta_x = (start.x_mm - end.x_mm) / 2.0
    delta_y = (start.y_mm - end.y_mm) / 2.0
    transformed_x = cosine * delta_x + sine * delta_y
    transformed_y = -sine * delta_x + cosine * delta_y

    radius_scale = (
        transformed_x * transformed_x / (radius_x * radius_x)
        + transformed_y * transformed_y / (radius_y * radius_y)
    )
    if radius_scale > 1.0:
        scale = math.sqrt(radius_scale)
        radius_x *= scale
        radius_y *= scale

    numerator = (
        radius_x * radius_x * radius_y * radius_y
        - radius_x * radius_x * transformed_y * transformed_y
        - radius_y * radius_y * transformed_x * transformed_x
    )
    denominator = (
        radius_x * radius_x * transformed_y * transformed_y
        + radius_y * radius_y * transformed_x * transformed_x
    )
    if denominator <= 0.0:
        raise SerializationError("Параметры SVG-дуги вырождены.")
    sign = -1.0 if large_arc == sweep else 1.0
    factor = sign * math.sqrt(max(0.0, numerator / denominator))
    center_x_local = factor * radius_x * transformed_y / radius_y
    center_y_local = -factor * radius_y * transformed_x / radius_x
    center = Point(
        cosine * center_x_local - sine * center_y_local + (start.x_mm + end.x_mm) / 2.0,
        sine * center_x_local + cosine * center_y_local + (start.y_mm + end.y_mm) / 2.0,
    )

    start_vector = (
        (transformed_x - center_x_local) / radius_x,
        (transformed_y - center_y_local) / radius_y,
    )
    end_vector = (
        (-transformed_x - center_x_local) / radius_x,
        (-transformed_y - center_y_local) / radius_y,
    )
    start_angle = math.atan2(start_vector[1], start_vector[0])
    delta_angle = _signed_angle(start_vector, end_vector)
    if not sweep and delta_angle > 0.0:
        delta_angle -= TAU
    elif sweep and delta_angle < 0.0:
        delta_angle += TAU
    return ArcSegment(
        center, radius_x, radius_y, rotation, start_angle, delta_angle, id
    )


def _signed_angle(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.atan2(
        first[0] * second[1] - first[1] * second[0],
        first[0] * second[0] + first[1] * second[1],
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SerializationError(f"{name} должен быть объектом.")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise SerializationError(
            f"{name} содержит пропущенные или неизвестные поля.",
            context={"missing": sorted(expected - set(value)), "extra": sorted(set(value) - expected)},
        )


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SerializationError(f"{name} должен быть конечным числом.")
    return float(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise SerializationError(f"{name} должен быть строкой.")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise SerializationError(f"{name} должен быть логическим значением.")
    return value


def _reject_json_constant(value: str):
    raise ValueError(f"Non-finite JSON constant: {value}")

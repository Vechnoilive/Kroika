"""Offsets with an explicit sign convention and bounded approximation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from .errors import (
    DegenerateGeometryError,
    InvalidParameterError,
    OffsetCollapseError,
    UnsupportedGeometryError,
)
from .primitives import (
    ArcSegment,
    Contour,
    CubicBezier,
    DEFAULT_TOLERANCE,
    GeometryTolerance,
    LineSegment,
    Point,
    Vector,
    curve_points,
)
from .validation import validate_simple_contour


@dataclass(frozen=True, slots=True)
class OffsetResult:
    contour: Contour
    distance_outward_mm: float
    approximation_tolerance_mm: float
    join: Literal["miter", "bevel"]


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidParameterError(f"{name} должен быть конечным числом.")
    return float(value)


def offset_line(line: LineSegment, distance_left_mm: float) -> LineSegment:
    """Move a directed line to its left by ``distance_left_mm``."""

    distance = _finite(distance_left_mm, "distance_left_mm")
    shift = (line.end - line.start).normalized().left_normal().scaled(distance)
    return LineSegment(line.start + shift, line.end + shift, line.id)


def offset_arc(
    arc: ArcSegment,
    distance_left_mm: float,
    tolerance: GeometryTolerance = DEFAULT_TOLERANCE,
) -> ArcSegment:
    """Exact offset for circular arcs; general elliptical offsets are not ellipses."""

    if not tolerance.close(arc.radius_x_mm, arc.radius_y_mm):
        raise UnsupportedGeometryError(
            "Точный offset эллиптической дуги не является эллипсом; "
            "используйте offset_contour с указанной точностью аппроксимации."
        )
    distance = _finite(distance_left_mm, "distance_left_mm")
    direction = 1.0 if arc.sweep_angle_rad > 0.0 else -1.0
    radius = arc.radius_x_mm - direction * distance
    if radius <= tolerance.absolute_mm:
        raise OffsetCollapseError("Смещение схлопывает радиус дуги.")
    return ArcSegment.circular(
        arc.center, radius, arc.start_angle_rad, arc.sweep_angle_rad, arc.id
    )


def offset_contour(
    contour: Contour,
    distance_outward_mm: float,
    *,
    join: Literal["miter", "bevel"] = "miter",
    miter_limit: float = 4.0,
    curve_flatness_mm: float = 0.02,
    tolerance: GeometryTolerance = DEFAULT_TOLERANCE,
) -> OffsetResult:
    """Offset a simple closed contour.

    Positive distance is outward regardless of contour orientation; negative
    distance is inward. Curves are flattened within ``curve_flatness_mm``.
    Invalid/self-intersecting results fail explicitly instead of being silently
    repaired, which is important for later seam-allowance generation.
    """

    if not contour.closed:
        raise UnsupportedGeometryError("Общий offset сейчас определён только для замкнутого контура.")
    distance = _finite(distance_outward_mm, "distance_outward_mm")
    flatness = _finite(curve_flatness_mm, "curve_flatness_mm")
    if flatness <= 0.0:
        raise InvalidParameterError("curve_flatness_mm должен быть больше нуля.")
    miter_limit = _finite(miter_limit, "miter_limit")
    if miter_limit < 1.0:
        raise InvalidParameterError("miter_limit должен быть не меньше 1.")
    if join not in {"miter", "bevel"}:
        raise InvalidParameterError("join должен быть 'miter' или 'bevel'.")
    validate_simple_contour(contour, tolerance, flatness_mm=flatness)
    if abs(distance) <= tolerance.absolute_mm:
        return OffsetResult(contour, 0.0, 0.0, join)

    vertices: list[Point] = []
    uses_approximation = False
    for segment in contour.segments:
        flattened = curve_points(segment, flatness)
        uses_approximation = uses_approximation or not isinstance(segment, LineSegment)
        for _, point in flattened[:-1]:
            if not vertices or not point.almost_equals(vertices[-1], tolerance):
                vertices.append(point)
    if len(vertices) < 3:
        raise DegenerateGeometryError("Для offset нужны минимум три различные вершины.")

    orientation_sign = 1.0 if contour.signed_area_mm2 > 0.0 else -1.0
    # CCW interior is left, so its outward side is right (negative left distance).
    distance_left = -orientation_sign * distance
    output: list[Point] = []
    for index, vertex in enumerate(vertices):
        previous = vertices[index - 1]
        following = vertices[(index + 1) % len(vertices)]
        previous_direction = (vertex - previous).normalized(tolerance)
        following_direction = (following - vertex).normalized(tolerance)
        previous_shift = previous_direction.left_normal().scaled(distance_left)
        following_shift = following_direction.left_normal().scaled(distance_left)
        previous_corner = vertex + previous_shift
        following_corner = vertex + following_shift
        cross = previous_direction.cross(following_direction)
        cross_limit = tolerance.relative + tolerance.absolute_mm / max(
            previous.distance_to(vertex), vertex.distance_to(following), 1.0
        )

        if abs(cross) <= cross_limit:
            if previous_direction.dot(following_direction) <= 0.0:
                raise OffsetCollapseError("В контуре обнаружен разворот на 180°.")
            _append_unique(output, following_corner, tolerance)
            continue

        intersection = _infinite_line_intersection(
            previous_corner, previous_direction, following_corner, following_direction
        )
        convex = cross * orientation_sign > 0.0
        miter_length = vertex.distance_to(intersection)
        bevel_required = convex and (
            join == "bevel" or miter_length > abs(distance) * miter_limit
        )
        if bevel_required:
            _append_unique(output, previous_corner, tolerance)
            _append_unique(output, following_corner, tolerance)
        else:
            _append_unique(output, intersection, tolerance)

    if len(output) >= 2 and output[0].almost_equals(output[-1], tolerance):
        output.pop()
    if len(output) < 3:
        raise OffsetCollapseError("Смещение схлопнуло контур.")

    segments: list[LineSegment] = []
    for index, start in enumerate(output):
        end = output[(index + 1) % len(output)]
        if start.almost_equals(end, tolerance):
            continue
        segments.append(LineSegment(start, end, f"{contour.id}_offset_{index + 1}"))
    if len(segments) < 3:
        raise OffsetCollapseError("После смещения осталось меньше трёх рёбер.")
    result = Contour(tuple(segments), True, f"{contour.id}_offset", tolerance)
    validate_simple_contour(result, tolerance, flatness_mm=flatness)
    try:
        result_orientation = result.orientation
    except DegenerateGeometryError as error:
        raise OffsetCollapseError("Смещение схлопнуло площадь контура.") from error
    if result_orientation != contour.orientation:
        raise OffsetCollapseError("Смещение пересекло медиальную ось и вывернуло контур.")
    return OffsetResult(result, distance, flatness if uses_approximation else 0.0, join)


def _append_unique(
    points: list[Point], candidate: Point, tolerance: GeometryTolerance
) -> None:
    if not points or not points[-1].almost_equals(candidate, tolerance):
        points.append(candidate)


def _infinite_line_intersection(
    first_point: Point,
    first_direction: Vector,
    second_point: Point,
    second_direction: Vector,
) -> Point:
    cross = first_direction.cross(second_direction)
    if abs(cross) <= 1e-15:
        raise OffsetCollapseError("Смещённые рёбра не имеют устойчивого пересечения.")
    parameter = (second_point - first_point).cross(second_direction) / cross
    return first_point + first_direction.scaled(parameter)

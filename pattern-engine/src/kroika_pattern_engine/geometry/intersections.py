"""Deterministic intersections with exact line/ellipse cases and bounded curve fallback."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from .errors import OverlappingGeometryError
from .primitives import (
    ArcSegment,
    Curve,
    DEFAULT_TOLERANCE,
    GeometryTolerance,
    LineSegment,
    Point,
    Vector,
    curve_points,
)


@dataclass(frozen=True, slots=True)
class Intersection:
    point: Point
    first_parameter: float
    second_parameter: float
    kind: Literal["crossing", "touching", "tangent"]


def _parameter_epsilon(segment: LineSegment, tolerance: GeometryTolerance) -> float:
    return min(0.25, tolerance.absolute_mm / max(segment.length_mm, tolerance.absolute_mm))


def line_line_intersections(
    first: LineSegment,
    second: LineSegment,
    tolerance: GeometryTolerance = DEFAULT_TOLERANCE,
) -> tuple[Intersection, ...]:
    """Intersect finite segments; a non-zero collinear overlap is explicitly ambiguous."""

    p = first.start
    q = second.start
    r = first.end - first.start
    s = second.end - second.start
    cross = r.cross(s)
    q_minus_p = q - p
    cross_limit = tolerance.absolute_mm * max(r.length_mm, s.length_mm, 1.0)
    first_epsilon = _parameter_epsilon(first, tolerance)
    second_epsilon = _parameter_epsilon(second, tolerance)

    if abs(cross) <= cross_limit:
        if abs(q_minus_p.cross(r)) > cross_limit:
            return ()
        rr = r.dot(r)
        t0 = q_minus_p.dot(r) / rr
        t1 = t0 + s.dot(r) / rr
        low = max(0.0, min(t0, t1))
        high = min(1.0, max(t0, t1))
        if high < low - first_epsilon:
            return ()
        if high - low > first_epsilon:
            raise OverlappingGeometryError(
                "Коллинеарные отрезки перекрываются на интервале; "
                "единственная точка пересечения не определена."
            )
        t = min(1.0, max(0.0, (low + high) / 2.0))
        point = first.point_at(t)
        ss = s.dot(s)
        u = (point - q).dot(s) / ss
        return (Intersection(point, t, min(1.0, max(0.0, u)), "touching"),)

    t = q_minus_p.cross(s) / cross
    u = q_minus_p.cross(r) / cross
    if not (-first_epsilon <= t <= 1.0 + first_epsilon):
        return ()
    if not (-second_epsilon <= u <= 1.0 + second_epsilon):
        return ()
    t = min(1.0, max(0.0, t))
    u = min(1.0, max(0.0, u))
    endpoint = (
        t <= first_epsilon
        or t >= 1.0 - first_epsilon
        or u <= second_epsilon
        or u >= 1.0 - second_epsilon
    )
    return (Intersection(first.point_at(t), t, u, "touching" if endpoint else "crossing"),)


def line_arc_intersections(
    line: LineSegment,
    arc: ArcSegment,
    tolerance: GeometryTolerance = DEFAULT_TOLERANCE,
) -> tuple[Intersection, ...]:
    """Exact finite line / rotated ellipse intersection, filtered to the arc sweep."""

    cosine, sine = math.cos(arc.rotation_rad), math.sin(arc.rotation_rad)

    def local(point: Point) -> Point:
        delta = point - arc.center
        return Point(
            (cosine * delta.dx_mm + sine * delta.dy_mm) / arc.radius_x_mm,
            (-sine * delta.dx_mm + cosine * delta.dy_mm) / arc.radius_y_mm,
        )

    start = local(line.start)
    end = local(line.end)
    direction = end - start
    a = direction.dot(direction)
    b = 2.0 * Vector(start.x_mm, start.y_mm).dot(direction)
    c = start.x_mm * start.x_mm + start.y_mm * start.y_mm - 1.0
    discriminant = b * b - 4.0 * a * c
    dimensionless_tolerance = tolerance.relative + tolerance.absolute_mm / max(
        arc.radius_x_mm, arc.radius_y_mm, 1.0
    )
    if discriminant < -dimensionless_tolerance:
        return ()
    discriminant = max(0.0, discriminant)
    root = math.sqrt(discriminant)
    candidates = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
    if root <= dimensionless_tolerance:
        candidates = [candidates[0]]
    parameter_epsilon = _parameter_epsilon(line, tolerance)
    found: list[Intersection] = []
    for line_parameter in sorted(candidates):
        if not -parameter_epsilon <= line_parameter <= 1.0 + parameter_epsilon:
            continue
        line_parameter = min(1.0, max(0.0, line_parameter))
        point = line.point_at(line_parameter)
        local_point = local(point)
        angle = math.atan2(local_point.y_mm, local_point.x_mm)
        arc_parameter = arc.parameter_for_angle(angle)
        if arc_parameter is None:
            continue
        line_tangent = line.tangent_at(line_parameter)
        arc_tangent = arc.tangent_at(arc_parameter)
        tangent_limit = tolerance.relative + tolerance.absolute_mm / max(
            line_tangent.length_mm, arc_tangent.length_mm, 1.0
        )
        normalized_cross = abs(line_tangent.cross(arc_tangent)) / (
            line_tangent.length_mm * arc_tangent.length_mm
        )
        endpoint = (
            line_parameter <= parameter_epsilon
            or line_parameter >= 1.0 - parameter_epsilon
            or arc_parameter <= 1e-12
            or arc_parameter >= 1.0 - 1e-12
        )
        kind: Literal["crossing", "touching", "tangent"] = "tangent" if normalized_cross <= tangent_limit else (
            "touching" if endpoint else "crossing"
        )
        found.append(Intersection(point, line_parameter, arc_parameter, kind))
    return _deduplicate(found, tolerance)


def intersections(
    first: Curve,
    second: Curve,
    tolerance: GeometryTolerance = DEFAULT_TOLERANCE,
    *,
    flatness_mm: float | None = None,
) -> tuple[Intersection, ...]:
    """Intersect any supported curves.

    Line/line and line/elliptical-arc cases are analytic. Other pairs use a
    deterministic adaptive polyline whose maximum requested flatness is part
    of the public numerical policy.
    """

    if isinstance(first, LineSegment) and isinstance(second, LineSegment):
        return line_line_intersections(first, second, tolerance)
    if isinstance(first, LineSegment) and isinstance(second, ArcSegment):
        return line_arc_intersections(first, second, tolerance)
    if isinstance(first, ArcSegment) and isinstance(second, LineSegment):
        return tuple(
            Intersection(item.point, item.second_parameter, item.first_parameter, item.kind)
            for item in line_arc_intersections(second, first, tolerance)
        )

    flatness = flatness_mm or tolerance.curve_flatness_mm
    first_points = curve_points(first, flatness)
    second_points = curve_points(second, flatness)
    first_pieces = _polyline_pieces(first_points, "first_flat", tolerance)
    second_pieces = _polyline_pieces(second_points, "second_flat", tolerance)
    found: list[Intersection] = []
    for first_t0, first_t1, first_line in first_pieces:
        first_box = first_line.bounding_box.expanded(tolerance.absolute_mm)
        for second_t0, second_t1, second_line in second_pieces:
            second_box = second_line.bounding_box.expanded(tolerance.absolute_mm)
            if not _boxes_overlap(first_box, second_box):
                continue
            for item in line_line_intersections(first_line, second_line, tolerance):
                first_parameter = first_t0 + (first_t1 - first_t0) * item.first_parameter
                second_parameter = second_t0 + (second_t1 - second_t0) * item.second_parameter
                first_tangent = first.tangent_at(first_parameter)
                second_tangent = second.tangent_at(second_parameter)
                denominator = first_tangent.length_mm * second_tangent.length_mm
                normalized_cross = abs(first_tangent.cross(second_tangent)) / max(
                    denominator, tolerance.absolute_mm
                )
                kind = "tangent" if normalized_cross <= 1e-7 else item.kind
                found.append(
                    Intersection(item.point, first_parameter, second_parameter, kind)
                )
    return _deduplicate(found, tolerance, distance_mm=max(tolerance.absolute_mm, flatness * 2.0))


def _polyline_pieces(points, prefix: str, tolerance: GeometryTolerance):
    pieces = []
    for index, (first, second) in enumerate(zip(points, points[1:], strict=False)):
        if first[1].almost_equals(second[1], tolerance):
            continue
        pieces.append(
            (first[0], second[0], LineSegment(first[1], second[1], f"{prefix}_{index}"))
        )
    return pieces


def _boxes_overlap(first, second) -> bool:
    return not (
        first.max_x_mm < second.min_x_mm
        or second.max_x_mm < first.min_x_mm
        or first.max_y_mm < second.min_y_mm
        or second.max_y_mm < first.min_y_mm
    )


def _deduplicate(
    values: list[Intersection],
    tolerance: GeometryTolerance,
    *,
    distance_mm: float | None = None,
) -> tuple[Intersection, ...]:
    distance = distance_mm or tolerance.absolute_mm
    ordered = sorted(
        values,
        key=lambda item: (
            round(item.first_parameter, 15),
            round(item.second_parameter, 15),
            item.point.x_mm,
            item.point.y_mm,
        ),
    )
    result: list[Intersection] = []
    for candidate in ordered:
        existing_index = next(
            (
                index
                for index, existing in enumerate(result)
                if existing.point.distance_to(candidate.point) <= distance
            ),
            None,
        )
        if existing_index is None:
            result.append(candidate)
            continue
        existing = result[existing_index]
        priorities = {"crossing": 0, "touching": 1, "tangent": 2}
        if priorities[candidate.kind] > priorities[existing.kind]:
            result[existing_index] = candidate
    return tuple(result)

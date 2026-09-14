"""Topology checks kept separate from primitive construction."""

from __future__ import annotations

from .errors import SelfIntersectionError
from .intersections import intersections, line_line_intersections
from .primitives import Contour, CubicBezier, DEFAULT_TOLERANCE, GeometryTolerance, LineSegment


def validate_simple_contour(
    contour: Contour,
    tolerance: GeometryTolerance = DEFAULT_TOLERANCE,
    *,
    flatness_mm: float | None = None,
) -> None:
    """Reject crossings, touches and overlaps outside expected adjacent endpoints."""

    count = len(contour.segments)
    for index, curve in enumerate(contour.segments):
        if isinstance(curve, CubicBezier):
            _validate_cubic_self_intersection(curve, tolerance, flatness_mm)
        for other_index in range(index + 1, count):
            other = contour.segments[other_index]
            adjacent = other_index == index + 1 or (
                contour.closed and index == 0 and other_index == count - 1
            )
            values = intersections(
                curve, other, tolerance, flatness_mm=flatness_mm
            )
            for item in values:
                expected_endpoint = adjacent and (
                    item.point.almost_equals(curve.end, tolerance)
                    or item.point.almost_equals(curve.start, tolerance)
                ) and (
                    item.point.almost_equals(other.start, tolerance)
                    or item.point.almost_equals(other.end, tolerance)
                )
                if not expected_endpoint:
                    raise SelfIntersectionError(
                        "Контур пересекает сам себя.",
                        context={"first_segment": curve.id, "second_segment": other.id},
                    )


def _validate_cubic_self_intersection(
    curve: CubicBezier,
    tolerance: GeometryTolerance,
    flatness_mm: float | None,
) -> None:
    points = curve.flatten(flatness_mm or tolerance.curve_flatness_mm)
    pieces = [
        LineSegment(first[1], second[1], f"flat_{index}")
        for index, (first, second) in enumerate(zip(points, points[1:], strict=False))
        if not first[1].almost_equals(second[1], tolerance)
    ]
    for index, first in enumerate(pieces):
        for other_index in range(index + 2, len(pieces)):
            # Consecutive polyline pieces meet by design. For a closed Bezier,
            # its first/last endpoint meeting is also the intended closure.
            if index == 0 and other_index == len(pieces) - 1 and curve.start.almost_equals(
                curve.end, tolerance
            ):
                continue
            if line_line_intersections(first, pieces[other_index], tolerance):
                raise SelfIntersectionError(
                    "Кривая Безье пересекает саму себя.", context={"segment": curve.id}
                )

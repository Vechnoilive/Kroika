from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

from hypothesis import given, settings, strategies as st
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src")]

from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine  # noqa: E402
from kroika_pattern_engine.geometry import (  # noqa: E402
    AffineTransform,
    ArcSegment,
    Contour,
    CubicBezier,
    DegenerateGeometryError,
    DisconnectedContourError,
    InvalidCoordinateError,
    InvalidParameterError,
    LineSegment,
    MAX_ABS_COORDINATE_MM,
    OffsetCollapseError,
    OpenContourError,
    OverlappingGeometryError,
    Point,
    SerializationError,
    SelfIntersectionError,
    UnsupportedGeometryError,
    Vector,
    arc_from_svg_endpoint,
    canonical_json,
    contour_from_json,
    contour_to_data,
    intersections,
    line_arc_intersections,
    line_line_intersections,
    offset_arc,
    offset_contour,
    offset_line,
    run_core_diagnostics,
    validate_simple_contour,
)


def rectangle(width: float = 100.0, height: float = 50.0, *, contour_id: str = "rectangle") -> Contour:
    points = (Point(0, 0), Point(width, 0), Point(width, height), Point(0, height))
    return Contour(
        tuple(
            LineSegment(points[index], points[(index + 1) % 4], f"edge_{index + 1}")
            for index in range(4)
        ),
        id=contour_id,
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "10"])
def test_coordinates_reject_non_finite_and_non_numeric_values(value):
    with pytest.raises(InvalidCoordinateError) as error:
        Point(value, 0)
    assert error.value.code == "GEOMETRY_INVALID_COORDINATE"


def test_finite_values_outside_documented_computational_domain_are_rejected():
    with pytest.raises(InvalidCoordinateError, match="вычислительную область"):
        Point(MAX_ABS_COORDINATE_MM + 1, 0)
    with pytest.raises(InvalidCoordinateError, match="координатную область"):
        ArcSegment.circular(Point(MAX_ABS_COORDINATE_MM - 5, 0), 10, 0, math.pi)


def test_vectors_and_degenerate_primitives_fail_explicitly():
    assert Vector(3, 4).length_mm == 5
    assert Vector(3, 4).normalized().length_mm == pytest.approx(1)
    with pytest.raises(DegenerateGeometryError, match="нулевой длины"):
        Vector(0, 0).normalized()
    with pytest.raises(DegenerateGeometryError, match="должны различаться"):
        LineSegment(Point(1, 1), Point(1, 1))


def test_line_length_parameter_and_bounds_are_exact():
    line = LineSegment(Point(-2, 4), Point(4, 12), "diagonal")
    assert line.length_mm == 10
    assert line.point_at(0.5) == Point(1, 8)
    assert line.bounding_box.width_mm == 6
    with pytest.raises(InvalidParameterError, match=r"\[0, 1\]"):
        line.point_at(1.01)


def test_circular_arc_length_bounds_and_sector_area_are_exact():
    arc = ArcSegment.circular(Point(0, 0), 10, 0, math.pi / 2, "quarter")
    sector = Contour(
        (
            arc,
            LineSegment(arc.end, Point(0, 0), "radius_2"),
            LineSegment(Point(0, 0), arc.start, "radius_1"),
        ),
        id="sector",
    )
    assert arc.length_mm == pytest.approx(5 * math.pi, abs=1e-12)
    assert arc.bounding_box.min_x_mm == pytest.approx(0, abs=1e-12)
    assert arc.bounding_box.max_y_mm == pytest.approx(10, abs=1e-12)
    assert sector.area_mm2 == pytest.approx(25 * math.pi, abs=1e-12)


def test_rotated_elliptical_arc_length_and_bounds_cover_samples():
    quarter = ArcSegment(Point(5, -7), 100, 50, math.radians(23), 0, math.pi / 2)
    assert quarter.length_mm == pytest.approx(121.10560275684584, rel=1e-12)
    bounds = quarter.bounding_box
    for index in range(101):
        point = quarter.point_at(index / 100)
        assert bounds.min_x_mm - 1e-10 <= point.x_mm <= bounds.max_x_mm + 1e-10
        assert bounds.min_y_mm - 1e-10 <= point.y_mm <= bounds.max_y_mm + 1e-10


def test_bezier_length_split_and_exact_extrema():
    curve = CubicBezier(
        Point(0, 0), Point(0, 100), Point(100, 100), Point(100, 0), "armscye"
    )
    left, right = curve.split()
    assert left.end == right.start == Point(50, 75)
    assert curve.length_mm == pytest.approx(200, abs=5e-4)
    assert curve.bounding_box.max_y_mm == pytest.approx(75, abs=1e-12)
    closed = Contour((curve, LineSegment(curve.end, curve.start, "base")), id="arch")
    assert closed.area_mm2 == pytest.approx(6_000, abs=1e-10)


def test_contour_requires_connected_segments_and_area_requires_closure():
    with pytest.raises(DisconnectedContourError):
        Contour(
            (
                LineSegment(Point(0, 0), Point(10, 0), "first"),
                LineSegment(Point(11, 0), Point(11, 10), "second"),
            ),
            closed=False,
        )
    open_path = Contour((LineSegment(Point(0, 0), Point(10, 0)),), closed=False)
    with pytest.raises(OpenContourError):
        _ = open_path.area_mm2


def test_rectangle_area_orientation_reverse_and_length():
    contour = rectangle()
    assert contour.area_mm2 == 5_000
    assert contour.length_mm == 300
    assert contour.orientation == "counterclockwise"
    reversed_contour = contour.reversed()
    assert reversed_contour.signed_area_mm2 == -5_000
    assert reversed_contour.orientation == "clockwise"


@settings(max_examples=80, deadline=None)
@given(
    width=st.floats(min_value=1, max_value=10_000, allow_nan=False, allow_infinity=False),
    height=st.floats(min_value=1, max_value=10_000, allow_nan=False, allow_infinity=False),
    scale_x=st.floats(min_value=0.05, max_value=20, allow_nan=False, allow_infinity=False),
    scale_y=st.floats(min_value=-20, max_value=-0.05, allow_nan=False, allow_infinity=False),
)
def test_affine_area_scales_by_absolute_determinant(width, height, scale_x, scale_y):
    contour = rectangle(width, height)
    transform = AffineTransform.scale(scale_x, scale_y)
    transformed = contour.transformed(transform)
    assert transformed.area_mm2 == pytest.approx(
        contour.area_mm2 * abs(transform.determinant), rel=1e-11, abs=1e-7
    )
    assert transformed.orientation != contour.orientation


@settings(max_examples=80, deadline=None)
@given(
    x=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    y=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    dx=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    dy=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    angle=st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False, allow_infinity=False),
)
def test_rigid_transform_preserves_distance(x, y, dx, dy, angle):
    first = Point(x, y)
    second = Point(x + dx, y + dy)
    transform = AffineTransform.rotation(angle).then(AffineTransform.translation(123, -456))
    assert transform.apply_point(first).distance_to(transform.apply_point(second)) == pytest.approx(
        first.distance_to(second), rel=2e-10, abs=2e-9
    )


def test_rotation_around_a_point_keeps_that_point_fixed():
    center = Point(12, -3)
    transform = AffineTransform.rotation_degrees(91, center)
    assert transform.apply_point(center).almost_equals(center)


def test_non_uniform_arc_transform_is_rejected_without_approximation():
    arc = ArcSegment.circular(Point(0, 0), 20, 0, math.pi)
    with pytest.raises(UnsupportedGeometryError, match="равномерном"):
        arc.transformed(AffineTransform.scale(2, 1))


def test_arc_similarity_transform_preserves_endpoints_and_scales_length():
    arc = ArcSegment(Point(3, -4), 20, 8, math.radians(17), 0.4, -2.2, "arc")
    transform = AffineTransform.scale(-2, 2).then(AffineTransform.translation(50, 70))
    transformed = arc.transformed(transform)
    assert transformed.start.distance_to(transform.apply_point(arc.start)) < 1e-10
    assert transformed.end.distance_to(transform.apply_point(arc.end)) < 1e-10
    assert transformed.length_mm == pytest.approx(arc.length_mm * 2, rel=1e-12)
    assert transformed.sweep_angle_rad == pytest.approx(-arc.sweep_angle_rad)


def test_line_intersections_cover_crossing_parallel_touch_and_overlap():
    horizontal = LineSegment(Point(-10, 0), Point(10, 0), "horizontal")
    vertical = LineSegment(Point(0, -10), Point(0, 10), "vertical")
    crossing = line_line_intersections(horizontal, vertical)
    assert len(crossing) == 1
    assert crossing[0].point == Point(0, 0)
    assert crossing[0].kind == "crossing"
    assert line_line_intersections(
        horizontal, LineSegment(Point(-10, 1), Point(10, 1), "parallel")
    ) == ()
    touching = line_line_intersections(
        horizontal, LineSegment(Point(10, 0), Point(10, 5), "touch")
    )
    assert touching[0].kind == "touching"
    with pytest.raises(OverlappingGeometryError):
        line_line_intersections(
            horizontal, LineSegment(Point(-5, 0), Point(15, 0), "overlap")
        )


@settings(max_examples=100, deadline=None)
@given(
    x=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    y=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    half_width=st.floats(min_value=0.1, max_value=1e4, allow_nan=False, allow_infinity=False),
    half_height=st.floats(min_value=0.1, max_value=1e4, allow_nan=False, allow_infinity=False),
)
def test_line_intersection_is_symmetric(x, y, half_width, half_height):
    first = LineSegment(Point(x - half_width, y), Point(x + half_width, y), "first")
    second = LineSegment(Point(x, y - half_height), Point(x, y + half_height), "second")
    direct = line_line_intersections(first, second)[0]
    reversed_order = line_line_intersections(second, first)[0]
    assert direct.point.distance_to(reversed_order.point) <= 1e-8
    assert direct.first_parameter == pytest.approx(reversed_order.second_parameter, abs=1e-12)


def test_line_ellipse_intersections_detect_tangent_and_sweep_filter():
    top_half = ArcSegment(Point(0, 0), 100, 50, 0, 0, math.pi, "top_half")
    tangent = line_arc_intersections(
        LineSegment(Point(-200, 50), Point(200, 50), "tangent"), top_half
    )
    assert len(tangent) == 1
    assert tangent[0].point.distance_to(Point(0, 50)) < 1e-8
    assert tangent[0].kind == "tangent"
    right_half = ArcSegment.circular(Point(0, 0), 10, -math.pi / 2, math.pi, "right_half")
    diameter = LineSegment(Point(-20, 0), Point(20, 0), "diameter")
    filtered = line_arc_intersections(diameter, right_half)
    assert len(filtered) == 1
    assert filtered[0].point.distance_to(Point(10, 0)) < 1e-8


def test_bezier_line_intersection_uses_bounded_flattening():
    curve = CubicBezier(
        Point(0, 0), Point(0, 100), Point(100, 100), Point(100, 0), "curve"
    )
    tangent = LineSegment(Point(-10, 75), Point(110, 75), "line")
    found = intersections(curve, tangent, flatness_mm=1e-4)
    assert len(found) == 1
    assert found[0].point.distance_to(Point(50, 75)) <= 2e-4
    assert found[0].kind == "tangent"


def test_simple_contour_validation_rejects_bow_tie():
    points = (Point(0, 0), Point(10, 10), Point(0, 10), Point(10, 0))
    bow_tie = Contour(
        tuple(
            LineSegment(points[index], points[(index + 1) % 4], f"edge_{index}")
            for index in range(4)
        ),
        id="bow_tie",
    )
    with pytest.raises(SelfIntersectionError, match="сам себя") as error:
        validate_simple_contour(bow_tie)
    assert error.value.code == "GEOMETRY_SELF_INTERSECTION"


def test_exact_line_and_circular_arc_offsets_follow_left_side():
    line = LineSegment(Point(0, 0), Point(10, 0), "edge")
    shifted = offset_line(line, 3)
    assert shifted.start == Point(0, 3)
    assert shifted.end == Point(10, 3)
    counterclockwise = ArcSegment.circular(Point(0, 0), 10, 0, math.pi / 2)
    assert offset_arc(counterclockwise, 2).radius_x_mm == 8
    clockwise = counterclockwise.reversed()
    assert offset_arc(clockwise, 2).radius_x_mm == 12
    ellipse = ArcSegment(Point(0, 0), 10, 5, 0, 0, math.pi)
    with pytest.raises(UnsupportedGeometryError, match="эллиптической"):
        offset_arc(ellipse, 1)


@settings(max_examples=80, deadline=None)
@given(
    width=st.floats(min_value=20, max_value=5_000, allow_nan=False, allow_infinity=False),
    height=st.floats(min_value=20, max_value=5_000, allow_nan=False, allow_infinity=False),
    factor=st.floats(min_value=0.001, max_value=0.24, allow_nan=False, allow_infinity=False),
)
def test_rectangle_offsets_preserve_expected_area(width, height, factor):
    distance = min(width, height) * factor
    source = rectangle(width, height)
    outward = offset_contour(source, distance).contour
    inward = offset_contour(source, -distance).contour
    assert outward.area_mm2 == pytest.approx(
        (width + 2 * distance) * (height + 2 * distance), rel=2e-10, abs=1e-7
    )
    assert inward.area_mm2 == pytest.approx(
        (width - 2 * distance) * (height - 2 * distance), rel=2e-10, abs=1e-7
    )


def test_curve_offset_reports_approximation_and_collapse_is_blocked():
    arc = ArcSegment.circular(Point(0, 0), 20, 0, math.pi, "arc")
    half_disk = Contour(
        (arc, LineSegment(arc.end, arc.start, "diameter")), id="half_disk"
    )
    result = offset_contour(half_disk, 2, curve_flatness_mm=0.05)
    assert result.approximation_tolerance_mm == 0.05
    assert result.contour.area_mm2 > half_disk.area_mm2
    with pytest.raises(OffsetCollapseError):
        offset_contour(rectangle(100, 50), -30)


def test_mixed_geometry_round_trip_is_canonical_and_schema_compatible():
    arc = ArcSegment(Point(50, 0), 50, 30, math.radians(15), math.pi, math.pi, "neckline")
    contour = Contour(
        (
            arc,
            CubicBezier(arc.end, Point(100, 50), Point(0, 50), arc.start, "hem_curve"),
        ),
        id="front_piece",
    )
    encoded = canonical_json(contour)
    restored = contour_from_json(encoded)
    assert canonical_json(restored) == encoded
    # SVG endpoint arcs are reconstructed through centre parameters; the
    # round-trip error stays far below the 0.001 mm geometry tolerance.
    assert restored.length_mm == pytest.approx(contour.length_mm, abs=1e-5)
    assert restored.area_mm2 == pytest.approx(contour.area_mm2, abs=1e-3)

    pattern = {
        "schema_version": "1.0.0",
        "unit": "mm",
        "pieces": [{
            "id": "front", "name_ru": "Перед", "cut_quantity": 1,
            "cut_on_fold": True, "mirrored_pair": False,
            "seam_contour": contour_to_data(contour), "cutting_contour": None,
            "internal_paths": [],
            "grainline": {"start": [50, 10], "end": [50, 100]},
            "notches": [], "annotations": [],
        }],
        "seam_pairs": [],
    }
    validate_document("pattern-data", pattern)


def test_svg_endpoint_conversion_corrects_small_radii_and_round_trips_large_arc():
    corrected = arc_from_svg_endpoint(Point(0, 0), Point(100, 0), 10, 10, 0, False, True)
    assert corrected.radius_x_mm == pytest.approx(50)
    source = ArcSegment(Point(20, -10), 60, 30, math.radians(25), 0.4, 1.6 * math.pi, "arc")
    restored = contour_from_json(
        canonical_json(
            Contour((source, LineSegment(source.end, source.start, "close")), id="shape")
        )
    ).segments[0]
    assert isinstance(restored, ArcSegment)
    for parameter in (0, 0.25, 0.5, 0.75, 1):
        assert source.point_at(parameter).distance_to(restored.point_at(parameter)) < 1e-8


@settings(max_examples=80, deadline=None)
@given(
    center_x=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    center_y=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    radius_x=st.floats(min_value=1, max_value=2_000, allow_nan=False, allow_infinity=False),
    radius_y=st.floats(min_value=1, max_value=2_000, allow_nan=False, allow_infinity=False),
    rotation=st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False, allow_infinity=False),
    start_angle=st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False, allow_infinity=False),
    sweep_magnitude=st.floats(
        min_value=0.05, max_value=2 * math.pi - 0.05, allow_nan=False, allow_infinity=False
    ),
    sweep_sign=st.sampled_from((-1.0, 1.0)),
)
def test_elliptical_arc_schema_round_trip_stays_below_core_tolerance(
    center_x, center_y, radius_x, radius_y, rotation, start_angle, sweep_magnitude, sweep_sign
):
    arc = ArcSegment(
        Point(center_x, center_y), radius_x, radius_y, rotation,
        start_angle, sweep_magnitude * sweep_sign, "arc",
    )
    source = Contour((arc, LineSegment(arc.end, arc.start, "chord")), id="shape")
    restored = contour_from_json(canonical_json(source)).segments[0]
    assert isinstance(restored, ArcSegment)
    assert max(
        arc.point_at(parameter).distance_to(restored.point_at(parameter))
        for parameter in (0, 0.25, 0.5, 0.75, 1)
    ) < 1e-3


@pytest.mark.parametrize(
    "payload",
    [
        '{"closed":true,"id":"x","segments":[],"extra":1}',
        '{"closed":true,"id":"x","segments":[{"id":"a","type":"line","start":[NaN,0],"end":[1,0]}]}',
        "[]",
    ],
)
def test_serialization_rejects_unknown_fields_non_finite_and_wrong_shapes(payload):
    with pytest.raises(SerializationError):
        contour_from_json(payload)


def test_core_diagnostic_and_engine_boundary_are_deterministic():
    diagnostic = run_core_diagnostics()
    assert diagnostic == run_core_diagnostics()
    assert diagnostic["precision"] == "ieee754-binary64"
    assert diagnostic["unit"] == "mm"
    assert len(diagnostic["fingerprint"]) == 64
    fixture = json.loads(
        (ROOT / "references" / "stage6" / "geometry-diagnostic.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostic["version"] == fixture["geometry_core_version"]
    assert diagnostic["precision"] == fixture["precision"]
    assert diagnostic["unit"] == fixture["unit"]
    assert diagnostic["fingerprint"] == fixture["canonical_fingerprint"]

    request = json.loads(
        (ROOT / "examples" / "v1" / "example-engine-request.json").read_text(encoding="utf-8")
    )
    fixed_time = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    engine = GeometryPatternEngine(clock=lambda: fixed_time)
    first = engine.generate(request)
    second = engine.generate(deepcopy(request))
    assert first == second
    assert first["status"] == "succeeded"
    assert first["pattern"] is not None
    assert first["validation_report"]["checks"][0]["status"] == "passed"
    assert "EXPERT_BLOCK_REVIEW_REQUIRED" in {
        issue["code"] for issue in first["validation_report"]["issues"]
    }


def test_stage6_runtime_bootstrap_is_the_latest_layer():
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-stage6.txt").read_text(encoding="utf-8")
    latest_requirements = max(
        ROOT.glob("requirements-stage*.txt"),
        key=lambda path: int(path.stem.removeprefix("requirements-stage")),
    ).name
    assert 'ROOT / "requirements-stage5.txt"' in launcher
    assert '"requirements-stage6.txt"' in launcher
    assert f'"-r", str(ROOT / "{latest_requirements}")' in launcher
    assert "requirements-stage6.txt" in dockerfile
    assert f"-r {latest_requirements}" in dockerfile
    assert "-r requirements-stage5.txt" in requirements
    assert "hypothesis==6.168.0" in requirements


def test_stage6_documentation_names_accuracy_and_fail_closed_boundaries():
    documentation = (ROOT / "docs" / "GEOMETRY_CORE.md").read_text(encoding="utf-8")
    report = (ROOT / "docs" / "STAGE_06_REPORT.md").read_text(encoding="utf-8")
    for term in ("IEEE-754 binary64", "миллиметры", "flatness_mm", "самопересечения"):
        assert term in documentation
    assert "BASE_BLOCKS_STAGE_NOT_READY" in documentation
    assert "PASSED" in report


def test_geometry_package_remains_independent_from_web_ai_database_and_native_geometry():
    geometry_root = ROOT / "pattern-engine" / "src" / "kroika_pattern_engine" / "geometry"
    source = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in sorted(geometry_root.glob("*.py"))
    )
    for forbidden in ("fastapi", "qwen", "gemini", "sqlite", "shapely", "numpy"):
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source

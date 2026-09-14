"""Double-precision, millimetre-based geometry primitives.

Python ``float`` is IEEE-754 binary64.  Every public coordinate and distance
in this module is explicitly named ``*_mm``; angles are stored in radians and
only converted to degrees at serialization boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Self, TypeAlias

from .errors import (
    ConvergenceError,
    DegenerateGeometryError,
    DisconnectedContourError,
    InvalidCoordinateError,
    InvalidParameterError,
    OpenContourError,
    UnsupportedGeometryError,
)

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
TAU = 2.0 * math.pi
MAX_ABS_COORDINATE_MM = 1_000_000_000.0


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidCoordinateError(f"{name} должен быть числом.", context={"field": name})
    result = float(value)
    if not math.isfinite(result):
        raise InvalidCoordinateError(
            f"{name} должен быть конечным числом.", context={"field": name}
        )
    return result


def _positive(value: float, name: str) -> float:
    result = _number(value, name)
    if result <= 0.0:
        raise InvalidParameterError(
            f"{name} должен быть больше нуля.", context={"field": name}
        )
    return result


def _coordinate(value: float, name: str) -> float:
    result = _number(value, name)
    if abs(result) > MAX_ABS_COORDINATE_MM:
        raise InvalidCoordinateError(
            f"{name} выходит за вычислительную область ±{MAX_ABS_COORDINATE_MM:g} mm.",
            context={"field": name},
        )
    return result


def _positive_length(value: float, name: str) -> float:
    result = _positive(value, name)
    if result > MAX_ABS_COORDINATE_MM:
        raise InvalidCoordinateError(
            f"{name} выходит за вычислительную область {MAX_ABS_COORDINATE_MM:g} mm.",
            context={"field": name},
        )
    return result


def _segment_id(value: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise InvalidParameterError(
            "Идентификатор геометрического элемента должен начинаться с латинской буквы "
            "и содержать только строчные буквы, цифры, '_' или '-'.",
            context={"field": "id"},
        )
    return value


def _parameter(value: float) -> float:
    result = _number(value, "t")
    if result < 0.0 or result > 1.0:
        raise InvalidParameterError("Параметр кривой t должен находиться в диапазоне [0, 1].")
    return result


@dataclass(frozen=True, slots=True)
class GeometryTolerance:
    """Numerical policy in millimetres, shared by all deterministic operations."""

    absolute_mm: float = 1e-8
    relative: float = 1e-12
    curve_flatness_mm: float = 1e-3
    max_subdivision_depth: int = 24

    def __post_init__(self) -> None:
        object.__setattr__(self, "absolute_mm", _positive(self.absolute_mm, "absolute_mm"))
        object.__setattr__(self, "relative", _positive(self.relative, "relative"))
        object.__setattr__(
            self, "curve_flatness_mm", _positive(self.curve_flatness_mm, "curve_flatness_mm")
        )
        if isinstance(self.max_subdivision_depth, bool) or not isinstance(
            self.max_subdivision_depth, int
        ) or not 4 <= self.max_subdivision_depth <= 40:
            raise InvalidParameterError(
                "max_subdivision_depth должен быть целым числом от 4 до 40."
            )

    def close(self, first: float, second: float, *, scale: float = 1.0) -> bool:
        limit = self.absolute_mm + self.relative * max(abs(first), abs(second), abs(scale))
        return abs(first - second) <= limit


DEFAULT_TOLERANCE = GeometryTolerance()


@dataclass(frozen=True, slots=True)
class Vector:
    dx_mm: float
    dy_mm: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "dx_mm", _number(self.dx_mm, "dx_mm"))
        object.__setattr__(self, "dy_mm", _number(self.dy_mm, "dy_mm"))

    @property
    def length_mm(self) -> float:
        return math.hypot(self.dx_mm, self.dy_mm)

    def normalized(self, tolerance: GeometryTolerance = DEFAULT_TOLERANCE) -> Self:
        length = self.length_mm
        if length <= tolerance.absolute_mm:
            raise DegenerateGeometryError("Нельзя нормализовать вектор нулевой длины.")
        return type(self)(self.dx_mm / length, self.dy_mm / length)

    def scaled(self, factor: float) -> Self:
        factor = _number(factor, "factor")
        return type(self)(self.dx_mm * factor, self.dy_mm * factor)

    def dot(self, other: Vector) -> float:
        return self.dx_mm * other.dx_mm + self.dy_mm * other.dy_mm

    def cross(self, other: Vector) -> float:
        return self.dx_mm * other.dy_mm - self.dy_mm * other.dx_mm

    def left_normal(self) -> Self:
        return type(self)(-self.dy_mm, self.dx_mm)

    def rotated(self, angle_rad: float) -> Self:
        angle_rad = _number(angle_rad, "angle_rad")
        cosine, sine = math.cos(angle_rad), math.sin(angle_rad)
        return type(self)(
            cosine * self.dx_mm - sine * self.dy_mm,
            sine * self.dx_mm + cosine * self.dy_mm,
        )

    def __add__(self, other: Vector) -> Self:
        if not isinstance(other, Vector):
            return NotImplemented
        return type(self)(self.dx_mm + other.dx_mm, self.dy_mm + other.dy_mm)

    def __sub__(self, other: Vector) -> Self:
        if not isinstance(other, Vector):
            return NotImplemented
        return type(self)(self.dx_mm - other.dx_mm, self.dy_mm - other.dy_mm)

    def __neg__(self) -> Self:
        return type(self)(-self.dx_mm, -self.dy_mm)


@dataclass(frozen=True, slots=True)
class Point:
    x_mm: float
    y_mm: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x_mm", _coordinate(self.x_mm, "x_mm"))
        object.__setattr__(self, "y_mm", _coordinate(self.y_mm, "y_mm"))

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x_mm - other.x_mm, self.y_mm - other.y_mm)

    def almost_equals(
        self, other: Point, tolerance: GeometryTolerance = DEFAULT_TOLERANCE
    ) -> bool:
        return self.distance_to(other) <= tolerance.absolute_mm + tolerance.relative * max(
            abs(self.x_mm), abs(self.y_mm), abs(other.x_mm), abs(other.y_mm), 1.0
        )

    def __add__(self, vector: Vector) -> Self:
        if not isinstance(vector, Vector):
            return NotImplemented
        return type(self)(self.x_mm + vector.dx_mm, self.y_mm + vector.dy_mm)

    def __sub__(self, other: object) -> Vector | Self:
        if isinstance(other, Point):
            return Vector(self.x_mm - other.x_mm, self.y_mm - other.y_mm)
        if isinstance(other, Vector):
            return type(self)(self.x_mm - other.dx_mm, self.y_mm - other.dy_mm)
        return NotImplemented


@dataclass(frozen=True, slots=True)
class BoundingBox:
    min_x_mm: float
    min_y_mm: float
    max_x_mm: float
    max_y_mm: float

    def __post_init__(self) -> None:
        values = {
            name: _coordinate(getattr(self, name), name)
            for name in ("min_x_mm", "min_y_mm", "max_x_mm", "max_y_mm")
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        if self.min_x_mm > self.max_x_mm or self.min_y_mm > self.max_y_mm:
            raise InvalidParameterError("Границы области заданы в обратном порядке.")

    @classmethod
    def from_points(cls, points: tuple[Point, ...] | list[Point]) -> Self:
        if not points:
            raise InvalidParameterError("Для области нужна хотя бы одна точка.")
        return cls(
            min(point.x_mm for point in points),
            min(point.y_mm for point in points),
            max(point.x_mm for point in points),
            max(point.y_mm for point in points),
        )

    @property
    def width_mm(self) -> float:
        return self.max_x_mm - self.min_x_mm

    @property
    def height_mm(self) -> float:
        return self.max_y_mm - self.min_y_mm

    def expanded(self, distance_mm: float) -> Self:
        distance_mm = _number(distance_mm, "distance_mm")
        if distance_mm < 0 and (
            -2 * distance_mm > self.width_mm or -2 * distance_mm > self.height_mm
        ):
            raise DegenerateGeometryError("Сжатие уничтожает ограничивающую область.")
        return type(self)(
            self.min_x_mm - distance_mm,
            self.min_y_mm - distance_mm,
            self.max_x_mm + distance_mm,
            self.max_y_mm + distance_mm,
        )


@dataclass(frozen=True, slots=True)
class AffineTransform:
    """2D affine matrix: x'=a*x+c*y+e, y'=b*x+d*y+f."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e_mm: float = 0.0
    f_mm: float = 0.0

    def __post_init__(self) -> None:
        for name in ("a", "b", "c", "d", "e_mm", "f_mm"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if abs(self.determinant) <= 1e-15:
            raise DegenerateGeometryError("Аффинное преобразование не должно вырождать плоскость.")

    @property
    def determinant(self) -> float:
        return self.a * self.d - self.b * self.c

    @classmethod
    def translation(cls, dx_mm: float, dy_mm: float) -> Self:
        return cls(e_mm=_number(dx_mm, "dx_mm"), f_mm=_number(dy_mm, "dy_mm"))

    @classmethod
    def scale(cls, scale_x: float, scale_y: float | None = None) -> Self:
        scale_x = _number(scale_x, "scale_x")
        scale_y = scale_x if scale_y is None else _number(scale_y, "scale_y")
        return cls(a=scale_x, d=scale_y)

    @classmethod
    def rotation(cls, angle_rad: float, center: Point | None = None) -> Self:
        angle_rad = _number(angle_rad, "angle_rad")
        cosine, sine = math.cos(angle_rad), math.sin(angle_rad)
        rotation = cls(a=cosine, b=sine, c=-sine, d=cosine)
        if center is None:
            return rotation
        return cls.translation(-center.x_mm, -center.y_mm).then(rotation).then(
            cls.translation(center.x_mm, center.y_mm)
        )

    @classmethod
    def rotation_degrees(cls, angle_deg: float, center: Point | None = None) -> Self:
        return cls.rotation(math.radians(_number(angle_deg, "angle_deg")), center)

    def apply_point(self, point: Point) -> Point:
        return Point(
            self.a * point.x_mm + self.c * point.y_mm + self.e_mm,
            self.b * point.x_mm + self.d * point.y_mm + self.f_mm,
        )

    def apply_vector(self, vector: Vector) -> Vector:
        return Vector(
            self.a * vector.dx_mm + self.c * vector.dy_mm,
            self.b * vector.dx_mm + self.d * vector.dy_mm,
        )

    def then(self, following: AffineTransform) -> Self:
        """Return a transform that applies ``self`` first and ``following`` second."""

        return type(self)(
            a=following.a * self.a + following.c * self.b,
            b=following.b * self.a + following.d * self.b,
            c=following.a * self.c + following.c * self.d,
            d=following.b * self.c + following.d * self.d,
            e_mm=following.a * self.e_mm + following.c * self.f_mm + following.e_mm,
            f_mm=following.b * self.e_mm + following.d * self.f_mm + following.f_mm,
        )

    def similarity_scale(self, tolerance: GeometryTolerance = DEFAULT_TOLERANCE) -> float:
        first = Vector(self.a, self.b)
        second = Vector(self.c, self.d)
        scale = first.length_mm
        if (
            scale <= tolerance.absolute_mm
            or not tolerance.close(scale, second.length_mm, scale=max(scale, second.length_mm, 1.0))
            or abs(first.dot(second)) > tolerance.absolute_mm + tolerance.relative * scale * scale
        ):
            raise UnsupportedGeometryError(
                "Дуга сохраняется дугой только при переносе, повороте, отражении "
                "и равномерном масштабировании."
            )
        return scale


@dataclass(frozen=True, slots=True)
class LineSegment:
    start: Point
    end: Point
    id: str = "line"

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _segment_id(self.id))
        if self.start.distance_to(self.end) <= DEFAULT_TOLERANCE.absolute_mm:
            raise DegenerateGeometryError("Начало и конец отрезка должны различаться.")

    @property
    def length_mm(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def bounding_box(self) -> BoundingBox:
        return BoundingBox.from_points([self.start, self.end])

    def point_at(self, t: float) -> Point:
        t = _parameter(t)
        return Point(
            self.start.x_mm + (self.end.x_mm - self.start.x_mm) * t,
            self.start.y_mm + (self.end.y_mm - self.start.y_mm) * t,
        )

    def tangent_at(self, t: float) -> Vector:
        _parameter(t)
        return self.end - self.start

    def transformed(self, transform: AffineTransform) -> Self:
        return type(self)(transform.apply_point(self.start), transform.apply_point(self.end), self.id)

    def reversed(self) -> Self:
        return type(self)(self.end, self.start, self.id)


def _angle_on_sweep(angle: float, start: float, sweep: float, epsilon: float = 1e-12) -> bool:
    if sweep > 0:
        delta = (angle - start) % TAU
        return delta <= sweep + epsilon
    delta = (start - angle) % TAU
    return delta <= -sweep + epsilon


@dataclass(frozen=True, slots=True)
class ArcSegment:
    """Rotated elliptical arc using centre parameterization."""

    center: Point
    radius_x_mm: float
    radius_y_mm: float
    rotation_rad: float
    start_angle_rad: float
    sweep_angle_rad: float
    id: str = "arc"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "radius_x_mm", _positive_length(self.radius_x_mm, "radius_x_mm")
        )
        object.__setattr__(
            self, "radius_y_mm", _positive_length(self.radius_y_mm, "radius_y_mm")
        )
        object.__setattr__(self, "rotation_rad", _number(self.rotation_rad, "rotation_rad"))
        object.__setattr__(
            self, "start_angle_rad", _number(self.start_angle_rad, "start_angle_rad")
        )
        sweep = _number(self.sweep_angle_rad, "sweep_angle_rad")
        if abs(sweep) <= 1e-15 or abs(sweep) >= TAU - 1e-12:
            raise InvalidParameterError(
                "Размах дуги должен быть ненулевым и меньше полного оборота; "
                "окружность задайте двумя дугами."
            )
        object.__setattr__(self, "sweep_angle_rad", sweep)
        object.__setattr__(self, "id", _segment_id(self.id))
        cosine, sine = math.cos(self.rotation_rad), math.sin(self.rotation_rad)
        extent_x = math.hypot(self.radius_x_mm * cosine, self.radius_y_mm * sine)
        extent_y = math.hypot(self.radius_x_mm * sine, self.radius_y_mm * cosine)
        if (
            abs(self.center.x_mm) + extent_x > MAX_ABS_COORDINATE_MM
            or abs(self.center.y_mm) + extent_y > MAX_ABS_COORDINATE_MM
        ):
            raise InvalidCoordinateError(
                "Эллиптическая дуга выходит за поддерживаемую координатную область."
            )

    @classmethod
    def circular(
        cls,
        center: Point,
        radius_mm: float,
        start_angle_rad: float,
        sweep_angle_rad: float,
        id: str = "arc",
    ) -> Self:
        return cls(center, radius_mm, radius_mm, 0.0, start_angle_rad, sweep_angle_rad, id)

    def _offset_at_angle(self, angle: float) -> Vector:
        cosine, sine = math.cos(angle), math.sin(angle)
        rotation_cosine, rotation_sine = math.cos(self.rotation_rad), math.sin(self.rotation_rad)
        local_x = self.radius_x_mm * cosine
        local_y = self.radius_y_mm * sine
        return Vector(
            rotation_cosine * local_x - rotation_sine * local_y,
            rotation_sine * local_x + rotation_cosine * local_y,
        )

    @property
    def start(self) -> Point:
        return self.center + self._offset_at_angle(self.start_angle_rad)

    @property
    def end(self) -> Point:
        return self.center + self._offset_at_angle(
            self.start_angle_rad + self.sweep_angle_rad
        )

    def point_at(self, t: float) -> Point:
        t = _parameter(t)
        return self.center + self._offset_at_angle(
            self.start_angle_rad + self.sweep_angle_rad * t
        )

    def tangent_at(self, t: float) -> Vector:
        t = _parameter(t)
        angle = self.start_angle_rad + self.sweep_angle_rad * t
        cosine, sine = math.cos(angle), math.sin(angle)
        rotation_cosine, rotation_sine = math.cos(self.rotation_rad), math.sin(self.rotation_rad)
        local_dx = -self.radius_x_mm * sine * self.sweep_angle_rad
        local_dy = self.radius_y_mm * cosine * self.sweep_angle_rad
        return Vector(
            rotation_cosine * local_dx - rotation_sine * local_dy,
            rotation_sine * local_dx + rotation_cosine * local_dy,
        )

    def parameter_for_angle(self, angle_rad: float) -> float | None:
        angle_rad = _number(angle_rad, "angle_rad")
        if not _angle_on_sweep(angle_rad, self.start_angle_rad, self.sweep_angle_rad):
            return None
        if self.sweep_angle_rad > 0:
            delta = (angle_rad - self.start_angle_rad) % TAU
        else:
            delta = -((self.start_angle_rad - angle_rad) % TAU)
        value = delta / self.sweep_angle_rad
        return min(1.0, max(0.0, value))

    @property
    def length_mm(self) -> float:
        if DEFAULT_TOLERANCE.close(self.radius_x_mm, self.radius_y_mm):
            return self.radius_x_mm * abs(self.sweep_angle_rad)

        start = self.start_angle_rad
        end = start + self.sweep_angle_rad

        def speed(angle: float) -> float:
            return math.hypot(
                self.radius_x_mm * math.sin(angle), self.radius_y_mm * math.cos(angle)
            )

        whole = _simpson(speed, start, end)
        epsilon = max(1e-10, abs(whole) * 1e-12)
        return abs(_adaptive_simpson(speed, start, end, whole, epsilon, 20))

    @property
    def bounding_box(self) -> BoundingBox:
        phi = self.rotation_rad
        candidates = [self.start_angle_rad, self.start_angle_rad + self.sweep_angle_rad]
        x_extreme = math.atan2(
            -self.radius_y_mm * math.sin(phi), self.radius_x_mm * math.cos(phi)
        )
        y_extreme = math.atan2(
            self.radius_y_mm * math.cos(phi), self.radius_x_mm * math.sin(phi)
        )
        for angle in (x_extreme, x_extreme + math.pi, y_extreme, y_extreme + math.pi):
            if _angle_on_sweep(angle, self.start_angle_rad, self.sweep_angle_rad):
                candidates.append(angle)
        return BoundingBox.from_points(
            [self.center + self._offset_at_angle(angle) for angle in candidates]
        )

    def transformed(self, transform: AffineTransform) -> Self:
        scale = transform.similarity_scale()
        new_center = transform.apply_point(self.center)
        new_start = transform.apply_point(self.start)
        axis = transform.apply_vector(
            Vector(math.cos(self.rotation_rad), math.sin(self.rotation_rad))
        )
        new_rotation = math.atan2(axis.dy_mm, axis.dx_mm)
        local = new_start - new_center
        cosine, sine = math.cos(new_rotation), math.sin(new_rotation)
        local_x = cosine * local.dx_mm + sine * local.dy_mm
        local_y = -sine * local.dx_mm + cosine * local.dy_mm
        new_start_angle = math.atan2(
            local_y / (self.radius_y_mm * scale), local_x / (self.radius_x_mm * scale)
        )
        handedness = 1.0 if transform.determinant > 0 else -1.0
        return type(self)(
            new_center,
            self.radius_x_mm * scale,
            self.radius_y_mm * scale,
            new_rotation,
            new_start_angle,
            self.sweep_angle_rad * handedness,
            self.id,
        )

    def reversed(self) -> Self:
        return type(self)(
            self.center,
            self.radius_x_mm,
            self.radius_y_mm,
            self.rotation_rad,
            self.start_angle_rad + self.sweep_angle_rad,
            -self.sweep_angle_rad,
            self.id,
        )


def _simpson(function, start: float, end: float) -> float:
    middle = (start + end) / 2.0
    return (end - start) * (function(start) + 4.0 * function(middle) + function(end)) / 6.0


def _adaptive_simpson(
    function, start: float, end: float, whole: float, epsilon: float, depth: int
) -> float:
    middle = (start + end) / 2.0
    left = _simpson(function, start, middle)
    right = _simpson(function, middle, end)
    if abs(left + right - whole) <= 15.0 * epsilon:
        return left + right + (left + right - whole) / 15.0
    if depth <= 0:
        raise ConvergenceError("Не удалось вычислить длину дуги с заданной точностью.")
    return _adaptive_simpson(function, start, middle, left, epsilon / 2.0, depth - 1) + (
        _adaptive_simpson(function, middle, end, right, epsilon / 2.0, depth - 1)
    )


@dataclass(frozen=True, slots=True)
class CubicBezier:
    start: Point
    control_1: Point
    control_2: Point
    end: Point
    id: str = "bezier"

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _segment_id(self.id))
        points = (self.start, self.control_1, self.control_2, self.end)
        if max(point.distance_to(self.start) for point in points) <= DEFAULT_TOLERANCE.absolute_mm:
            raise DegenerateGeometryError("Кривая Безье не должна состоять из одной точки.")

    def point_at(self, t: float) -> Point:
        t = _parameter(t)
        one = 1.0 - t
        return Point(
            one**3 * self.start.x_mm
            + 3.0 * one * one * t * self.control_1.x_mm
            + 3.0 * one * t * t * self.control_2.x_mm
            + t**3 * self.end.x_mm,
            one**3 * self.start.y_mm
            + 3.0 * one * one * t * self.control_1.y_mm
            + 3.0 * one * t * t * self.control_2.y_mm
            + t**3 * self.end.y_mm,
        )

    def tangent_at(self, t: float) -> Vector:
        t = _parameter(t)
        one = 1.0 - t
        return Vector(
            3.0 * one * one * (self.control_1.x_mm - self.start.x_mm)
            + 6.0 * one * t * (self.control_2.x_mm - self.control_1.x_mm)
            + 3.0 * t * t * (self.end.x_mm - self.control_2.x_mm),
            3.0 * one * one * (self.control_1.y_mm - self.start.y_mm)
            + 6.0 * one * t * (self.control_2.y_mm - self.control_1.y_mm)
            + 3.0 * t * t * (self.end.y_mm - self.control_2.y_mm),
        )

    def split(self, t: float = 0.5) -> tuple[Self, Self]:
        t = _parameter(t)
        p01 = _lerp(self.start, self.control_1, t)
        p12 = _lerp(self.control_1, self.control_2, t)
        p23 = _lerp(self.control_2, self.end, t)
        p012 = _lerp(p01, p12, t)
        p123 = _lerp(p12, p23, t)
        middle = _lerp(p012, p123, t)
        return (
            type(self)(self.start, p01, p012, middle, f"{self.id}_a"),
            type(self)(middle, p123, p23, self.end, f"{self.id}_b"),
        )

    def flatten(
        self,
        flatness_mm: float = DEFAULT_TOLERANCE.curve_flatness_mm,
        max_depth: int = DEFAULT_TOLERANCE.max_subdivision_depth,
    ) -> tuple[tuple[float, Point], ...]:
        flatness_mm = _positive(flatness_mm, "flatness_mm")
        output: list[tuple[float, Point]] = [(0.0, self.start)]

        def recurse(curve: CubicBezier, t0: float, t1: float, depth: int) -> None:
            if _bezier_flatness(curve) <= flatness_mm:
                output.append((t1, curve.end))
                return
            if depth <= 0:
                raise ConvergenceError("Кривую Безье не удалось линеаризовать с заданной точностью.")
            left, right = curve.split()
            middle = (t0 + t1) / 2.0
            recurse(left, t0, middle, depth - 1)
            recurse(right, middle, t1, depth - 1)

        recurse(self, 0.0, 1.0, max_depth)
        return tuple(output)

    @property
    def length_mm(self) -> float:
        flattened = self.flatten()
        return sum(
            first[1].distance_to(second[1])
            for first, second in zip(flattened, flattened[1:], strict=False)
        )

    @property
    def bounding_box(self) -> BoundingBox:
        parameters = {0.0, 1.0}
        for coordinates in (
            (self.start.x_mm, self.control_1.x_mm, self.control_2.x_mm, self.end.x_mm),
            (self.start.y_mm, self.control_1.y_mm, self.control_2.y_mm, self.end.y_mm),
        ):
            parameters.update(_bezier_extrema(*coordinates))
        return BoundingBox.from_points([self.point_at(value) for value in sorted(parameters)])

    def transformed(self, transform: AffineTransform) -> Self:
        return type(self)(
            transform.apply_point(self.start),
            transform.apply_point(self.control_1),
            transform.apply_point(self.control_2),
            transform.apply_point(self.end),
            self.id,
        )

    def reversed(self) -> Self:
        return type(self)(self.end, self.control_2, self.control_1, self.start, self.id)


def _lerp(first: Point, second: Point, t: float) -> Point:
    return Point(
        first.x_mm + (second.x_mm - first.x_mm) * t,
        first.y_mm + (second.y_mm - first.y_mm) * t,
    )


def _distance_to_infinite_line(point: Point, start: Point, end: Point) -> float:
    direction = end - start
    length = direction.length_mm
    if length <= DEFAULT_TOLERANCE.absolute_mm:
        return point.distance_to(start)
    return abs((point - start).cross(direction)) / length


def _bezier_flatness(curve: CubicBezier) -> float:
    return max(
        _distance_to_infinite_line(curve.control_1, curve.start, curve.end),
        _distance_to_infinite_line(curve.control_2, curve.start, curve.end),
    )


def _bezier_extrema(p0: float, p1: float, p2: float, p3: float) -> set[float]:
    # Roots of B'(t) / 3 = a*t^2 + b*t + c.
    a = -p0 + 3.0 * p1 - 3.0 * p2 + p3
    b = 2.0 * (p0 - 2.0 * p1 + p2)
    c = p1 - p0
    roots: set[float] = set()
    epsilon = 1e-15
    if abs(a) <= epsilon:
        if abs(b) > epsilon:
            root = -c / b
            if 0.0 < root < 1.0:
                roots.add(root)
        return roots
    discriminant = b * b - 4.0 * a * c
    if discriminant < -epsilon:
        return roots
    discriminant = max(0.0, discriminant)
    square_root = math.sqrt(discriminant)
    # Numerically stable quadratic formula.
    q = -0.5 * (b + math.copysign(square_root, b))
    candidates = (-b / (2.0 * a),) if q == 0.0 else (q / a, c / q)
    for root in candidates:
        if 0.0 < root < 1.0:
            roots.add(root)
    return roots


Curve: TypeAlias = LineSegment | ArcSegment | CubicBezier


def _curve_area_integral(curve: Curve) -> float:
    if isinstance(curve, LineSegment):
        return curve.start.x_mm * curve.end.y_mm - curve.start.y_mm * curve.end.x_mm
    if isinstance(curve, ArcSegment):
        start_offset = curve.start - curve.center
        end_offset = curve.end - curve.center
        translation = curve.center.x_mm * (end_offset.dy_mm - start_offset.dy_mm) - (
            curve.center.y_mm * (end_offset.dx_mm - start_offset.dx_mm)
        )
        return translation + curve.radius_x_mm * curve.radius_y_mm * curve.sweep_angle_rad
    return _cubic_area_integral(curve)


def _polynomial_product(first: list[float], second: list[float]) -> list[float]:
    result = [0.0] * (len(first) + len(second) - 1)
    for first_index, first_value in enumerate(first):
        for second_index, second_value in enumerate(second):
            result[first_index + second_index] += first_value * second_value
    return result


def _cubic_area_integral(curve: CubicBezier) -> float:
    def coefficients(values: tuple[float, float, float, float]) -> list[float]:
        p0, p1, p2, p3 = values
        return [p0, 3 * (p1 - p0), 3 * (p0 - 2 * p1 + p2), -p0 + 3 * p1 - 3 * p2 + p3]

    x = coefficients((curve.start.x_mm, curve.control_1.x_mm, curve.control_2.x_mm, curve.end.x_mm))
    y = coefficients((curve.start.y_mm, curve.control_1.y_mm, curve.control_2.y_mm, curve.end.y_mm))
    dx = [index * value for index, value in enumerate(x)][1:]
    dy = [index * value for index, value in enumerate(y)][1:]
    x_dy = _polynomial_product(x, dy)
    y_dx = _polynomial_product(y, dx)
    size = max(len(x_dy), len(y_dx))
    x_dy.extend([0.0] * (size - len(x_dy)))
    y_dx.extend([0.0] * (size - len(y_dx)))
    return sum((x_dy[index] - y_dx[index]) / (index + 1) for index in range(size))


@dataclass(frozen=True, slots=True)
class Contour:
    segments: tuple[Curve, ...]
    closed: bool = True
    id: str = "contour"
    tolerance: GeometryTolerance = field(default=DEFAULT_TOLERANCE, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", tuple(self.segments))
        object.__setattr__(self, "id", _segment_id(self.id))
        if not self.segments:
            raise InvalidParameterError("Контур должен содержать хотя бы один сегмент.")
        identifiers = [segment.id for segment in self.segments]
        if len(identifiers) != len(set(identifiers)):
            raise InvalidParameterError("Идентификаторы сегментов внутри контура должны быть уникальны.")
        for index, (first, second) in enumerate(
            zip(self.segments, self.segments[1:], strict=False)
        ):
            if not first.end.almost_equals(second.start, self.tolerance):
                raise DisconnectedContourError(
                    "Соседние сегменты контура не соединены.", context={"after_index": index}
                )
        if self.closed and not self.segments[-1].end.almost_equals(
            self.segments[0].start, self.tolerance
        ):
            raise DisconnectedContourError("Последний сегмент замкнутого контура не соединён с первым.")

    @property
    def start(self) -> Point:
        return self.segments[0].start

    @property
    def end(self) -> Point:
        return self.segments[-1].end

    @property
    def length_mm(self) -> float:
        return math.fsum(segment.length_mm for segment in self.segments)

    @property
    def bounding_box(self) -> BoundingBox:
        boxes = [segment.bounding_box for segment in self.segments]
        return BoundingBox(
            min(box.min_x_mm for box in boxes),
            min(box.min_y_mm for box in boxes),
            max(box.max_x_mm for box in boxes),
            max(box.max_y_mm for box in boxes),
        )

    @property
    def signed_area_mm2(self) -> float:
        if not self.closed:
            raise OpenContourError("Площадь определена только для замкнутого контура.")
        return 0.5 * math.fsum(_curve_area_integral(segment) for segment in self.segments)

    @property
    def area_mm2(self) -> float:
        return abs(self.signed_area_mm2)

    @property
    def orientation(self) -> str:
        signed = self.signed_area_mm2
        scale = max(self.bounding_box.width_mm * self.bounding_box.height_mm, 1.0)
        if abs(signed) <= self.tolerance.absolute_mm * scale:
            raise DegenerateGeometryError("Площадь контура слишком мала для определения направления.")
        return "counterclockwise" if signed > 0.0 else "clockwise"

    def transformed(self, transform: AffineTransform) -> Self:
        return type(self)(
            tuple(segment.transformed(transform) for segment in self.segments),
            self.closed,
            self.id,
            self.tolerance,
        )

    def reversed(self) -> Self:
        return type(self)(
            tuple(segment.reversed() for segment in reversed(self.segments)),
            self.closed,
            self.id,
            self.tolerance,
        )


def curve_points(
    curve: Curve, flatness_mm: float = DEFAULT_TOLERANCE.curve_flatness_mm
) -> tuple[tuple[float, Point], ...]:
    """Return a deterministic polyline with source parameters for intersections/offsets."""

    flatness_mm = _positive(flatness_mm, "flatness_mm")
    if isinstance(curve, LineSegment):
        return ((0.0, curve.start), (1.0, curve.end))
    if isinstance(curve, CubicBezier):
        return curve.flatten(flatness_mm)
    bounding_radius = max(
        curve.radius_x_mm * curve.radius_x_mm / curve.radius_y_mm,
        curve.radius_y_mm * curve.radius_y_mm / curve.radius_x_mm,
    )
    if flatness_mm >= bounding_radius:
        step = math.pi / 2.0
    else:
        step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - flatness_mm / bounding_radius)))
    divisions = max(1, math.ceil(abs(curve.sweep_angle_rad) / max(step, 1e-9)))
    if divisions > 200_000:
        raise ConvergenceError("Для линеаризации дуги требуется слишком много сегментов.")
    return tuple((index / divisions, curve.point_at(index / divisions)) for index in range(divisions + 1))

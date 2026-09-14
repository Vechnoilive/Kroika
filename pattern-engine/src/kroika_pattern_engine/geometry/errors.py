"""Stable, user-safe failures raised by the geometry core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class GeometryError(ValueError):
    """Base error with a machine code and a Russian user-facing explanation."""

    code = "GEOMETRY_ERROR"

    def __init__(self, message_ru: str, *, context: Mapping[str, Any] | None = None):
        self.message_ru = message_ru
        self.context = dict(context or {})
        super().__init__(f"{self.code}: {message_ru}")


class InvalidCoordinateError(GeometryError):
    code = "GEOMETRY_INVALID_COORDINATE"


class InvalidParameterError(GeometryError):
    code = "GEOMETRY_INVALID_PARAMETER"


class DegenerateGeometryError(GeometryError):
    code = "GEOMETRY_DEGENERATE"


class DisconnectedContourError(GeometryError):
    code = "GEOMETRY_CONTOUR_DISCONNECTED"


class OpenContourError(GeometryError):
    code = "GEOMETRY_CONTOUR_OPEN"


class OverlappingGeometryError(GeometryError):
    code = "GEOMETRY_OVERLAP_AMBIGUOUS"


class SelfIntersectionError(GeometryError):
    code = "GEOMETRY_SELF_INTERSECTION"


class OffsetCollapseError(GeometryError):
    code = "GEOMETRY_OFFSET_COLLAPSED"


class UnsupportedGeometryError(GeometryError):
    code = "GEOMETRY_UNSUPPORTED_OPERATION"


class ConvergenceError(GeometryError):
    code = "GEOMETRY_CONVERGENCE_FAILED"


class SerializationError(GeometryError):
    code = "GEOMETRY_SERIALIZATION_INVALID"

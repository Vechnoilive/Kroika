"""A tiny deterministic integration check used by the engine boundary."""

from __future__ import annotations

from hashlib import sha256

from .primitives import AffineTransform, Contour, LineSegment, Point
from .serialization import canonical_json, contour_from_json

GEOMETRY_CORE_VERSION = "0.1.0"


def run_core_diagnostics() -> dict[str, str]:
    points = (Point(0, 0), Point(100, 0), Point(100, 50), Point(0, 50))
    contour = Contour(
        tuple(
            LineSegment(points[index], points[(index + 1) % 4], f"edge_{index + 1}")
            for index in range(4)
        ),
        id="diagnostic_rectangle",
    )
    transformed = contour.transformed(
        AffineTransform.rotation_degrees(37).then(AffineTransform.translation(15, -22))
    )
    payload = canonical_json(transformed)
    restored = contour_from_json(payload)
    if abs(restored.area_mm2 - 5_000.0) > 1e-8 or abs(restored.length_mm - 300.0) > 1e-8:
        raise RuntimeError("Geometry core diagnostic invariant failed")
    return {
        "version": GEOMETRY_CORE_VERSION,
        "precision": "ieee754-binary64",
        "unit": "mm",
        "fingerprint": sha256(payload.encode("utf-8")).hexdigest(),
    }

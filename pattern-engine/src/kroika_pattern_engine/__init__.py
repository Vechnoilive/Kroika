"""Public entry points for the isolated Kroika pattern engine."""

from . import blocks, geometry
from .assembly import GarmentAssembly, assemble_garment
from .scaffold import GeometryPatternEngine, ScaffoldPatternEngine
from .svg import SVGRenderError, render_pattern_svg

__all__ = [
    "GarmentAssembly",
    "GeometryPatternEngine",
    "SVGRenderError",
    "ScaffoldPatternEngine",
    "assemble_garment",
    "blocks",
    "geometry",
    "render_pattern_svg",
]

"""Public entry points for the isolated Kroika pattern engine."""

from . import blocks, geometry
from .assembly import GarmentAssembly, assemble_garment
from .pdf import PDFRenderError, PDFRenderResult, render_pattern_pdf
from .scaffold import GeometryPatternEngine, ScaffoldPatternEngine
from .svg import SVG_PREVIEW_LAYERS, SVGRenderError, render_pattern_svg

__all__ = [
    "GarmentAssembly",
    "GeometryPatternEngine",
    "PDFRenderError",
    "PDFRenderResult",
    "SVGRenderError",
    "SVG_PREVIEW_LAYERS",
    "ScaffoldPatternEngine",
    "assemble_garment",
    "blocks",
    "geometry",
    "render_pattern_svg",
    "render_pattern_pdf",
]

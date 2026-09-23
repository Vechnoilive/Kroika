"""Public entry points for the isolated Kroika pattern engine."""

from . import blocks, geometry
from .assembly import GarmentAssembly, assemble_garment
from .coverage import DesignCoverageResult, compile_design_coverage
from .topology import TopologyResult, apply_topology_transformations
from .garment_catalogue import garment_acceptance, garment_catalogue, release_gate
from .pdf import PDFRenderError, PDFRenderResult, render_pattern_pdf
from .scaffold import GeometryPatternEngine, ScaffoldPatternEngine
from .svg import SVG_PREVIEW_LAYERS, SVGRenderError, render_pattern_svg

__all__ = [
    "GarmentAssembly",
    "DesignCoverageResult",
    "GeometryPatternEngine",
    "PDFRenderError",
    "PDFRenderResult",
    "SVGRenderError",
    "SVG_PREVIEW_LAYERS",
    "ScaffoldPatternEngine",
    "assemble_garment",
    "compile_design_coverage",
    "TopologyResult",
    "apply_topology_transformations",
    "blocks",
    "geometry",
    "garment_acceptance",
    "garment_catalogue",
    "release_gate",
    "render_pattern_svg",
    "render_pattern_pdf",
]

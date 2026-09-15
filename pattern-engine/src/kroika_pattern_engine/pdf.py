"""Deterministic tiled A4 PDF renderer for stage-9 diagnostic printing."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
from typing import Any, Mapping

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .geometry import curve_from_data, curve_points
from .print_layout import PatternLayout, PlacedPiece, Tile, TilePlan, layout_pattern, make_tile_plan, notch_geometry


@dataclass(frozen=True, slots=True)
class PDFRenderResult:
    content: bytes
    page_count: int
    tile_count: int
    columns: int
    rows: int


class PDFRenderError(ValueError):
    pass


_FONT_NAME = "KroikaDejaVu"
_FONT_BOLD_NAME = "KroikaDejaVuBold"
_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/local/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)
_BOLD_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/local/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
)


def _register_fonts() -> tuple[str, str]:
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        regular = next((path for path in _FONT_CANDIDATES if path.is_file()), None)
        if regular is None:
            raise PDFRenderError(
                "Не найден Unicode-шрифт: PDF остановлен, чтобы русские подписи не повредились."
            )
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(regular)))
    if _FONT_BOLD_NAME not in pdfmetrics.getRegisteredFontNames():
        bold = next((path for path in _BOLD_FONT_CANDIDATES if path.is_file()), None)
        if bold is None:
            return _FONT_NAME, _FONT_NAME
        pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, str(bold)))
    return _FONT_NAME, _FONT_BOLD_NAME


def _draw_top_text(
    document: canvas.Canvas,
    value: str,
    x_mm: float,
    y_from_top_mm: float,
    *,
    font: str,
    size: float,
    color=HexColor("#211d22"),
) -> None:
    document.setFont(font, size)
    document.setFillColor(color)
    document.drawString(x_mm * mm, A4[1] - y_from_top_mm * mm, value)


def _draw_cross(document: canvas.Canvas, x_mm: float, y_mm: float, size_mm: float = 4) -> None:
    document.setStrokeColor(HexColor("#323033"))
    document.setLineWidth(0.25 * mm)
    document.line((x_mm - size_mm) * mm, y_mm * mm, (x_mm + size_mm) * mm, y_mm * mm)
    document.line(x_mm * mm, (y_mm - size_mm) * mm, x_mm * mm, (y_mm + size_mm) * mm)


def _draw_map_page(
    document: canvas.Canvas,
    layout: PatternLayout,
    plan: TilePlan,
    regular_font: str,
    bold_font: str,
) -> None:
    document.setFillColor(HexColor("#fffdf9"))
    document.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    _draw_top_text(document, "Kroika · карта печати A4", 12, 14, font=bold_font, size=16)
    _draw_top_text(
        document,
        f"Масштаб 1:1 · листов выкройки: {len(plan.tiles)} · нахлёст: {plan.overlap_mm:g} мм",
        12,
        23,
        font=regular_font,
        size=8.5,
    )
    document.setStrokeColor(HexColor("#17141a"))
    document.setLineWidth(0.35 * mm)
    document.rect(12 * mm, (297 - 82) * mm, 50 * mm, 50 * mm, fill=0, stroke=1)
    _draw_top_text(document, "50 x 50 mm", 12, 87, font=bold_font, size=8)
    _draw_top_text(document, "1. Печатайте «Actual size / 100%».", 72, 39, font=bold_font, size=9)
    _draw_top_text(document, "2. Отключите «Подогнать к странице».", 72, 50, font=regular_font, size=8.5)
    _draw_top_text(document, "3. Измерьте квадрат: каждая сторона 50 мм.", 72, 61, font=regular_font, size=8.5)
    _draw_top_text(document, "4. Совмещайте одинаковые метки листов.", 72, 72, font=regular_font, size=8.5)
    _draw_top_text(document, "Только бумага/макет — не раскраивайте ткань.", 72, 84, font=bold_font, size=8.5, color=HexColor("#a33e34"))

    map_x, map_y, map_width, map_height = 14.0, 18.0, 182.0, 172.0
    scale = min(map_width / layout.width_mm, map_height / layout.height_mm)
    drawn_width = layout.width_mm * scale
    drawn_height = layout.height_mm * scale
    origin_x = map_x + (map_width - drawn_width) / 2
    origin_y = map_y + (map_height - drawn_height) / 2
    document.setFillColor(HexColor("#f5f0e9"))
    document.setStrokeColor(HexColor("#b6aaa0"))
    for placed in layout.pieces:
        document.rect(
            (origin_x + placed.offset_x_mm * scale) * mm,
            (origin_y + (layout.height_mm - placed.offset_y_mm - placed.height_mm) * scale) * mm,
            placed.width_mm * scale * mm,
            placed.height_mm * scale * mm,
            fill=1,
            stroke=1,
        )
    document.setFillColor(Color(1, 1, 1, alpha=0))
    document.setStrokeColor(HexColor("#3c596d"))
    document.setLineWidth(0.35 * mm)
    document.setFont(bold_font, 6.5)
    for tile in plan.tiles:
        x = origin_x + tile.origin_x_mm * scale
        y_top = origin_y + drawn_height - tile.origin_y_mm * scale
        width = min(plan.printable_width_mm, layout.width_mm - tile.origin_x_mm) * scale
        height = min(plan.printable_height_mm, layout.height_mm - tile.origin_y_mm) * scale
        if width <= 0 or height <= 0:
            continue
        document.rect(x * mm, (y_top - height) * mm, width * mm, height * mm, fill=0, stroke=1)
        document.setFillColor(HexColor("#294b62"))
        document.drawCentredString((x + width / 2) * mm, (y_top - height / 2) * mm, tile.label)
    _draw_top_text(document, "Карта листов: начинайте с A1, собирайте по строкам.", 14, 286, font=regular_font, size=8)
    document.showPage()


def _page_point(plan: TilePlan, tile: Tile, point: tuple[float, float]) -> tuple[float, float]:
    return (
        plan.margin_mm + point[0] - tile.origin_x_mm,
        plan.page_height_mm - plan.margin_mm - point[1] + tile.origin_y_mm,
    )


def _draw_path(
    document: canvas.Canvas,
    path_data: Mapping[str, Any],
    placed: PlacedPiece,
    plan: TilePlan,
    tile: Tile,
) -> None:
    path = document.beginPath()
    started = False
    for segment in path_data["segments"]:
        points = curve_points(curve_from_data(segment), flatness_mm=0.1)
        if not started:
            start = _page_point(plan, tile, placed.point((points[0][1].x_mm, points[0][1].y_mm)))
            path.moveTo(start[0] * mm, start[1] * mm)
            started = True
        for _, sample in points[1:]:
            end = _page_point(plan, tile, placed.point((sample.x_mm, sample.y_mm)))
            path.lineTo(end[0] * mm, end[1] * mm)
    if path_data.get("closed"):
        path.close()
    document.drawPath(path, fill=0, stroke=1)


def _draw_tile_content(
    document: canvas.Canvas,
    layout: PatternLayout,
    plan: TilePlan,
    tile: Tile,
    regular_font: str,
    bold_font: str,
) -> None:
    document.setFillColor(HexColor("#ffffff"))
    document.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    document.setFont(bold_font, 8)
    document.setFillColor(HexColor("#211d22"))
    document.drawString(plan.margin_mm * mm, (plan.page_height_mm - 4.5) * mm, f"Kroika · лист {tile.label}")
    document.setFont(regular_font, 6.5)
    document.drawRightString((plan.page_width_mm - plan.margin_mm) * mm, (plan.page_height_mm - 4.5) * mm, "100% · квадрат на странице 1")
    for x in (plan.margin_mm, plan.page_width_mm - plan.margin_mm):
        for y in (plan.margin_mm, plan.page_height_mm - plan.margin_mm):
            _draw_cross(document, x, y)

    document.saveState()
    clip = document.beginPath()
    clip.rect(
        plan.margin_mm * mm,
        plan.margin_mm * mm,
        plan.printable_width_mm * mm,
        plan.printable_height_mm * mm,
    )
    document.clipPath(clip, stroke=0, fill=0)
    for placed in layout.pieces:
        piece = placed.piece
        document.setStrokeColor(HexColor("#17141a"))
        document.setLineWidth(0.45 * mm)
        document.setDash()
        _draw_path(document, piece["cutting_contour"], placed, plan, tile)
        document.setStrokeColor(HexColor("#b84539"))
        document.setLineWidth(0.28 * mm)
        document.setDash([5 * mm, 3 * mm])
        _draw_path(document, piece["seam_contour"], placed, plan, tile)
        document.setStrokeColor(HexColor("#806378"))
        document.setLineWidth(0.22 * mm)
        document.setDash([4 * mm, 3 * mm])
        for internal in piece.get("internal_paths", ()):
            _draw_path(document, internal, placed, plan, tile)
        fold_ids = {
            allowance["segment_id"]
            for allowance in piece.get("edge_allowances", ())
            if allowance["edge_type"] == "fold"
        }
        document.setStrokeColor(HexColor("#17746f"))
        document.setLineWidth(0.55 * mm)
        document.setDash([10 * mm, 3 * mm, 2 * mm, 3 * mm])
        for segment in piece["seam_contour"]["segments"]:
            if segment["id"] in fold_ids:
                _draw_path(document, {"closed": False, "segments": [segment]}, placed, plan, tile)
        document.setDash()
        document.setStrokeColor(HexColor("#604a70"))
        document.setLineWidth(0.3 * mm)
        grain_start = _page_point(plan, tile, placed.point(piece["grainline"]["start"]))
        grain_end = _page_point(plan, tile, placed.point(piece["grainline"]["end"]))
        document.line(grain_start[0] * mm, grain_start[1] * mm, grain_end[0] * mm, grain_end[1] * mm)
        grain_dx = grain_end[0] - grain_start[0]
        grain_dy = grain_end[1] - grain_start[1]
        grain_length = max(math.hypot(grain_dx, grain_dy), 1e-9)
        ux, uy = grain_dx / grain_length, grain_dy / grain_length
        arrow = document.beginPath()
        arrow.moveTo(grain_end[0] * mm, grain_end[1] * mm)
        arrow.lineTo((grain_end[0] - 5 * ux + 2 * uy) * mm, (grain_end[1] - 5 * uy - 2 * ux) * mm)
        arrow.lineTo((grain_end[0] - 5 * ux - 2 * uy) * mm, (grain_end[1] - 5 * uy + 2 * ux) * mm)
        arrow.close()
        document.setFillColor(HexColor("#604a70"))
        document.drawPath(arrow, fill=1, stroke=0)
        for notch in piece.get("notches", ()):
            geometry = notch_geometry(placed, notch)
            if geometry:
                first = _page_point(plan, tile, geometry[0])
                second = _page_point(plan, tile, geometry[1])
                document.setStrokeColor(HexColor("#17141a"))
                document.setLineWidth(0.45 * mm)
                document.line(first[0] * mm, first[1] * mm, second[0] * mm, second[1] * mm)
        center = _page_point(
            plan,
            tile,
            (placed.offset_x_mm + placed.width_mm / 2, placed.offset_y_mm + placed.height_mm / 2),
        )
        document.setFillColor(HexColor("#262127"))
        document.setFont(bold_font, 7)
        document.drawCentredString(center[0] * mm, center[1] * mm, str(piece["name_ru"]))
        document.setFont(regular_font, 6)
        suffix = " · СГИБ" if piece["cut_on_fold"] else ""
        document.drawCentredString(center[0] * mm, (center[1] - 4) * mm, f"Крой: {piece['cut_quantity']}{suffix}")

    document.setFillColor(Color(0.72, 0.25, 0.2, alpha=0.10))
    document.setFont(bold_font, 26)
    document.saveState()
    document.translate(A4[0] / 2, A4[1] / 2)
    document.rotate(35)
    document.drawCentredString(0, 0, "ЭКСПЕРИМЕНТАЛЬНО · НЕ ДЛЯ ТКАНИ")
    document.restoreState()
    document.restoreState()
    document.setFont(regular_font, 6)
    document.setFillColor(HexColor("#755e5a"))
    document.drawCentredString(A4[0] / 2, 3 * mm, f"Лист {tile.label} · совместите кресты и область нахлёста {plan.overlap_mm:g} мм")
    document.showPage()


def render_pattern_pdf(pattern: Mapping[str, Any]) -> PDFRenderResult:
    """Create an A4 PDF: one assembly map followed by exact 1:1 pattern tiles."""

    spec = pattern.get("print_layout")
    if not isinstance(spec, Mapping) or spec.get("page_format") != "A4" or spec.get("scale") != 1:
        raise PDFRenderError("Выкройка не содержит проверенный макет A4 1:1.")
    if not all(piece.get("cutting_contour") for piece in pattern.get("pieces", ())):
        raise PDFRenderError("PDF нельзя построить без линий среза всех деталей.")
    regular_font, bold_font = _register_fonts()
    try:
        layout = layout_pattern(pattern)
        plan = make_tile_plan(layout, spec)
    except (KeyError, TypeError, ValueError) as error:
        raise PDFRenderError("Параметры разбиения выкройки на листы некорректны.") from error
    output = BytesIO()
    document = canvas.Canvas(
        output,
        pagesize=A4,
        pageCompression=1,
        invariant=1,
        pdfVersion=(1, 7),
    )
    document.setTitle("Kroika — диагностическая выкройка A4 1:1")
    document.setAuthor("Kroika")
    document.setSubject("Экспериментальная выкройка; production-ready=false")
    _draw_map_page(document, layout, plan, regular_font, bold_font)
    for tile in plan.tiles:
        _draw_tile_content(document, layout, plan, tile, regular_font, bold_font)
    document.save()
    return PDFRenderResult(output.getvalue(), len(plan.tiles) + 1, len(plan.tiles), plan.columns, plan.rows)

"""Safe deterministic SVG with selectable preview layers and complete print output."""

from __future__ import annotations

from html import escape
import math
from collections.abc import Collection
from typing import Any, Mapping

from .geometry import curve_from_data, curve_points
from .print_layout import PlacedPiece, layout_pattern, notch_geometry


class SVGRenderError(ValueError):
    pass


SVG_PREVIEW_LAYERS = frozenset({
    "cutting", "seam", "internal", "fold", "grain", "notches", "labels", "dimensions",
})


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SVGRenderError(f"{name} должен быть конечным числом.")
    return float(value)


def _fmt(value: float) -> str:
    rounded = round(value, 3)
    return f"{0.0 if rounded == 0 else rounded:.3f}".rstrip("0").rstrip(".")


def _point(placed: PlacedPiece, raw: list[float], shift_y: float) -> tuple[float, float]:
    x, y = placed.point(raw)
    return x, y + shift_y


def _path_data(path: Mapping[str, Any], placed: PlacedPiece, shift_y: float) -> str:
    segments = path.get("segments")
    if not isinstance(segments, list) or not segments:
        raise SVGRenderError("Пустой путь нельзя показать.")
    commands: list[str] = []
    for segment_index, segment in enumerate(segments):
        samples = curve_points(curve_from_data(segment), flatness_mm=0.1)
        if segment_index == 0:
            start = _point(placed, [samples[0][1].x_mm, samples[0][1].y_mm], shift_y)
            commands.append(f"M {_fmt(start[0])} {_fmt(start[1])}")
        for _, sample in samples[1:]:
            end = _point(placed, [sample.x_mm, sample.y_mm], shift_y)
            commands.append(f"L {_fmt(end[0])} {_fmt(end[1])}")
    if path.get("closed"):
        commands.append("Z")
    return " ".join(commands)


def _fold_paths(placed: PlacedPiece, shift_y: float) -> list[str]:
    fold_ids = {
        item["segment_id"]
        for item in placed.piece.get("edge_allowances", ())
        if item.get("edge_type") == "fold"
    }
    return [
        _path_data({"closed": False, "segments": [segment]}, placed, shift_y)
        for segment in placed.piece["seam_contour"]["segments"]
        if segment["id"] in fold_ids
    ]


def render_pattern_svg(
    pattern: Mapping[str, Any], visible_layers: Collection[str] | None = None,
) -> str:
    """Render a printable 1:1 unified SVG without scripts or external resources."""

    layers = SVG_PREVIEW_LAYERS if visible_layers is None else frozenset(visible_layers)
    unknown = layers - SVG_PREVIEW_LAYERS
    if unknown:
        raise SVGRenderError(f"Неизвестные слои SVG: {', '.join(sorted(unknown))}.")

    try:
        layout = layout_pattern(pattern)
    except (KeyError, TypeError, ValueError) as error:
        raise SVGRenderError("Не удалось разместить детали на общем листе.") from error
    header_height = 88.0
    canvas_width = max(layout.width_mm, 210.0)
    canvas_height = layout.height_mm + header_height
    has_cutting = all(piece.piece.get("cutting_contour") for piece in layout.pieces)
    mode = "линия шва и линия среза" if has_cutting else "только линия шва"
    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 {_fmt(canvas_width)} {_fmt(canvas_height)}" width="{_fmt(canvas_width)}mm" height="{_fmt(canvas_height)}mm">',
        "<title>Выкройка Kroika для диагностической печати 1:1</title>",
        "<desc>Экспериментальная выкройка. Проверьте квадрат 50 на 50 мм и изготовьте макет до раскроя ткани.</desc>",
        "<metadata>unit=mm; scale=1:1; export=diagnostic; production-ready=false</metadata>",
        '<defs><marker id="grain-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#604a70"/></marker></defs>',
        "<style>.sheet{fill:#fff}.cutting{fill:#fffaf4;stroke:#17141a;stroke-width:1;vector-effect:non-scaling-stroke}.seam{fill:none;stroke:#b84539;stroke-width:.65;stroke-dasharray:5 3;vector-effect:non-scaling-stroke}.internal{fill:none;stroke:#806378;stroke-width:.55;stroke-dasharray:4 3;vector-effect:non-scaling-stroke}.grain{stroke:#604a70;stroke-width:.7;stroke-dasharray:8 3;marker-end:url(#grain-arrow);vector-effect:non-scaling-stroke}.notch{stroke:#17141a;stroke-width:1.2;vector-effect:non-scaling-stroke}.fold{fill:none;stroke:#17746f;stroke-width:1.5;stroke-dasharray:10 3 2 3;vector-effect:non-scaling-stroke}.label{font:700 7px sans-serif;fill:#17141a}.meta{font:5px sans-serif;fill:#5f5762}.dimension{font:4.5px sans-serif;fill:#6b587f}.title{font:700 9px sans-serif;fill:#17141a}.warning{font:700 6px sans-serif;fill:#a43e34}.calibration{fill:none;stroke:#17141a;stroke-width:.45}.legend{font:5.5px sans-serif;fill:#302b32}.watermark{font:700 18px sans-serif;fill:#b84539;opacity:.08}</style>",
        f'<rect class="sheet" width="{_fmt(canvas_width)}" height="{_fmt(canvas_height)}"/>',
        '<text class="title" x="18" y="13">Kroika · печатный SVG 1:1</text>',
        f'<text class="legend" x="18" y="20">{escape(mode)} · единицы: мм</text>',
        '<rect id="control-square-50mm" class="calibration" x="18" y="26" width="50" height="50"/>',
        '<text class="legend" x="18" y="83">Контрольный квадрат 50 × 50 мм</text>',
        '<text class="legend" x="82" y="31">Сплошная чёрная — линия среза</text>',
        '<text class="legend" x="82" y="40">Красный пунктир — линия шва</text>',
        '<text class="legend" x="82" y="49">Зелёный штрихпунктир — сгиб</text>',
        '<text class="warning" x="82" y="61">Печатать 100% / Actual size</text>',
        '<text class="warning" x="82" y="70">Не использовать «Подогнать к странице»</text>',
        f'<text class="watermark" x="{_fmt(canvas_width / 2 - 75)}" y="{_fmt(header_height + 22)}">ЭКСПЕРИМЕНТАЛЬНО</text>',
    ]

    for placed in layout.pieces:
        piece = placed.piece
        name = escape(str(piece["name_ru"]))
        center_x = placed.offset_x_mm + placed.width_mm / 2
        center_y = header_height + placed.offset_y_mm + placed.height_mm / 2
        fragments.append(f'<g id="piece-{escape(str(piece["id"]))}">')
        cutting = piece.get("cutting_contour")
        if cutting and "cutting" in layers:
            fragments.append(f'<path class="cutting" data-layer="cutting" d="{_path_data(cutting, placed, header_height)}"/>')
        if "seam" in layers:
            fragments.append(f'<path class="seam" data-layer="seam" d="{_path_data(piece["seam_contour"], placed, header_height)}"/>')
        if "internal" in layers:
            for path in piece.get("internal_paths", ()):
                fragments.append(f'<path class="internal" data-layer="internal" d="{_path_data(path, placed, header_height)}"/>')
        if "fold" in layers:
            for fold_path in _fold_paths(placed, header_height):
                fragments.append(f'<path class="fold" data-layer="fold" d="{fold_path}"/>')
        if "grain" in layers:
            grain_start = _point(placed, piece["grainline"]["start"], header_height)
            grain_end = _point(placed, piece["grainline"]["end"], header_height)
            fragments.append(f'<line class="grain" data-layer="grain" x1="{_fmt(grain_start[0])}" y1="{_fmt(grain_start[1])}" x2="{_fmt(grain_end[0])}" y2="{_fmt(grain_end[1])}"/>')
        if "notches" in layers:
            for notch in piece.get("notches", ()):
                notch_line = notch_geometry(placed, notch)
                if notch_line:
                    (x1, y1), (x2, y2) = notch_line
                    fragments.append(f'<line class="notch" data-layer="notches" data-match="{escape(str(notch["match_id"]))}" x1="{_fmt(x1)}" y1="{_fmt(y1 + header_height)}" x2="{_fmt(x2)}" y2="{_fmt(y2 + header_height)}"/>')
        fold_text = " · СГИБ" if piece["cut_on_fold"] else ""
        meta = f"Крой: {piece['cut_quantity']}{fold_text}"
        if "labels" in layers:
            fragments.append(f'<text class="label" data-layer="labels" text-anchor="middle" x="{_fmt(center_x)}" y="{_fmt(center_y)}">{name}</text>')
            fragments.append(f'<text class="meta" data-layer="labels" text-anchor="middle" x="{_fmt(center_x)}" y="{_fmt(center_y + 8)}">{escape(meta)}</text>')
        if "dimensions" in layers:
            dimensions = f"{_fmt(placed.width_mm)} × {_fmt(placed.height_mm)} мм"
            fragments.append(f'<text class="dimension" data-layer="dimensions" text-anchor="middle" x="{_fmt(center_x)}" y="{_fmt(center_y + 16)}">{dimensions}</text>')
        fragments.append("</g>")
    fragments.append("</svg>")
    return "".join(fragments)

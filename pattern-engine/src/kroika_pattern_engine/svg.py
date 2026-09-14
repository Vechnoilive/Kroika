"""Safe deterministic SVG preview for canonical pattern data."""

from __future__ import annotations

from html import escape
import math
from typing import Any, Mapping


class SVGRenderError(ValueError):
    pass


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SVGRenderError(f"{name} должен быть конечным числом.")
    return float(value)


def _fmt(value: float) -> str:
    rounded = round(value, 3)
    if rounded == 0:
        rounded = 0.0
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def _points(path: Mapping[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for segment in path["segments"]:
        for key in ("start", "control_1", "control_2", "end"):
            if key in segment:
                raw = segment[key]
                points.append((_number(raw[0], key), _number(raw[1], key)))
    return points


def _piece_bounds(piece: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = _points(piece["seam_contour"])
    for path in piece["internal_paths"]:
        points.extend(_points(path))
    grainline = piece["grainline"]
    for raw in (grainline["start"], grainline["end"]):
        points.append((_number(raw[0], "grainline"), _number(raw[1], "grainline")))
    if not points:
        raise SVGRenderError("Деталь не содержит точек.")
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _transform(point: list[float], bounds, offset_x: float, offset_y: float) -> tuple[float, float]:
    return (
        offset_x + _number(point[0], "x") - bounds[0],
        offset_y + bounds[3] - _number(point[1], "y"),
    )


def _path_data(
    path: Mapping[str, Any], bounds, offset_x: float, offset_y: float
) -> str:
    segments = path["segments"]
    if not segments:
        raise SVGRenderError("Пустой путь нельзя показать.")
    start = _transform(segments[0]["start"], bounds, offset_x, offset_y)
    commands = [f"M {_fmt(start[0])} {_fmt(start[1])}"]
    for segment in segments:
        end = _transform(segment["end"], bounds, offset_x, offset_y)
        kind = segment["type"]
        if kind == "line":
            commands.append(f"L {_fmt(end[0])} {_fmt(end[1])}")
        elif kind == "cubic_bezier":
            first = _transform(segment["control_1"], bounds, offset_x, offset_y)
            second = _transform(segment["control_2"], bounds, offset_x, offset_y)
            commands.append(
                f"C {_fmt(first[0])} {_fmt(first[1])} "
                f"{_fmt(second[0])} {_fmt(second[1])} "
                f"{_fmt(end[0])} {_fmt(end[1])}"
            )
        elif kind == "arc":
            commands.append(
                f"A {_fmt(_number(segment['radius_x_mm'], 'radius_x_mm'))} "
                f"{_fmt(_number(segment['radius_y_mm'], 'radius_y_mm'))} "
                f"{_fmt(-_number(segment['rotation_deg'], 'rotation_deg'))} "
                f"{1 if segment['large_arc'] else 0} "
                f"{0 if segment['sweep'] else 1} "
                f"{_fmt(end[0])} {_fmt(end[1])}"
            )
        else:
            raise SVGRenderError("Неизвестный тип сегмента.")
    if path["closed"]:
        commands.append("Z")
    return " ".join(commands)


def _notch_line(piece: Mapping[str, Any], notch: Mapping[str, Any], bounds, ox, oy) -> str:
    segments = {
        segment["id"]: segment for segment in piece["seam_contour"]["segments"]
    }
    segment = segments.get(notch["segment_id"])
    if segment is None:
        return ""
    start = segment["start"]
    end = segment["end"]
    chord = math.hypot(end[0] - start[0], end[1] - start[1])
    fraction = 0.5 if chord <= 1e-9 else min(
        1.0, max(0.0, _number(notch["distance_from_start_mm"], "notch") / chord)
    )
    raw = [
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    ]
    x, y = _transform(raw, bounds, ox, oy)
    return (
        f'<line class="notch" x1="{_fmt(x - 3)}" y1="{_fmt(y - 3)}" '
        f'x2="{_fmt(x + 3)}" y2="{_fmt(y + 3)}"/>'
    )


def render_pattern_svg(pattern: Mapping[str, Any]) -> str:
    """Render a responsive diagnostic preview without scripts or external assets."""

    pieces = pattern.get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise SVGRenderError("Для предпросмотра нужна хотя бы одна деталь.")
    margin = 18.0
    gap = 24.0
    label_height = 16.0
    columns = 2
    bounds = [_piece_bounds(piece) for piece in pieces]
    widths = [item[2] - item[0] for item in bounds]
    heights = [item[3] - item[1] for item in bounds]
    rows = (len(pieces) + columns - 1) // columns
    column_widths = [
        max((widths[index] for index in range(column, len(pieces), columns)), default=0.0)
        for column in range(columns)
    ]
    row_heights = [
        max(
            (heights[index] for index in range(row * columns, min((row + 1) * columns, len(pieces)))),
            default=0.0,
        )
        for row in range(rows)
    ]
    canvas_width = margin * 2 + sum(column_widths) + gap * (columns - 1)
    canvas_height = margin * 2 + sum(height + label_height for height in row_heights) + gap * max(0, rows - 1)
    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="0 0 {_fmt(canvas_width)} {_fmt(canvas_height)}" '
        f'width="{_fmt(canvas_width)}mm" height="{_fmt(canvas_height)}mm">',
        "<title>Диагностический предпросмотр выкройки Kroika</title>",
        "<desc>Детали без припусков. Перед раскроем обязательны проверка закройщика и макет.</desc>",
        "<defs><marker id="grain-arrow" viewBox="0 0 6 6" refX="5" refY="3" "
        "markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L6,3 L0,6 Z" "
        "fill="#6b587f"/></marker></defs>",
        "<style>.sheet{fill:#fffdfb}.piece{fill:#fff5ed;stroke:#2f2833;stroke-width:1.1;"
        "vector-effect:non-scaling-stroke}.internal{fill:none;stroke:#b94b3d;stroke-width:.7;"
        "stroke-dasharray:4 3;vector-effect:non-scaling-stroke}.grain{stroke:#6b587f;"
        "stroke-width:.7;stroke-dasharray:7 3;marker-end:url(#grain-arrow);"
        "vector-effect:non-scaling-stroke}.notch{stroke:#2f2833;stroke-width:1.4;"
        "vector-effect:non-scaling-stroke}.label{font:700 7px system-ui,sans-serif;fill:#2f2833}"
        ".meta{font:5px system-ui,sans-serif;fill:#756b78}</style>",
        f'<rect class="sheet" width="{_fmt(canvas_width)}" height="{_fmt(canvas_height)}"/>',
    ]
    column_offsets = [margin]
    for column in range(1, columns):
        column_offsets.append(column_offsets[-1] + column_widths[column - 1] + gap)
    row_offsets = [margin]
    for row in range(1, rows):
        row_offsets.append(row_offsets[-1] + row_heights[row - 1] + label_height + gap)

    for index, piece in enumerate(pieces):
        column = index % columns
        row = index // columns
        ox = column_offsets[column]
        oy = row_offsets[row] + label_height
        piece_bounds = bounds[index]
        name = escape(str(piece["name_ru"]))
        meta = (
            f"Крой: {piece['cut_quantity']} "
            f"{'со сгибом' if piece['cut_on_fold'] else 'зеркально'} · без припусков"
        )
        fragments.append(f'<g id="piece-{escape(str(piece["id"]))}">')
        fragments.append(
            f'<text class="label" x="{_fmt(ox)}" y="{_fmt(oy - 8)}">{name}</text>'
        )
        fragments.append(
            f'<text class="meta" x="{_fmt(ox)}" y="{_fmt(oy - 2)}">{escape(meta)}</text>'
        )
        fragments.append(
            f'<path class="piece" d="{_path_data(piece["seam_contour"], piece_bounds, ox, oy)}"/>'
        )
        for path in piece["internal_paths"]:
            fragments.append(
                f'<path class="internal" d="{_path_data(path, piece_bounds, ox, oy)}"/>'
            )
        grain_start = _transform(piece["grainline"]["start"], piece_bounds, ox, oy)
        grain_end = _transform(piece["grainline"]["end"], piece_bounds, ox, oy)
        fragments.append(
            f'<line class="grain" x1="{_fmt(grain_start[0])}" y1="{_fmt(grain_start[1])}" '
            f'x2="{_fmt(grain_end[0])}" y2="{_fmt(grain_end[1])}"/>'
        )
        for notch in piece["notches"]:
            fragments.append(_notch_line(piece, notch, piece_bounds, ox, oy))
        fragments.append("</g>")
    fragments.append("</svg>")
    return "".join(fragments)

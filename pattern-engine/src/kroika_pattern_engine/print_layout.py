"""Shared millimetre layout primitives for SVG and tiled A4 output."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .geometry import contour_from_data, curve_from_data, curve_points


@dataclass(frozen=True, slots=True)
class PlacedPiece:
    piece: Mapping[str, Any]
    bounds: tuple[float, float, float, float]
    offset_x_mm: float
    offset_y_mm: float

    @property
    def width_mm(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def height_mm(self) -> float:
        return self.bounds[3] - self.bounds[1]

    def point(self, raw: list[float] | tuple[float, float]) -> tuple[float, float]:
        return (
            self.offset_x_mm + float(raw[0]) - self.bounds[0],
            self.offset_y_mm + self.bounds[3] - float(raw[1]),
        )


@dataclass(frozen=True, slots=True)
class PatternLayout:
    pieces: tuple[PlacedPiece, ...]
    width_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class Tile:
    index: int
    column: int
    row: int
    label: str
    origin_x_mm: float
    origin_y_mm: float


@dataclass(frozen=True, slots=True)
class TilePlan:
    tiles: tuple[Tile, ...]
    columns: int
    rows: int
    page_width_mm: float
    page_height_mm: float
    margin_mm: float
    overlap_mm: float
    printable_width_mm: float
    printable_height_mm: float
    stride_x_mm: float
    stride_y_mm: float


def _path_points(path: Mapping[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for segment in path["segments"]:
        curve = curve_from_data(segment)
        points.extend(
            (point.x_mm, point.y_mm) for _, point in curve_points(curve, flatness_mm=0.2)
        )
    return points


def piece_bounds(piece: Mapping[str, Any]) -> tuple[float, float, float, float]:
    paths = [piece.get("cutting_contour") or piece["seam_contour"], piece["seam_contour"]]
    paths.extend(piece.get("internal_paths", ()))
    points = [point for path in paths for point in _path_points(path)]
    grainline = piece.get("grainline")
    if grainline:
        points.extend((tuple(grainline["start"]), tuple(grainline["end"])))
    if not points:
        raise ValueError("Деталь не содержит точек для печатного макета.")
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def layout_pattern(
    pattern: Mapping[str, Any], *, columns: int = 2, margin_mm: float = 15, gap_mm: float = 25
) -> PatternLayout:
    pieces = pattern.get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise ValueError("Для печатного макета нужна хотя бы одна деталь.")
    if columns < 1:
        raise ValueError("Число колонок должно быть положительным.")
    bounds = [piece_bounds(piece) for piece in pieces]
    rows = math.ceil(len(pieces) / columns)
    widths = [item[2] - item[0] for item in bounds]
    heights = [item[3] - item[1] for item in bounds]
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
    column_offsets = [margin_mm]
    for column in range(1, columns):
        column_offsets.append(column_offsets[-1] + column_widths[column - 1] + gap_mm)
    row_offsets = [margin_mm]
    for row in range(1, rows):
        row_offsets.append(row_offsets[-1] + row_heights[row - 1] + gap_mm)
    placed = tuple(
        PlacedPiece(
            piece,
            bounds[index],
            column_offsets[index % columns],
            row_offsets[index // columns],
        )
        for index, piece in enumerate(pieces)
    )
    return PatternLayout(
        placed,
        margin_mm * 2 + sum(column_widths) + gap_mm * max(0, columns - 1),
        margin_mm * 2 + sum(row_heights) + gap_mm * max(0, rows - 1),
    )


def make_tile_plan(layout: PatternLayout, spec: Mapping[str, Any]) -> TilePlan:
    page_width = float(spec["page_width_mm"])
    page_height = float(spec["page_height_mm"])
    margin = float(spec["margin_mm"])
    overlap = float(spec["overlap_mm"])
    printable_width = page_width - 2 * margin
    printable_height = page_height - 2 * margin
    stride_x = printable_width - overlap
    stride_y = printable_height - overlap
    if min(printable_width, printable_height, stride_x, stride_y) <= 0:
        raise ValueError("Параметры листа и нахлёста не образуют печатную область.")
    columns = max(1, math.ceil(max(0.0, layout.width_mm - printable_width) / stride_x) + 1)
    rows = max(1, math.ceil(max(0.0, layout.height_mm - printable_height) / stride_y) + 1)
    tiles = tuple(
        Tile(
            row * columns + column,
            column,
            row,
            f"{_column_label(column)}{row + 1}",
            column * stride_x,
            row * stride_y,
        )
        for row in range(rows)
        for column in range(columns)
    )
    return TilePlan(
        tiles,
        columns,
        rows,
        page_width,
        page_height,
        margin,
        overlap,
        printable_width,
        printable_height,
        stride_x,
        stride_y,
    )


def notch_geometry(
    placed: PlacedPiece, notch: Mapping[str, Any], *, length_mm: float = 7
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    source = next(
        (
            segment
            for segment in placed.piece["seam_contour"]["segments"]
            if segment["id"] == notch["segment_id"]
        ),
        None,
    )
    if source is None:
        return None
    points = [point for _, point in curve_points(curve_from_data(source), flatness_mm=0.1)]
    remaining = min(max(float(notch["distance_from_start_mm"]), 0.0), sum(
        start.distance_to(end) for start, end in zip(points, points[1:], strict=False)
    ))
    point = points[0]
    tangent = points[1] - points[0]
    for start, end in zip(points, points[1:], strict=False):
        edge_length = start.distance_to(end)
        tangent = end - start
        if remaining <= edge_length or edge_length <= 1e-12:
            fraction = 0.0 if edge_length <= 1e-12 else remaining / edge_length
            point = start + tangent.scaled(fraction)
            break
        remaining -= edge_length
    orientation = 1.0 if contour_from_data(placed.piece["seam_contour"]).signed_area_mm2 > 0 else -1.0
    outward = tangent.normalized().left_normal().scaled(-orientation)
    allowance = next(
        (
            float(item["allowance_mm"])
            for item in placed.piece.get("edge_allowances", ())
            if item["segment_id"] == notch["segment_id"]
        ),
        0.0,
    )
    cutting_point = point + outward.scaled(allowance)
    first_raw = cutting_point - outward.scaled(length_mm * 0.55)
    second_raw = cutting_point + outward.scaled(length_mm * 0.45)
    first = placed.point((first_raw.x_mm, first_raw.y_mm))
    second = placed.point((second_raw.x_mm, second_raw.y_mm))
    return first, second


def _column_label(index: int) -> str:
    label = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(65 + remainder) + label
    return label

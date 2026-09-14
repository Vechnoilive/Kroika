"""Deterministic experimental geometry for the stage-7 base blocks.

Coordinates use millimetres. Bodices are drafted upward from the waist;
skirts downward from the waist. Darts are explicit internal seam paths and
their intake is included in the effective-waist control calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping
from typing import Any

from ..geometry import (
    Contour,
    CubicBezier,
    GeometryError,
    LineSegment,
    Point,
    contour_to_data,
    validate_simple_contour,
)
from .errors import BlockConstructionError
from .formulas import FORMULA_IDS, calculate_request_values, constructive_formula_inputs


@dataclass(frozen=True, slots=True)
class DraftPiece:
    id: str
    name_ru: str
    seam_contour: Contour
    internal_paths: tuple[Contour, ...]
    grainline_start: Point
    grainline_end: Point
    cut_quantity: int
    cut_on_fold: bool
    mirrored_pair: bool

    def to_pattern_data(self) -> dict[str, Any]:
        center = self.seam_contour.bounding_box
        return {
            "id": self.id,
            "name_ru": self.name_ru,
            "cut_quantity": self.cut_quantity,
            "cut_on_fold": self.cut_on_fold,
            "mirrored_pair": self.mirrored_pair,
            "seam_contour": contour_to_data(self.seam_contour),
            "cutting_contour": None,
            "internal_paths": [contour_to_data(path) for path in self.internal_paths],
            "grainline": {
                "start": [self.grainline_start.x_mm, self.grainline_start.y_mm],
                "end": [self.grainline_end.x_mm, self.grainline_end.y_mm],
            },
            "notches": [],
            "annotations": [{
                "id": f"{self.id}_experimental",
                "text_ru": "Экспериментальный базовый блок: перед раскроем нужна проверка закройщиком и макет.",
                "position": [
                    (center.min_x_mm + center.max_x_mm) / 2.0,
                    (center.min_y_mm + center.max_y_mm) / 2.0,
                ],
            }],
        }


@dataclass(frozen=True, slots=True)
class BaseBlockSet:
    front_bodice: DraftPiece
    back_bodice: DraftPiece
    front_skirt: DraftPiece
    back_skirt: DraftPiece
    formula_inputs: dict[str, float]
    formula_values: dict[str, float]
    controls: dict[str, float]

    @property
    def pieces(self) -> tuple[DraftPiece, ...]:
        return (
            self.front_bodice,
            self.back_bodice,
            self.front_skirt,
            self.back_skirt,
        )

    def to_pattern_data(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "unit": "mm",
            "pieces": [piece.to_pattern_data() for piece in self.pieces],
            # Assembly and seam-pair policy intentionally belong to stage 8.
            "seam_pairs": [],
        }


@dataclass(frozen=True, slots=True)
class SleeveBlock:
    piece: DraftPiece
    target_cap_length_mm: float
    actual_cap_length_mm: float
    cap_height_mm: float


def _line_path(path_id: str, points: tuple[Point, ...]) -> Contour:
    if len(points) < 2:
        raise ValueError("An internal path needs at least two points")
    return Contour(
        tuple(
            LineSegment(points[index], points[index + 1], f"{path_id}_{index + 1}")
            for index in range(len(points) - 1)
        ),
        closed=False,
        id=path_id,
    )


def _measurement(request: Mapping[str, Any], name: str) -> float:
    try:
        value = request["body_measurements"]["values"][name]["value"]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "BLOCK_MEASUREMENT_REQUIRED",
            f"Для геометрии базового блока нужна мерка «{name}».",
            f"/body_measurements/values/{name}",
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BlockConstructionError(
            "BLOCK_INPUT_NOT_NUMERIC",
            "Мерка должна быть конечным числом.",
            f"/body_measurements/values/{name}/value",
        )
    return float(value)


def _style_number(container: Mapping[str, Any], key: str, pointer: str) -> float:
    try:
        value = container[key]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "BLOCK_STYLE_PARAMETER_REQUIRED",
            f"Для построения нужен параметр «{key}».",
            pointer,
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BlockConstructionError(
            "BLOCK_STYLE_PARAMETER_INVALID",
            f"Параметр «{key}» должен быть конечным числом.",
            pointer,
        )
    return float(value)


def _shoulder_points(
    half_span: float,
    tip_height: float,
    shoulder_length: float,
    shoulder_angle_rad: float,
    piece_pointer: str,
) -> tuple[Point, Point]:
    tip = Point(half_span, tip_height)
    neck = Point(
        half_span - shoulder_length * math.cos(shoulder_angle_rad),
        tip_height + shoulder_length * math.sin(shoulder_angle_rad),
    )
    if neck.x_mm <= 10.0:
        raise BlockConstructionError(
            "BLOCK_SHOULDER_OUTSIDE_DOMAIN",
            "Длина плеча не помещается в половине плечевого обхвата; перепроверьте обе мерки.",
            piece_pointer,
        )
    return tip, neck


def _front_bodice(
    inputs: Mapping[str, float],
    values: Mapping[str, float],
    shoulder_length: float,
    front_neck_depth: float,
) -> DraftPiece:
    half_span = inputs["shoulder_span"] / 2.0
    angle = math.atan(values["shoulder_tan"])
    shoulder_tip, neck_shoulder = _shoulder_points(
        half_span, values["front_max_length"], shoulder_length, angle,
        "/body_measurements/values/shoulder_length",
    )
    center_neck = Point(0.0, neck_shoulder.y_mm - front_neck_depth)
    underarm = Point(
        values["front_width"],
        values["front_max_length"] - values["armhole_depth"],
    )
    waist_side = Point(values["front_waist"] + values["front_waist_dart"], 0.0)
    if center_neck.y_mm <= 20.0 or underarm.y_mm <= 20.0:
        raise BlockConstructionError(
            "BLOCK_FRONT_VERTICAL_DOMAIN",
            "Глубина горловины или проймы не помещается в длине переда.",
            "/garment_spec/parameters/neckline",
        )

    side_dart_start_y = values["bust_from_waist"]
    side_dart_end_y = side_dart_start_y + values["side_dart_width"]
    if side_dart_start_y <= 0.0 or side_dart_end_y >= underarm.y_mm:
        raise BlockConstructionError(
            "BLOCK_SIDE_DART_OUTSIDE_SEAM",
            "Нагрудная вытачка не помещается между талией и проймой; перепроверьте баланс переда.",
            "/body_measurements",
        )

    vertical = shoulder_tip.y_mm - underarm.y_mm
    horizontal = underarm.x_mm - shoulder_tip.x_mm
    contour = Contour(
        (
            LineSegment(Point(0.0, 0.0), waist_side, "front_waist"),
            CubicBezier(
                waist_side,
                Point(waist_side.x_mm, underarm.y_mm * 0.38),
                Point(underarm.x_mm, underarm.y_mm * 0.72),
                underarm,
                "front_side",
            ),
            CubicBezier(
                underarm,
                Point(underarm.x_mm, underarm.y_mm + vertical * 0.45),
                Point(shoulder_tip.x_mm + horizontal * 0.35, shoulder_tip.y_mm - vertical * 0.20),
                shoulder_tip,
                "front_armhole",
            ),
            LineSegment(shoulder_tip, neck_shoulder, "front_shoulder"),
            CubicBezier(
                neck_shoulder,
                Point(neck_shoulder.x_mm * 0.55, neck_shoulder.y_mm),
                Point(0.0, center_neck.y_mm + (neck_shoulder.y_mm - center_neck.y_mm) * 0.55),
                center_neck,
                "front_neckline",
            ),
            LineSegment(center_neck, Point(0.0, 0.0), "front_center"),
        ),
        id="front_bodice_seam",
    )

    dart_center = inputs["bust_span"] / 2.0
    dart_half = values["front_waist_dart"] / 2.0
    if dart_center - dart_half <= 5.0 or dart_center + dart_half >= waist_side.x_mm - 5.0:
        raise BlockConstructionError(
            "BLOCK_WAIST_DART_OUTSIDE_SEAM",
            "Талиевая вытачка переда не помещается на линии талии.",
            "/body_measurements/values/bust_span",
        )
    waist_dart = _line_path(
        "front_waist_dart",
        (
            Point(dart_center - dart_half, 0.0),
            Point(dart_center, values["front_waist_dart_depth"]),
            Point(dart_center + dart_half, 0.0),
        ),
    )
    side_dart = _line_path(
        "front_side_dart",
        (
            Point(underarm.x_mm, side_dart_start_y),
            Point(underarm.x_mm - values["side_dart_depth"], (side_dart_start_y + side_dart_end_y) / 2.0),
            Point(underarm.x_mm, side_dart_end_y),
        ),
    )
    bust_line = _line_path(
        "front_bust_line",
        (Point(0.0, values["bust_from_waist"]), Point(values["front_width"], values["bust_from_waist"])),
    )
    return DraftPiece(
        "front_bodice",
        "Базовый лиф — перед",
        contour,
        (waist_dart, side_dart, bust_line),
        Point(20.0, 30.0),
        Point(20.0, center_neck.y_mm - 30.0),
        1,
        True,
        False,
    )


def _back_bodice(
    inputs: Mapping[str, float],
    values: Mapping[str, float],
    shoulder_length: float,
    back_neck_depth: float,
) -> DraftPiece:
    half_span = inputs["shoulder_span"] / 2.0
    angle = math.atan(values["shoulder_tan"])
    shoulder_tip, neck_shoulder = _shoulder_points(
        half_span, values["back_length"], shoulder_length, angle,
        "/body_measurements/values/shoulder_length",
    )
    center_neck = Point(0.0, neck_shoulder.y_mm - back_neck_depth)
    underarm = Point(values["back_width"], values["back_length"] - values["armhole_depth"])
    waist_raw = values["back_width"] - values["back_side_take"]
    waist_side = Point(waist_raw, 0.0)
    if center_neck.y_mm <= 20.0 or underarm.y_mm <= 20.0:
        raise BlockConstructionError(
            "BLOCK_BACK_VERTICAL_DOMAIN",
            "Глубина горловины или проймы не помещается в длине спинки.",
            "/garment_spec/parameters/neckline",
        )

    vertical = shoulder_tip.y_mm - underarm.y_mm
    horizontal = underarm.x_mm - shoulder_tip.x_mm
    contour = Contour(
        (
            LineSegment(Point(0.0, 0.0), waist_side, "back_waist"),
            CubicBezier(
                waist_side,
                Point(waist_side.x_mm, underarm.y_mm * 0.38),
                Point(underarm.x_mm, underarm.y_mm * 0.72),
                underarm,
                "back_side",
            ),
            CubicBezier(
                underarm,
                Point(underarm.x_mm, underarm.y_mm + vertical * 0.42),
                Point(shoulder_tip.x_mm + horizontal * 0.32, shoulder_tip.y_mm - vertical * 0.18),
                shoulder_tip,
                "back_armhole",
            ),
            LineSegment(shoulder_tip, neck_shoulder, "back_shoulder"),
            CubicBezier(
                neck_shoulder,
                Point(neck_shoulder.x_mm * 0.55, neck_shoulder.y_mm),
                Point(0.0, center_neck.y_mm + (neck_shoulder.y_mm - center_neck.y_mm) * 0.45),
                center_neck,
                "back_neckline",
            ),
            LineSegment(center_neck, Point(0.0, 0.0), "back_center"),
        ),
        id="back_bodice_seam",
    )

    dart_width = values["back_each_dart"]
    centers = (waist_raw * 0.34, waist_raw * 0.69)
    depths = (values["back_dart_depth"], values["back_short_dart_depth"])
    darts: list[Contour] = []
    if dart_width > 0.0:
        for index, (center, depth) in enumerate(zip(centers, depths, strict=True), start=1):
            half = dart_width / 2.0
            if center - half <= 5.0 or center + half >= waist_raw - 5.0:
                raise BlockConstructionError(
                    "BLOCK_BACK_DART_OUTSIDE_SEAM",
                    "Задние талиевые вытачки не помещаются на линии талии.",
                    "/body_measurements/values/back_waist_arc",
                )
            darts.append(_line_path(
                f"back_waist_dart_{index}",
                (
                    Point(center - half, 0.0),
                    Point(center, depth),
                    Point(center + half, 0.0),
                ),
            ))
    darts.append(_line_path(
        "back_bust_line",
        (Point(0.0, values["bust_from_waist"]), Point(values["back_width"], values["bust_from_waist"])),
    ))
    return DraftPiece(
        "back_bodice",
        "Базовый лиф — спинка",
        contour,
        tuple(darts),
        Point(20.0, 30.0),
        Point(20.0, center_neck.y_mm - 30.0),
        2,
        False,
        True,
    )


def _skirt_piece(
    *,
    piece_id: str,
    name_ru: str,
    hip_width: float,
    waist_width: float,
    dart_widths: tuple[float, ...],
    dart_depths: tuple[float, ...],
    hip_depth: float,
    length: float,
    expansion: float,
    cut_on_fold: bool,
) -> DraftPiece:
    if length <= hip_depth + 50.0:
        raise BlockConstructionError(
            "BLOCK_SKIRT_LENGTH_DOMAIN",
            "Длина юбки должна быть минимум на 50 мм ниже линии бёдер.",
            "/garment_spec/parameters/skirt/length_from_waist_mm",
        )
    center_waist = Point(0.0, 0.0)
    center_hem = Point(0.0, -length)
    side_hem = Point(hip_width + expansion, -length)
    side_hip = Point(hip_width, -hip_depth)
    side_waist = Point(waist_width, 0.0)
    contour = Contour(
        (
            LineSegment(center_waist, center_hem, f"{piece_id}_center"),
            LineSegment(center_hem, side_hem, f"{piece_id}_hem"),
            CubicBezier(
                side_hem,
                Point(side_hem.x_mm, -length + (length - hip_depth) * 0.35),
                Point(side_hip.x_mm, -hip_depth - (length - hip_depth) * 0.28),
                side_hip,
                f"{piece_id}_side_lower",
            ),
            CubicBezier(
                side_hip,
                Point(side_hip.x_mm, -hip_depth * 0.55),
                Point(side_waist.x_mm, -hip_depth * 0.22),
                side_waist,
                f"{piece_id}_side_upper",
            ),
            LineSegment(side_waist, center_waist, f"{piece_id}_waist"),
        ),
        id=f"{piece_id}_seam",
    )

    internal: list[Contour] = []
    count = len(dart_widths)
    centers = (
        (waist_width * 0.45,)
        if count == 1
        else (waist_width * 0.34, waist_width * 0.69)
    )
    for index, (center, width, depth) in enumerate(
        zip(centers, dart_widths, dart_depths, strict=True), start=1
    ):
        if width <= 0.0:
            continue
        half = width / 2.0
        if center - half <= 5.0 or center + half >= waist_width - 5.0:
            raise BlockConstructionError(
                "BLOCK_SKIRT_DART_OUTSIDE_SEAM",
                "Талиевая вытачка юбки не помещается на линии талии.",
                "/body_measurements",
            )
        internal.append(_line_path(
            f"{piece_id}_dart_{index}",
            (
                Point(center - half, 0.0),
                Point(center, -depth),
                Point(center + half, 0.0),
            ),
        ))
    internal.append(_line_path(
        f"{piece_id}_hip_line",
        (Point(0.0, -hip_depth), Point(hip_width, -hip_depth)),
    ))
    return DraftPiece(
        piece_id,
        name_ru,
        contour,
        tuple(internal),
        Point(20.0, -30.0),
        Point(20.0, -length + 30.0),
        1 if cut_on_fold else 2,
        cut_on_fold,
        not cut_on_fold,
    )


def _segment(piece: DraftPiece, segment_id: str):
    return next(segment for segment in piece.seam_contour.segments if segment.id == segment_id)


def build_base_blocks(request: Mapping[str, Any]) -> BaseBlockSet:
    """Build front/back bodice and skirt blocks for the bounded first scenario."""

    inputs = constructive_formula_inputs(request)
    values = calculate_request_values(request)
    shoulder_length = _measurement(request, "shoulder_length")

    try:
        parameters = request["garment_spec"]["parameters"]
        neckline = parameters["neckline"]
        skirt = parameters["skirt"]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "BLOCK_STYLE_PARAMETER_REQUIRED",
            "Не хватает параметров горловины или юбки.",
            "/garment_spec/parameters",
        ) from error
    if neckline.get("type") != "round" or skirt.get("type") != "a_line":
        raise BlockConstructionError(
            "BLOCK_VARIANT_NOT_IMPLEMENTED",
            "На этапе 7 проверяется круглая горловина и базовая А-силуэтная юбка.",
            "/garment_spec/parameters",
        )
    front_depth = _style_number(neckline, "front_depth_mm", "/garment_spec/parameters/neckline/front_depth_mm")
    back_depth = _style_number(neckline, "back_depth_mm", "/garment_spec/parameters/neckline/back_depth_mm")
    skirt_length = _style_number(skirt, "length_from_waist_mm", "/garment_spec/parameters/skirt/length_from_waist_mm")
    expansion = _style_number(skirt, "hem_expansion_each_side_mm", "/garment_spec/parameters/skirt/hem_expansion_each_side_mm")
    if min(front_depth, back_depth) <= 0.0 or expansion < 0.0:
        raise BlockConstructionError(
            "BLOCK_STYLE_PARAMETER_INVALID",
            "Глубины горловины должны быть положительными, расширение низа — неотрицательным.",
            "/garment_spec/parameters",
        )

    front_bodice = _front_bodice(inputs, values, shoulder_length, front_depth)
    back_bodice = _back_bodice(inputs, values, shoulder_length, back_depth)
    front_skirt = _skirt_piece(
        piece_id="front_skirt",
        name_ru="Базовая юбка — перед",
        hip_width=values["skirt_front_hip"],
        waist_width=values["skirt_front_hip"] - values["skirt_front_side_take"],
        dart_widths=(values["skirt_front_dart"],),
        dart_depths=(values["skirt_front_dart_depth"],),
        hip_depth=inputs["hip_depth"],
        length=skirt_length,
        expansion=expansion,
        cut_on_fold=True,
    )
    back_skirt = _skirt_piece(
        piece_id="back_skirt",
        name_ru="Базовая юбка — спинка",
        hip_width=values["skirt_back_hip"],
        waist_width=values["skirt_back_hip"] - values["skirt_back_side_take"],
        dart_widths=(values["skirt_back_each_dart"], values["skirt_back_each_dart"]),
        dart_depths=(values["skirt_back_dart_depth"], values["skirt_back_dart_depth"] * 0.9),
        hip_depth=values["skirt_back_depth"],
        length=skirt_length,
        expansion=expansion,
        cut_on_fold=False,
    )
    for piece in (front_bodice, back_bodice, front_skirt, back_skirt):
        try:
            validate_simple_contour(piece.seam_contour)
        except GeometryError as error:
            raise BlockConstructionError(
                "BLOCK_GEOMETRY_INVALID",
                f"Контур «{piece.name_ru}» не прошёл геометрическую проверку.",
                f"/pattern/pieces/{piece.id}",
            ) from error

    front_bodice_effective = _segment(front_bodice, "front_waist").length_mm - values["front_waist_dart"]
    back_bodice_effective = (
        _segment(back_bodice, "back_waist").length_mm - 2.0 * values["back_each_dart"]
    )
    front_skirt_effective = (
        _segment(front_skirt, "front_skirt_waist").length_mm - values["skirt_front_dart"]
    )
    back_skirt_effective = (
        _segment(back_skirt, "back_skirt_waist").length_mm - values["skirt_back_dart_total"]
    )
    controls = {
        "formula_count": float(len(FORMULA_IDS)),
        "front_bodice_waist_residual_mm": front_bodice_effective - values["front_waist"],
        "back_bodice_waist_residual_mm": back_bodice_effective - values["back_waist"],
        "front_skirt_waist_residual_mm": front_skirt_effective - values["front_waist"],
        "back_skirt_waist_residual_mm": back_skirt_effective - values["back_waist"],
        "front_side_projection_residual_mm": (
            values["front_max_length"] - values["side_dart_width"] - values["front_side_target"]
        ),
        "front_armhole_length_mm": _segment(front_bodice, "front_armhole").length_mm,
        "back_armhole_length_mm": _segment(back_bodice, "back_armhole").length_mm,
        "shoulder_length_residual_front_mm": (
            _segment(front_bodice, "front_shoulder").length_mm - shoulder_length
        ),
        "shoulder_length_residual_back_mm": (
            _segment(back_bodice, "back_shoulder").length_mm - shoulder_length
        ),
        "skirt_side_length_residual_mm": (
            _segment(back_skirt, "back_skirt_side_lower").length_mm
            + _segment(back_skirt, "back_skirt_side_upper").length_mm
            - _segment(front_skirt, "front_skirt_side_lower").length_mm
            - _segment(front_skirt, "front_skirt_side_upper").length_mm
        ),
    }
    return BaseBlockSet(
        front_bodice,
        back_bodice,
        front_skirt,
        back_skirt,
        inputs,
        values,
        controls,
    )


def build_one_piece_sleeve(
    *,
    front_armhole_length_mm: float,
    back_armhole_length_mm: float,
    upper_arm_circumference_mm: float,
    upper_arm_ease_mm: float,
    sleeve_length_mm: float,
    wrist_circumference_mm: float,
    hand_circumference_mm: float,
    sleeve_balance_mm: float,
    cap_ease_mm: float = 0.0,
) -> SleeveBlock:
    """Draft a symmetric one-piece sleeve and solve cap height by seam length."""

    numbers = {
        "front_armhole_length_mm": front_armhole_length_mm,
        "back_armhole_length_mm": back_armhole_length_mm,
        "upper_arm_circumference_mm": upper_arm_circumference_mm,
        "upper_arm_ease_mm": upper_arm_ease_mm,
        "sleeve_length_mm": sleeve_length_mm,
        "wrist_circumference_mm": wrist_circumference_mm,
        "hand_circumference_mm": hand_circumference_mm,
        "sleeve_balance_mm": sleeve_balance_mm,
        "cap_ease_mm": cap_ease_mm,
    }
    for key, value in numbers.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BlockConstructionError("SLEEVE_INPUT_INVALID", "Параметры рукава должны быть конечными числами.", f"/{key}")
    if min(front_armhole_length_mm, back_armhole_length_mm, upper_arm_circumference_mm,
           sleeve_length_mm, wrist_circumference_mm, hand_circumference_mm, sleeve_balance_mm) <= 0.0:
        raise BlockConstructionError("SLEEVE_INPUT_INVALID", "Основные размеры рукава должны быть больше нуля.", "/sleeve")
    if upper_arm_ease_mm < 0.0 or cap_ease_mm < 0.0:
        raise BlockConstructionError("SLEEVE_INPUT_INVALID", "Отрицательная прибавка рукава не поддерживается.", "/sleeve")

    flat_biceps_width = (upper_arm_circumference_mm + upper_arm_ease_mm) / 2.0
    target = front_armhole_length_mm + back_armhole_length_mm + cap_ease_mm
    if target <= flat_biceps_width:
        raise BlockConstructionError(
            "SLEEVE_CAP_DOMAIN",
            "Длина проймы недостаточна для заданной ширины рукава.",
            "/sleeve",
        )
    half_width = flat_biceps_width / 2.0

    def cap(height: float) -> tuple[CubicBezier, CubicBezier]:
        left = Point(-half_width, 0.0)
        top = Point(0.0, height)
        right = Point(half_width, 0.0)
        front = CubicBezier(
            left,
            Point(-half_width, height * 0.50),
            Point(-half_width * 0.52, height),
            top,
            "sleeve_cap_front",
        )
        back = CubicBezier(
            top,
            Point(half_width * 0.48, height),
            Point(half_width, height * 0.56),
            right,
            "sleeve_cap_back",
        )
        return front, back

    low = 0.001
    high = max(sleeve_balance_mm, target)
    for _ in range(16):
        front, back = cap(high)
        if front.length_mm + back.length_mm >= target:
            break
        high *= 2.0
    else:
        raise BlockConstructionError("SLEEVE_CAP_SOLVER", "Не удалось ограничить высоту оката.", "/sleeve")

    for _ in range(80):
        middle = (low + high) / 2.0
        front, back = cap(middle)
        if front.length_mm + back.length_mm < target:
            low = middle
        else:
            high = middle
    cap_height = (low + high) / 2.0
    front_cap, back_cap = cap(cap_height)
    actual = front_cap.length_mm + back_cap.length_mm

    flat_wrist_width = max(wrist_circumference_mm, hand_circumference_mm) / 2.0
    right_underarm = Point(half_width, 0.0)
    right_wrist = Point(flat_wrist_width / 2.0, -sleeve_length_mm)
    left_wrist = Point(-flat_wrist_width / 2.0, -sleeve_length_mm)
    left_underarm = Point(-half_width, 0.0)
    contour = Contour(
        (
            front_cap,
            back_cap,
            LineSegment(right_underarm, right_wrist, "sleeve_back_seam"),
            LineSegment(right_wrist, left_wrist, "sleeve_hem"),
            LineSegment(left_wrist, left_underarm, "sleeve_front_seam"),
        ),
        id="sleeve_seam",
    )
    try:
        validate_simple_contour(contour)
    except GeometryError as error:
        raise BlockConstructionError(
            "SLEEVE_GEOMETRY_INVALID",
            "Контур рукава не прошёл геометрическую проверку.",
            "/sleeve",
        ) from error

    piece = DraftPiece(
        "base_sleeve",
        "Базовый одношовный рукав",
        contour,
        (_line_path("sleeve_biceps_line", (left_underarm, right_underarm)),),
        Point(0.0, cap_height - 20.0),
        Point(0.0, -sleeve_length_mm + 20.0),
        2,
        False,
        True,
    )
    return SleeveBlock(piece, target, actual, cap_height)

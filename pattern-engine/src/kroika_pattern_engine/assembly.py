"""Component assembly for the bounded stage-12 woven garment catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .blocks import (
    BaseBlockSet,
    BlockConstructionError,
    DraftPiece,
    SkirtBlockSet,
    TrouserBlockSet,
    build_one_piece_sleeve,
)
from .geometry import Contour, CubicBezier, LineSegment, Point, validate_simple_contour


MAX_UNVERIFIED_EASE_MM = 5.0


@dataclass(frozen=True, slots=True)
class GarmentAssembly:
    pattern: dict[str, Any]
    controls: dict[str, float]


def _segment(piece: DraftPiece, segment_id: str):
    try:
        return next(segment for segment in piece.seam_contour.segments if segment.id == segment_id)
    except StopIteration as error:
        raise BlockConstructionError(
            "GARMENT_INTERFACE_MISSING",
            "В базовом блоке отсутствует требуемый участок шва.",
            f"/pattern/pieces/{piece.id}/seam_contour",
        ) from error


def _reverse(segment, segment_id: str):
    if isinstance(segment, LineSegment):
        return LineSegment(segment.end, segment.start, segment_id)
    if isinstance(segment, CubicBezier):
        return CubicBezier(
            segment.end,
            segment.control_2,
            segment.control_1,
            segment.start,
            segment_id,
        )
    raise BlockConstructionError(
        "GARMENT_FACING_CURVE_UNSUPPORTED",
        "Тип кривой пока не поддерживается для обтачки.",
        "/pattern/pieces",
    )


def _facing_piece(bodice: DraftPiece, prefix: str, name_ru: str, cut_on_fold: bool) -> DraftPiece:
    armhole = _segment(bodice, f"{prefix}_armhole")
    shoulder = _segment(bodice, f"{prefix}_shoulder")
    neckline = _segment(bodice, f"{prefix}_neckline")
    underarm = armhole.start
    center_neck = neckline.end
    facing_depth = 50.0
    lower_y = min(underarm.y_mm, center_neck.y_mm) - facing_depth
    if lower_y <= 5.0:
        raise BlockConstructionError(
            "GARMENT_FACING_OUTSIDE_DOMAIN",
            "Высоты лифа недостаточно для цельнокроеной обтачки шириной 50 мм.",
            f"/pattern/pieces/{bodice.id}",
        )
    lower_center = Point(0.0, lower_y)
    lower_side = Point(underarm.x_mm, lower_y)
    contour = Contour(
        (
            LineSegment(lower_center, center_neck, f"{prefix}_facing_center"),
            _reverse(neckline, f"{prefix}_facing_neckline"),
            _reverse(shoulder, f"{prefix}_facing_shoulder"),
            _reverse(armhole, f"{prefix}_facing_armhole"),
            LineSegment(underarm, lower_side, f"{prefix}_facing_side"),
            CubicBezier(
                lower_side,
                Point(underarm.x_mm * 0.72, lower_y),
                Point(underarm.x_mm * 0.28, lower_y),
                lower_center,
                f"{prefix}_facing_inner",
            ),
        ),
        id=f"{prefix}_facing_seam",
    )
    try:
        validate_simple_contour(contour)
    except Exception as error:
        raise BlockConstructionError(
            "GARMENT_FACING_GEOMETRY_INVALID",
            f"Обтачка «{name_ru}» не прошла геометрическую проверку.",
            f"/pattern/pieces/{prefix}_facing",
        ) from error
    return DraftPiece(
        f"{prefix}_facing",
        name_ru,
        contour,
        (),
        Point(min(20.0, underarm.x_mm * 0.25), lower_y + 10.0),
        Point(min(20.0, underarm.x_mm * 0.25), center_neck.y_mm - 10.0),
        1 if cut_on_fold else 2,
        cut_on_fold,
        not cut_on_fold,
    )


def _neck_facing_piece(
    bodice: DraftPiece, prefix: str, name_ru: str, cut_on_fold: bool
) -> DraftPiece:
    """Build a separate 45 mm neckline facing for a sleeved upper garment."""

    neckline = _segment(bodice, f"{prefix}_neckline")
    shoulder = _segment(bodice, f"{prefix}_shoulder")
    if not isinstance(shoulder, LineSegment):
        raise BlockConstructionError(
            "GARMENT_NECK_FACING_UNSUPPORTED",
            "Плечевой срез должен быть отрезком для построения обтачки горловины.",
            f"/pattern/pieces/{bodice.id}",
        )
    facing_depth = min(45.0, shoulder.length_mm * 0.45)
    shoulder_inner = shoulder.point_at(1.0 - facing_depth / shoulder.length_mm)
    center_outer = neckline.end
    center_inner = Point(center_outer.x_mm, center_outer.y_mm - facing_depth)
    neck_shoulder = neckline.start
    contour = Contour(
        (
            LineSegment(center_inner, center_outer, f"{prefix}_neck_facing_center"),
            _reverse(neckline, f"{prefix}_neck_facing_neckline"),
            LineSegment(
                neck_shoulder, shoulder_inner, f"{prefix}_neck_facing_shoulder"
            ),
            CubicBezier(
                shoulder_inner,
                Point(shoulder_inner.x_mm * 0.72, shoulder_inner.y_mm - 8.0),
                Point(center_inner.x_mm + neck_shoulder.x_mm * 0.25, center_inner.y_mm),
                center_inner,
                f"{prefix}_neck_facing_inner",
            ),
        ),
        id=f"{prefix}_neck_facing_seam",
    )
    try:
        validate_simple_contour(contour)
    except Exception as error:
        raise BlockConstructionError(
            "GARMENT_NECK_FACING_GEOMETRY_INVALID",
            f"Обтачка горловины «{name_ru}» не прошла геометрическую проверку.",
            f"/pattern/pieces/{prefix}_neck_facing",
        ) from error
    return DraftPiece(
        f"{prefix}_neck_facing",
        name_ru,
        contour,
        (),
        Point(max(5.0, neck_shoulder.x_mm * 0.2), center_inner.y_mm + 5.0),
        Point(max(5.0, neck_shoulder.x_mm * 0.2), center_outer.y_mm - 5.0),
        1 if cut_on_fold else 2,
        cut_on_fold,
        not cut_on_fold,
    )


def _length(piece: DraftPiece, segment_ids: tuple[str, ...]) -> float:
    return sum(_segment(piece, segment_id).length_mm for segment_id in segment_ids)


def _add_notches(
    data: dict[str, Any],
    piece: DraftPiece,
    specifications: tuple[tuple[str, str, str, float], ...],
) -> None:
    for notch_id, match_id, segment_id, fraction in specifications:
        try:
            segment = _segment(piece, segment_id)
        except BlockConstructionError:
            continue
        data["notches"].append({
            "id": notch_id,
            "match_id": match_id,
            "segment_id": segment_id,
            "distance_from_start_mm": round(segment.length_mm * fraction, 6),
            "kind": "single",
        })


def _decorate_piece(
    piece: DraftPiece, garment_name: str, *, armhole_finish: str = "facing"
) -> dict[str, Any]:
    data = piece.to_pattern_data()
    data["name_ru"] = data["name_ru"].replace("Базовый лиф", f"{garment_name} · лиф")
    center = piece.seam_contour.bounding_box
    data["annotations"].insert(0, {
        "id": f"{piece.id}_cut",
        "text_ru": (
            f"{data['name_ru']}. Крой: {data['cut_quantity']} "
            f"{'со сгибом' if data['cut_on_fold'] else 'зеркально'}; без припусков."
        ),
        "position": [
            (center.min_x_mm + center.max_x_mm) / 2.0,
            (center.min_y_mm + center.max_y_mm) / 2.0 + 12.0,
        ],
    })
    notch_map: dict[str, tuple[tuple[str, str, str, float], ...]] = {
        "front_bodice": (
            ("front_waist_match", "front_waist_join", "front_waist", 0.2),
            ("front_side_match", "bodice_side_join", "front_side", 0.45),
            ("front_shoulder_match", "bodice_shoulder_join", "front_shoulder", 0.5),
            (
                "front_armhole_match",
                "front_sleeve_join" if armhole_finish == "sleeve" else "front_armhole_facing",
                "front_armhole",
                0.55,
            ),
            ("front_neckline_match", "front_neckline_facing", "front_neckline", 0.5),
        ),
        "back_bodice": (
            ("back_waist_match", "back_waist_join", "back_waist", 0.2),
            ("back_side_match", "bodice_side_join", "back_side", 0.45),
            ("back_shoulder_match", "bodice_shoulder_join", "back_shoulder", 0.5),
            (
                "back_armhole_match",
                "back_sleeve_join" if armhole_finish == "sleeve" else "back_armhole_facing",
                "back_armhole",
                0.55,
            ),
            ("back_neckline_match", "back_neckline_facing", "back_neckline", 0.5),
        ),
        "front_skirt": (
            ("front_skirt_waist_match", "front_waist_join", "front_skirt_waist", 0.8),
            ("front_skirt_side_match", "skirt_side_join", "front_skirt_side_upper", 0.5),
        ),
        "back_skirt": (
            ("back_skirt_waist_match", "back_waist_join", "back_skirt_waist", 0.8),
            ("back_skirt_side_match", "skirt_side_join", "back_skirt_side_upper", 0.5),
        ),
        "front_facing": (
            ("front_facing_neck_match", "front_neckline_facing", "front_facing_neckline", 0.5),
            ("front_facing_arm_match", "front_armhole_facing", "front_facing_armhole", 0.45),
            ("front_facing_shoulder_match", "facing_shoulder_join", "front_facing_shoulder", 0.5),
        ),
        "back_facing": (
            ("back_facing_neck_match", "back_neckline_facing", "back_facing_neckline", 0.5),
            ("back_facing_arm_match", "back_armhole_facing", "back_facing_armhole", 0.45),
            ("back_facing_shoulder_match", "facing_shoulder_join", "back_facing_shoulder", 0.5),
        ),
        "front_neck_facing": (
            ("front_neck_facing_match", "front_neckline_facing", "front_neck_facing_neckline", 0.5),
            ("front_neck_facing_shoulder_match", "neck_facing_shoulder_join", "front_neck_facing_shoulder", 0.5),
        ),
        "back_neck_facing": (
            ("back_neck_facing_match", "back_neckline_facing", "back_neck_facing_neckline", 0.5),
            ("back_neck_facing_shoulder_match", "neck_facing_shoulder_join", "back_neck_facing_shoulder", 0.5),
        ),
        "base_sleeve": (
            ("sleeve_front_match", "front_sleeve_join", "sleeve_cap_front", 0.55),
            ("sleeve_back_match", "back_sleeve_join", "sleeve_cap_back", 0.55),
        ),
        "front_trouser": (
            ("front_side_hip_match", "trouser_side_upper_join", "front_side_upper", 0.75),
            ("front_side_leg_match", "trouser_side_lower_join", "front_side_lower", 0.55),
            ("front_inseam_match", "trouser_inseam_upper_join", "front_inseam_upper", 0.5),
            ("front_waist_match", "trouser_front_waist_join", "front_waist", 0.75),
        ),
        "back_trouser": (
            ("back_side_hip_match", "trouser_side_upper_join", "back_side_upper", 0.75),
            ("back_side_leg_match", "trouser_side_lower_join", "back_side_lower", 0.55),
            ("back_inseam_match", "trouser_inseam_upper_join", "back_inseam_upper", 0.5),
            ("back_waist_match", "trouser_back_waist_join", "back_waist", 0.75),
        ),
    }
    _add_notches(data, piece, notch_map.get(piece.id, ()))
    return data


def _line_path(path_id: str, start: Point, end: Point, segment_id: str) -> Contour:
    return Contour((LineSegment(start, end, segment_id),), closed=False, id=path_id)


def _rectangle_piece(
    piece_id: str,
    name_ru: str,
    width_mm: float,
    height_mm: float,
    *,
    cut_quantity: int,
    cut_on_fold: bool,
    mirrored_pair: bool,
) -> DraftPiece:
    if min(width_mm, height_mm) <= 0.0:
        raise BlockConstructionError(
            "GARMENT_COMPONENT_OUTSIDE_DOMAIN",
            f"Размеры детали «{name_ru}» должны быть положительными.",
            f"/pattern/pieces/{piece_id}",
        )
    lower_left = Point(0.0, 0.0)
    lower_right = Point(width_mm, 0.0)
    upper_right = Point(width_mm, height_mm)
    upper_left = Point(0.0, height_mm)
    contour = Contour(
        (
            LineSegment(lower_left, lower_right, f"{piece_id}_lower"),
            LineSegment(lower_right, upper_right, f"{piece_id}_side"),
            LineSegment(upper_right, upper_left, f"{piece_id}_upper"),
            LineSegment(upper_left, lower_left, f"{piece_id}_center"),
        ),
        id=f"{piece_id}_seam",
    )
    validate_simple_contour(contour)
    return DraftPiece(
        piece_id,
        name_ru,
        contour,
        (),
        Point(width_mm * 0.25, 5.0),
        Point(width_mm * 0.75, 5.0),
        cut_quantity,
        cut_on_fold,
        mirrored_pair,
    )


def _extend_bodice(
    piece: DraftPiece,
    prefix: str,
    name_ru: str,
    extension_mm: float,
    hem_width_mm: float,
    *,
    front_opening: bool = False,
    back_on_fold: bool = False,
    front_extension_mm: float = 30.0,
) -> DraftPiece:
    if not 40.0 <= extension_mm <= 300.0:
        raise BlockConstructionError(
            "GARMENT_UPPER_LENGTH_OUTSIDE_DOMAIN",
            "Длина верха ниже талии должна быть от 40 до 300 мм.",
            "/garment_spec/parameters/upper/length_below_waist_mm",
        )
    waist = _segment(piece, f"{prefix}_waist")
    center = _segment(piece, f"{prefix}_center")
    side_hem = Point(max(hem_width_mm, waist.end.x_mm), -extension_mm)
    placket_width = front_extension_mm if front_opening else 0.0
    center_hem = Point(-placket_width, -extension_mm)
    segments: list[Any] = [
        LineSegment(center_hem, side_hem, f"{prefix}_upper_hem"),
        LineSegment(side_hem, waist.end, f"{prefix}_upper_extension_side"),
        *piece.seam_contour.segments[1:-1],
    ]
    internal = list(piece.internal_paths)
    internal.append(_line_path(
        f"{prefix}_waist_reference",
        waist.start,
        waist.end,
        f"{prefix}_waist_reference_line",
    ))
    if front_opening:
        placket_top = Point(-placket_width, center.start.y_mm)
        segments.extend((
            LineSegment(center.start, placket_top, "front_placket_top"),
            LineSegment(placket_top, center_hem, "front_placket_edge"),
        ))
        internal.append(_line_path(
            "front_placket_fold",
            Point(0.0, -extension_mm),
            center.start,
            "front_placket_fold_line",
        ))
    else:
        segments.append(LineSegment(center.start, center_hem, f"{prefix}_center"))
    contour = Contour(tuple(segments), id=f"{prefix}_upper_seam")
    try:
        validate_simple_contour(contour)
    except Exception as error:
        raise BlockConstructionError(
            "GARMENT_UPPER_GEOMETRY_INVALID",
            f"Удлинённая деталь «{name_ru}» не прошла проверку геометрии.",
            f"/pattern/pieces/{piece.id}",
        ) from error
    cut_on_fold = (not front_opening) if prefix == "front" else back_on_fold
    return DraftPiece(
        piece.id,
        name_ru,
        contour,
        tuple(internal),
        Point(20.0, center_hem.y_mm + 20.0),
        Point(20.0, center.start.y_mm - 20.0),
        1 if cut_on_fold else 2,
        cut_on_fold,
        not cut_on_fold,
    )


def _collar_band(front_neck_mm: float, back_neck_mm: float) -> DraftPiece:
    total = front_neck_mm + back_neck_mm
    height = 35.0
    p0 = Point(0.0, 0.0)
    split = Point(front_neck_mm, 0.0)
    p1 = Point(total, 0.0)
    p2 = Point(total, height)
    p3 = Point(0.0, height)
    contour = Contour(
        (
            LineSegment(p0, split, "collar_band_front_neckline"),
            LineSegment(split, p1, "collar_band_back_neckline"),
            LineSegment(p1, p2, "collar_band_front_edge"),
            LineSegment(p2, p3, "collar_band_upper"),
            LineSegment(p3, p0, "collar_band_center"),
        ),
        id="collar_band_seam",
    )


def _clone_piece(piece: DraftPiece, piece_id: str, name_ru: str, prefix: str) -> DraftPiece:
    """Copy exact geometry while giving a lining/layer its own stable segment ids."""

    def clone_segment(segment):
        segment_id = f"{prefix}_{segment.id}"
        if isinstance(segment, LineSegment):
            return LineSegment(segment.start, segment.end, segment_id)
        if isinstance(segment, CubicBezier):
            return CubicBezier(
                segment.start, segment.control_1, segment.control_2, segment.end, segment_id
            )
        raise BlockConstructionError(
            "GARMENT_LAYER_CURVE_UNSUPPORTED",
            "Тип кривой не поддерживается для слоя жакета.",
            f"/pattern/pieces/{piece_id}",
        )

    return DraftPiece(
        piece_id,
        name_ru,
        Contour(
            tuple(clone_segment(segment) for segment in piece.seam_contour.segments),
            closed=True,
            id=f"{piece_id}_seam",
        ),
        tuple(
            Contour(
                tuple(clone_segment(segment) for segment in path.segments),
                closed=path.closed,
                id=f"{prefix}_{path.id}",
            )
            for path in piece.internal_paths
        ),
        piece.grainline_start,
        piece.grainline_end,
        piece.cut_quantity,
        piece.cut_on_fold,
        piece.mirrored_pair,
    )


def _jacket_collar(
    piece_id: str, name_ru: str, front_neck_mm: float, back_neck_mm: float,
    collar_width_mm: float,
) -> DraftPiece:
    total = front_neck_mm + back_neck_mm
    p0 = Point(0.0, 0.0)
    split = Point(front_neck_mm, 0.0)
    p1 = Point(total, 0.0)
    p2 = Point(total + 12.0, collar_width_mm)
    p3 = Point(0.0, collar_width_mm)
    contour = Contour((
        LineSegment(p0, split, f"{piece_id}_front_neckline"),
        LineSegment(split, p1, f"{piece_id}_back_neckline"),
        LineSegment(p1, p2, f"{piece_id}_gorge"),
        LineSegment(p2, p3, f"{piece_id}_outer"),
        LineSegment(p3, p0, f"{piece_id}_center"),
    ), id=f"{piece_id}_seam")
    validate_simple_contour(contour)
    return DraftPiece(
        piece_id, name_ru, contour,
        (_line_path(
            f"{piece_id}_roll_line", Point(0.0, 25.0), Point(total, 25.0),
            f"{piece_id}_roll_line_segment",
        ),),
        Point(total * 0.25, 10.0), Point(total * 0.75, 10.0),
        2, True, False,
    )


def _jacket_facing(front_edge_mm: float, width_mm: float) -> DraftPiece:
    return _rectangle_piece(
        "jacket_front_facing", "Жакет · подборт", width_mm, front_edge_mm,
        cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )


def _named_cubic(curve: CubicBezier, segment_id: str) -> CubicBezier:
    return CubicBezier(
        curve.start, curve.control_1, curve.control_2, curve.end, segment_id
    )


def _split_jacket_front(
    front: DraftPiece, princess_x: float, extension_mm: float,
) -> tuple[DraftPiece, DraftPiece]:
    """Turn the front princess line into two actual cut pieces."""

    armhole = _segment(front, "front_armhole")
    if not isinstance(armhole, CubicBezier):
        raise BlockConstructionError(
            "JACKET_PRINCESS_ARMHOLE_UNSUPPORTED",
            "Для рельефа жакета пройма переда должна быть кривой Безье.",
            "/pattern/pieces/front_bodice/front_armhole",
        )
    side_armhole_raw, center_armhole_raw = armhole.split(0.48)
    side_armhole = _named_cubic(side_armhole_raw, "jacket_side_front_armhole")
    center_armhole = _named_cubic(center_armhole_raw, "jacket_center_front_armhole")
    hem = _segment(front, "front_upper_hem")
    hem_split = Point(princess_x, -extension_mm)
    if not hem.start.x_mm < hem_split.x_mm < hem.end.x_mm:
        raise BlockConstructionError(
            "JACKET_PRINCESS_OUTSIDE_FRONT",
            "Рельеф переда не помещается между бортом и боковой линией.",
            "/garment_spec/parameters/jacket",
        )
    princess = LineSegment(
        hem_split, side_armhole.end, "jacket_center_princess"
    )
    center_contour = Contour((
        LineSegment(hem.start, hem_split, "jacket_center_front_hem"),
        princess,
        center_armhole,
        _segment(front, "front_shoulder"),
        _segment(front, "front_neckline"),
        _segment(front, "front_placket_top"),
        _segment(front, "front_placket_edge"),
    ), id="jacket_front_center_seam")
    side_contour = Contour((
        LineSegment(hem_split, hem.end, "jacket_side_front_hem"),
        _segment(front, "front_upper_extension_side"),
        _segment(front, "front_side"),
        side_armhole,
        LineSegment(princess.end, princess.start, "jacket_side_princess"),
    ), id="jacket_side_front_seam")
    try:
        validate_simple_contour(center_contour)
        validate_simple_contour(side_contour)
    except Exception as error:
        raise BlockConstructionError(
            "JACKET_PRINCESS_GEOMETRY_INVALID",
            "Детали рельефного переда не прошли геометрическую проверку.",
            "/garment_spec/parameters/jacket",
        ) from error
    center_paths = tuple(
        path for path in front.internal_paths
        if path.id in {"front_placket_fold", "jacket_roll_line", "jacket_button_line"}
    )
    side_paths = tuple(
        path for path in front.internal_paths
        if path.id in {"front_bust_line", "front_waist_reference"}
    )
    return (
        DraftPiece(
            "jacket_front_center", "Жакет · центр переда", center_contour, center_paths,
            Point(15.0, -extension_mm + 25.0),
            Point(15.0, front.grainline_end.y_mm),
            2, False, True,
        ),
        DraftPiece(
            "jacket_side_front", "Жакет · боковая часть переда", side_contour, side_paths,
            Point(princess_x + 15.0, -extension_mm + 25.0),
            Point(princess_x + 15.0, side_armhole.end.y_mm - 25.0),
            2, False, True,
        ),
    )


def _split_jacket_sleeve_front(
    sleeve: DraftPiece, side_armhole_mm: float, total_front_armhole_mm: float,
) -> DraftPiece:
    cap = _segment(sleeve, "sleeve_cap_front")
    if not isinstance(cap, CubicBezier):
        raise BlockConstructionError(
            "JACKET_SLEEVE_CAP_UNSUPPORTED", "Окат рукава должен быть кривой Безье.",
            "/pattern/pieces/base_sleeve",
        )
    fraction = side_armhole_mm / total_front_armhole_mm
    low, high = 0.0, 1.0
    target = cap.length_mm * fraction
    for _ in range(64):
        middle = (low + high) / 2.0
        left, _ = cap.split(middle)
        if left.length_mm < target:
            low = middle
        else:
            high = middle
    side_raw, center_raw = cap.split((low + high) / 2.0)
    contour = Contour((
        _named_cubic(side_raw, "sleeve_cap_front_side"),
        _named_cubic(center_raw, "sleeve_cap_front_center"),
        *sleeve.seam_contour.segments[1:],
    ), id=sleeve.seam_contour.id)
    validate_simple_contour(contour)
    return DraftPiece(
        sleeve.id, sleeve.name_ru, contour, sleeve.internal_paths,
        sleeve.grainline_start, sleeve.grainline_end, sleeve.cut_quantity,
        sleeve.cut_on_fold, sleeve.mirrored_pair,
    )
    validate_simple_contour(contour)
    return DraftPiece(
        "collar_band",
        "Рубашка · стойка воротника",
        contour,
        (),
        Point(total * 0.25, 8.0),
        Point(total * 0.75, 8.0),
        2,
        True,
        False,
    )


def _append_pair(
    pairs: list[dict[str, Any]],
    by_id: Mapping[str, DraftPiece],
    pair_id: str,
    first_piece_id: str,
    first_segment_ids: tuple[str, ...],
    second_piece_id: str,
    second_segment_ids: tuple[str, ...],
    first_length_reduction_mm: float = 0.0,
    second_length_reduction_mm: float = 0.0,
) -> None:
    first_length = _length(by_id[first_piece_id], first_segment_ids)
    second_length = _length(by_id[second_piece_id], second_segment_ids)
    first_effective = first_length - first_length_reduction_mm
    second_effective = second_length - second_length_reduction_mm
    if min(first_effective, second_effective) <= 0.0:
        raise BlockConstructionError(
            "GARMENT_INTERFACE_REDUCTION_INVALID",
            "Раствор вытачки превышает длину соответствующего участка шва.",
            "/pattern/seam_pairs",
        )
    pairs.append({
        "id": pair_id,
        "first_piece_id": first_piece_id,
        "first_segment_ids": list(first_segment_ids),
        "second_piece_id": second_piece_id,
        "second_segment_ids": list(second_segment_ids),
        "first_length_reduction_mm": round(first_length_reduction_mm, 6),
        "second_length_reduction_mm": round(second_length_reduction_mm, 6),
        "allowed_ease_mm": round(abs(first_effective - second_effective), 6),
        "tolerance_mm": 1.0,
    })


def _interface_controls(
    pairs: list[dict[str, Any]], by_id: Mapping[str, DraftPiece]
) -> tuple[float, float]:
    residuals: list[float] = []
    for pair in pairs:
        first = _length(by_id[pair["first_piece_id"]], tuple(pair["first_segment_ids"]))
        first -= pair["first_length_reduction_mm"]
        second = _length(by_id[pair["second_piece_id"]], tuple(pair["second_segment_ids"]))
        second -= pair["second_length_reduction_mm"]
        residuals.append(abs(abs(first - second) - pair["allowed_ease_mm"]))
    maximum_ease = max((pair["allowed_ease_mm"] for pair in pairs), default=0.0)
    if maximum_ease > MAX_UNVERIFIED_EASE_MM:
        raise BlockConstructionError(
            "GARMENT_SEAM_TRUEING_OUTSIDE_DOMAIN",
            "Разница парных швов превышает безопасный исследовательский предел 5 мм.",
            "/pattern/seam_pairs",
        )
    return max(residuals, default=0.0), maximum_ease


def _measurement(request: Mapping[str, Any], key: str) -> float:
    try:
        value = request["body_measurements"]["values"][key]["value"]
    except (KeyError, TypeError) as error:
        raise BlockConstructionError(
            "BLOCK_MEASUREMENT_REQUIRED",
            f"Для выбранного изделия нужна мерка «{key}».",
            f"/body_measurements/values/{key}",
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0.0:
        raise BlockConstructionError(
            "BLOCK_MEASUREMENT_INVALID",
            "Мерка должна быть положительным числом.",
            f"/body_measurements/values/{key}/value",
        )
    return float(value)


def _assemble_skirt(request: Mapping[str, Any], blocks: SkirtBlockSet) -> GarmentAssembly:
    front_band = _rectangle_piece(
        "front_waistband", "Юбка · пояс переда", blocks.formula_values["front_waist"], 40.0,
        cut_quantity=1, cut_on_fold=True, mirrored_pair=False,
    )
    back_band = _rectangle_piece(
        "back_waistband", "Юбка · пояс спинки", blocks.formula_values["back_waist"], 40.0,
        cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )
    pieces = (blocks.front_skirt, blocks.back_skirt, front_band, back_band)
    by_id = {piece.id: piece for piece in pieces}
    pairs: list[dict[str, Any]] = []
    _append_pair(
        pairs, by_id, "front_waist_join", "front_skirt", ("front_skirt_waist",),
        "front_waistband", ("front_waistband_lower",),
        blocks.formula_values["skirt_front_dart"],
    )
    _append_pair(
        pairs, by_id, "back_waist_join", "back_skirt", ("back_skirt_waist",),
        "back_waistband", ("back_waistband_lower",),
        blocks.formula_values["skirt_back_dart_total"],
    )
    _append_pair(
        pairs, by_id, "skirt_side_join", "front_skirt",
        ("front_skirt_side_lower", "front_skirt_side_upper"), "back_skirt",
        ("back_skirt_side_lower", "back_skirt_side_upper"),
    )
    _append_pair(
        pairs, by_id, "waistband_side_join", "front_waistband",
        ("front_waistband_side",), "back_waistband", ("back_waistband_side",),
    )
    residual, maximum_ease = _interface_controls(pairs, by_id)
    return GarmentAssembly(
        {
            "schema_version": "1.0.0",
            "unit": "mm",
            "pieces": [_decorate_piece(piece, "Юбка") for piece in pieces],
            "seam_pairs": pairs,
        },
        {
            "piece_count": float(len(pieces)),
            "seam_pair_count": float(len(pairs)),
            "maximum_interface_residual_mm": residual,
            "maximum_declared_ease_mm": maximum_ease,
            "waist_control_residual_mm": max(
                abs(blocks.controls["front_skirt_waist_residual_mm"]),
                abs(blocks.controls["back_skirt_waist_residual_mm"]),
            ),
        },
    )


def _assemble_trousers(
    request: Mapping[str, Any], blocks: TrouserBlockSet
) -> GarmentAssembly:
    """Assemble the bounded straight-trouser or tailored-shorts set."""

    spec = request["garment_spec"]
    parameters = spec["parameters"]
    trousers = parameters["trousers"]
    finishing = parameters["finishing"]
    expected_variant = "straight_trousers" if spec["garment_type"] == "trousers" else "tailored_shorts"
    supported = (
        trousers["variant"] == expected_variant
        and trousers["leg_shape"] == "straight"
        and trousers["waist_position"] == "natural"
        and trousers["pocket_type"] == "slash"
        and trousers["pleat_count"] == 0
        and parameters["shaping"] == "darts"
        and parameters["sleeve"]["type"] == "sleeveless"
        and parameters["closure"]["type"] == "zipper"
        and parameters["closure"]["location"] == "center_front"
        and finishing.get("waistband") is True
        and finishing.get("pockets") is True
        and finishing.get("fly_front") is True
        and finishing.get("neckline_facing") is False
        and finishing.get("armhole_facing") is False
        and not finishing.get("lining", False)
    )
    if not supported:
        raise BlockConstructionError(
            "GARMENT_VARIANT_NOT_IMPLEMENTED",
            "Поддержаны только прямые брюки или шорты на естественной талии: "
            "вытачки, прямой пояс, боковые карманы и передняя молния.",
            "/garment_spec/parameters",
        )
    garment_name = "Брюки" if spec["garment_type"] == "trousers" else "Шорты"
    band_height = float(trousers["waistband_width_mm"])
    fly_length = float(trousers["fly_length_mm"])
    pocket_opening = float(trousers["pocket_opening_mm"])
    front_band = _rectangle_piece(
        "trouser_front_waistband", f"{garment_name} · пояс переда",
        blocks.formula_values["front_waist"], band_height,
        cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )
    back_band = _rectangle_piece(
        "trouser_back_waistband", f"{garment_name} · пояс спинки",
        blocks.formula_values["back_waist"], band_height,
        cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )
    fly_facing = _rectangle_piece(
        "trouser_fly_facing", f"{garment_name} · обтачка гульфика",
        fly_length, 48.0, cut_quantity=1, cut_on_fold=False, mirrored_pair=False,
    )
    fly_shield = _rectangle_piece(
        "trouser_fly_shield", f"{garment_name} · откосок",
        fly_length, 70.0, cut_quantity=1, cut_on_fold=False, mirrored_pair=False,
    )
    pocket_bag = _rectangle_piece(
        "trouser_pocket_bag", f"{garment_name} · мешковина кармана",
        pocket_opening, 180.0, cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )
    pocket_facing = _rectangle_piece(
        "trouser_pocket_facing", f"{garment_name} · подзор кармана",
        pocket_opening, 65.0, cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )
    pieces = (
        blocks.front_leg, blocks.back_leg, front_band, back_band,
        fly_facing, fly_shield, pocket_bag, pocket_facing,
    )
    by_id = {piece.id: piece for piece in pieces}
    pairs: list[dict[str, Any]] = []
    _append_pair(pairs, by_id, "trouser_side_upper_join", "front_trouser",
                 ("front_side_upper",), "back_trouser", ("back_side_upper",))
    _append_pair(pairs, by_id, "trouser_side_lower_join", "front_trouser",
                 ("front_side_lower", "front_side_below_balance"), "back_trouser",
                 ("back_side_lower", "back_side_below_balance"))
    _append_pair(pairs, by_id, "trouser_inseam_upper_join", "front_trouser",
                 ("front_inseam_upper",), "back_trouser", ("back_inseam_upper",))
    _append_pair(pairs, by_id, "trouser_inseam_lower_join", "front_trouser",
                 ("front_inseam_lower",), "back_trouser", ("back_inseam_lower",))
    _append_pair(pairs, by_id, "trouser_front_crotch_join", "front_trouser",
                 ("front_center_crotch",), "front_trouser", ("front_center_crotch",))
    _append_pair(pairs, by_id, "trouser_back_crotch_join", "back_trouser",
                 ("back_center_crotch",), "back_trouser", ("back_center_crotch",))
    _append_pair(
        pairs, by_id, "trouser_front_waist_join", "front_trouser", ("front_waist",),
        "trouser_front_waistband", ("trouser_front_waistband_lower",),
        blocks.formula_values["front_waist_dart"],
    )
    _append_pair(
        pairs, by_id, "trouser_back_waist_join", "back_trouser", ("back_waist",),
        "trouser_back_waistband", ("trouser_back_waistband_lower",),
        blocks.formula_values["back_waist_dart"],
    )
    _append_pair(pairs, by_id, "trouser_waistband_side_join", "trouser_front_waistband",
                 ("trouser_front_waistband_side",), "trouser_back_waistband",
                 ("trouser_back_waistband_side",))
    _append_pair(pairs, by_id, "trouser_fly_facing_join", "trouser_fly_facing",
                 ("trouser_fly_facing_lower",), "trouser_fly_shield",
                 ("trouser_fly_shield_lower",))
    _append_pair(pairs, by_id, "trouser_fly_outer_join", "trouser_fly_facing",
                 ("trouser_fly_facing_upper",), "trouser_fly_shield",
                 ("trouser_fly_shield_upper",))
    _append_pair(pairs, by_id, "trouser_pocket_join", "trouser_pocket_bag",
                 ("trouser_pocket_bag_lower",), "trouser_pocket_facing",
                 ("trouser_pocket_facing_lower",))
    residual, maximum_ease = _interface_controls(pairs, by_id)
    return GarmentAssembly(
        {
            "schema_version": "1.0.0", "unit": "mm",
            "pieces": [_decorate_piece(piece, garment_name) for piece in pieces],
            "seam_pairs": pairs,
        },
        {
            "piece_count": float(len(pieces)),
            "seam_pair_count": float(len(pairs)),
            "maximum_interface_residual_mm": residual,
            "maximum_declared_ease_mm": maximum_ease,
            "waist_control_residual_mm": blocks.controls["finished_waist_residual_mm"],
            "trouser_side_residual_mm": blocks.controls["side_seam_residual_mm"],
            "trouser_inseam_residual_mm": blocks.controls["inseam_residual_mm"],
            "trouser_hip_residual_mm": blocks.controls["finished_hip_residual_mm"],
        },
    )


def _assemble_upper(request: Mapping[str, Any], blocks: BaseBlockSet) -> GarmentAssembly:
    spec = request["garment_spec"]
    garment_type = spec["garment_type"]
    names = {"top": "Топ", "blouse": "Блузка", "shirt": "Рубашка", "vest": "Жилет"}
    garment_name = names[garment_type]
    upper = spec["parameters"].get("upper", {})
    extension = float(upper.get("length_below_waist_mm", 100.0))
    ratio = min(1.0, extension / blocks.formula_inputs["hip_depth"])
    front_waist = _segment(blocks.front_bodice, "front_waist").end.x_mm
    back_waist = _segment(blocks.back_bodice, "back_waist").end.x_mm
    front_hem = front_waist + (blocks.formula_values["skirt_front_hip"] - front_waist) * ratio
    back_hem = back_waist + (blocks.formula_values["skirt_back_hip"] - back_waist) * ratio
    front_opening = garment_type in {"shirt", "vest"}
    back_on_fold = front_opening
    front = _extend_bodice(
        blocks.front_bodice, "front", f"{garment_name} · перед", extension, front_hem,
        front_opening=front_opening,
    )
    back = _extend_bodice(
        blocks.back_bodice, "back", f"{garment_name} · спинка", extension, back_hem,
        back_on_fold=back_on_fold,
    )
    pieces: list[DraftPiece] = [front, back]
    pairs: list[dict[str, Any]] = []

    sleeved = garment_type in {"blouse", "shirt"}
    if sleeved:
        sleeve = build_one_piece_sleeve(
            front_armhole_length_mm=blocks.controls["front_armhole_length_mm"],
            back_armhole_length_mm=blocks.controls["back_armhole_length_mm"],
            upper_arm_circumference_mm=_measurement(request, "upper_arm_circumference"),
            upper_arm_ease_mm=request["fit_settings"]["wearing_ease_mm"]["upper_arm"],
            sleeve_length_mm=float(spec["parameters"]["sleeve"]["length_mm"]),
            wrist_circumference_mm=_measurement(request, "wrist_circumference"),
            hand_circumference_mm=_measurement(request, "hand_circumference"),
            sleeve_balance_mm=blocks.formula_values["sleeve_balance"],
        ).piece
        pieces.append(sleeve)
        if garment_type == "blouse":
            pieces.extend((
                _neck_facing_piece(
                    front, "front", "Блузка · обтачка горловины переда", True
                ),
                _neck_facing_piece(
                    back, "back", "Блузка · обтачка горловины спинки", False
                ),
            ))
    else:
        front_facing = _facing_piece(
            front, "front", f"{garment_name} · обтачка переда", not front_opening
        )
        back_facing = _facing_piece(
            back, "back", f"{garment_name} · обтачка спинки", back_on_fold
        )
        pieces.extend((front_facing, back_facing))

    if garment_type == "shirt":
        front_neck = _length(front, ("front_neckline",))
        back_neck = _length(back, ("back_neckline",))
        band = _collar_band(front_neck, back_neck)
        collar = _rectangle_piece(
            "shirt_collar", "Рубашка · воротник", front_neck + back_neck, 65.0,
            cut_quantity=2, cut_on_fold=True, mirrored_pair=False,
        )
        pieces.extend((band, collar))

    by_id = {piece.id: piece for piece in pieces}
    _append_pair(
        pairs, by_id, "bodice_shoulder_join", "front_bodice", ("front_shoulder",),
        "back_bodice", ("back_shoulder",),
    )
    _append_pair(
        pairs, by_id, "bodice_side_join", "front_bodice", ("front_side",),
        "back_bodice", ("back_side",), blocks.controls["front_side_dart_seam_reduction_mm"],
    )
    _append_pair(
        pairs, by_id, "upper_extension_side_join", "front_bodice",
        ("front_upper_extension_side",), "back_bodice", ("back_upper_extension_side",),
    )
    if sleeved:
        _append_pair(
            pairs, by_id, "front_sleeve_join", "front_bodice", ("front_armhole",),
            "base_sleeve", ("sleeve_cap_front",),
        )
        _append_pair(
            pairs, by_id, "back_sleeve_join", "back_bodice", ("back_armhole",),
            "base_sleeve", ("sleeve_cap_back",),
        )
        if garment_type == "blouse":
            _append_pair(
                pairs, by_id, "front_neckline_facing", "front_bodice", ("front_neckline",),
                "front_neck_facing", ("front_neck_facing_neckline",),
            )
            _append_pair(
                pairs, by_id, "back_neckline_facing", "back_bodice", ("back_neckline",),
                "back_neck_facing", ("back_neck_facing_neckline",),
            )
            _append_pair(
                pairs, by_id, "neck_facing_shoulder_join", "front_neck_facing",
                ("front_neck_facing_shoulder",), "back_neck_facing",
                ("back_neck_facing_shoulder",),
            )
    else:
        _append_pair(
            pairs, by_id, "front_neckline_facing", "front_bodice", ("front_neckline",),
            "front_facing", ("front_facing_neckline",),
        )
        _append_pair(
            pairs, by_id, "back_neckline_facing", "back_bodice", ("back_neckline",),
            "back_facing", ("back_facing_neckline",),
        )
        _append_pair(
            pairs, by_id, "front_armhole_facing", "front_bodice", ("front_armhole",),
            "front_facing", ("front_facing_armhole",),
        )
        _append_pair(
            pairs, by_id, "back_armhole_facing", "back_bodice", ("back_armhole",),
            "back_facing", ("back_facing_armhole",),
        )
        _append_pair(
            pairs, by_id, "facing_shoulder_join", "front_facing", ("front_facing_shoulder",),
            "back_facing", ("back_facing_shoulder",),
        )
    if garment_type == "shirt":
        _append_pair(
            pairs, by_id, "front_collar_band_join", "front_bodice", ("front_neckline",),
            "collar_band", ("collar_band_front_neckline",),
        )
        _append_pair(
            pairs, by_id, "back_collar_band_join", "back_bodice", ("back_neckline",),
            "collar_band", ("collar_band_back_neckline",),
        )
        _append_pair(
            pairs, by_id, "collar_join", "collar_band", ("collar_band_upper",),
            "shirt_collar", ("shirt_collar_lower",),
        )

    residual, maximum_ease = _interface_controls(pairs, by_id)
    return GarmentAssembly(
        {
            "schema_version": "1.0.0",
            "unit": "mm",
            "pieces": [
                _decorate_piece(piece, garment_name, armhole_finish="sleeve" if sleeved else "facing")
                for piece in pieces
            ],
            "seam_pairs": pairs,
        },
        {
            "piece_count": float(len(pieces)),
            "seam_pair_count": float(len(pairs)),
            "maximum_interface_residual_mm": residual,
            "maximum_declared_ease_mm": maximum_ease,
            "waist_control_residual_mm": max(
                abs(blocks.controls["front_bodice_waist_residual_mm"]),
                abs(blocks.controls["back_bodice_waist_residual_mm"]),
            ),
        },
    )


def _assemble_jacket(request: Mapping[str, Any], blocks: BaseBlockSet) -> GarmentAssembly:
    """Assemble the single bounded stage-13 light-jacket variant."""

    parameters = request["garment_spec"]["parameters"]
    jacket = parameters["jacket"]
    finishing = parameters["finishing"]
    supported = (
        parameters["bodice_fit"] == "semi_fitted"
        and parameters["shaping"] == "princess_seams"
        and parameters["sleeve"]["type"] == "long"
        and parameters["closure"]["type"] == "buttons"
        and parameters["closure"]["location"] == "center_front"
        and jacket["variant"] == "light_single_breasted"
        and jacket["button_count"] == 2
        and jacket["pocket_type"] == "patch"
        and jacket["sleeve_construction"] == "one_piece"
        and jacket["lining"] == "full"
        and finishing.get("front_facing") is True
        and finishing.get("lining") is True
        and finishing.get("pockets") is True
        and finishing.get("vent") is True
        and finishing.get("collar") is True
        and finishing.get("armhole_facing") is False
    )
    if not supported:
        raise BlockConstructionError(
            "GARMENT_VARIANT_NOT_IMPLEMENTED",
            "Поддержан только лёгкий однобортный жакет на две пуговицы с рельефом, "
            "одношовным рукавом, воротником, подбортом, подкладкой, карманами и шлицей.",
            "/garment_spec/parameters",
        )
    extension = float(parameters["upper"]["length_below_waist_mm"])
    front_extension = float(jacket["front_extension_mm"])
    ratio = min(1.0, extension / blocks.formula_inputs["hip_depth"])
    front_waist = _segment(blocks.front_bodice, "front_waist").end.x_mm
    back_waist = _segment(blocks.back_bodice, "back_waist").end.x_mm
    front_hem = front_waist + (blocks.formula_values["skirt_front_hip"] - front_waist) * ratio
    back_hem = back_waist + (blocks.formula_values["skirt_back_hip"] - back_waist) * ratio

    front_base = _extend_bodice(
        blocks.front_bodice, "front", "Жакет · перед", extension, front_hem,
        front_opening=True, front_extension_mm=front_extension,
    )
    roll_y = float(jacket["roll_line_from_waist_mm"])
    princess_x = min(
        blocks.formula_inputs["bust_span"] / 2.0,
        front_waist * 0.72,
    )
    front_unsplit = DraftPiece(
        front_base.id, front_base.name_ru, front_base.seam_contour,
        (*front_base.internal_paths,
         _line_path(
             "jacket_roll_line", Point(0.0, roll_y),
             Point(float(jacket["lapel_width_mm"]), roll_y + 105.0),
             "jacket_roll_line_segment",
         ),
         _line_path(
             "jacket_button_line", Point(-front_extension / 2.0, 25.0),
             Point(-front_extension / 2.0, 125.0), "jacket_button_line_segment",
         )),
        front_base.grainline_start, front_base.grainline_end,
        front_base.cut_quantity, front_base.cut_on_fold, front_base.mirrored_pair,
    )
    front, side_front = _split_jacket_front(front_unsplit, princess_x, extension)
    back_base = _extend_bodice(
        blocks.back_bodice, "back", "Жакет · спинка", extension, back_hem,
        back_on_fold=False,
    )
    back = DraftPiece(
        back_base.id, back_base.name_ru, back_base.seam_contour,
        (*back_base.internal_paths,
         _line_path(
             "back_center_vent", Point(0.0, -extension),
             Point(0.0, -extension + float(jacket["vent_length_mm"])),
             "back_center_vent_segment",
         )),
        back_base.grainline_start, back_base.grainline_end,
        back_base.cut_quantity, back_base.cut_on_fold, back_base.mirrored_pair,
    )
    sleeve_base = build_one_piece_sleeve(
        front_armhole_length_mm=blocks.controls["front_armhole_length_mm"],
        back_armhole_length_mm=blocks.controls["back_armhole_length_mm"],
        upper_arm_circumference_mm=_measurement(request, "upper_arm_circumference"),
        upper_arm_ease_mm=request["fit_settings"]["wearing_ease_mm"]["upper_arm"],
        sleeve_length_mm=float(parameters["sleeve"]["length_mm"]),
        wrist_circumference_mm=_measurement(request, "wrist_circumference"),
        hand_circumference_mm=_measurement(request, "hand_circumference"),
        sleeve_balance_mm=blocks.formula_values["sleeve_balance"],
    ).piece
    side_front_armhole = _length(side_front, ("jacket_side_front_armhole",))
    total_front_armhole = side_front_armhole + _length(
        front, ("jacket_center_front_armhole",)
    )
    sleeve = _split_jacket_sleeve_front(
        sleeve_base, side_front_armhole, total_front_armhole
    )
    front_neck = _length(front, ("front_neckline",))
    back_neck = _length(back, ("back_neckline",))
    collar_width = float(jacket["collar_stand_mm"] + jacket["collar_fall_mm"])
    under_collar = _jacket_collar(
        "jacket_under_collar", "Жакет · нижний воротник",
        front_neck, back_neck, collar_width,
    )
    top_collar = _jacket_collar(
        "jacket_top_collar", "Жакет · верхний воротник",
        front_neck, back_neck, collar_width,
    )
    facing = _jacket_facing(
        _length(front, ("front_placket_edge",)), float(jacket["lapel_width_mm"])
    )
    back_facing = _neck_facing_piece(
        back, "back", "Жакет · обтачка горловины спинки", False
    )
    pocket = _rectangle_piece(
        "jacket_patch_pocket", "Жакет · накладной карман",
        float(jacket["pocket_width_mm"]), float(jacket["pocket_depth_mm"]),
        cut_quantity=2, cut_on_fold=False, mirrored_pair=True,
    )
    front_lining = _clone_piece(
        front, "jacket_front_lining", "Жакет · подкладка центра переда", "lining"
    )
    side_front_lining = _clone_piece(
        side_front, "jacket_side_front_lining",
        "Жакет · подкладка боковой части переда", "lining",
    )
    back_lining = _clone_piece(back, "jacket_back_lining", "Жакет · подкладка спинки", "lining")
    sleeve_lining = _clone_piece(sleeve, "jacket_sleeve_lining", "Жакет · подкладка рукава", "lining")

    pieces = (
        front, side_front, back, sleeve, facing, back_facing, under_collar, top_collar,
        pocket, front_lining, side_front_lining, back_lining, sleeve_lining,
    )
    by_id = {piece.id: piece for piece in pieces}
    pairs: list[dict[str, Any]] = []
    _append_pair(pairs, by_id, "jacket_princess_join", "jacket_front_center",
                 ("jacket_center_princess",), "jacket_side_front", ("jacket_side_princess",))
    _append_pair(pairs, by_id, "jacket_shoulder_join", "jacket_front_center", ("front_shoulder",),
                 "back_bodice", ("back_shoulder",))
    _append_pair(
        pairs, by_id, "jacket_side_join", "jacket_side_front", ("front_side",),
        "back_bodice", ("back_side",), blocks.controls["front_side_dart_seam_reduction_mm"],
    )
    _append_pair(pairs, by_id, "jacket_lower_side_join", "jacket_side_front",
                 ("front_upper_extension_side",), "back_bodice", ("back_upper_extension_side",))
    _append_pair(pairs, by_id, "jacket_front_sleeve_side_join", "jacket_side_front",
                 ("jacket_side_front_armhole",), "base_sleeve", ("sleeve_cap_front_side",))
    _append_pair(pairs, by_id, "jacket_front_sleeve_center_join", "jacket_front_center",
                 ("jacket_center_front_armhole",), "base_sleeve", ("sleeve_cap_front_center",))
    _append_pair(pairs, by_id, "jacket_back_sleeve_join", "back_bodice", ("back_armhole",),
                 "base_sleeve", ("sleeve_cap_back",))
    _append_pair(pairs, by_id, "jacket_front_collar_join", "jacket_front_center", ("front_neckline",),
                 "jacket_under_collar", ("jacket_under_collar_front_neckline",))
    _append_pair(pairs, by_id, "jacket_back_collar_join", "back_bodice", ("back_neckline",),
                 "jacket_under_collar", ("jacket_under_collar_back_neckline",))
    _append_pair(pairs, by_id, "jacket_collar_layers_front", "jacket_under_collar",
                 ("jacket_under_collar_front_neckline",), "jacket_top_collar",
                 ("jacket_top_collar_front_neckline",))
    _append_pair(pairs, by_id, "jacket_collar_layers_back", "jacket_under_collar",
                 ("jacket_under_collar_back_neckline",), "jacket_top_collar",
                 ("jacket_top_collar_back_neckline",))
    _append_pair(pairs, by_id, "jacket_front_edge_facing", "jacket_front_center",
                 ("front_placket_edge",), "jacket_front_facing", ("jacket_front_facing_side",))
    _append_pair(pairs, by_id, "jacket_facing_lining", "jacket_front_facing",
                 ("jacket_front_facing_center",), "jacket_front_lining",
                 ("lining_front_placket_edge",))
    _append_pair(pairs, by_id, "jacket_back_neck_facing", "back_bodice", ("back_neckline",),
                 "back_neck_facing", ("back_neck_facing_neckline",))
    _append_pair(pairs, by_id, "jacket_lining_shoulder", "jacket_front_lining",
                 ("lining_front_shoulder",), "jacket_back_lining", ("lining_back_shoulder",))
    _append_pair(pairs, by_id, "jacket_lining_princess", "jacket_front_lining",
                 ("lining_jacket_center_princess",), "jacket_side_front_lining",
                 ("lining_jacket_side_princess",))
    _append_pair(
        pairs, by_id, "jacket_lining_side", "jacket_side_front_lining", ("lining_front_side",),
        "jacket_back_lining", ("lining_back_side",),
        blocks.controls["front_side_dart_seam_reduction_mm"],
    )
    _append_pair(pairs, by_id, "jacket_lining_lower_side", "jacket_side_front_lining",
                 ("lining_front_upper_extension_side",), "jacket_back_lining",
                 ("lining_back_upper_extension_side",))
    _append_pair(pairs, by_id, "jacket_lining_front_sleeve_side", "jacket_side_front_lining",
                 ("lining_jacket_side_front_armhole",), "jacket_sleeve_lining",
                 ("lining_sleeve_cap_front_side",))
    _append_pair(pairs, by_id, "jacket_lining_front_sleeve_center", "jacket_front_lining",
                 ("lining_jacket_center_front_armhole",), "jacket_sleeve_lining",
                 ("lining_sleeve_cap_front_center",))
    _append_pair(pairs, by_id, "jacket_lining_back_sleeve", "jacket_back_lining",
                 ("lining_back_armhole",), "jacket_sleeve_lining", ("lining_sleeve_cap_back",))

    residual, maximum_ease = _interface_controls(pairs, by_id)
    return GarmentAssembly(
        {
            "schema_version": "1.0.0", "unit": "mm",
            "pieces": [
                _decorate_piece(piece, "Жакет", armhole_finish="sleeve")
                for piece in pieces
            ],
            "seam_pairs": pairs,
        },
        {
            "piece_count": float(len(pieces)),
            "seam_pair_count": float(len(pairs)),
            "maximum_interface_residual_mm": residual,
            "maximum_declared_ease_mm": maximum_ease,
            "waist_control_residual_mm": max(
                abs(blocks.controls["front_bodice_waist_residual_mm"]),
                abs(blocks.controls["back_bodice_waist_residual_mm"]),
            ),
            "jacket_collar_residual_mm": 0.0,
            "jacket_facing_residual_mm": 0.0,
            "jacket_lining_residual_mm": 0.0,
        },
    )


def assemble_garment(
    request: Mapping[str, Any], blocks: BaseBlockSet | SkirtBlockSet | TrouserBlockSet
) -> GarmentAssembly:
    """Create main pieces, facings, seam relationships and matching marks."""

    spec = request["garment_spec"]
    parameters = spec["parameters"]
    if spec["garment_type"] == "skirt":
        if not isinstance(blocks, SkirtBlockSet):
            raise BlockConstructionError(
                "GARMENT_COMPONENT_MISMATCH",
                "Для юбки должен использоваться независимый нижний базовый блок.",
                "/garment_spec/garment_type",
            )
        return _assemble_skirt(request, blocks)
    if spec["garment_type"] in {"trousers", "shorts"}:
        if not isinstance(blocks, TrouserBlockSet):
            raise BlockConstructionError(
                "GARMENT_COMPONENT_MISMATCH",
                "Для брюк и шорт должна использоваться независимая брючная основа.",
                "/garment_spec/garment_type",
            )
        return _assemble_trousers(request, blocks)
    if spec["garment_type"] in {"top", "blouse", "shirt", "vest"}:
        if not isinstance(blocks, BaseBlockSet):
            raise BlockConstructionError(
                "GARMENT_COMPONENT_MISMATCH",
                "Для верха должен использоваться базовый блок лифа.",
                "/garment_spec/garment_type",
            )
        return _assemble_upper(request, blocks)
    if spec["garment_type"] == "jacket":
        if not isinstance(blocks, BaseBlockSet):
            raise BlockConstructionError(
                "GARMENT_COMPONENT_MISMATCH",
                "Для жакета должен использоваться базовый блок корпуса.",
                "/garment_spec/garment_type",
            )
        return _assemble_jacket(request, blocks)
    if not isinstance(blocks, BaseBlockSet):
        raise BlockConstructionError(
            "GARMENT_COMPONENT_MISMATCH",
            "Для платья нужен связанный блок лифа и юбки.",
            "/garment_spec/garment_type",
        )
    supported = (
        spec["garment_type"] in {"dress", "sundress"}
        and parameters["bodice_fit"] in {"fitted", "semi_fitted"}
        and parameters["neckline"]["type"] == "round"
        and parameters["sleeve"]["type"] == "sleeveless"
        and parameters["skirt"]["type"] == "a_line"
        and parameters["closure"] == {
            "type": "zipper",
            "location": "center_back",
            "length_mm": parameters["closure"]["length_mm"],
        }
        and parameters["finishing"]["neckline_facing"] is True
        and parameters["finishing"]["armhole_facing"] is True
        and parameters["finishing"].get("waistband", False) is False
        and parameters["finishing"].get("front_placket", False) is False
        and parameters["finishing"].get("collar", False) is False
    )
    if not supported:
        raise BlockConstructionError(
            "GARMENT_VARIANT_NOT_IMPLEMENTED",
            "Сейчас строятся платье и сарафан без рукавов: круглая горловина, "
            "отрезная А-юбка, вытачки, обтачки и молния по центру спинки.",
            "/garment_spec/parameters",
        )

    garment_name = "Платье" if spec["garment_type"] == "dress" else "Сарафан"
    front_facing = _facing_piece(
        blocks.front_bodice, "front", f"{garment_name} · обтачка переда", True
    )
    back_facing = _facing_piece(
        blocks.back_bodice, "back", f"{garment_name} · обтачка спинки", False
    )
    pieces = (
        blocks.front_bodice,
        blocks.back_bodice,
        blocks.front_skirt,
        blocks.back_skirt,
        front_facing,
        back_facing,
    )
    by_id = {piece.id: piece for piece in pieces}
    pairs: list[dict[str, Any]] = []

    def add_pair(
        pair_id: str,
        first_piece_id: str,
        first_segment_ids: tuple[str, ...],
        second_piece_id: str,
        second_segment_ids: tuple[str, ...],
        first_length_reduction_mm: float = 0.0,
        second_length_reduction_mm: float = 0.0,
    ) -> None:
        first_length = _length(by_id[first_piece_id], first_segment_ids)
        second_length = _length(by_id[second_piece_id], second_segment_ids)
        first_effective = first_length - first_length_reduction_mm
        second_effective = second_length - second_length_reduction_mm
        if min(first_effective, second_effective) <= 0.0:
            raise BlockConstructionError(
                "GARMENT_INTERFACE_REDUCTION_INVALID",
                "Раствор вытачки превышает длину соответствующего участка шва.",
                "/pattern/seam_pairs",
            )
        pairs.append({
            "id": pair_id,
            "first_piece_id": first_piece_id,
            "first_segment_ids": list(first_segment_ids),
            "second_piece_id": second_piece_id,
            "second_segment_ids": list(second_segment_ids),
            "first_length_reduction_mm": round(first_length_reduction_mm, 6),
            "second_length_reduction_mm": round(second_length_reduction_mm, 6),
            "allowed_ease_mm": round(abs(first_effective - second_effective), 6),
            "tolerance_mm": 1.0,
        })

    add_pair("front_waist_join", "front_bodice", ("front_waist",),
             "front_skirt", ("front_skirt_waist",),
             blocks.formula_values["front_waist_dart"],
             blocks.formula_values["skirt_front_dart"])
    add_pair("back_waist_join", "back_bodice", ("back_waist",),
             "back_skirt", ("back_skirt_waist",),
             2.0 * blocks.formula_values["back_each_dart"],
             blocks.formula_values["skirt_back_dart_total"])
    add_pair("bodice_shoulder_join", "front_bodice", ("front_shoulder",),
             "back_bodice", ("back_shoulder",))
    add_pair("bodice_side_join", "front_bodice", ("front_side",),
             "back_bodice", ("back_side",),
             blocks.controls["front_side_dart_seam_reduction_mm"])
    add_pair("skirt_side_join", "front_skirt",
             ("front_skirt_side_lower", "front_skirt_side_upper"),
             "back_skirt", ("back_skirt_side_lower", "back_skirt_side_upper"))
    add_pair("front_neckline_facing", "front_bodice", ("front_neckline",),
             "front_facing", ("front_facing_neckline",))
    add_pair("back_neckline_facing", "back_bodice", ("back_neckline",),
             "back_facing", ("back_facing_neckline",))
    add_pair("front_armhole_facing", "front_bodice", ("front_armhole",),
             "front_facing", ("front_facing_armhole",))
    add_pair("back_armhole_facing", "back_bodice", ("back_armhole",),
             "back_facing", ("back_facing_armhole",))
    add_pair("facing_shoulder_join", "front_facing", ("front_facing_shoulder",),
             "back_facing", ("back_facing_shoulder",))

    pair_residuals = []
    for pair in pairs:
        first = (
            _length(by_id[pair["first_piece_id"]], tuple(pair["first_segment_ids"]))
            - pair["first_length_reduction_mm"]
        )
        second = (
            _length(by_id[pair["second_piece_id"]], tuple(pair["second_segment_ids"]))
            - pair["second_length_reduction_mm"]
        )
        pair_residuals.append(abs(abs(first - second) - pair["allowed_ease_mm"]))

    maximum_declared_ease = max(
        (pair["allowed_ease_mm"] for pair in pairs), default=0.0
    )
    if maximum_declared_ease > MAX_UNVERIFIED_EASE_MM:
        raise BlockConstructionError(
            "GARMENT_SEAM_TRUEING_OUTSIDE_DOMAIN",
            "После закрытия вытачек разница парных швов превышает безопасный предел 5 мм.",
            "/pattern/seam_pairs",
        )

    return GarmentAssembly(
        {
            "schema_version": "1.0.0",
            "unit": "mm",
            "pieces": [_decorate_piece(piece, garment_name) for piece in pieces],
            "seam_pairs": pairs,
        },
        {
            "piece_count": float(len(pieces)),
            "seam_pair_count": float(len(pairs)),
            "maximum_interface_residual_mm": max(pair_residuals, default=0.0),
            "maximum_declared_ease_mm": maximum_declared_ease,
            "waist_control_residual_mm": max(
                abs(blocks.controls[name])
                for name in (
                    "front_bodice_waist_residual_mm",
                    "back_bodice_waist_residual_mm",
                    "front_skirt_waist_residual_mm",
                    "back_skirt_waist_residual_mm",
                )
            ),
        },
    )

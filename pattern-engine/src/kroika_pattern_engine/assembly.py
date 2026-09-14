"""Stage-8 assembly of bounded dress and sundress variants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .blocks import BaseBlockSet, BlockConstructionError, DraftPiece
from .geometry import Contour, CubicBezier, LineSegment, Point, validate_simple_contour


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


def _length(piece: DraftPiece, segment_ids: tuple[str, ...]) -> float:
    return sum(_segment(piece, segment_id).length_mm for segment_id in segment_ids)


def _add_notches(piece: dict[str, Any], specifications: tuple[tuple[str, str, float], ...]) -> None:
    segments = {
        segment["id"]: segment
        for segment in piece["seam_contour"]["segments"]
    }
    for notch_id, segment_id, fraction in specifications:
        segment = segments.get(segment_id)
        if segment is None:
            continue
        start = segment["start"]
        end = segment["end"]
        chord = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        piece["notches"].append({
            "id": notch_id,
            "segment_id": segment_id,
            "distance_from_start_mm": chord * fraction,
            "kind": "single",
        })


def _decorate_piece(piece: DraftPiece, garment_name: str) -> dict[str, Any]:
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
    notch_map: dict[str, tuple[tuple[str, str, float], ...]] = {
        "front_bodice": (
            ("front_waist_match", "front_waist", 0.2),
            ("front_side_match", "front_side", 0.45),
            ("front_shoulder_match", "front_shoulder", 0.5),
            ("front_armhole_match", "front_armhole", 0.55),
            ("front_neckline_match", "front_neckline", 0.5),
        ),
        "back_bodice": (
            ("back_waist_match", "back_waist", 0.2),
            ("back_side_match", "back_side", 0.45),
            ("back_shoulder_match", "back_shoulder", 0.5),
            ("back_armhole_match", "back_armhole", 0.55),
            ("back_neckline_match", "back_neckline", 0.5),
        ),
        "front_skirt": (
            ("front_skirt_waist_match", "front_skirt_waist", 0.8),
            ("front_skirt_side_match", "front_skirt_side_upper", 0.5),
        ),
        "back_skirt": (
            ("back_skirt_waist_match", "back_skirt_waist", 0.8),
            ("back_skirt_side_match", "back_skirt_side_upper", 0.5),
        ),
        "front_facing": (
            ("front_facing_neck_match", "front_facing_neckline", 0.5),
            ("front_facing_arm_match", "front_facing_armhole", 0.45),
        ),
        "back_facing": (
            ("back_facing_neck_match", "back_facing_neckline", 0.5),
            ("back_facing_arm_match", "back_facing_armhole", 0.45),
        ),
    }
    _add_notches(data, notch_map.get(piece.id, ()))
    return data


def assemble_garment(request: Mapping[str, Any], blocks: BaseBlockSet) -> GarmentAssembly:
    """Create main pieces, facings, seam relationships and matching marks."""

    spec = request["garment_spec"]
    parameters = spec["parameters"]
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
        and parameters["finishing"] == {
            "neckline_facing": True,
            "armhole_facing": True,
        }
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
    ) -> None:
        first_length = _length(by_id[first_piece_id], first_segment_ids)
        second_length = _length(by_id[second_piece_id], second_segment_ids)
        pairs.append({
            "id": pair_id,
            "first_piece_id": first_piece_id,
            "first_segment_ids": list(first_segment_ids),
            "second_piece_id": second_piece_id,
            "second_segment_ids": list(second_segment_ids),
            "allowed_ease_mm": round(abs(first_length - second_length), 6),
            "tolerance_mm": 1.0,
        })

    add_pair("front_waist_join", "front_bodice", ("front_waist",),
             "front_skirt", ("front_skirt_waist",))
    add_pair("back_waist_join", "back_bodice", ("back_waist",),
             "back_skirt", ("back_skirt_waist",))
    add_pair("bodice_shoulder_join", "front_bodice", ("front_shoulder",),
             "back_bodice", ("back_shoulder",))
    add_pair("bodice_side_join", "front_bodice", ("front_side",),
             "back_bodice", ("back_side",))
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
        first = _length(by_id[pair["first_piece_id"]], tuple(pair["first_segment_ids"]))
        second = _length(by_id[pair["second_piece_id"]], tuple(pair["second_segment_ids"]))
        pair_residuals.append(abs(abs(first - second) - pair["allowed_ease_mm"]))

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
            "maximum_declared_ease_mm": max(
                (pair["allowed_ease_mm"] for pair in pairs), default=0.0
            ),
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

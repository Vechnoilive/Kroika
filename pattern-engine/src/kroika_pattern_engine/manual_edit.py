"""Safe, auditable manual adjustments for an immutable generated pattern."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from .allowances import apply_seam_allowances
from .geometry import GeometryError, contour_from_data, validate_simple_contour


MAX_POINT_MOVE_MM = 50.0
MIN_PIECE_AREA_MM2 = 25.0


class ManualEditError(ValueError):
    """A user-facing rejection that keeps the original generation untouched."""

    def __init__(self, code: str, message_ru: str, json_pointer: str):
        super().__init__(message_ru)
        self.code = code
        self.message_ru = message_ru
        self.json_pointer = json_pointer


@dataclass(frozen=True, slots=True)
class ManualEditResult:
    pattern: dict[str, Any]
    audit_edits: list[dict[str, Any]]
    maximum_seam_residual_mm: float


def _piece(pattern: Mapping[str, Any], piece_id: str, pointer: str) -> dict[str, Any]:
    for candidate in pattern.get("pieces", ()):
        if candidate.get("id") == piece_id:
            return candidate
    raise ManualEditError(
        "MANUAL_PIECE_NOT_FOUND",
        "Выбранная деталь отсутствует в этой версии выкройки.",
        pointer,
    )


def _segment_index(piece: Mapping[str, Any], segment_id: str, pointer: str) -> int:
    for index, segment in enumerate(piece["seam_contour"]["segments"]):
        if segment.get("id") == segment_id:
            return index
    raise ManualEditError(
        "MANUAL_SEGMENT_NOT_FOUND",
        "Выбранный участок отсутствует в этой детали.",
        pointer,
    )


def _point(value: object, pointer: str) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise ManualEditError(
            "MANUAL_POINT_INVALID",
            "Координаты точки должны состоять из двух конечных чисел.",
            pointer,
        )
    result = [float(value[0]), float(value[1])]
    if not all(math.isfinite(item) for item in result):
        raise ManualEditError(
            "MANUAL_POINT_INVALID",
            "Координаты точки должны быть конечными числами.",
            pointer,
        )
    return result


def _protected_fold_segments(piece: Mapping[str, Any]) -> set[str]:
    return {
        str(item["segment_id"])
        for item in piece.get("edge_allowances", ())
        if item.get("edge_type") == "fold"
    }


def _validate_fold_edges(
    before: Mapping[str, Any], after: Mapping[str, Any], piece_id: str
) -> None:
    protected = _protected_fold_segments(before)
    if not protected:
        return
    old_segments = {item["id"]: item for item in before["seam_contour"]["segments"]}
    new_segments = {item["id"]: item for item in after["seam_contour"]["segments"]}
    if any(old_segments[segment_id] != new_segments.get(segment_id) for segment_id in protected):
        raise ManualEditError(
            "MANUAL_FOLD_EDGE_LOCKED",
            "Линию сгиба нельзя менять точечно. Измените параметры изделия и перестройте выкройку.",
            f"/pattern/pieces/{piece_id}/seam_contour",
        )


def _validate_piece(piece: Mapping[str, Any]) -> None:
    piece_id = str(piece["id"])
    try:
        contour = contour_from_data(piece["seam_contour"])
        validate_simple_contour(contour, flatness_mm=0.05)
    except GeometryError as error:
        raise ManualEditError(
            "MANUAL_CONTOUR_INVALID",
            f"После правки контур детали «{piece['name_ru']}» пересекается или разрывается.",
            f"/pattern/pieces/{piece_id}/seam_contour",
        ) from error
    if contour.area_mm2 < MIN_PIECE_AREA_MM2:
        raise ManualEditError(
            "MANUAL_CONTOUR_DEGENERATE",
            f"После правки площадь детали «{piece['name_ru']}» стала слишком малой.",
            f"/pattern/pieces/{piece_id}/seam_contour",
        )
    segments = {segment.id: segment for segment in contour.segments}
    for notch in piece.get("notches", ()):
        segment = segments.get(str(notch.get("segment_id")))
        distance = float(notch.get("distance_from_start_mm", -1))
        if segment is None or distance < 0 or distance > segment.length_mm:
            raise ManualEditError(
                "MANUAL_NOTCH_OUTSIDE_SEGMENT",
                f"После правки надсечка детали «{piece['name_ru']}» вышла за границу участка.",
                f"/pattern/pieces/{piece_id}/notches/{notch.get('id', '')}",
            )


def _segment_length(piece: Mapping[str, Any], segment_id: str) -> float:
    contour = contour_from_data(piece["seam_contour"])
    try:
        return next(segment.length_mm for segment in contour.segments if segment.id == segment_id)
    except StopIteration as error:
        raise ManualEditError(
            "MANUAL_SEAM_SEGMENT_MISSING",
            "После правки не найден участок парного шва.",
            f"/pattern/pieces/{piece['id']}/seam_contour",
        ) from error


def _validate_seam_pairs(pattern: Mapping[str, Any]) -> float:
    pieces = {str(piece["id"]): piece for piece in pattern["pieces"]}
    maximum = 0.0
    for pair in pattern.get("seam_pairs", ()):
        first = sum(
            _segment_length(pieces[str(pair["first_piece_id"])], segment_id)
            for segment_id in pair["first_segment_ids"]
        ) - float(pair["first_length_reduction_mm"])
        second = sum(
            _segment_length(pieces[str(pair["second_piece_id"])], segment_id)
            for segment_id in pair["second_segment_ids"]
        ) - float(pair["second_length_reduction_mm"])
        residual = abs(abs(first - second) - float(pair["allowed_ease_mm"]))
        maximum = max(maximum, residual)
        if residual > float(pair["tolerance_mm"]) + 1e-6:
            raise ManualEditError(
                "MANUAL_SEAM_PAIR_MISMATCH",
                "Ручная правка нарушила сопряжение парных швов. Исправьте обе соединяемые детали согласованно.",
                f"/pattern/seam_pairs/{pair['id']}",
            )
    return maximum


def apply_manual_edits(
    pattern: Mapping[str, Any],
    edits: Sequence[Mapping[str, Any]],
    input_snapshot: Mapping[str, Any],
    *,
    base_generation_id: str,
    note: str = "",
) -> ManualEditResult:
    """Apply bounded point edits and rebuild every derived cutting contour."""

    result = deepcopy(dict(pattern))
    original_pieces = {str(piece["id"]): deepcopy(piece) for piece in result["pieces"]}
    seen: set[tuple[str, str, str]] = set()
    audit: list[dict[str, Any]] = []

    for index, edit in enumerate(edits):
        pointer = f"/edits/{index}"
        piece_id = str(edit["piece_id"])
        segment_id = str(edit["segment_id"])
        handle = str(edit["handle"])
        key = (piece_id, segment_id, handle)
        if key in seen:
            raise ManualEditError(
                "MANUAL_EDIT_DUPLICATE",
                "Одна и та же точка указана в наборе правок дважды.",
                pointer,
            )
        seen.add(key)
        piece = _piece(result, piece_id, f"{pointer}/piece_id")
        segments = piece["seam_contour"]["segments"]
        segment_index = _segment_index(piece, segment_id, f"{pointer}/segment_id")
        segment = segments[segment_index]
        if handle in {"control_1", "control_2"} and segment.get("type") != "cubic_bezier":
            raise ManualEditError(
                "MANUAL_HANDLE_UNAVAILABLE",
                "У выбранного участка нет такой управляющей точки.",
                f"{pointer}/handle",
            )
        before = _point(segment.get(handle), f"{pointer}/handle")
        after = [float(edit["x_mm"]), float(edit["y_mm"])]
        distance = math.hypot(after[0] - before[0], after[1] - before[1])
        if distance <= 1e-9:
            raise ManualEditError(
                "MANUAL_EDIT_NO_CHANGE",
                "Новая координата совпадает с исходной; измените точку перед сохранением.",
                pointer,
            )
        if distance > MAX_POINT_MOVE_MM + 1e-9:
            raise ManualEditError(
                "MANUAL_MOVE_TOO_LARGE",
                f"За одну правку точку можно переместить максимум на {MAX_POINT_MOVE_MM:g} мм.",
                pointer,
            )
        segment[handle] = after
        if handle == "end":
            segments[(segment_index + 1) % len(segments)]["start"] = list(after)
        audit.append({
            "piece_id": piece_id,
            "segment_id": segment_id,
            "handle": handle,
            "before": before,
            "after": after,
            "distance_mm": round(distance, 6),
        })

    for piece in result["pieces"]:
        _validate_fold_edges(original_pieces[str(piece["id"])], piece, str(piece["id"]))
        _validate_piece(piece)
        piece["cutting_contour"] = None

    maximum_residual = _validate_seam_pairs(result)
    result["manual_adjustments"] = {
        "schema_version": "1.0.0",
        "base_generation_id": base_generation_id,
        "note": note.strip(),
        "edits": audit,
    }
    try:
        printable = apply_seam_allowances(result, input_snapshot)
    except ValueError as error:
        raise ManualEditError(
            "MANUAL_CUTTING_CONTOUR_INVALID",
            "После ручной правки не удалось безопасно пересчитать линию среза.",
            "/pattern/pieces",
        ) from error
    return ManualEditResult(printable, audit, maximum_residual)

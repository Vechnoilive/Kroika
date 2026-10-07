"""Final assembly checks shared by generation, manual edits and exports."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .blocks import BlockConstructionError
from .geometry import GeometryError, contour_from_data, validate_simple_contour
from .modeling import validate_modeling_placements
from .fullness import validate_fullness_placements
from .structural import validate_structural_placements
from .back_closure import validate_back_closure_placements
from .layers import validate_foundation_layers


def _fail(code: str, message: str, pointer: str) -> None:
    raise BlockConstructionError(code, message, pointer)


def _unique(values: list[str], pointer: str) -> None:
    if len(values) != len(set(values)):
        _fail("ASSEMBLY_ID_DUPLICATE", "В собранной выкройке повторяются идентификаторы.", pointer)


def geometry_index(pattern: Mapping[str, Any]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {
        "piece_ids": set(),
        "seam_pair_ids": set(),
        "path_ids": set(),
        "segment_ids": set(),
        "operation_ids": set(),
    }
    for piece in pattern["pieces"]:
        index["piece_ids"].add(piece["id"])
        for path in [piece["seam_contour"], *piece.get("internal_paths", [])]:
            index["path_ids"].add(path["id"])
            index["segment_ids"].update(edge["id"] for edge in path["segments"])
    index["seam_pair_ids"].update(pair["id"] for pair in pattern.get("seam_pairs", []))
    for key in ("modeling_operations", "topology_operations", "composite_operations"):
        index["operation_ids"].update(op["operation_id"] for op in pattern.get(key, []))
    return index


def validate_export_coverage(pattern: Mapping[str, Any]) -> None:
    """Reject missing printable evidence, including in a stored generation."""
    validate_modeling_placements(pattern)
    validate_fullness_placements(pattern)
    validate_structural_placements(pattern)
    validate_back_closure_placements(pattern)
    validate_foundation_layers(pattern)
    index = geometry_index(pattern)
    for module in (pattern.get("design_coverage") or {}).get("modules", []):
        evidence_sets = [module["evidence"], *module.get("source_evidence", {}).values()]
        for evidence in evidence_sets:
            if not any(evidence[key] for key in index if key != "operation_ids"):
                _fail(
                    "DESIGN_COVERAGE_EVIDENCE_MISSING",
                    "Подтверждение фасона не содержит отображаемой геометрии.",
                    "/pattern/design_coverage",
                )
            for key, available in index.items():
                if set(evidence[key]) - available:
                    _fail(
                        "DESIGN_COVERAGE_REFERENCE_MISSING",
                        "Деталь, линия или соединение фасона отсутствует в экспортируемой выкройке.",
                        f"/pattern/design_coverage/{module['module_id']}/{key}",
                    )


def validate_pattern_assembly(pattern: Mapping[str, Any]) -> float:
    """Check every final seam contour, notch and declared join after all modules."""
    validate_modeling_placements(pattern)
    validate_fullness_placements(pattern)
    validate_structural_placements(pattern)
    validate_back_closure_placements(pattern)
    validate_foundation_layers(pattern)
    _unique([p["id"] for p in pattern["pieces"]], "/pattern/pieces")
    _unique([p["id"] for p in pattern.get("seam_pairs", [])], "/pattern/seam_pairs")
    pieces = {p["id"]: p for p in pattern["pieces"]}
    lengths: dict[str, dict[str, float]] = {}
    for piece_id, piece in pieces.items():
        pointer = f"/pattern/pieces/{piece_id}"
        paths = [piece["seam_contour"], *piece.get("internal_paths", [])]
        _unique([path["id"] for path in paths], f"{pointer}/paths")
        _unique([edge["id"] for path in paths for edge in path["segments"]], f"{pointer}/segments")
        try:
            contour = contour_from_data(piece["seam_contour"])
            validate_simple_contour(contour, flatness_mm=0.05)
            if not contour.closed or contour.area_mm2 < 25:
                raise GeometryError("Контур не замкнут или вырожден.")
            lengths[piece_id] = {
                edge.id: edge.length_mm
                for path in paths
                for edge in contour_from_data(path).segments
            }
        except GeometryError as error:
            raise BlockConstructionError(
                "ASSEMBLY_CONTOUR_INVALID",
                f"Итоговый контур детали «{piece['name_ru']}» разорван, вырожден или пересекается.",
                f"{pointer}/seam_contour",
            ) from error
        _unique([n["id"] for n in piece.get("notches", [])], f"{pointer}/notches")
        for notch in piece.get("notches", []):
            length = lengths[piece_id].get(notch["segment_id"])
            distance = notch["distance_from_start_mm"]
            if (
                length is None
                or not math.isfinite(distance)
                or not -1e-6 <= distance <= length + 1e-6
            ):
                _fail(
                    "ASSEMBLY_NOTCH_INVALID",
                    "Надсечка не принадлежит существующему участку детали.",
                    f"{pointer}/notches/{notch['id']}",
                )

    maximum = 0.0
    for pair in pattern.get("seam_pairs", []):
        pointer = f"/pattern/seam_pairs/{pair['id']}"
        joined = []
        for side in ("first", "second"):
            pid = pair[f"{side}_piece_id"]
            ids = pair[f"{side}_segment_ids"]
            if (
                pid not in lengths
                or not ids
                or len(ids) != len(set(ids))
                or any(sid not in lengths[pid] for sid in ids)
            ):
                _fail(
                    "ASSEMBLY_JOIN_REFERENCE_MISSING",
                    "Не найден участок итогового соединения.",
                    pointer,
                )
            reduction = pair[f"{side}_length_reduction_mm"]
            effective = sum(lengths[pid][sid] for sid in ids) - reduction
            if not math.isfinite(reduction) or reduction < 0 or effective <= 0:
                _fail(
                    "ASSEMBLY_JOIN_REDUCTION_INVALID",
                    "Раствор или сборка поглощает весь срез.",
                    pointer,
                )
            joined.append(effective)
        ease, tolerance = pair["allowed_ease_mm"], pair["tolerance_mm"]
        if not all(math.isfinite(v) and v >= 0 for v in (ease, tolerance)):
            _fail(
                "ASSEMBLY_JOIN_LIMIT_INVALID",
                "Недопустимый допуск или посадка соединения.",
                pointer,
            )
        residual = abs(abs(joined[0] - joined[1]) - ease)
        maximum = max(maximum, residual)
        if residual > tolerance + 1e-6:
            _fail(
                "ASSEMBLY_JOIN_MISMATCH",
                "После сборки модулей длины соединяемых срезов не совпали.",
                pointer,
            )
        if pair.get("second_instance") == "mirror":
            second = pieces[pair["second_piece_id"]]
            if not (
                second["cut_on_fold"] or (second["mirrored_pair"] and second["cut_quantity"] >= 2)
            ):
                _fail(
                    "ASSEMBLY_MIRROR_COPY_MISSING",
                    "Для соединения отсутствует зеркальная копия.",
                    pointer,
                )
        if pair.get("copy_pairing") == "mirrored_copies":
            first = pieces[pair["first_piece_id"]]
            if (
                pair["first_piece_id"] != pair["second_piece_id"]
                or not first["mirrored_pair"]
                or first["cut_quantity"] != 2
            ):
                _fail(
                    "ASSEMBLY_MIRROR_COPY_MISSING",
                    "Для соединения нужны две зеркальные детали.",
                    pointer,
                )

    index = geometry_index(pattern)
    for key in ("modeling_operations", "topology_operations", "composite_operations"):
        operations = pattern.get(key, [])
        _unique([op["operation_id"] for op in operations], f"/pattern/{key}")
        for op in operations:
            targets = set(op["target_piece_ids"]) | set(op.get("added_piece_ids", []))
            interfaces = set(op.get("interface_ids", []))
            if targets - index["piece_ids"] or interfaces - (
                index["seam_pair_ids"] | index["path_ids"]
            ):
                _fail(
                    "ASSEMBLY_OPERATION_REFERENCE_MISSING",
                    "Операция фасона ссылается на удалённую геометрию.",
                    f"/pattern/{key}/{op['operation_id']}",
                )
    return maximum

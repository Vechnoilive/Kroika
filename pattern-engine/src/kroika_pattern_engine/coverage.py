"""Auditable design-to-geometry coverage catalogue introduced at stage 20."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .blocks import BlockConstructionError


@dataclass(frozen=True, slots=True)
class DesignCoverageResult:
    """Pattern enriched with evidence for every implemented design module."""

    pattern: dict[str, Any]
    module_count: int
    required_module_count: int


def compile_design_coverage(
    pattern: Mapping[str, Any], request: Mapping[str, Any],
) -> DesignCoverageResult:
    """Index real geometry and fail when a confirmed module has no evidence.

    The catalogue deliberately contains module-level evidence rather than a
    copy of the current photo analysis. This keeps a cached geometric result
    reusable while the frontend compares it with the current reviewed plan.
    """

    result = deepcopy(dict(pattern))
    index = _geometry_index(result)
    catalogue: dict[str, dict[str, set[str]]] = {}

    def add(
        module_id: str,
        *,
        source_ids: list[str] | None = None,
        piece_ids: list[str] | None = None,
        seam_pair_ids: list[str] | None = None,
        path_ids: list[str] | None = None,
        segment_ids: list[str] | None = None,
        operation_ids: list[str] | None = None,
    ) -> None:
        evidence = catalogue.setdefault(module_id, {
            "source_ids": set(),
            "piece_ids": set(),
            "seam_pair_ids": set(),
            "path_ids": set(),
            "segment_ids": set(),
            "operation_ids": set(),
        })
        evidence["source_ids"].update(source_ids or [])
        evidence["piece_ids"].update(piece_ids or [])
        evidence["seam_pair_ids"].update(seam_pair_ids or [])
        evidence["path_ids"].update(path_ids or [])
        evidence["segment_ids"].update(segment_ids or [])
        evidence["operation_ids"].update(operation_ids or [])

    core_pieces = sorted(
        piece_id for piece_id in index["piece_ids"]
        if piece_id in {
            "front_bodice", "back_bodice", "front_skirt", "back_skirt",
            "front_trouser", "back_trouser", "jacket_front_center",
            "jacket_side_front", "base_sleeve",
        }
    )
    if core_pieces:
        add("main_fabric_layer", piece_ids=core_pieces)
        add("bounded_visual_proportions", piece_ids=core_pieces)

    _add_token_evidence(add, index, "straight_waistband", ("waistband",))
    _add_token_evidence(add, index, "base_dart_shaping", ("dart",))
    _add_token_evidence(
        add, index, "jacket_princess_seam", ("princess", "jacket_side_front")
    )
    _add_token_evidence(add, index, "bounded_collar", ("collar",))
    _add_token_evidence(add, index, "bounded_pocket", ("pocket",))
    _add_token_evidence(add, index, "jacket_back_vent", ("vent",))
    _add_token_evidence(add, index, "jacket_full_lining", ("lining",))

    closure = request.get("garment_spec", {}).get("parameters", {}).get("closure", {})
    location = closure.get("location") if isinstance(closure, Mapping) else None
    closure_tokens = {
        "center_front": ("fly", "placket", "button_line"),
        "center_back": ("back_center", "center_back"),
        "side": ("side",),
    }.get(str(location), ())
    if closure_tokens:
        _add_token_evidence(add, index, "bounded_closure", closure_tokens)

    for operation in result.get("modeling_operations", []):
        if not isinstance(operation, Mapping):
            continue
        add(
            str(operation["module_id"]),
            source_ids=[str(operation["source_element_id"])],
            piece_ids=[str(item) for item in operation.get("target_piece_ids", [])],
            operation_ids=[str(operation["operation_id"])],
        )

    for operation in result.get("composite_operations", []):
        if not isinstance(operation, Mapping):
            continue
        interface_ids = [str(item) for item in operation.get("interface_ids", [])]
        add(
            str(operation["module_id"]),
            source_ids=[str(operation["source_id"])],
            piece_ids=[
                str(item) for item in (
                    list(operation.get("target_piece_ids", []))
                    + list(operation.get("added_piece_ids", []))
                )
            ],
            seam_pair_ids=[item for item in interface_ids if item in index["seam_pair_ids"]],
            path_ids=[item for item in interface_ids if item in index["path_ids"]],
            operation_ids=[str(operation["operation_id"])],
        )

    modules = []
    for module_id, evidence in sorted(catalogue.items()):
        geometry_count = sum(
            len(evidence[key])
            for key in (
                "piece_ids", "seam_pair_ids", "path_ids", "segment_ids", "operation_ids"
            )
        )
        if geometry_count == 0:
            continue
        modules.append({
            "module_id": module_id,
            "source_ids": sorted(evidence["source_ids"]),
            "evidence": {
                "piece_ids": sorted(evidence["piece_ids"]),
                "seam_pair_ids": sorted(evidence["seam_pair_ids"]),
                "path_ids": sorted(evidence["path_ids"]),
                "segment_ids": sorted(evidence["segment_ids"]),
                "operation_ids": sorted(evidence["operation_ids"]),
            },
        })

    available = {entry["module_id"] for entry in modules}
    required = _required_module_ids(request)
    missing = sorted(required - available)
    if missing:
        raise BlockConstructionError(
            "DESIGN_COVERAGE_EVIDENCE_MISSING",
            "В готовой геометрии нет доказательства для подтверждённых модулей: "
            f"{', '.join(missing)}.",
            "/garment_spec/design_intent",
        )

    result["design_coverage"] = {
        "schema_version": "1.0.0",
        "modules": modules,
        "physical_validation_required": True,
    }
    return DesignCoverageResult(result, len(modules), len(required))


def _required_module_ids(request: Mapping[str, Any]) -> set[str]:
    intent = request.get("garment_spec", {}).get("design_intent")
    if not isinstance(intent, Mapping):
        return set()
    required: set[str] = set()
    for group in ("elements", "layers"):
        for item in intent.get(group, []):
            if (
                isinstance(item, Mapping)
                and item.get("included") is not False
                and item.get("support_status") == "supported"
                and isinstance(item.get("module_id"), str)
            ):
                required.add(str(item["module_id"]))
    proportions = intent.get("proportions")
    if (
        isinstance(proportions, Mapping)
        and proportions.get("support_status") == "supported"
        and isinstance(proportions.get("module_id"), str)
    ):
        required.add(str(proportions["module_id"]))
    return required


def _geometry_index(pattern: Mapping[str, Any]) -> dict[str, set[str]]:
    index = {
        "piece_ids": set(),
        "seam_pair_ids": set(),
        "path_ids": set(),
        "segment_ids": set(),
    }
    for pair in pattern.get("seam_pairs", []):
        if isinstance(pair, Mapping):
            index["seam_pair_ids"].add(str(pair["id"]))
    for piece in pattern.get("pieces", []):
        if not isinstance(piece, Mapping):
            continue
        index["piece_ids"].add(str(piece["id"]))
        paths = [piece.get("seam_contour"), *piece.get("internal_paths", [])]
        cutting = piece.get("cutting_contour")
        if cutting is not None:
            paths.append(cutting)
        for path in paths:
            if not isinstance(path, Mapping):
                continue
            index["path_ids"].add(str(path["id"]))
            for segment in path.get("segments", []):
                if isinstance(segment, Mapping):
                    index["segment_ids"].add(str(segment["id"]))
    return index


def _add_token_evidence(
    add: Any,
    index: Mapping[str, set[str]],
    module_id: str,
    tokens: tuple[str, ...],
) -> None:
    selected = {
        key: sorted(item for item in values if any(token in item for token in tokens))
        for key, values in index.items()
    }
    if any(selected.values()):
        add(
            module_id,
            piece_ids=selected["piece_ids"],
            seam_pair_ids=selected["seam_pair_ids"],
            path_ids=selected["path_ids"],
            segment_ids=selected["segment_ids"],
        )

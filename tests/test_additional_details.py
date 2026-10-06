from __future__ import annotations
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine/src"), str(ROOT / "backend/src")]
from kroika_contracts.contract_io import validate_document  # noqa: E402
from kroika_contracts.design_modules import matching_module  # noqa: E402
from kroika_contracts.hashing import canonical_generation_payload, compute_input_hash  # noqa: E402
from kroika_contracts.semantic import validate_engine_request  # noqa: E402
from kroika_pattern_engine import GeometryPatternEngine  # noqa: E402
from kroika_pattern_engine.details import apply_detail_transformations, validate_detail_placements  # noqa: E402
from kroika_pattern_engine.blocks import BlockConstructionError, build_base_blocks  # noqa: E402
from kroika_pattern_engine.assembly import assemble_garment  # noqa: E402
from kroika_pattern_engine.manual_edit import apply_manual_edits, ManualEditError  # noqa: E402
from tests.test_stage19_composites import _element, _dimensions, _intent, _layer  # noqa: E402
from tests.test_stage11_workflow import client, project_document, engine_request  # noqa: E402
from tests.test_stage12_garments import _project as upper_project  # noqa: E402

CASES = [
    ("straight_sash_v1", "sash", "straight", "waist", 1, dict(width=80, length=1600)),
    ("paired_waist_ties_v1", "belt", "tie", "waist", 2, dict(width=30, length=500)),
    (
        "placed_patch_pocket_v1",
        "pocket",
        "patch",
        "skirt_back",
        1,
        dict(width=80, depth=100, spacing=60),
    ),
    (
        "rectangular_applied_panel_v1",
        "overlay",
        "straight",
        "skirt_front",
        2,
        dict(width=80, length=100, spacing=60),
    ),
    ("gathered_edge_ruffle_v1", "ruffle", "gathered", "hem", 1, dict(depth=80, width=150)),
    ("circular_edge_flounce_v1", "flounce", "circular", "neckline", 1, dict(depth=60)),
    ("circular_waist_peplum_v1", "peplum", "circular", "waist", 1, dict(depth=150)),
]


def element(case: tuple, source: str = "detail") -> dict:
    module, typ, variant, location, count, sizes = case
    return _element(
        source,
        typ,
        variant,
        location,
        "applied" if typ == "overlay" else "separate_piece",
        count,
        module,
        _dimensions(**sizes),
    )


def request(
    elements: list[dict], layers: list[dict] | None = None, project: dict | None = None
) -> dict:
    project = project or project_document()
    project["garment_spec"]["design_intent"] = _intent(elements, layers)
    project["garment_spec"]["design_intent"]["coverage_schema_version"] = "1.0.0"
    return engine_request(project)


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_each_detail_has_geometry_seam_evidence_and_safe_cutting_contours(case):
    req = request([element(case)])
    validate_engine_request(req)
    assert (
        matching_module(
            req["garment_spec"]["design_intent"]["elements"][0], req["garment_spec"], kind="element"
        )
        == case[0]
    )
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "succeeded", result["validation_report"]
    pattern = result["pattern"]
    validate_document("pattern-data", pattern)
    op = next(op for op in pattern["composite_operations"] if op["module_id"] == case[0])
    assert op["added_piece_ids"] and op["interface_ids"]
    pieces = {p["id"]: p for p in pattern["pieces"]}
    assert all(pieces[pid]["cutting_contour"] is not None for pid in op["added_piece_ids"])
    coverage = next(m for m in pattern["design_coverage"]["modules"] if m["module_id"] == case[0])
    assert set(op["added_piece_ids"]) <= set(coverage["evidence"]["piece_ids"])
    assert canonical_generation_payload(req)["hash_contract_version"] == "1.5.0"
    if case[2] == "circular":
        for pid in op["added_piece_ids"]:
            target = pieces[
                next(
                    pair["first_piece_id"]
                    for pair in pattern["seam_pairs"]
                    if pair["second_piece_id"] == pid and pair["id"].endswith("_attachment")
                )
            ]
            assert pieces[pid]["cut_quantity"] == target["cut_quantity"] * (
                2 if target["cut_on_fold"] else 1
            )


@pytest.mark.parametrize(
    "module,role,coverage",
    [
        ("bodice_interfacing_v1", "interfacing", "bodice"),
        ("bodice_overlay_layer_v1", "overlay", "bodice"),
        ("sleeve_overlay_layer_v1", "overlay", "sleeves"),
    ],
)
def test_layers_have_explicit_contours_and_matched_boundaries(module, role, coverage):
    layer = _layer("extra_layer", role, coverage, "opaque", module)
    if role == "interfacing":
        layer["drape"] = "medium"
    req = request([], [layer], upper_project("blouse") if coverage == "sleeves" else None)
    validate_engine_request(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "succeeded", result["validation_report"]
    op = next(op for op in result["pattern"]["composite_operations"] if op["module_id"] == module)
    assert len(op["added_piece_ids"]) == (1 if coverage == "sleeves" else 2)
    assert op["interface_ids"]


def test_combined_project_survives_save_cache_svg_and_pdf(tmp_path):
    elements = [element(case, f"detail_{i}") for i, case in enumerate(CASES)]
    layers = [
        _layer("interfacing", "interfacing", "bodice", "opaque", "bodice_interfacing_v1"),
        _layer("upper_overlay", "overlay", "bodice", "semi_transparent", "bodice_overlay_layer_v1"),
    ]
    layers[0]["drape"] = "medium"
    req = request(elements, layers)
    project = project_document()
    project["garment_spec"] = deepcopy(req["garment_spec"])
    req = engine_request(project)
    with client(tmp_path) as api:
        saved = api.post("/api/v1/projects", json=project)
        assert saved.status_code == 201, saved.text
        saved = api.get(f"/api/v1/projects/{project['project_id']}").json()
        result = api.post(
            "/api/v1/patterns/generate", json=engine_request(saved), headers={"If-Match": "1"}
        )
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["status"] == "succeeded", result["validation_report"]
        assert len(result["pattern"]["pieces"]) == 22
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        cached = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(current),
            headers={"If-Match": str(current["revision"])},
        )
        assert cached.status_code == 200, cached.text
        assert cached.json()["generation_id"] == result["generation_id"]
        svg = api.get(f"/api/v1/patterns/{result['generation_id']}/preview.svg")
        assert svg.status_code == 200, svg.text
        for piece in result["pattern"]["pieces"]:
            assert piece["id"] in svg.text
        pdf = api.post(f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf")
        assert pdf.status_code == 200, pdf.text
        text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
        for piece in result["pattern"]["pieces"]:
            assert piece["name_ru"] in text
        assert "50 x 50 mm" in text
        assert len(current["garment_spec"]["design_intent"]["elements"]) == 7


def test_wrong_dimensions_and_unavailable_sleeve_are_not_supported():
    req = request([element(CASES[4])])
    spec = req["garment_spec"]
    item = spec["design_intent"]["elements"][0]
    for dims in [
        _dimensions(depth=80),
        _dimensions(depth=251, width=100),
        _dimensions(depth=80, width=100, length=500),
    ]:
        assert matching_module({**item, "dimensions_mm": dims}, spec, kind="element") is None
    assert matching_module({**item, "location": "sleeve"}, spec, kind="element") is None


def test_placement_and_edge_conflicts_reject_geometry_instead_of_dropping_elements():
    item = element(CASES[2])
    req = request([item])
    pattern = assemble_garment(req, build_base_blocks(req)).pattern
    req["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["spacing"] = 800
    with pytest.raises(BlockConstructionError, match="Карман|панель"):
        apply_detail_transformations(pattern, req)
    item["dimensions_mm"]["spacing"] = 60
    req["garment_spec"]["design_intent"]["elements"] = [
        element(CASES[4], "ruffle_1"),
        element(CASES[4], "ruffle_2"),
    ]
    with pytest.raises(BlockConstructionError, match="две отделочные"):
        apply_detail_transformations(pattern, req)


def test_gathering_reduction_changes_both_cut_length_and_hash():
    req = request([element(CASES[4])])
    pattern = assemble_garment(req, build_base_blocks(req)).pattern
    first = apply_detail_transformations(pattern, req).pattern
    old_hash = compute_input_hash(req)
    req["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["width"] += 100
    second = apply_detail_transformations(pattern, req).pattern
    assert compute_input_hash(req) != old_hash
    for result in [first, second]:
        joins = [
            pair
            for pair in result["seam_pairs"]
            if pair["id"].startswith("detail_") and pair["id"].endswith("_attachment")
        ]
        assert len(joins) == 2
    assert next(p for p in second["pieces"] if p["id"] == "detail_front_skirt")["seam_contour"][
        "segments"
    ][0]["end"][0] - next(p for p in first["pieces"] if p["id"] == "detail_front_skirt")[
        "seam_contour"
    ]["segments"][0]["end"][0] == pytest.approx(100)


def test_manual_edits_keep_detail_interfaces_and_placement_safe():
    req = request([element(CASES[2])])
    pattern = apply_detail_transformations(
        assemble_garment(req, build_base_blocks(req)).pattern, req
    ).pattern
    piece = next(p for p in pattern["pieces"] if p["id"] == "detail_patch_pocket")
    segment = piece["seam_contour"]["segments"][0]
    with pytest.raises(ManualEditError, match="сопряжение"):
        apply_manual_edits(
            pattern,
            [
                {
                    "piece_id": piece["id"],
                    "segment_id": segment["id"],
                    "handle": "end",
                    "x_mm": 90,
                    "y_mm": 0,
                }
            ],
            req,
            base_generation_id="11111111-1111-4111-8111-111111111111",
        )
    target = next(p for p in pattern["pieces"] if p["id"] == "back_skirt")
    path = next(p for p in target["internal_paths"] if p["id"] == "detail_placement")
    for edge in path["segments"]:
        edge["start"][0] += 10000
        edge["end"][0] += 10000
    with pytest.raises(BlockConstructionError):
        validate_detail_placements(pattern)


def test_existing_hem_flounce_covers_both_halves_of_folded_skirt():
    req = request(
        [
            _element(
                "hem_flounce",
                "flounce",
                "circular",
                "hem",
                "separate_piece",
                1,
                "circular_hem_flounce_v1",
                _dimensions(depth=80),
            )
        ]
    )
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "succeeded"
    pieces = {p["id"]: p for p in result["pattern"]["pieces"]}
    for base in ["front_skirt", "back_skirt"]:
        assert pieces[f"{base}_flounce"]["cut_quantity"] == 2
        assert pieces[f"{base}_flounce"]["mirrored_pair"] is True
        flounce = pieces[f"{base}_flounce"]
        radius = flounce["seam_contour"]["segments"][0]["radius_x_mm"]
        for point in [*flounce["grainline"].values(), flounce["annotations"][0]["position"]]:
            assert radius < (point[0] ** 2 + point[1] ** 2) ** 0.5 < radius + 80


def test_hash_matches_frontend_for_new_details(tmp_path):
    req = request([element(CASES[4])])
    # Execute the actual frontend hash function, not an independent reimplementation.
    source = ROOT / "frontend/src/generation.ts"
    output = subprocess.check_output(
        [
            "node",
            "--input-type=module",
            "-e",
            "import {stripTypeScriptTypes as strip} from 'node:module'; import fs from 'node:fs'; const gen=strip(fs.readFileSync('src/generation.ts','utf8'),{mode:'transform'}); const mod=strip(fs.readFileSync('src/designModules.ts','utf8'),{mode:'transform'}); const reg=JSON.parse(fs.readFileSync('../src/kroika_contracts/design_modules.json','utf8')); const moduleUrl='data:text/javascript;base64,'+Buffer.from(mod.replace(/import registry.*;/, 'const registry='+JSON.stringify(reg)+';')).toString('base64'); const code=gen.replace(\"'./designModules'\",JSON.stringify(moduleUrl)); const lib=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64')); const request=JSON.parse(process.argv[1]); process.stdout.write(lib.stableJson(lib.canonicalGenerationPayload(request)));",
            json.dumps(req),
        ],
        cwd=source.parent.parent,
        text=True,
    )
    assert json.loads(output) == canonical_generation_payload(req)


def test_allowances_do_not_silently_change_sash_width_or_consume_shallow_ruffles():
    req = request([element(CASES[0])])
    pattern = apply_detail_transformations(
        assemble_garment(req, build_base_blocks(req)).pattern, req
    ).pattern
    from kroika_pattern_engine.allowances import apply_seam_allowances

    sash = next(
        p for p in apply_seam_allowances(pattern, req)["pieces"] if p["id"] == "detail_sash"
    )
    assert {edge["edge_type"] for edge in sash["edge_allowances"]} == {"normal"}
    req = request([element(CASES[4])])
    req["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["depth"] = 20
    pattern = assemble_garment(req, build_base_blocks(req)).pattern
    with pytest.raises(BlockConstructionError, match="припуск"):
        apply_detail_transformations(pattern, req)
    req["fit_settings"]["seam_allowances_mm"]["hem"] = 5
    assert apply_detail_transformations(pattern, req).applied_count == 1


def test_mirrored_copy_joins_and_overlay_coverage_are_explicit():
    req = request(
        [element(CASES[4])],
        [_layer("skirt_overlay", "overlay", "skirt", "semi_transparent", "skirt_overlay_layer_v1")],
    )
    from kroika_pattern_engine.composites import apply_composite_transformations

    pattern = apply_composite_transformations(
        assemble_garment(req, build_base_blocks(req)).pattern, req
    ).pattern
    result = apply_detail_transformations(pattern, req).pattern
    op = next(
        o for o in result["composite_operations"] if o["module_id"] == "gathered_edge_ruffle_v1"
    )
    assert len(op["added_piece_ids"]) == 4
    layer = next(
        o for o in result["composite_operations"] if o["module_id"] == "skirt_overlay_layer_v1"
    )
    assert {"detail_overlay_front_skirt", "detail_overlay_back_skirt"} <= set(
        layer["added_piece_ids"]
    )
    copies = [
        pair for pair in result["seam_pairs"] if pair.get("copy_pairing") == "mirrored_copies"
    ]
    assert len(copies) == 4
    assert all(pair["first_piece_id"] == pair["second_piece_id"] for pair in copies)
    sides = [
        pair
        for pair in result["seam_pairs"]
        if pair["id"].endswith("_side_join") and pair["id"].startswith("detail_")
    ]
    assert len(sides) == 2

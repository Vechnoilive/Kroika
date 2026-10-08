from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import subprocess

import pytest
from pypdf import PdfReader

from tests.test_additional_details import request
from tests.test_stage19_composites import _element, _dimensions, _layer
from tests.test_stage11_workflow import client, project_document, engine_request
from tests.test_stage12_garments import _project as upper_project
from kroika_contracts.contract_io import validate_document
from kroika_contracts.design_modules import matching_module, FULLNESS_MODULES
from kroika_contracts.hashing import compute_input_hash, canonical_generation_payload
from kroika_contracts.semantic import validate_engine_request, SemanticContractError
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg, render_pattern_pdf
from kroika_pattern_engine.blocks import build_base_blocks, BlockConstructionError
from kroika_pattern_engine.assembly import assemble_garment
from kroika_pattern_engine.fullness import apply_fullness_foundation, validate_fullness_placements
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.validation import validate_pattern_assembly
from kroika_pattern_engine.svg import SVGRenderError
from kroika_pattern_engine.pdf import PDFRenderError


CASES = [
    (
        "placed_skirt_pleats_v2",
        "pleat",
        "knife",
        "skirt_front",
        "integrated",
        4,
        dict(width=20, depth=10, length=150, spacing=30),
    ),
    (
        "placed_skirt_tucks_v2",
        "tuck",
        "straight",
        "skirt_front",
        "integrated",
        4,
        dict(width=20, depth=5, length=150, spacing=30),
    ),
    (
        "placed_skirt_gathers_v2",
        "gather",
        "gathered",
        "skirt_front",
        "integrated",
        4,
        dict(width=20, depth=40, length=150, spacing=30),
    ),
    (
        "integrated_bodice_drape_v2",
        "drape",
        "soft",
        "bodice_front",
        "integrated",
        2,
        dict(width=20, depth=40, spacing=30),
    ),
    (
        "integrated_bodice_gather_v2",
        "gather",
        "gathered",
        "bodice_back",
        "integrated",
        2,
        dict(width=20, depth=40, spacing=30),
    ),
    (
        "separate_bodice_drape_v2",
        "drape",
        "soft",
        "bodice_back",
        "separate_piece",
        2,
        dict(width=30, depth=60, spacing=15),
    ),
    (
        "diagonal_bodice_drape_v2",
        "drape",
        "soft",
        "bodice_front",
        "separate_piece",
        1,
        dict(width=30, depth=60, spacing=15),
    ),
    (
        "placed_edge_ruffle_v2",
        "ruffle",
        "gathered",
        "skirt_front",
        "separate_piece",
        2,
        dict(length=100, depth=80, spacing=10, width=60),
    ),
    (
        "placed_edge_flounce_v2",
        "flounce",
        "circular",
        "bodice_front",
        "separate_piece",
        2,
        dict(length=70, depth=70, spacing=10),
    ),
    (
        "asymmetric_waist_peplum_v2",
        "peplum",
        "shaped",
        "skirt_front",
        "separate_piece",
        1,
        dict(depth=90, length=130),
    ),
    (
        "placed_cascade_flounce_v2",
        "flounce",
        "soft",
        "skirt_back",
        "separate_piece",
        1,
        dict(depth=90, length=250, spacing=35),
    ),
    (
        "tiered_hem_ruffle_v2",
        "ruffle",
        "gathered",
        "hem",
        "separate_piece",
        3,
        dict(depth=80, width=60),
    ),
    ("tiered_hem_flounce_v2", "flounce", "circular", "hem", "separate_piece", 2, dict(depth=80)),
]


def element(index, source=None, **overrides):
    module, typ, variant, location, construction, count, sizes = CASES[index]
    item = _element(
        source or f"fullness_{index}",
        typ,
        variant,
        location,
        construction,
        count,
        module,
        _dimensions(**sizes),
    )
    if index in {6, 9, 10}:
        item.update(symmetry="asymmetric", placement=dict(side="right"))
    elif index in {5, 7, 8}:
        item["placement"] = dict(side="both")
    item.update(overrides)
    return item


def generate(req):
    req["input_hash"] = compute_input_hash(req)
    validate_engine_request(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "succeeded", result["validation_report"]
    validate_document("pattern-data", result["pattern"])
    assert validate_pattern_assembly(result["pattern"]) < 1
    validate_fullness_placements(result["pattern"])
    return result["pattern"]


@pytest.mark.parametrize("index", range(len(CASES)), ids=[case[0] for case in CASES])
def test_every_module_has_real_cutting_geometry_printed_marks_and_seam_evidence(index):
    item = element(index)
    req = request([item])
    assert matching_module(item, req["garment_spec"], kind="element") == item["module_id"]
    pattern = generate(req)
    operations = pattern["modeling_operations"] + pattern["composite_operations"]
    op = next(op for op in operations if op["module_id"] == item["module_id"])
    assert op["target_piece_ids"]
    evidence = next(
        m for m in pattern["design_coverage"]["modules"] if m["module_id"] == item["module_id"]
    )
    assert item["source_element_id"] in evidence["source_evidence"]
    assert evidence["evidence"]["path_ids"] or evidence["evidence"]["seam_pair_ids"]
    assert canonical_generation_payload(req)["hash_contract_version"] == "1.8.0"
    svg = render_pattern_svg(pattern)
    for path_id in evidence["evidence"]["path_ids"]:
        assert path_id in svg
    for pid in op.get("added_piece_ids", []):
        assert next(p for p in pattern["pieces"] if p["id"] == pid)["cutting_contour"] is not None
        assert pid in svg


@pytest.mark.parametrize(
    "variant,factor", [("knife", 2), ("box", 4), ("inverted", 4), ("accordion", 2)]
)
def test_distributed_pleats_conserve_finished_waist_and_dart_intake(variant, factor):
    item = element(0, variant=variant)
    req = request([item])
    base = assemble_garment(req, build_base_blocks(req)).pattern
    expanded = apply_fullness_foundation(base, req)
    before = next(p for p in base["pieces"] if p["id"] == "front_skirt")
    after = next(p for p in expanded["pieces"] if p["id"] == "front_skirt")
    expected = 2 * 10 * factor
    assert contour_from_data(after["seam_contour"]).bounding_box.max_x_mm - contour_from_data(
        before["seam_contour"]
    ).bounding_box.max_x_mm == pytest.approx(expected)
    a = next(p for p in base["seam_pairs"] if p["id"] == "front_waist_join")
    b = next(p for p in expanded["seam_pairs"] if p["id"] == a["id"])
    assert b["second_length_reduction_mm"] - a["second_length_reduction_mm"] == pytest.approx(
        expected
    )
    old_dart = contour_from_data(next(p for p in before["internal_paths"] if "dart" in p["id"]))
    new_dart = contour_from_data(next(p for p in after["internal_paths"] if "dart" in p["id"]))
    assert new_dart.segments[0].length_mm == pytest.approx(old_dart.segments[0].length_mm)
    assert validate_pattern_assembly(expanded) < 1


def test_multiple_modules_use_disjoint_zones_and_survive_together():
    first, second = element(1, "first", count=2), element(2, "second", count=2)
    second["dimensions_mm"]["width"] = 50
    pattern = generate(request([second, first]))
    front = next(p for p in pattern["pieces"] if p["id"] == "front_skirt")
    paths = {p["id"]: contour_from_data(p) for p in front["internal_paths"]}
    assert (
        paths["first_fullness_0_2"].segments[0].start.x_mm
        < paths["second_fullness_0_0"].segments[0].start.x_mm
    )
    modules = {m["module_id"] for m in pattern["design_coverage"]["modules"]}
    assert {"placed_skirt_tucks_v2", "placed_skirt_gathers_v2"} <= modules


@pytest.mark.parametrize("case", ["duplicate", "dart", "outside", "too_long"])
def test_invalid_spreading_is_rejected_with_a_specific_reason(case):
    first = element(1, count=2)
    second = element(2, count=2)
    if case == "dart":
        first["dimensions_mm"]["width"] = 105
    if case == "outside":
        first["dimensions_mm"]["width"] = 1000
    if case == "too_long":
        first["dimensions_mm"]["length"] = 900
    req = request([first, second] if case == "duplicate" else [first])
    base = assemble_garment(req, build_base_blocks(req)).pattern
    with pytest.raises(BlockConstructionError) as error:
        apply_fullness_foundation(base, req)
    assert (
        error.value.code
        == {
            "duplicate": "FULLNESS_ZONE_CONFLICT",
            "dart": "FULLNESS_DART_CONFLICT",
            "outside": "FULLNESS_SLASH_OUTSIDE",
            "too_long": "FULLNESS_MARK_LENGTH_OUTSIDE",
        }[case]
    )


@pytest.mark.parametrize("location", ["skirt_front", "skirt_back"])
@pytest.mark.parametrize(
    "fit,volume", [("fitted", "regular"), ("semi_fitted", "relaxed"), ("semi_fitted", "voluminous")]
)
def test_fold_modules_work_on_both_sides_for_supported_fit_and_volume(location, fit, volume):
    project = project_document()
    project["garment_spec"]["parameters"]["bodice_fit"] = fit
    project["fit_settings"]["preset"]["id"] = (
        "woven_fitted_trial" if fit == "fitted" else "woven_semi_fitted_trial"
    )
    req = request([element(1, location=location)], project=project)
    req["garment_spec"]["design_intent"]["proportions"].update(
        volume=volume, module_id="parametric_visual_proportions_v1"
    )
    generate(req)


@pytest.mark.parametrize(
    "index,location,garment",
    [
        (3, "bodice_back", "dress"),
        (4, "bodice_front", "top"),
        (5, "bodice_front", "blouse"),
        (7, "sleeve", "blouse"),
        (8, "bodice_back", "top"),
    ],
)
def test_upper_garments_back_drapes_and_sleeve_edge_gathers(index, location, garment):
    project = project_document() if garment == "dress" else upper_project(garment)
    item = element(index, location=location)
    if location == "sleeve":
        item["dimensions_mm"]["length"] = 60
    if index == 8 and location == "bodice_back":
        item["dimensions_mm"]["length"] = 40
        item["placement"]["sweep_angle_deg"] = 90
    generate(request([item], project=project))


@pytest.mark.parametrize("index", [11, 12])
def test_tiered_shape_requires_real_tiers_and_has_correct_lengths(index):
    req = request([element(index)], project=upper_project("skirt"))
    req["garment_spec"]["design_intent"]["proportions"].update(
        hem_shape="tiered", module_id="parametric_visual_proportions_v1"
    )
    pattern = generate(req)
    op = next(op for op in pattern["composite_operations"] if op["module_id"] == CASES[index][0])
    assert len(op["added_piece_ids"]) == 2 * CASES[index][5]
    assert op["parameters_mm"]["total_added_length"] == CASES[index][5] * 80
    for pid in op["added_piece_ids"]:
        panel = next(p for p in pattern["pieces"] if p["id"] == pid)
        assert panel["cut_quantity"] == 2 and panel["mirrored_pair"]
    req["garment_spec"]["design_intent"]["elements"] = []
    with pytest.raises(SemanticContractError):
        validate_engine_request(req)


@pytest.mark.parametrize("angle", [90, 135, 270])
def test_sector_angle_changes_the_cutting_geometry_and_keeps_attachment_length(angle):
    item = element(8, location="skirt_back", placement=dict(side="both", sweep_angle_deg=angle))
    item["dimensions_mm"]["length"] = 160
    pattern = generate(request([item]))
    panel = next(p for p in pattern["pieces"] if p["id"] == f"{item['source_element_id']}_detail")
    join = contour_from_data(panel["seam_contour"]).segments[0]
    assert join.length_mm == pytest.approx(160)
    assert math_degrees(join.sweep_angle_rad) == pytest.approx(angle)


def math_degrees(value):
    import math

    return math.degrees(value)


@pytest.mark.parametrize("index", [5, 6, 7, 9, 10])
def test_asymmetry_requires_a_side_and_is_not_silently_normalized(index):
    item = element(index, count=1, symmetry="asymmetric", placement=dict(side="left"))
    req = request([item])
    pattern = generate(req)
    assert req["garment_spec"]["design_intent"]["elements"][0]["symmetry"] == "asymmetric"
    first_hash = compute_input_hash(req)
    item["placement"]["side"] = "right"
    req["garment_spec"]["design_intent"]["elements"][0]["placement"]["side"] = "right"
    assert compute_input_hash(req) != first_hash
    assert any("левую сторону" in a["text_ru"] for p in pattern["pieces"] for a in p["annotations"])
    del item["placement"]
    assert matching_module(item, req["garment_spec"], kind="element") is None


@pytest.fixture(scope="module")
def printable():
    return generate(request([element(1), element(7), element(11)]))


def test_export_and_manual_edit_cannot_lose_or_move_a_fold_mark(printable):
    pattern = deepcopy(printable)
    front = next(p for p in pattern["pieces"] if p["id"] == "front_skirt")
    mark = next(p for p in front["internal_paths"] if p["id"].startswith("fullness_1_fullness_"))
    mark["segments"][0]["end"][0] += 3
    with pytest.raises(SVGRenderError):
        render_pattern_svg(pattern)
    with pytest.raises(PDFRenderError):
        render_pattern_pdf(pattern)
    front["internal_paths"].remove(mark)
    with pytest.raises(BlockConstructionError) as error:
        validate_fullness_placements(pattern)
    assert error.value.code == "FULLNESS_MARK_MISSING"


def test_save_reopen_cache_and_print_keep_the_full_combination(tmp_path):
    # Distinct body/skirt targets and a late tier chain exercise all phases.
    selected = [element(1), element(3), element(5), element(10), element(11)]
    req = request(selected, [_layer("lining", "lining", "skirt", "opaque", "skirt_full_lining_v1")])
    project = project_document()
    project["garment_spec"] = deepcopy(req["garment_spec"])
    with client(tmp_path) as api:
        saved = api.post("/api/v1/projects", json=project)
        assert saved.status_code == 201, saved.text
        reopened = api.get(f"/api/v1/projects/{project['project_id']}").json()
        result = api.post(
            "/api/v1/patterns/generate", json=engine_request(reopened), headers={"If-Match": "1"}
        )
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["status"] == "succeeded", result["validation_report"]
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        cached = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(current),
            headers={"If-Match": str(current["revision"])},
        )
        assert cached.status_code == 200, cached.text
        assert cached.json()["generation_id"] == result["generation_id"]
        svg = api.get(f"/api/v1/patterns/{result['generation_id']}/preview.svg")
        pdf = api.post(f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf")
        assert svg.status_code == 200 and pdf.status_code == 200
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "ярус" in text.lower() and "50 x 50 mm" in text
        modules = {entry["module_id"] for entry in result["pattern"]["design_coverage"]["modules"]}
        assert {item["module_id"] for item in selected} <= modules
        assert (
            current["garment_spec"]["design_intent"]["elements"][-2]["placement"]["side"] == "right"
        )


def test_python_and_typescript_use_identical_fullness_hash_payloads():
    root = Path(__file__).resolve().parents[1]
    req = request([element(1), element(6, placement=dict(side="left")), element(11)])
    script = r"""import {stripTypeScriptTypes as strip} from 'node:module'; import fs from 'node:fs';
    const mod=strip(fs.readFileSync('src/designModules.ts','utf8'),{mode:'transform'});
    const reg=JSON.parse(fs.readFileSync('../src/kroika_contracts/design_modules.json','utf8'));
    const url='data:text/javascript;base64,'+Buffer.from(mod.replace(/import registry.*;/,'const registry='+JSON.stringify(reg)+';')).toString('base64');
    const gen=strip(fs.readFileSync('src/generation.ts','utf8'),{mode:'transform'}).replace("'./designModules'",JSON.stringify(url));
    const lib=await import('data:text/javascript;base64,'+Buffer.from(gen).toString('base64'));
    let input='';for await(const chunk of process.stdin)input+=chunk;
    process.stdout.write(lib.stableJson(lib.canonicalGenerationPayload(JSON.parse(input))));"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=root / "frontend",
        input=json.dumps(req),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(run.stdout) == canonical_generation_payload(req)
    assert FULLNESS_MODULES == {case[0] for case in CASES}


def test_manual_edit_preserves_protected_markers_and_rejects_tampered_anchors():
    from kroika_pattern_engine.manual_edit import apply_manual_edits, ManualEditError

    req = request([element(1)])
    pattern = generate(req)
    front = next(p for p in pattern["pieces"] if p["id"] == "front_skirt")
    hem = next(
        s
        for s in front["seam_contour"]["segments"]
        if s["id"].endswith("_hem") and "_split_" in s["id"]
    )
    edit = dict(
        piece_id="front_skirt",
        segment_id=hem["id"],
        handle="end",
        x_mm=hem["end"][0] - 0.2,
        y_mm=hem["end"][1],
    )
    edited = apply_manual_edits(pattern, [edit], req, base_generation_id="base")
    validate_fullness_placements(edited.pattern)
    render_pattern_svg(edited.pattern)
    mark = next(p for p in front["internal_paths"] if p["id"].startswith("fullness_1_fullness_"))
    mark["segments"][0]["end"][0] += 5
    with pytest.raises((BlockConstructionError, ManualEditError)):
        apply_manual_edits(pattern, [edit], req, base_generation_id="base")


def test_small_circular_radius_reports_allowance_conflict_instead_of_missing_module():
    item = element(8, location="skirt_back", placement=dict(side="both", sweep_angle_deg=270))
    req = request([item])
    req["input_hash"] = compute_input_hash(req)
    validate_engine_request(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "rejected"
    assert result["validation_report"]["issues"][0]["code"] == "FULLNESS_SECTOR_ALLOWANCE_CONFLICT"


@pytest.mark.parametrize(
    "location,edge,garment",
    [
        ("skirt_front", "neckline", "skirt"),
        ("sleeve", "hem", "top"),
        ("bodice_back", "hem", "dress"),
    ],
)
def test_impossible_catalogue_edges_and_sleeveless_targets_are_not_supported(
    location, edge, garment
):
    project = upper_project(garment) if garment in {"top", "skirt"} else project_document()
    item = element(7, location=location, placement=dict(side="both", edge=edge))
    assert matching_module(item, project["garment_spec"], kind="element") is None


def test_selected_recipe_cannot_be_substituted_when_sizes_stop_matching():
    item = element(6, selected_module_id="diagonal_bodice_drape_v2")
    req = request([item])
    assert matching_module(item, req["garment_spec"], kind="element") == "diagonal_bodice_drape_v2"
    item["dimensions_mm"]["width"] = 200
    assert matching_module(item, req["garment_spec"], kind="element") is None


def test_attachment_intervals_must_be_disjoint_on_the_same_physical_side():
    first = element(7, count=1, symmetry="asymmetric", placement=dict(side="left"))
    second = element(
        7, source_element_id="second", count=1, symmetry="asymmetric", placement=dict(side="left")
    )
    req = request([first, second])
    req["input_hash"] = compute_input_hash(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "rejected"
    assert result["validation_report"]["issues"][0]["code"] == "FULLNESS_ATTACHMENT_CONFLICT"
    second["placement"]["side"] = "right"
    generate(request([first, second]))
    second["placement"]["side"] = "left"
    second["dimensions_mm"]["spacing"] = 130
    generate(request([first, second]))


@pytest.mark.parametrize("index", [3, 4])
def test_front_unfolding_combination_uses_new_composition_contract(index):
    req = request([element(index, location="bodice_front"), element(6)])
    req["input_hash"] = compute_input_hash(req)
    validate_engine_request(req)
    assert canonical_generation_payload(req)["hash_contract_version"] == "1.11.0"


def test_geometry_failure_returns_a_rejected_report_instead_of_crashing(monkeypatch):
    from kroika_pattern_engine.geometry import DisconnectedContourError
    import kroika_pattern_engine.scaffold as scaffold

    def broken(*_args):
        raise DisconnectedContourError("Тест несвязного контура.")

    monkeypatch.setattr(scaffold, "apply_fullness_details", broken)
    result = GeometryPatternEngine().generate(request([element(7)]))
    assert result["status"] == "rejected"
    assert result["validation_report"]["issues"][0]["code"] == "GEOMETRY_CONTOUR_DISCONNECTED"
    assert result["validation_report"]["issues"][0]["json_pointer"] == "/pattern"

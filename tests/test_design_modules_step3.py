from copy import deepcopy
from kroika_pattern_engine.geometry import contour_from_data
import pytest
from kroika_contracts.design_modules import MODULES, STRUCTURAL_MODULES, matching_module
from kroika_contracts.hashing import compute_input_hash, canonical_generation_payload
from kroika_contracts.contract_io import validate_document
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_svg
from tests.test_additional_details import request
from tests.test_stage19_composites import _element, _dimensions
from tests.test_stage12_garments import _project as upper_project
from tests.test_stage14_lower_garments import _project as lower_project

SIZES = {
    "side_skirt_slit_v3": dict(width=30, length=150),
    "back_skirt_slit_v3": dict(width=30, length=150),
    "back_skirt_vent_v3": dict(width=40, length=150),
    "fitted_two_piece_hood_v3": dict(width=280, length=340, depth=30),
    "straight_shoulder_straps_v3": dict(width=25, length=350, depth=40, spacing=45),
    "elastic_waistband_v3": dict(width=30, length=650),
    "shaped_belt_v3": dict(width=50, length=1000, depth=40),
    "tapered_sash_v3": dict(width=80, length=1600, depth=80),
    "rounded_patch_pocket_v3": dict(width=80, depth=100, spacing=140),
    "welt_pocket_v3": dict(length=90, width=10, depth=140, spacing=140),
    "shaped_flat_collar_v3": dict(width=70, depth=45),
    "shawl_collar_v3": dict(width=100, depth=50),
    "doubled_cuff_v3": dict(width=50, depth=25),
    "shaped_cuff_v3": dict(width=50, depth=80),
    "front_bodice_yoke_v3": dict(depth=70),
    "back_bodice_yoke_v3": dict(depth=70),
    "offset_skirt_panel_v3": dict(width=40),
    "shoulder_princess_seam_v3": dict(spacing=50),
    "side_to_waist_dart_v3": dict(width=5),
    "placed_decorative_stitch_v3": dict(length=100, spacing=140),
    "explicit_polygon_detail_v3": dict(length=100, spacing=30),
    "back_hooks_v3": {},
}


def make_request(module, **overrides):
    recipe = next(m for m in MODULES if m["id"] == module)
    rule = recipe["rules"][0]
    garment = (
        "blouse"
        if module in {"doubled_cuff_v3", "shaped_cuff_v3"}
        else "skirt"
        if module == "elastic_waistband_v3"
        else "dress"
    )
    project = upper_project(garment) if garment != "dress" else None
    location = rule["location"][0]
    if module in {
        "rounded_patch_pocket_v3",
        "welt_pocket_v3",
        "placed_decorative_stitch_v3",
        "explicit_polygon_detail_v3",
    }:
        location = "skirt_front"
    element = _element(
        "structural_detail",
        rule["type"][0],
        rule["variant"][0],
        location,
        rule["construction"][0],
        rule.get("count", [1])[0],
        module,
        _dimensions(**SIZES[module]),
    )
    element["selected_module_id"] = module
    if recipe.get("placement", {}).get("side"):
        element["placement"] = {"side": "both"}
        element["count"] = 2
    if module in {"rounded_patch_pocket_v3", "welt_pocket_v3", "placed_decorative_stitch_v3"}:
        element["placement"]["offset_mm"] = 260
    if module == "explicit_polygon_detail_v3":
        element["outline_mm"] = [[0, 0], [100, 0], [80, 60], [0, 60]]
        element["placement"].update(edge="hem", outline_edge_index=0)
    element.update(overrides)
    r = request([element], project=project)
    if module == "back_hooks_v3":
        r["garment_spec"]["parameters"]["closure"] = {
            "type": "hooks",
            "location": "center_back",
            "length_mm": 350,
            "loop_pitch_mm": 80,
        }
    r["input_hash"] = compute_input_hash(r)
    return r


@pytest.mark.parametrize("module", sorted(STRUCTURAL_MODULES))
def test_every_registered_recipe_has_actual_cut_or_marker_geometry(module):
    r = make_request(module)
    e = r["garment_spec"]["design_intent"]["elements"][0]
    assert matching_module(e, r["garment_spec"], kind="element") == module
    validate_document("pattern-engine-request", r)
    validate_engine_request(r)
    output = GeometryPatternEngine().generate(r)
    assert output["pattern"] is not None, output["validation_report"]
    pattern = output["pattern"]
    validate_document("pattern-data", pattern)
    evidence = next(m for m in pattern["design_coverage"]["modules"] if m["module_id"] == module)
    assert evidence["evidence"]["piece_ids"] and evidence["evidence"]["operation_ids"]
    op = next(o for o in pattern["composite_operations"] if o["module_id"] == module)
    assert op["interface_ids"]
    assert op["invariant_residual_mm"] <= 1
    svg = render_pattern_svg(pattern)
    assert source_printed(svg, op)
    assert canonical_generation_payload(r)["hash_contract_version"] == "1.9.0"


def source_printed(svg, op):
    return op["source_id"] in svg or any(pid in svg for pid in op["added_piece_ids"])


def generate(r):
    r["input_hash"] = compute_input_hash(r)
    validate_engine_request(r)
    output = GeometryPatternEngine().generate(r)
    assert output["pattern"] is not None, output["validation_report"]["issues"]
    return output["pattern"]


@pytest.mark.parametrize("garment", ["trousers", "shorts"])
@pytest.mark.parametrize("location", ["trouser_front", "trouser_back"])
@pytest.mark.parametrize("module", ["rounded_patch_pocket_v3", "welt_pocket_v3"])
def test_pockets_attach_to_the_actual_front_or_back_of_lower_garments(garment, location, module):
    element = make_request(module)["garment_spec"]["design_intent"]["elements"][0]
    element["location"] = location
    element["placement"]["offset_mm"] = 80
    pattern = generate(request([element], project=lower_project(garment)))
    op = next(o for o in pattern["composite_operations"] if o["module_id"] == module)
    expected = "front_trouser" if location == "trouser_front" else "back_trouser"
    assert op["target_piece_ids"] == [expected]
    attachments = [
        pair for pair in pattern["seam_pairs"]
        if pair["id"] in op["interface_ids"] and pair["first_piece_id"] == expected
    ]
    assert len(attachments) == (5 if module == "rounded_patch_pocket_v3" else 2)
    assert all(pair["second_piece_id"] in op["added_piece_ids"] for pair in attachments)
    validate_document("pattern-data", pattern)


@pytest.mark.parametrize(
    "module,changes",
    [
        (
            "front_bodice_yoke_v3",
            dict(variant="shaped", dimensions_mm=_dimensions(depth=70, width=15)),
        ),
        (
            "back_bodice_yoke_v3",
            dict(variant="shaped", dimensions_mm=_dimensions(depth=70, width=15)),
        ),
        (
            "offset_skirt_panel_v3",
            dict(variant="shaped", dimensions_mm=_dimensions(width=30, depth=20)),
        ),
        ("offset_skirt_panel_v3", dict(location="skirt_back")),
        ("shoulder_princess_seam_v3", dict(location="bodice_back")),
        ("rounded_patch_pocket_v3", dict(location="skirt_back")),
        (
            "placed_decorative_stitch_v3",
            dict(
                placement={"side": "both", "offset_mm": 280, "orientation": "horizontal"},
                dimensions_mm=_dimensions(length=80, spacing=140),
            ),
        ),
    ],
)
def test_changed_forms_and_back_locations_remain_actual_geometry(module, changes):
    pattern = generate(make_request(module, **changes))
    assert any(o["module_id"] == module for o in pattern["composite_operations"])
    validate_document("pattern-data", pattern)


@pytest.mark.parametrize(
    "module",
    [
        "side_skirt_slit_v3",
        "rounded_patch_pocket_v3",
        "welt_pocket_v3",
        "explicit_polygon_detail_v3",
    ],
)
@pytest.mark.parametrize("side", ["left", "right"])
def test_one_sided_details_keep_count_and_physical_side(module, side):
    r = make_request(module)
    item = r["garment_spec"]["design_intent"]["elements"][0]
    item.update(count=1, symmetry="asymmetric")
    item["placement"]["side"] = side
    first = compute_input_hash(r)
    pattern = generate(r)
    op = next(o for o in pattern["composite_operations"] if o["module_id"] == module)
    assert all(
        next(p for p in pattern["pieces"] if p["id"] == pid)["cut_quantity"] == 1
        for pid in op["added_piece_ids"]
    )
    assert all(
        pair.get("physical_side") == side
        for pair in pattern["seam_pairs"]
        if pair["id"] in op["interface_ids"]
    )
    if module == "side_skirt_slit_v3":
        other = next(
            pair for pair in pattern["seam_pairs"] if pair["id"].endswith("other_side_closed")
        )
        assert other["physical_side"] != side
        assert other["first_segment_ids"] == ["front_skirt_side_lower", "front_skirt_side_upper"]
    item["placement"]["side"] = "right" if side == "left" else "left"
    assert compute_input_hash(r) != first


@pytest.mark.parametrize("typ", ["zipper", "buttons", "lacing", "hooks"])
def test_yoke_keeps_measured_closure_across_both_back_fragments(typ):
    r = make_request("back_bodice_yoke_v3")
    r["garment_spec"]["parameters"]["closure"] = {
        "type": typ,
        "location": "center_back",
        "length_mm": 350,
        **({} if typ == "zipper" else {"loop_pitch_mm": 80}),
    }
    pattern = generate(r)
    lines = [
        contour_from_data(path).segments[0].length_mm
        for p in pattern["pieces"]
        for path in p["internal_paths"]
        if p["id"].startswith("back_bodice") and path["id"].endswith("_back_opening")
    ]
    assert len(lines) == 2 and sum(lines) == pytest.approx(350)


def test_reverse_dart_preserves_finished_seams_by_rotation():
    r = make_request("side_to_waist_dart_v3")
    pattern = generate(r)
    op = next(o for o in pattern["composite_operations"] if o["kind"] == "dart")
    assert op["parameters_mm"]["opened_waist_intake"] > 0
    assert op["parameters_mm"]["opened_waist_intake"] != pytest.approx(5)
    waist = next(pair for pair in pattern["seam_pairs"] if pair["id"] == "front_waist_join")
    assert waist["first_length_reduction_mm"] > 36.6
    front = next(p for p in pattern["pieces"] if p["id"] == "front_bodice")
    assert len([p for p in front["internal_paths"] if "waist_dart" in p["id"]]) == 2


@pytest.mark.parametrize(
    "module", ["front_bodice_yoke_v3", "shoulder_princess_seam_v3", "side_to_waist_dart_v3"]
)
def test_bodice_cuts_also_balance_on_the_fitted_foundation(module):
    r = make_request(module)
    r["garment_spec"]["parameters"]["bodice_fit"] = "fitted"
    r["fit_settings"]["preset"]["id"] = "woven_fitted_trial"
    r["fit_settings"]["wearing_ease_mm"].update(bust=40, waist=20, hips=40)
    pattern = generate(r)
    op = next(o for o in pattern["composite_operations"] if o["module_id"] == module)
    assert op["invariant_residual_mm"] <= 1
    validate_document("pattern-data", pattern)


@pytest.mark.parametrize("module", ["shaped_belt_v3", "tapered_sash_v3"])
def test_tied_belts_require_length_for_a_knot_as_well_as_waist(module):
    r = make_request(module)
    r["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["length"] = (
        r["body_measurements"]["values"]["waist"]["value"] + 10
    )
    r["input_hash"] = compute_input_hash(r)
    output = GeometryPatternEngine().generate(r)
    assert output["pattern"] is None
    assert "STRUCTURAL_GEOMETRY_INVALID" in {
        issue["code"] for issue in output["validation_report"]["issues"]
    }


def test_vent_is_an_integrated_extension_and_back_openings_do_not_overlap():
    r = make_request("back_skirt_vent_v3")
    pattern = generate(r)
    back = next(p for p in pattern["pieces"] if p["id"] == "back_skirt")
    assert contour_from_data(back["seam_contour"]).bounding_box.min_x_mm == -40
    assert any(p["id"].endswith("vent_fold") for p in back["internal_paths"])
    r = make_request("back_skirt_slit_v3")
    r["garment_spec"]["parameters"]["closure"]["length_mm"] = 800
    r["input_hash"] = compute_input_hash(r)
    output = GeometryPatternEngine().generate(r)
    assert output["pattern"] is None
    assert "BACK_OPENINGS_OVERLAP" in {i["code"] for i in output["validation_report"]["issues"]}


@pytest.mark.parametrize(
    "outline", [[[0, 0], [100, 0], [0, 0]], [[0, 0], [100, 0], [0, 60], [100, 60]]]
)
def test_degenerate_and_crossed_explicit_outlines_are_rejected(outline):
    r = make_request("explicit_polygon_detail_v3", outline_mm=outline)
    r["input_hash"] = compute_input_hash(r)
    output = GeometryPatternEngine().generate(r)
    assert output["pattern"] is None and output["status"] == "rejected"


@pytest.mark.parametrize(
    "changes",
    [
        dict(outline_mm=None),
        dict(outline_mm=[[0, 0], [90, 0], [0, 60]]),
        dict(placement={"side": "both", "edge": "hem", "outline_edge_index": 4}),
        dict(placement={"side": "both", "edge": "neckline", "outline_edge_index": 0}),
    ],
)
def test_missing_outline_or_mismatched_attachment_is_not_ready(changes):
    r = make_request("explicit_polygon_detail_v3", **changes)
    item = r["garment_spec"]["design_intent"]["elements"][0]
    assert matching_module(item, r["garment_spec"], kind="element") is None


def test_cut_cannot_pass_through_a_dart():
    r = make_request("offset_skirt_panel_v3", dimensions_mm=_dimensions(width=100))
    r["input_hash"] = compute_input_hash(r)
    output = GeometryPatternEngine().generate(r)
    assert output["pattern"] is None
    assert any("DART_CONFLICT" in i["code"] for i in output["validation_report"]["issues"])


@pytest.fixture(scope="module")
def printed():
    return generate(make_request("welt_pocket_v3"))


def test_markers_survive_pdf_and_cannot_be_moved_on_export(printed):
    from io import BytesIO
    from pypdf import PdfReader
    from kroika_pattern_engine import render_pattern_pdf
    from kroika_pattern_engine.svg import SVGRenderError
    from kroika_pattern_engine.pdf import PDFRenderError

    pdf = render_pattern_pdf(printed)
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert "Мешковина" in text and "треугольники" in text
    damaged = deepcopy(printed)
    front = next(p for p in damaged["pieces"] if p["id"] == "front_skirt")
    mark = next(p for p in front["internal_paths"] if "welt_mark_0" in p["id"])
    mark["segments"][0]["end"][0] += 2
    with pytest.raises(SVGRenderError):
        render_pattern_svg(damaged)
    with pytest.raises(PDFRenderError):
        render_pattern_pdf(damaged)


def test_source_detail_round_trips_through_project_cache_and_print(tmp_path):
    from tests.test_stage11_workflow import client, project_document, engine_request

    project = project_document()
    r = make_request("explicit_polygon_detail_v3")
    project["garment_spec"] = r["garment_spec"]
    with client(tmp_path) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        saved = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert saved["garment_spec"]["design_intent"]["elements"][0]["outline_mm"] == [
            [0, 0],
            [100, 0],
            [80, 60],
            [0, 60],
        ]
        req = engine_request(saved)
        first = api.post(
            "/api/v1/patterns/generate", json=req, headers={"If-Match": str(saved["revision"])}
        )
        assert first.status_code == 200, first.text
        data = first.json()
        assert data["pattern"] is not None, data
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        again = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(current),
            headers={"If-Match": str(current["revision"])},
        )
        assert again.status_code == 200, again.text
        assert again.json()["pattern"] == data["pattern"]
        assert "structural_detail_detail" in render_pattern_svg(again.json()["pattern"])


def test_structural_hash_is_identical_in_python_and_typescript():
    import subprocess
    import json
    from pathlib import Path
    from tests.test_design_modules_step2 import (
        test_python_and_typescript_use_identical_fullness_hash_payloads,
    )
    import inspect

    script = (
        inspect.getsource(test_python_and_typescript_use_identical_fullness_hash_payloads)
        .split('script = r"""')[1]
        .split('"""')[0]
    )
    for module in ["explicit_polygon_detail_v3", "back_hooks_v3", "side_to_waist_dart_v3"]:
        r = make_request(module)
        run = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=Path(__file__).resolve().parents[1] / "frontend",
            input=json.dumps(r),
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(run.stdout) == canonical_generation_payload(r)

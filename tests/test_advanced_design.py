from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import subprocess

import pytest
from pypdf import PdfReader

from tests.test_additional_details import request, ROOT
from tests.test_stage19_composites import _element, _dimensions, _layer
from tests.test_stage11_workflow import client, project_document, engine_request
from tests.test_stage12_garments import _project as upper_project
from tests.test_stage14_lower_garments import _project as lower_project
from kroika_contracts.contract_io import validate_document
from kroika_contracts.design_modules import matching_module
from kroika_contracts.hashing import compute_input_hash, canonical_generation_payload
from kroika_contracts.semantic import validate_engine_request, SemanticContractError
from kroika_pattern_engine import GeometryPatternEngine
from kroika_pattern_engine.advanced import prepare_proportions, validate_advanced_placements
from kroika_pattern_engine.blocks import BlockConstructionError
from kroika_pattern_engine.geometry import contour_from_data

CASES = [
    (
        "crossed_bodice_drape_v1",
        "drape",
        "soft",
        "bodice_front",
        "layered",
        2,
        dict(width=50, depth=100, spacing=30),
    ),
    (
        "off_shoulder_bands_v1",
        "strap",
        "shaped",
        "shoulder",
        "separate_piece",
        2,
        dict(width=50, length=350, depth=30),
    ),
    (
        "vertical_cascade_flounce_v1",
        "flounce",
        "soft",
        "skirt_front",
        "separate_piece",
        1,
        dict(length=450, depth=150, spacing=30),
    ),
]


def elements():
    result = []
    for index, (module, typ, variant, loc, construction, count, dimensions) in enumerate(CASES):
        item = _element(
            f"advanced_{index}",
            typ,
            variant,
            loc,
            construction,
            count,
            module,
            _dimensions(**dimensions),
        )
        item["symmetry"] = "single" if index == 2 else "symmetric"
        result.append(item)
    return result


def proportions(req, **values):
    req["garment_spec"]["design_intent"]["proportions"].update(
        module_id="parametric_visual_proportions_v1", **values
    )
    req["input_hash"] = compute_input_hash(req)
    return req


def generate(req):
    req["input_hash"] = compute_input_hash(req)
    validate_engine_request(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "succeeded", result["validation_report"]
    validate_document("pattern-data", result["pattern"])
    return result["pattern"]


@pytest.mark.parametrize("index", range(3), ids=[c[0] for c in CASES])
def test_modules_have_cutting_geometry_and_explicit_join_evidence(index):
    req = request([elements()[index]])
    assert (
        matching_module(
            req["garment_spec"]["design_intent"]["elements"][0], req["garment_spec"], kind="element"
        )
        == CASES[index][0]
    )
    pattern = generate(req)
    op = next(o for o in pattern["composite_operations"] if o["module_id"] == CASES[index][0])
    assert op["added_piece_ids"] and op["interface_ids"]
    assert op["invariant_residual_mm"] < 1
    assert canonical_generation_payload(req)["hash_contract_version"] == "1.6.0"
    if index == 0:
        front = next(p for p in pattern["pieces"] if p["id"] == "front_bodice")
        assert not front["cut_on_fold"] and front["cut_quantity"] == 1
        assert contour_from_data(front["seam_contour"]).bounding_box.min_x_mm < 0
        assert any(pair.get("second_instance") == "mirror" for pair in pattern["seam_pairs"])
        joins = [
            pair
            for pair in pattern["seam_pairs"]
            if pair["second_piece_id"] in op["added_piece_ids"]
        ]
        assert len(joins) == 4
        assert all(pair["second_length_reduction_mm"] == 100 for pair in joins)
    elif index == 1:
        assert not any("shoulder" in pair["id"] for pair in pattern["seam_pairs"])
        for pid in ["front_bodice", "back_bodice", "front_facing", "back_facing"]:
            piece = next(p for p in pattern["pieces"] if p["id"] == pid)
            assert not any("shoulder" in edge["id"] for edge in piece["seam_contour"]["segments"])
    else:
        assert (
            next(p for p in pattern["pieces"] if p["id"] == op["added_piece_ids"][0])[
                "cut_quantity"
            ]
            == 1
        )


def test_dress_combination_survives_save_reopen_cache_and_svg_pdf(tmp_path):
    req = proportions(request(elements()), asymmetry="yes")
    project = project_document()
    project["garment_spec"] = deepcopy(req["garment_spec"])
    with client(tmp_path) as api:
        saved = api.post("/api/v1/projects", json=project)
        assert saved.status_code == 201, saved.text
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        result = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(current),
            headers={"If-Match": str(current["revision"])},
        )
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["status"] == "succeeded", result["validation_report"]
        assert len(result["pattern"]["pieces"]) == 10
        assert (
            api.get(f"/api/v1/projects/{project['project_id']}").json()["garment_spec"][
                "design_intent"
            ]["elements"]
            == project["garment_spec"]["design_intent"]["elements"]
        )
        current = api.get(f"/api/v1/projects/{project['project_id']}").json()
        cached = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(current),
            headers={"If-Match": str(current["revision"])},
        )
        assert (
            cached.status_code == 200 and cached.json()["generation_id"] == result["generation_id"]
        )
        svg = api.get(f"/api/v1/patterns/{result['generation_id']}/preview.svg")
        assert svg.status_code == 200, svg.text
        for op in result["pattern"]["composite_operations"]:
            for pid in op["added_piece_ids"]:
                assert pid in svg.text
        pdf = api.post(f"/api/v1/patterns/{result['generation_id']}/export/a4-pdf")
        assert pdf.status_code == 200, pdf.text
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "50 x 50 mm" in text
        for piece in result["pattern"]["pieces"]:
            assert piece["name_ru"] in text


@pytest.mark.parametrize(
    "garment",
    ["dress", "sundress", "skirt", "top", "blouse", "shirt", "vest", "trousers", "shorts"],
)
def test_relaxed_fit_changes_real_geometry_for_each_supported_basis(garment):
    base = request(
        [],
        project=lower_project(garment)
        if garment in {"trousers", "shorts"}
        else project_document()
        if garment in {"dress", "sundress"}
        else upper_project(garment),
    )
    base["garment_spec"]["garment_type"] = garment
    regular = generate(deepcopy(base))
    relaxed_request = proportions(deepcopy(base), volume="relaxed")
    source_copy = deepcopy(relaxed_request)
    relaxed = generate(relaxed_request)
    assert relaxed_request == source_copy
    target = {"trousers": "front_trouser", "shorts": "front_trouser", "skirt": "front_skirt"}.get(
        garment, "front_bodice"
    )
    a = contour_from_data(next(p for p in regular["pieces"] if p["id"] == target)["seam_contour"])
    b = contour_from_data(next(p for p in relaxed["pieces"] if p["id"] == target)["seam_contour"])
    assert b.bounding_box.width_mm > a.bounding_box.width_mm
    assert compute_input_hash(base) != compute_input_hash(relaxed_request)


@pytest.mark.parametrize("waist,sign", [("high", -1), ("low", 1)])
def test_shifted_waist_uses_measured_arcs_and_keeps_total_length(waist, sign):
    req = proportions(
        request([]),
        waist_position=waist,
        waist_shift_mm=30,
        waist_level_circumference_mm=800,
        back_waist_level_arc_mm=400,
    )
    before = deepcopy(req)
    derived = prepare_proportions(req)
    assert req == before
    for key in ["front_neck_to_waist_over_bust", "back_neck_to_waist"]:
        assert (
            derived["body_measurements"]["values"][key]["value"]
            == before["body_measurements"]["values"][key]["value"] + sign * 30
        )
    assert (
        derived["body_measurements"]["values"]["hip_depth"]["value"]
        == before["body_measurements"]["values"]["hip_depth"]["value"] - sign * 30
    )
    assert derived["garment_spec"]["parameters"]["skirt"]["length_from_waist_mm"] == 550 - sign * 30
    generate(req)
    req["garment_spec"]["design_intent"]["proportions"]["back_waist_level_arc_mm"] = None
    req["input_hash"] = compute_input_hash(req)
    with pytest.raises(SemanticContractError):
        validate_engine_request(req)


@pytest.mark.parametrize("shape", ["curved", "asymmetric"])
def test_shaped_hem_preserves_side_connections_and_uses_real_center_height(shape):
    req = proportions(
        request([]),
        hem_shape=shape,
        hem_delta_mm=80,
        asymmetry="yes" if shape == "asymmetric" else "no",
    )
    pattern = generate(req)
    pieces = {p["id"]: p for p in pattern["pieces"]}
    assert pieces["front_skirt"]["seam_contour"]["segments"][0]["end"][1] == -470
    assert pieces["back_skirt"]["seam_contour"]["segments"][0]["end"][1] == (
        -550 if shape == "asymmetric" else -470
    )
    assert pieces["front_skirt"]["seam_contour"]["segments"][1]["end"][1] == -550


def test_false_asymmetry_and_outside_cascade_return_reviewable_errors():
    req = proportions(request([]), asymmetry="yes")
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "rejected"
    assert result["validation_report"]["issues"][0]["code"] == "ASYMMETRY_GEOMETRY_REQUIRED"
    req = request([elements()[2]])
    req["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["length"] = 600
    req["input_hash"] = compute_input_hash(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "rejected"
    assert "Длина крепления" in result["validation_report"]["issues"][0]["message_ru"]
    req = request([elements()[2]])
    pattern = generate(req)
    target = next(p for p in pattern["pieces"] if p["id"] == "front_skirt")
    path = next(p for p in target["internal_paths"] if "cascade_anchor" in p["id"])
    path["segments"][0]["start"][0] = path["segments"][0]["end"][0] = 10000
    with pytest.raises(BlockConstructionError, match="Метка крепления"):
        validate_advanced_placements(pattern)


def test_off_shoulder_overlay_and_drape_copy_the_final_foundation():
    layer = _layer("overlay", "overlay", "bodice", "semi_transparent", "bodice_overlay_layer_v1")
    req = request([elements()[1]], [layer])
    generate(req)
    req = request(elements()[:2], [layer])
    pattern = generate(req)
    pieces = {p["id"]: p for p in pattern["pieces"]}
    assert pieces["overlay_front_bodice"]["cut_quantity"] == 1
    assert not pieces["overlay_front_bodice"]["cut_on_fold"]
    assert len(pieces["overlay_front_bodice"]["seam_contour"]["segments"]) == len(
        pieces["front_bodice"]["seam_contour"]["segments"]
    )


def test_advanced_hash_matches_actual_frontend_function():
    req = proportions(
        request(elements()),
        waist_position="high",
        waist_shift_mm=30,
        waist_level_circumference_mm=800,
        back_waist_level_arc_mm=400,
        hem_shape="asymmetric",
        hem_delta_mm=80,
        asymmetry="yes",
    )
    output = subprocess.check_output(
        [
            "node",
            "--input-type=module",
            "-e",
            "import {stripTypeScriptTypes as strip} from 'node:module'; import fs from 'node:fs'; const gen=strip(fs.readFileSync('src/generation.ts','utf8'),{mode:'transform'}); const mod=strip(fs.readFileSync('src/designModules.ts','utf8'),{mode:'transform'}); const reg=JSON.parse(fs.readFileSync('../src/kroika_contracts/design_modules.json','utf8')); const moduleUrl='data:text/javascript;base64,'+Buffer.from(mod.replace(/import registry.*;/, 'const registry='+JSON.stringify(reg)+';')).toString('base64'); const code=gen.replace(\"'./designModules'\",JSON.stringify(moduleUrl)); const lib=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64')); process.stdout.write(lib.stableJson(lib.canonicalGenerationPayload(JSON.parse(process.argv[1]))));",
            json.dumps(req),
        ],
        cwd=ROOT / "frontend",
        text=True,
    )
    assert json.loads(output) == canonical_generation_payload(req)
    before = compute_input_hash(req)
    req["garment_spec"]["design_intent"]["proportions"]["waist_shift_mm"] += 1
    assert compute_input_hash(req) != before


def test_manual_editor_preserves_internal_attachment_marks():
    from kroika_pattern_engine.manual_edit import apply_manual_edits
    from kroika_pattern_engine.print_layout import PlacedPiece, notch_geometry

    req = request(elements()[:2])
    pattern = generate(req)
    front = next(p for p in pattern["pieces"] if p["id"] == "front_bodice")
    notch = next(n for n in front["notches"] if "anchor" in n["segment_id"])
    placed = PlacedPiece(front, (-260, 0, 260, 300), 0, 0)
    assert notch_geometry(placed, notch) is not None
    panel = next(p for p in pattern["pieces"] if p["id"] == "advanced_0_drape_1")
    edge = panel["seam_contour"]["segments"][0]
    edited = apply_manual_edits(
        pattern,
        [
            dict(
                piece_id=panel["id"],
                segment_id=edge["id"],
                handle="end",
                x_mm=edge["end"][0] + 0.1,
                y_mm=edge["end"][1],
            )
        ],
        req,
        base_generation_id="11111111-1111-4111-8111-111111111111",
    )
    assert edited.audit_edits
    validate_advanced_placements(edited.pattern)


@pytest.mark.parametrize("garment", ["dress", "blouse", "trousers"])
def test_voluminous_fit_increases_fullness_and_preserves_interfaces(garment):
    project = (
        lower_project(garment)
        if garment == "trousers"
        else upper_project(garment)
        if garment == "blouse"
        else project_document()
    )
    req = proportions(request([], project=project), volume="voluminous")
    pattern = generate(req)
    op = next(op for op in pattern["composite_operations"] if op["kind"] == "proportions")
    assert op["parameters_mm"]["effective_design_waist"] == 120
    if garment == "blouse":
        assert op["parameters_mm"]["effective_design_upper_arm"] == 60
    from kroika_pattern_engine.composites import _pair_residual

    assert _pair_residual(pattern) < 1

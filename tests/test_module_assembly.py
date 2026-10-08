from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import xml.etree.ElementTree as ET

import pytest
from pypdf import PdfReader

from tests.test_additional_details import request
from tests.test_advanced_design import elements, proportions, generate
from tests.test_stage19_composites import _element, _dimensions, _layer
from tests.test_stage11_workflow import client, project_document, engine_request
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.semantic import validate_engine_request
from kroika_pattern_engine import render_pattern_svg, render_pattern_pdf
from kroika_pattern_engine.blocks import BlockConstructionError
from kroika_pattern_engine.coverage import compile_design_coverage
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.pdf import PDFRenderError
from kroika_pattern_engine.print_layout import layout_pattern, instruction_lines
from kroika_pattern_engine.svg import SVGRenderError
from kroika_pattern_engine.validation import validate_pattern_assembly, validate_export_coverage


def detail(source, typ, variant, location, count, module, **dimensions):
    return _element(
        source, typ, variant, location, "separate_piece", count, module, _dimensions(**dimensions)
    )


def yoke():
    return detail(
        "yoke", "yoke", "straight", "waist", 2, "paired_straight_skirt_yoke_v1", depth=120
    )


def gather():
    item = detail(
        "gather", "gather", "gathered", "skirt_front", 1, "waist_gather_allowance_v1", width=100
    )
    item["construction"] = "integrated"
    return item


def flounce():
    return detail(
        "hem_flounce", "flounce", "circular", "hem", 1, "circular_hem_flounce_v1", depth=80
    )


def collar():
    return detail("stand", "collar", "stand", "neckline", 1, "stand_collar_v1", width=35)


def layers():
    interfacing = _layer("interfacing", "interfacing", "bodice", "opaque", "bodice_interfacing_v1")
    interfacing["drape"] = "medium"
    return [
        _layer("lining", "lining", "skirt", "opaque", "skirt_full_lining_v1"),
        _layer("overlay", "overlay", "bodice", "semi_transparent", "bodice_overlay_layer_v1"),
        interfacing,
    ]


@pytest.mark.parametrize("extra", ["lining", "overlay", "interfacing", "collar"])
def test_drape_layers_and_collar_use_the_unfolded_final_neckline(extra):
    layer = next((item for item in layers() if item["source_layer_id"] == extra), None)
    pattern = generate(
        request(
            [elements()[0], *([collar()] if extra == "collar" else [])], [layer] if layer else []
        )
    )
    assert validate_pattern_assembly(pattern) < 1
    if extra in {"overlay", "interfacing"}:
        piece = next(p for p in pattern["pieces"] if p["id"] == f"{extra}_front_bodice")
        assert not piece["cut_on_fold"] and piece["cut_quantity"] == 1
        assert contour_from_data(piece["seam_contour"]).bounding_box.min_x_mm < 0
    if extra == "collar":
        assert any(p["id"] == "stand_front_collar_attachment_mirror" for p in pattern["seam_pairs"])


@pytest.mark.parametrize("extra", ["gather", "lining", "flounce", "all"])
def test_yoke_combines_with_lower_gathers_lining_and_hem_flounce(extra):
    selected = [yoke()]
    if extra in {"gather", "all"}:
        selected.append(gather())
    if extra in {"flounce", "all"}:
        selected.append(flounce())
    pattern = generate(request(selected, [layers()[0]] if extra in {"lining", "all"} else []))
    pieces = {p["id"]: p for p in pattern["pieces"]}
    assert {"front_skirt_yoke", "back_skirt_yoke"} <= pieces.keys()
    assert validate_pattern_assembly(pattern) < 1
    if extra in {"gather", "all"}:
        pair = next(p for p in pattern["seam_pairs"] if p["id"] == "front_skirt_yoke_join")
        assert pair["second_length_reduction_mm"] == 100
        assert any(p["id"] == "gather_gather_line" for p in pieces["front_skirt"]["internal_paths"])
        assert not any("gather" in p["id"] for p in pieces["front_skirt_yoke"]["internal_paths"])
    if extra in {"lining", "all"}:
        assert {
            "lining_front_skirt_yoke",
            "lining_back_skirt_yoke",
            "lining_front_skirt",
            "lining_back_skirt",
        } <= pieces.keys()
        assert any(p["id"] == "lining_front_skirt_yoke_join" for p in pattern["seam_pairs"])


@pytest.mark.parametrize("shape", ["curved", "asymmetric"])
def test_flounce_joins_follow_the_changed_hem(shape):
    pattern = generate(
        proportions(
            request([flounce(), elements()[2]]), hem_shape=shape, hem_delta_mm=80, asymmetry="yes"
        )
    )
    assert validate_pattern_assembly(pattern) < 1
    assert {"front_skirt_flounce", "back_skirt_flounce", "advanced_2_cascade"} <= {
        p["id"] for p in pattern["pieces"]
    }


@pytest.fixture(scope="module")
def combined():
    req = proportions(
        request([*elements(), flounce()], layers()),
        hem_shape="asymmetric",
        hem_delta_mm=80,
        asymmetry="yes",
    )
    return req, generate(req)


@pytest.mark.parametrize(
    "corruption,code",
    [
        ("notch", "ASSEMBLY_NOTCH_INVALID"),
        ("join_reference", "ASSEMBLY_JOIN_REFERENCE_MISSING"),
        ("join_reduction", "ASSEMBLY_JOIN_REDUCTION_INVALID"),
        ("join_length", "ASSEMBLY_JOIN_MISMATCH"),
        ("duplicate", "ASSEMBLY_ID_DUPLICATE"),
        ("open_contour", "ASSEMBLY_CONTOUR_INVALID"),
        ("operation", "ASSEMBLY_OPERATION_REFERENCE_MISSING"),
        ("mirror", "ASSEMBLY_MIRROR_COPY_MISSING"),
    ],
)
def test_final_validator_detects_broken_assembly(combined, corruption, code):
    _, base = combined
    pattern = deepcopy(base)
    pair = pattern["seam_pairs"][0]
    if corruption == "notch":
        next(p for p in pattern["pieces"] if p["notches"])["notches"][0][
            "distance_from_start_mm"
        ] = 1e6
    elif corruption == "join_reference":
        pair["second_segment_ids"] = ["missing"]
    elif corruption == "join_reduction":
        pair["first_length_reduction_mm"] = 1e6
    elif corruption == "join_length":
        pair["allowed_ease_mm"] += 50
    elif corruption == "duplicate":
        pattern["pieces"].append(deepcopy(pattern["pieces"][0]))
    elif corruption == "open_contour":
        pattern["pieces"][0]["seam_contour"]["closed"] = False
    elif corruption == "operation":
        pattern["composite_operations"][0]["target_piece_ids"] = ["missing"]
    else:
        pair = next(p for p in pattern["seam_pairs"] if p.get("second_instance") == "mirror")
        piece = next(p for p in pattern["pieces"] if p["id"] == pair["second_piece_id"])
        piece["cut_on_fold"] = piece["mirrored_pair"] = False
    with pytest.raises(BlockConstructionError) as error:
        validate_pattern_assembly(pattern)
    assert error.value.code == code


def test_same_module_cannot_cover_another_lost_source(combined):
    req, pattern = combined
    changed = deepcopy(req)
    duplicate = deepcopy(changed["garment_spec"]["design_intent"]["elements"][0])
    duplicate["source_element_id"] = "lost_drape"
    changed["garment_spec"]["design_intent"]["elements"].append(duplicate)
    with pytest.raises(BlockConstructionError) as error:
        compile_design_coverage(pattern, changed)
    assert error.value.code == "DESIGN_COVERAGE_EVIDENCE_MISSING"
    assert error.value.json_pointer.endswith("/lost_drape")


def test_missing_export_evidence_stops_both_renderers(combined):
    _, base = combined
    pattern = deepcopy(base)
    pattern["pieces"] = [p for p in pattern["pieces"] if p["id"] != "advanced_2_cascade"]
    with pytest.raises(BlockConstructionError):
        validate_export_coverage(pattern)
    with pytest.raises(SVGRenderError):
        render_pattern_svg(pattern)
    with pytest.raises(PDFRenderError):
        render_pattern_pdf(pattern)


def test_export_contains_all_lines_notches_and_sewing_instructions(combined):
    _, pattern = combined
    svg = ET.fromstring(render_pattern_svg(pattern))
    paths = {p.attrib["data-path"] for p in svg.iter() if "data-path" in p.attrib}
    assert paths == {path["id"] for piece in pattern["pieces"] for path in piece["internal_paths"]}
    annotations = {p.attrib["data-annotation"] for p in svg.iter() if "data-annotation" in p.attrib}
    assert annotations == {a["id"] for piece in pattern["pieces"] for a in piece["annotations"]}
    assert sum(p.attrib.get("data-layer") == "notches" for p in svg.iter()) == sum(
        len(p["notches"]) for p in pattern["pieces"]
    )
    layout = layout_pattern(pattern)
    for placed in layout.pieces:
        lines = instruction_lines(placed.piece, placed.width_mm)
        assert placed.offset_y_mm + placed.height_mm + 6 + len(lines) * 3.2 < layout.height_mm
    pdf = render_pattern_pdf(pattern)
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
    assert "50 x 50 mm" in text
    assert "Собрать оба конца" in text
    for piece in pattern["pieces"]:
        assert piece["name_ru"] in text


def test_save_reopen_edit_parameters_and_cache_keep_all_modules(tmp_path, combined):
    req, _ = combined
    project = project_document("Совместная сборка модулей")
    project["garment_spec"] = deepcopy(req["garment_spec"])
    with client(tmp_path) as api:
        created = api.post("/api/v1/projects", json=project)
        assert created.status_code == 201, created.text
        url = f"/api/v1/projects/{project['project_id']}"
        saved = api.get(url).json()
        first = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(saved),
            headers={"If-Match": str(saved["revision"])},
        ).json()
        assert first["status"] == "succeeded", first
        saved = api.get(url).json()
        cached = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(saved),
            headers={"If-Match": str(saved["revision"])},
        ).json()
        assert cached["generation_id"] == first["generation_id"]
        saved = api.get(url).json()
        saved["garment_spec"]["design_intent"]["elements"][0]["dimensions_mm"]["depth"] = 120
        updated = api.put(url, json=saved, headers={"If-Match": str(saved["revision"])})
        assert updated.status_code == 200, updated.text
        current = api.get(url).json()
        assert current["latest_generation"] is None
        regenerated = api.post(
            "/api/v1/patterns/generate",
            json=engine_request(current),
            headers={"If-Match": str(current["revision"])},
        ).json()
        assert regenerated["status"] == "succeeded", regenerated
        assert regenerated["generation_id"] != first["generation_id"]
        old_panel = next(p for p in first["pattern"]["pieces"] if p["id"] == "advanced_0_drape_1")
        new_panel = next(p for p in regenerated["pattern"]["pieces"] if p["id"] == old_panel["id"])
        assert (
            contour_from_data(new_panel["seam_contour"]).bounding_box.height_mm
            == contour_from_data(old_panel["seam_contour"]).bounding_box.height_mm + 20
        )
        assert validate_pattern_assembly(regenerated["pattern"]) < 1
        pdf = api.post(f"/api/v1/patterns/{regenerated['generation_id']}/export/a4-pdf")
        assert pdf.status_code == 200, pdf.text
        assert "Каскадный волан" in " ".join(
            p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages
        )


def test_panel_gather_combination_has_a_cuttable_center_panel():
    panel = detail("panels", "panel", "straight", "full_garment", 3, "paired_equal_skirt_panels_v1")
    req = request([panel, gather()])
    req["input_hash"] = compute_input_hash(req)
    validate_engine_request(req)
    pattern = generate(req)
    operation = next(o for o in pattern["modeling_operations"] if o["module_id"] == "waist_gather_allowance_v1")
    assert operation["target_piece_ids"] == ["front_skirt_panel_1"]
    validate_pattern_assembly(pattern)


def test_panel_lining_preserves_topology_and_proportion_references():
    panel = detail("panels", "panel", "straight", "full_garment", 3, "paired_equal_skirt_panels_v1")
    pattern = generate(proportions(request([panel], [layers()[0]]), volume="relaxed"))
    assert len([p for p in pattern["pieces"] if p["id"].startswith("lining_")]) == 6
    validate_pattern_assembly(pattern)
    validate_export_coverage(pattern)

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import subprocess

import pytest
from pypdf import PdfReader

from tests.test_additional_details import request
from tests.test_advanced_design import elements, generate
from tests.test_module_assembly import yoke, gather, layers
from tests.test_stage12_garments import _project
from tests.test_stage11_workflow import client, engine_request
from kroika_contracts.hashing import compute_input_hash, canonical_generation_payload
from kroika_contracts.design_modules import matching_module
from tests.test_stage19_composites import _element, _dimensions
from kroika_pattern_engine import GeometryPatternEngine, render_pattern_pdf, render_pattern_svg
from kroika_pattern_engine.geometry import contour_from_data
from kroika_pattern_engine.validation import validate_pattern_assembly
from kroika_pattern_engine.back_closure import validate_back_closure_placements


def with_closure(req, typ, length=None, pitch=80):
    result = deepcopy(req)
    closure = result["garment_spec"]["parameters"]["closure"]
    closure["type"] = typ
    if length is not None:
        closure["length_mm"] = length
    if typ != "zipper":
        closure["loop_pitch_mm"] = pitch
    result["input_hash"] = compute_input_hash(result)
    return result


@pytest.mark.parametrize("garment", ["dress", "sundress", "top", "blouse"])
@pytest.mark.parametrize("typ", ["zipper", "buttons", "lacing"])
def test_back_choices_build_real_openings_and_details(garment, typ):
    req = request([]) if garment in {"dress", "sundress"} else engine_request(_project(garment))
    req["garment_spec"]["garment_type"] = garment
    pattern = generate(with_closure(req, typ))
    pieces = {p["id"]: p for p in pattern["pieces"]}
    op = next(op for op in pattern["composite_operations"] if op["kind"] == "closure")
    assert op["invariant_residual_mm"] < 1
    assert validate_pattern_assembly(pattern) < 1
    assert any(
        path["id"] == "back_bodice_back_opening" for path in pieces["back_bodice"]["internal_paths"]
    )
    assert any(n["match_id"] == "back_opening_stop" for p in pieces.values() for n in p["notches"])
    for pair in pattern["seam_pairs"]:
        if pair["id"].endswith("_closed_center_join"):
            assert (
                sum(n.get("match_id") == pair["id"] for p in pieces.values() for n in p["notches"])
                == 2
            )
    if typ != "zipper":
        assert {"back_closure_facing", "back_closure_loops"} <= pieces.keys()
        count = op["parameters_mm"]["loop_count"]
        assert pieces["back_closure_loops"]["cut_quantity"] == count * (2 if typ == "lacing" else 1)
        strip = contour_from_data(pieces["back_closure_loops"]["cutting_contour"]).bounding_box
        assert strip.width_mm == 60 and strip.height_mm == 20
        assert any(
            a["edge_type"] == "normal" and a["segment_id"] == "back_center"
            for a in pieces["back_bodice"]["edge_allowances"]
        )
    if typ == "lacing":
        assert {"back_lacing_underlap", "back_lacing_ribbon"} <= pieces.keys()
        ribbon = contour_from_data(pieces["back_lacing_ribbon"]["cutting_contour"]).bounding_box
        assert ribbon.height_mm == 30
        assert ribbon.width_mm == pytest.approx(op["parameters_mm"]["ribbon_length"])
        assert (
            contour_from_data(pieces["back_lacing_underlap"]["seam_contour"]).bounding_box.height_mm
            == 80
        )


@pytest.mark.parametrize("typ", ["buttons", "lacing"])
def test_back_opening_survives_yoke_layers_and_advanced_geometry(typ):
    for selected in ([yoke(), gather()], elements()):
        pattern = generate(with_closure(request(selected, layers()), typ))
        assert validate_pattern_assembly(pattern) < 1
        assert "back_closure_loops" in {p["id"] for p in pattern["pieces"]}
        assert any(
            path["id"].startswith("lining_back_skirt") and "back_opening" in path["id"]
            for p in pattern["pieces"]
            for path in p["internal_paths"]
        )


@pytest.mark.parametrize(
    "length,pitch,code",
    [
        (90, 80, "BACK_OPENING_LENGTH_INVALID"),
        (5000, 80, "BACK_OPENING_LENGTH_INVALID"),
        (850, 40, "BACK_LOOP_COUNT_INVALID"),
    ],
)
def test_invalid_back_geometry_has_explicit_error(length, pitch, code):
    result = GeometryPatternEngine().generate(with_closure(request([]), "lacing", length, pitch))
    assert result["status"] == "rejected"
    assert code in {issue["code"] for issue in result["validation_report"]["issues"]}


def test_missing_back_opening_length_has_explicit_error():
    req = with_closure(request([]), "lacing")
    req["garment_spec"]["parameters"]["closure"]["length_mm"] = None
    req["input_hash"] = compute_input_hash(req)
    result = GeometryPatternEngine().generate(req)
    assert result["status"] == "rejected"
    assert "BACK_OPENING_LENGTH_INVALID" in {
        issue["code"] for issue in result["validation_report"]["issues"]
    }


def test_save_reopen_change_back_choice_hash_and_export(tmp_path):
    project = _project("top")
    project["garment_spec"]["parameters"]["closure"] = {
        "type": "lacing",
        "location": "center_back",
        "length_mm": 350,
        "loop_pitch_mm": 80,
    }
    with client(tmp_path) as api:
        assert api.post("/api/v1/projects", json=project).status_code == 201
        url = f"/api/v1/projects/{project['project_id']}"
        saved = api.get(url).json()
        first_request = engine_request(saved)
        assert canonical_generation_payload(first_request)["hash_contract_version"] == "1.7.0"
        first = api.post(
            "/api/v1/patterns/generate",
            json=first_request,
            headers={"If-Match": str(saved["revision"])},
        ).json()
        assert first["status"] == "succeeded", first
        assert "back_lacing_ribbon" in {p["id"] for p in first["pattern"]["pieces"]}
        pdf = render_pattern_pdf(first["pattern"])
        text = " ".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
        assert "Лента для шнуровки" in text and "Метка 1:" in text
        assert "back_closure_loops" in render_pattern_svg(first["pattern"])
        saved = api.get(url).json()
        saved["garment_spec"]["parameters"]["closure"]["type"] = "buttons"
        changed = api.put(url, json=saved, headers={"If-Match": str(saved["revision"])})
        assert changed.status_code == 200, changed.text
        reopened = api.get(url).json()
        assert reopened["latest_generation"] is None
        second_request = engine_request(reopened)
        assert second_request["input_hash"] != first_request["input_hash"]
        second = api.post(
            "/api/v1/patterns/generate",
            json=second_request,
            headers={"If-Match": str(reopened["revision"])},
        ).json()
        assert second["status"] == "succeeded", second
        assert "back_closure_loops" in {p["id"] for p in second["pattern"]["pieces"]}
        assert "back_lacing_ribbon" not in {p["id"] for p in second["pattern"]["pieces"]}


def test_python_typescript_back_hash_agree():
    req = with_closure(request([]), "lacing")
    script = "import {stripTypeScriptTypes as strip} from 'node:module'; import fs from 'node:fs'; const gen=strip(fs.readFileSync('src/generation.ts','utf8'),{mode:'transform'}); const mod=strip(fs.readFileSync('src/designModules.ts','utf8'),{mode:'transform'}); const reg=JSON.parse(fs.readFileSync('../src/kroika_contracts/design_modules.json','utf8')); const moduleUrl='data:text/javascript;base64,'+Buffer.from(mod.replace(/import registry.*;/, 'const registry='+JSON.stringify(reg)+';')).toString('base64'); const code=gen.replace(\"'./designModules'\",JSON.stringify(moduleUrl)); const lib=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64')); process.stdout.write(lib.stableJson(lib.canonicalGenerationPayload(JSON.parse(process.argv[1]))));"
    text = subprocess.check_output(
        ["node", "--input-type=module", "-e", script, json.dumps(req)], text=True, cwd="frontend"
    )
    assert json.loads(text) == canonical_generation_payload(req)


def test_manual_center_move_cannot_leave_stale_closure_lines():
    pattern = generate(with_closure(request([]), "lacing"))
    validate_back_closure_placements(pattern)
    back = next(piece for piece in pattern["pieces"] if piece["id"] == "back_bodice")
    for segment in back["seam_contour"]["segments"]:
        for key in ("start", "end"):
            if segment[key][0] == 0:
                segment[key][0] = 2
    with pytest.raises(ValueError, match="центрального среза"):
        validate_back_closure_placements(pattern)


def test_confirmed_detected_lacing_gets_module_and_export_evidence():
    item = _element(
        "back_ai",
        "closure",
        "tie",
        "bodice_back",
        "separate_piece",
        1,
        "back_lacing_v1",
        _dimensions(),
    )
    req = with_closure(request([item]), "lacing")
    assert matching_module(item, req["garment_spec"], kind="element") == "back_lacing_v1"
    pattern = generate(req)
    evidence = next(
        m for m in pattern["design_coverage"]["modules"] if m["module_id"] == "back_lacing_v1"
    )
    assert "back_closure_loops" in evidence["evidence"]["piece_ids"]
    assert "back_lacing_ribbon" in evidence["evidence"]["piece_ids"]

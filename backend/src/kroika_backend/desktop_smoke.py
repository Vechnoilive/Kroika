"""Exercise the real packaged server and window using isolated diagnostic data."""

import base64
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import time
from urllib.request import ProxyHandler, Request, build_opener

from kroika_contracts.contract_io import available_schemas
from kroika_contracts.hashing import compute_input_hash
from kroika_contracts.resources import resource_root

from .config import Settings
from .desktop_preferences import atomic_json
from .desktop_version import VERSION


def check_bundle(frontend: Path, result_path: Path) -> int:
    from .desktop import DesktopServer, DesktopError
    report = {"ok": False, "version": VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    server = None
    upstream = None
    preferences = None
    temporary = tempfile.TemporaryDirectory(prefix="kroika-package-check-")
    try:
        root = Path(temporary.name)
        from .desktop_gemini_check import GeminiLoopback, configure_and_check, clear_key
        upstream = GeminiLoopback().__enter__()
        current = Settings(database_path=root / "data/kroika.db", image_storage_path=root / "data/images",
                           gemini_base_url=upstream.url)
        server = DesktopServer(current, frontend, 0, root)
        server.start()
        opener = build_opener(ProxyHandler({}))

        def request(path, method="GET", value=None, raw=False):
            data = json.dumps(value).encode() if value is not None else None
            with opener.open(Request(server.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"}), timeout=60) as response:
                content = response.read()
                return content if raw else json.loads(content)

        assert len(available_schemas()) >= 10
        assert b'id="root"' in request("/", raw=True)
        assert request("/api/v1/garments/catalog")
        project = json.loads((resource_root() / "examples/v1/example-dress-project.json").read_text(encoding="utf-8"))
        image = (resource_root() / "evaluation/stage10/images/synthetic-01.png").read_bytes()
        uploaded = request("/api/v1/images", "POST", {"file_name": "front.png", "media_type": "image/png",
                                                      "data_base64": base64.b64encode(image).decode()})
        project["image_refs"] = [uploaded["image_ref"]]
        project = request("/api/v1/projects", "POST", project)
        back = (resource_root() / "evaluation/stage10/images/synthetic-02.png").read_bytes()
        back_ref = request("/api/v1/images", "POST", {"file_name": "back.png", "media_type": "image/png",
                                                     "data_base64": base64.b64encode(back).decode()})["image_ref"]
        preferences = configure_and_check(server, root, upstream, [uploaded["image_ref"], back_ref], request)
        engine = json.loads((resource_root() / "examples/v1/example-engine-request.json").read_text(encoding="utf-8"))
        for field in ("project_id", "pattern_method", "body_measurements", "garment_spec", "fit_settings", "fabric_properties"):
            engine[field] = project[field]
        engine["input_hash"] = compute_input_hash(engine)
        generated = request("/api/v1/patterns/generate", "POST", engine)
        assert generated["status"] == "succeeded"
        generation = generated["generation_id"]
        for route, method, prefix in (("a4-pdf", "POST", b"%PDF"), ("scale-check-pdf", "POST", b"%PDF"),
                                      ("print.svg", "GET", b"<svg"), ("project-json", "GET", b"{")):
            assert prefix in request(f"/api/v1/patterns/{generation}/export/{route}", method, raw=True)[:200]
        request("/api/v1/measurement-profiles", "POST", project["body_measurements"])
        server.stop()
        restored = preferences.load(server.settings)
        server = DesktopServer(restored, frontend, 0, root)
        server.start()
        saved = request(f"/api/v1/projects/{project['project_id']}")
        assert saved["latest_generation"]["generation_id"] == generation
        assert request(f"/api/v1/images/{uploaded['image_ref']}", raw=True)
        assert len(request("/api/v1/measurement-profiles")["items"]) == 1
        if sys.platform == "win32":
            request("/api/v1/ai/providers/gemini/check", "POST")
        report.update(ok=True, checks=["schemas", "interface", "catalog", "images", "generation", "pdf", "svg", "json", "restart", "profiles",
                                      "gemini_native_key", "gemini_https", "gemini_front_back"])
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, DesktopError):
            report["error"] = str(error)
    finally:
        if server is not None:
            server.stop()
        try:
            if preferences is not None:
                clear_key(preferences)
        except Exception as error:
            report.update(ok=False, error_type=type(error).__name__)
        finally:
            if upstream is not None:
                upstream.__exit__()
            temporary.cleanup()
            atomic_json(result_path.resolve(), report)
    return 0 if report["ok"] else 1


def check_window(window, result_path: Path) -> None:
    report = {"ok": False, "version": VERSION}
    done = Event()
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if window.evaluate_js("Boolean(document.getElementById('root')?.children.length && window.pywebview?.api?.get_settings)"):
                break
            time.sleep(0.2)
        else:
            raise TimeoutError()

        def received(value):
            report["ok"] = bool(isinstance(value, dict) and value.get("ok")
                                and value.get("value", {}).get("app_version") == VERSION)
            done.set()

        window.evaluate_js("window.pywebview.api.get_settings()", received)
        if not done.wait(15):
            raise TimeoutError()
        if not report["ok"]:
            raise RuntimeError()
        report["checks"] = ["webview2", "react", "native_bridge"]
    except Exception as error:
        report["error_type"] = type(error).__name__
    finally:
        atomic_json(result_path.resolve(), report)
        window.destroy()

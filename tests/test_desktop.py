"""Desktop transport, persistence and process lifecycle regression checks."""

from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
               str(ROOT / "backend" / "src")]

from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.desktop import (  # noqa: E402
    DesktopError, DesktopServer, INSTANCE_HEADER, create_desktop_app, desktop_settings, run_desktop,
)
from kroika_contracts.hashing import compute_input_hash  # noqa: E402
from scripts import start_desktop  # noqa: E402


@pytest.fixture
def frontend(tmp_path):
    directory = tmp_path / "frontend"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text('<div id="root">Кройка</div>', encoding="utf-8")
    (directory / "assets" / "app.js").write_text("console.log('app');", encoding="utf-8")
    return directory


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "data" / "kroika.db",
                    image_storage_path=tmp_path / "data" / "images", log_level="CRITICAL")


def request(server, path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    opener = build_opener(ProxyHandler({}))
    return opener.open(Request(server.url + path, data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})}),
                       timeout=10)


def test_production_ui_and_every_api_share_an_origin(settings, frontend):
    app = create_desktop_app(settings, frontend, 18765, "test-instance")
    with TestClient(app, base_url="http://127.0.0.1:18765") as client:
        response = client.get("/")
        assert "Кройка" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers[INSTANCE_HEADER] == "test-instance"
        assert "javascript" in client.get("/assets/app.js").headers["content-type"]
        assert client.get("/health/ready").json()["database"] == "ok"
        assert client.get("/api/v1/garments/catalog").status_code == 200
        assert client.get("/api/v1/projects").json() == {"items": []}
        assert client.get("/api/missing").json() == {"detail": "Not Found"}
        assert client.get("/health/missing").status_code == 404
        assert client.get("/missing.js").status_code == 404
        assert client.get("/../data/kroika.db").status_code == 404
        assert client.get("/%2e%2e/data/kroika.db").status_code == 404


@pytest.mark.parametrize("headers", [
    {"Origin": "https://example.org"}, {"Origin": "null"},
    {"Host": "example.org:18765"}, {"Host": "127.0.0.1:5173"},
])
def test_desktop_rejects_external_origins_and_rebound_hosts(settings, frontend, headers):
    with TestClient(create_desktop_app(settings, frontend, 18765, "id"),
                    base_url="http://127.0.0.1:18765") as client:
        response = client.get("/api/v1/projects", headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "DESKTOP_ORIGIN_REJECTED"
        assert "access-control-allow-origin" not in response.headers
        assert client.get("/api/v1/projects", headers={"Origin": "http://127.0.0.1:18765"})


def test_missing_build_does_not_initialize_the_database(settings, tmp_path):
    with pytest.raises(DesktopError, match="сборка интерфейса"):
        create_desktop_app(settings, tmp_path / "missing", 18765, "id")
    assert not settings.database_path.exists()


def test_data_defaults_and_explicit_environment_are_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv("KROIKA_DATABASE_PATH", raising=False)
    monkeypatch.delenv("KROIKA_IMAGE_STORAGE_PATH", raising=False)
    defaults = desktop_settings(tmp_path)
    assert defaults.database_path == tmp_path / "kroika.db"
    assert defaults.image_storage_path == tmp_path / "images"
    monkeypatch.setenv("KROIKA_DATABASE_PATH", str(tmp_path / "existing.db"))
    monkeypatch.setenv("KROIKA_IMAGE_STORAGE_PATH", str(tmp_path / "existing-images"))
    assert desktop_settings(tmp_path / "other").database_path == tmp_path / "existing.db"
    assert desktop_settings(tmp_path / "other").image_storage_path == tmp_path / "existing-images"


def test_real_spawn_server_builds_exports_and_reopens_existing_projects(settings, frontend):
    server = DesktopServer(settings, frontend, port=0)
    server.start()
    try:
        project = json.loads((ROOT / "examples/v1/example-dress-project.json").read_text(
            encoding="utf-8",
        ))
        with request(server, "/api/v1/projects", "POST", project) as response:
            assert response.status == 201
        image = (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
        with request(server, "/api/v1/images", "POST", {
            "file_name": "front.png", "media_type": "image/png",
            "data_base64": base64.b64encode(image).decode(),
        }) as response:
            image_ref = json.load(response)["image_ref"]
        with request(server, f"/api/v1/images/{image_ref}") as response:
            stored_image = response.read()
        with Image.open(BytesIO(image)) as original, Image.open(BytesIO(stored_image)) as stored:
            assert stored.size == original.size
            assert stored.convert("RGB").tobytes() == original.convert("RGB").tobytes()
        engine_request = json.loads((ROOT / "examples/v1/example-engine-request.json").read_text(
            encoding="utf-8",
        ))
        engine_request["project_id"] = project["project_id"]
        for field in ("pattern_method", "body_measurements", "garment_spec", "fit_settings",
                      "fabric_properties"):
            engine_request[field] = project[field]
        engine_request["input_hash"] = compute_input_hash(engine_request)
        with request(server, "/api/v1/patterns/generate", "POST", engine_request) as response:
            generated = json.load(response)
        assert generated["status"] == "succeeded"
        generation_id = generated["generation_id"]
        for export, method, prefix in [("a4-pdf", "POST", b"%PDF"),
                                       ("print.svg", "GET", b"<svg")]:
            with request(server, f"/api/v1/patterns/{generation_id}/export/{export}",
                         method) as response:
                assert prefix in response.read()[:200]
                assert "attachment" in response.headers["content-disposition"]
        with request(server, f"/api/v1/patterns/{generation_id}/preview.svg") as response:
            assert b"<svg" in response.read()[:200]
        with request(server, "/api/v1/measurement-profiles", "POST",
                     project["body_measurements"]) as response:
            assert response.status == 201
        with request(server, f"/api/v1/projects/{project['project_id']}/history") as response:
            assert len(json.load(response)["items"]) >= 2
    finally:
        server.stop()
    assert not server.process.is_alive()
    assert server.process.exitcode == 0
    port = server.port
    reopened = DesktopServer(settings, frontend, port)
    reopened.start()
    try:
        with request(reopened, f"/api/v1/projects/{project['project_id']}") as response:
            saved = json.load(response)
        assert saved["latest_generation"]["generation_id"] == generation_id
        with request(reopened, "/api/v1/measurement-profiles") as response:
            assert len(json.load(response)["items"]) == 1
        with request(reopened, f"/api/v1/images/{image_ref}") as response:
            assert response.read() == stored_image
    finally:
        reopened.stop()
    assert not reopened.process.is_alive()


def test_occupied_port_never_opens_an_unrelated_server(settings, frontend):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = DesktopServer(settings, frontend, listener.getsockname()[1])
        with pytest.raises(DesktopError, match="порт"):
            server.start()
        assert server.process is None
        assert not settings.database_path.exists()


def test_startup_failure_and_timeout_leave_no_process(settings, frontend):
    settings.database_path.parent.mkdir(parents=True)
    settings.database_path.write_text("not a SQLite database")
    server = DesktopServer(settings, frontend, 0)
    with pytest.raises(DesktopError, match="DatabaseError"):
        server.start()
    assert not server.process.is_alive()
    server = DesktopServer(replace(settings, database_path=settings.database_path.with_name("ok.db")),
                           frontend, 0)
    with pytest.raises(DesktopError, match="отведённое"):
        server.start(timeout_seconds=0)
    assert not server.process.is_alive()


@pytest.mark.parametrize("fail", [False, True])
def test_window_has_persistent_storage_and_cleans_up_on_close_or_gui_failure(
    settings, frontend, tmp_path, monkeypatch, fail,
):
    calls = {}

    class ClosedEvent:
        def __iadd__(self, callback):
            self.callback = callback
            return self

    window = SimpleNamespace(events=SimpleNamespace(closed=ClosedEvent()), destroy=lambda: None)

    def create_window(title, url, **kwargs):
        calls.update(title=title, url=url, window_options=kwargs)
        return window

    def start(func, **kwargs):
        calls["start_options"] = kwargs
        if fail:
            raise RuntimeError("GUI unavailable")
        window.events.closed.callback()
        func()

    webview = SimpleNamespace(settings={}, create_window=create_window, start=start)
    monkeypatch.setitem(sys.modules, "webview", webview)
    if fail:
        with pytest.raises(DesktopError, match="открыть окно"):
            run_desktop(settings, frontend, tmp_path / "profile", port=0)
    else:
        run_desktop(settings, frontend, tmp_path / "profile", port=0)
    assert webview.settings["ALLOW_DOWNLOADS"] is True
    assert calls["start_options"]["private_mode"] is False
    assert calls["start_options"]["storage_path"] == str(tmp_path / "profile")
    assert calls["window_options"]["confirm_close"] is True
    with pytest.raises((URLError, ConnectionError, OSError)):
        build_opener(ProxyHandler({})).open(calls["url"] + "/health/ready", timeout=0.5)


def test_frontend_build_fingerprint_tracks_code_and_images(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    for name in ("index.html", "package.json", "package-lock.json", "vite.config.ts"):
        (frontend / name).write_text("original")
    (frontend / "src").mkdir()
    (frontend / "src" / "App.tsx").write_text("original")
    (frontend / "public").mkdir()
    (frontend / "public" / "atlas.svg").write_text("original")
    monkeypatch.setattr(start_desktop, "ROOT", tmp_path)
    original = start_desktop.frontend_fingerprint()
    (frontend / "src" / "App.tsx").write_text("changed")
    changed = start_desktop.frontend_fingerprint()
    assert original != changed
    (frontend / "public" / "atlas.svg").write_text("changed")
    assert changed != start_desktop.frontend_fingerprint()

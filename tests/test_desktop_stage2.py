"""Credential isolation, migration integrity and native action regression tests."""

from __future__ import annotations

import base64
from dataclasses import replace
import json
import sqlite3
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
               str(ROOT / "backend" / "src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.backup import BackupError, verify_backup  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.desktop import DesktopLock, DesktopError, DesktopServer, create_desktop_app  # noqa: E402
from kroika_backend.desktop_bridge import DesktopBridge  # noqa: E402
from kroika_backend.desktop_data import import_data, migrate_legacy  # noqa: E402
from kroika_backend.desktop_preferences import Preferences, PreferenceError, SystemVault  # noqa: E402
from kroika_backend.repository import SQLiteRepository  # noqa: E402
from kroika_contracts.hashing import compute_input_hash  # noqa: E402


class Vault:
    available = True

    def __init__(self):
        self.values = {}

    def get(self, service, key):
        return self.values.get((service, key))

    def set(self, service, key, value):
        self.values[service, key] = value

    def delete(self, service, key):
        self.values.pop((service, key), None)
        return True


def settings(tmp_path):
    return Settings(database_path=tmp_path / "data" / "kroika.db",
                    image_storage_path=tmp_path / "data" / "images", log_level="CRITICAL")


def payload(current, **changes):
    return {**Preferences._values(current), "key_action": "keep", "api_key": "",
            "remember": True, **changes}


def example(name="example-dress-project.json"):
    return json.loads((ROOT / "examples" / "v1" / name).read_text(encoding="utf-8"))


def test_saved_key_never_enters_settings_projects_or_response_and_can_be_removed(tmp_path):
    vault = Vault()
    store = Preferences(tmp_path / "home", vault)
    current = settings(tmp_path)
    candidate, document = store.prepare(payload(current, key_action="set", api_key="private-test-key",
                                                provider="gemini"), current)
    store.commit(candidate, document)
    assert "private-test-key" not in store.path.read_text(encoding="utf-8")
    assert "private-test-key" not in json.dumps(store.describe(candidate))
    assert Preferences(store.home, vault).load(current).gemini_api_key == "private-test-key"
    assert store.describe(candidate)["key_storage"] == "system"
    removed, document = store.prepare(payload(candidate, key_action="remove"), candidate)
    store.commit(removed, document)
    assert not vault.values
    # Removing a saved key also suppresses an old environment key on the next launch.
    assert Preferences(store.home, vault).load(replace(current, gemini_api_key="old-env-key")).gemini_api_key is None


def test_session_key_is_never_persisted_and_insecure_vault_does_not_get_used(tmp_path):
    vault = Vault()
    vault.available = False
    store = Preferences(tmp_path / "home", vault)
    current = settings(tmp_path)
    candidate, document = store.prepare(payload(current, key_action="set", api_key="session-key",
                                                remember=False), current)
    store.commit(candidate, document)
    assert not vault.values
    assert Preferences(store.home, vault).load(current).gemini_api_key is None
    assert candidate.gemini_api_key == "session-key"


def test_atomic_preferences_failure_keeps_old_credential_and_removes_uncommitted_key(tmp_path, monkeypatch):
    import kroika_backend.desktop_preferences as module
    vault = Vault()
    store = Preferences(tmp_path / "home", vault)
    current = settings(tmp_path)
    current, document = store.prepare(payload(current, key_action="set", api_key="first-key"), current)
    store.commit(current, document)
    before = store.path.read_bytes()
    candidate, document = store.prepare(payload(current, key_action="set", api_key="second-key"), current)
    monkeypatch.setattr(module, "atomic_json", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        store.commit(candidate, document)
    assert store.path.read_bytes() == before
    assert list(vault.values.values()) == ["first-key"]


@pytest.mark.parametrize("change", [{"timeout": -1}, {"timeout": float("nan")},
                                    {"max_output_tokens": 2}, {"attempts": 4},
                                    {"model": "unsupported", "thinking": "minimal"}])
def test_invalid_settings_never_write_credentials_or_configuration(tmp_path, change):
    vault = Vault()
    store = Preferences(tmp_path, vault)
    current = settings(tmp_path)
    with pytest.raises(PreferenceError):
        store.prepare(payload(current, key_action="set", api_key="do-not-store", **change), current)
    assert not vault.values
    assert not store.path.exists()


def test_malformed_preferences_fail_clearly(tmp_path):
    (tmp_path / "settings.json").write_text('{"version":1,"key_mode":"system"}')
    with pytest.raises(PreferenceError, match="повреждён"):
        Preferences(tmp_path, Vault())


@pytest.fixture
def frontend(tmp_path):
    root = tmp_path / "frontend"
    root.mkdir()
    (root / "index.html").write_text('<div id="root">app</div>')
    return root


def test_runtime_settings_are_token_protected_and_replace_only_future_provider_instances(tmp_path, frontend):
    app = create_desktop_app(settings(tmp_path), frontend, 18765, "instance", "private-token",
                             tmp_path / "backups")
    old_provider = app.state.provider_registry.get("gemini") if "gemini" in app.state.provider_registry.enabled_for_users else app.state.provider_registry.providers["gemini"]
    update = {**Preferences._values(settings(tmp_path)), "provider": "gemini", "model": "gemini-3.6-flash",
              "api_key": "never-return-this-key", "thinking": "minimal"}
    with TestClient(app, base_url="http://127.0.0.1:18765") as client:
        assert client.post("/_desktop/ai-settings", json=update).status_code == 403
        response = client.post("/_desktop/ai-settings", json=update,
                               headers={"X-Kroika-Desktop-Token": "private-token"})
        assert response.status_code == 200
        statuses = client.get("/api/v1/ai/providers").json()
        assert statuses["default_provider"] == "gemini"
        assert next(item for item in statuses["items"] if item["provider_id"] == "gemini")["configured"]
        assert "never-return-this-key" not in json.dumps(statuses)
        assert client.get("/health/ready").json()["ai_provider"] == "gemini"
        assert app.state.provider_registry.get("gemini") is not old_provider
        assert old_provider.api_key is None
        bad = {**update, "timeout": -1}
        assert client.post("/_desktop/ai-settings", json=bad,
                           headers={"X-Kroika-Desktop-Token": "private-token"}).status_code == 422
        assert app.state.settings.ai_timeout_seconds == update["timeout"]
    with TestClient(create_app(settings(tmp_path))) as web:
        assert web.post("/_desktop/ai-settings", json=update).status_code == 404


def seed_source(root):
    current = settings(root)
    project = example()
    image = (ROOT / "evaluation/stage10/images/synthetic-01.png").read_bytes()
    with TestClient(create_app(current)) as api:
        uploaded = api.post("/api/v1/images", json={"file_name": "front.png", "media_type": "image/png",
                                                   "data_base64": base64.b64encode(image).decode()}).json()
        project["image_refs"] = [uploaded["image_ref"]]
        project = api.post("/api/v1/projects", json=project).json()
        request = example("example-engine-request.json")
        for field in ("project_id", "pattern_method", "body_measurements", "garment_spec", "fit_settings", "fabric_properties"):
            request[field] = project[field]
        request["input_hash"] = compute_input_hash(request)
        generated = api.post("/api/v1/patterns/generate", json=request).json()
        assert generated["status"] == "succeeded"
        api.post("/api/v1/measurement-profiles", json=project["body_measurements"])
        record = api.post(f"/api/v1/patterns/{generated['generation_id']}/physical-validation", json={
            "gate": "expert", "outcome": "failed", "reviewer_name": "Проверяющий",
            "notes": "Нужна проверка на макете", "evidence_image_refs": project["image_refs"],
        })
        assert record.status_code == 201, record.text
    return current, project, generated


def test_import_retains_images_patterns_snapshots_profiles_and_history_and_is_repeatable(tmp_path):
    source, project, generated = seed_source(tmp_path / "source # данные")
    target = settings(tmp_path / "target")
    repository = SQLiteRepository(target.database_path)
    repository.initialize()
    source_before = source.database_path.read_bytes()
    report = import_data(source.database_path.parent, repository, target.image_storage_path,
                         tmp_path / "backups")
    assert report["projects"] == report["generations"] == report["measurement_profiles"] == 1
    assert report["generation_input_snapshots"] == 1
    assert report["physical_validation_records"] == 1
    verify_backup(Path(report["backup_dir"]))
    assert source.database_path.read_bytes() == source_before
    with TestClient(create_app(target)) as api:
        saved = api.get(f"/api/v1/projects/{project['project_id']}").json()
        assert saved["latest_generation"]["generation_id"] == generated["generation_id"]
        assert api.get(f"/api/v1/projects/{project['project_id']}/history").json()["items"]
        assert len(api.get("/api/v1/measurement-profiles").json()["items"]) == 1
        assert api.get(f"/api/v1/images/{project['image_refs'][0]}").status_code == 200
        assert api.post(f"/api/v1/patterns/{generated['generation_id']}/export/a4-pdf").content.startswith(b"%PDF")
    repeated = import_data(source.database_path.parent, repository, target.image_storage_path,
                           tmp_path / "backups")
    assert repeated["projects"] == repeated["generations"] == repeated["images"] == 0
    assert repeated["skipped"] > 0


def test_conflicting_ids_and_missing_photos_never_change_existing_data(tmp_path):
    source, project, _ = seed_source(tmp_path / "source")
    target = settings(tmp_path / "target")
    repository = SQLiteRepository(target.database_path)
    repository.initialize()
    different = example()
    different["name"] = "Не перезаписывать"
    repository.create_project(different)
    before = repository.get_project(different["project_id"])
    with pytest.raises(BackupError, match="одинаковыми ID"):
        import_data(source.database_path.parent, repository, target.image_storage_path, tmp_path / "backups")
    assert repository.get_project(different["project_id"]) == before
    assert not list(target.image_storage_path.iterdir())
    for image in source.image_storage_path.iterdir():
        image.unlink()
    with pytest.raises(BackupError, match="не хватает фотографий"):
        import_data(source.database_path.parent, repository, target.image_storage_path, tmp_path / "backups")
    assert repository.get_project(different["project_id"]) == before


def test_first_launch_migrates_legacy_data_and_window_profile_without_touching_source(tmp_path):
    root = tmp_path / "repo"
    source, project, _ = seed_source(root)
    old = root / ".local-state" / "desktop" / "webview"
    old.mkdir(parents=True)
    (old / "draft.json").write_text("draft")
    home = tmp_path / "user"
    migrate_legacy(root, home / "data", home)
    repository = SQLiteRepository(home / "data" / "kroika.db")
    assert repository.get_project(project["project_id"])
    assert (home / "webview" / "draft.json").read_text() == "draft"
    assert source.database_path.exists() and (old / "draft.json").exists()
    migrate_legacy(root, home / "data", home)


def test_native_window_guard_and_dialog_cancellation(tmp_path):
    server = SimpleNamespace(url="http://127.0.0.1:18765", settings=settings(tmp_path), control_token="token")
    bridge = DesktopBridge(server, Preferences(tmp_path / "home", Vault()),
                           SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1, SAVE=2, FOLDER=3)))
    bridge._window = SimpleNamespace(get_current_url=lambda: "https://evil.example/", create_file_dialog=lambda *_args, **_kwargs: None)
    assert bridge.get_settings()["ok"] is False
    assert bridge.choose_images()["ok"] is False
    bridge._window.get_current_url = lambda: server.url + "/"
    assert bridge.choose_images() == {"ok": True, "value": []}
    assert bridge.import_data() == {"ok": True, "value": {"cancelled": True}}
    assert bridge.save_export("../../data/kroika.db", "project-json")["ok"] is False
    assert bridge.open_folder("/etc")["ok"] is False


def test_native_real_server_updates_and_saves_exports_without_restart(tmp_path, frontend, monkeypatch):
    current, project, generated = seed_source(tmp_path / "source")
    server = DesktopServer(current, frontend, 0, tmp_path / "home")
    server.start()
    try:
        store = Preferences(tmp_path / "home", Vault())
        bridge = DesktopBridge(server, store, SimpleNamespace(FileDialog=SimpleNamespace(SAVE=2)))
        output = tmp_path / "pattern.pdf"
        bridge._window = SimpleNamespace(get_current_url=lambda: server.url + "/",
                                         create_file_dialog=lambda *_args, **_kwargs: (str(output),))
        pid = server.process.pid
        response = bridge.save_settings(payload(current, provider="gemini", key_action="set", api_key="test-secret"))
        assert response["ok"] is True and response["value"]["has_key"]
        assert "test-secret" not in json.dumps(response)
        assert server.process.pid == pid
        assert bridge.save_export(generated["generation_id"], "a4-pdf")["ok"] is True
        assert output.read_bytes().startswith(b"%PDF")
        assert not list(tmp_path.glob(".kroika-export-*"))
        before = current.database_path.read_bytes()
        bridge._window.create_file_dialog = lambda *_args, **_kwargs: (str(current.database_path),)
        assert not bridge.save_export(generated["generation_id"], "a4-pdf")["ok"]
        assert current.database_path.read_bytes() == before
        store.commit = lambda *_: (_ for _ in ()).throw(OSError("disk full"))
        failed = bridge.save_settings(payload(server.settings, model="other-flash", thinking="auto"))
        assert not failed["ok"]
        assert server.settings.gemini_model == current.gemini_model
        state = json.loads(bridge._request("/api/v1/ai/providers"))
        assert next(item for item in state["items"] if item["provider_id"] == "gemini")["model"] == current.gemini_model
    finally:
        server.stop()


def test_two_windows_cannot_share_the_same_desktop_profile(tmp_path):
    with DesktopLock(tmp_path / "desktop.lock"):
        with pytest.raises(DesktopError, match="уже открыта"):
            with DesktopLock(tmp_path / "desktop.lock"):
                pytest.fail("Second lock acquired")
    with DesktopLock(tmp_path / "desktop.lock"):
        pass


def test_import_rolls_back_all_rows_and_new_images_after_late_database_failure(tmp_path):
    source, project, _ = seed_source(tmp_path / "source")
    target = settings(tmp_path / "target")
    repository = SQLiteRepository(target.database_path)
    repository.initialize()
    with sqlite3.connect(target.database_path) as database:
        database.execute("CREATE TRIGGER reject_import BEFORE INSERT ON generations "
                         "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(BackupError):
        import_data(source.database_path.parent, repository, target.image_storage_path, tmp_path / "backups")
    assert repository.get_project(project["project_id"]) is None
    assert not repository.list_measurement_profiles()
    assert not list(target.image_storage_path.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows credential manager only")
def test_windows_real_system_vault_round_trip_does_not_use_plaintext_files():
    vault = SystemVault()
    assert vault.available
    service = f"Kroika-test-{uuid4()}"
    key_id = str(uuid4())
    second_id = str(uuid4())
    try:
        vault.set(service, key_id, "temporary-ci-key")
        assert vault.get(service, key_id) == "temporary-ci-key"
        vault.set(service, second_id, "rotated-ci-key")
        assert vault.get(service, key_id) == "temporary-ci-key"
        assert vault.get(service, second_id) == "rotated-ci-key"
        vault.delete(service, key_id)
        assert vault.get(service, second_id) == "rotated-ci-key"
    finally:
        vault.delete(service, key_id)
        vault.delete(service, second_id)
    assert vault.get(service, key_id) is None

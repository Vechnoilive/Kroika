"""Standalone resources, release checks and preservation across desktop versions."""

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "backend/src"), str(ROOT / "pattern-engine/src")]

from kroika_contracts.resources import resource_root  # noqa: E402
from kroika_backend.backup import verify_backup  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.desktop_bridge import DesktopBridge  # noqa: E402
from kroika_backend.desktop_preferences import Preferences, PreferenceError  # noqa: E402
from kroika_backend.desktop_smoke import check_bundle  # noqa: E402
from kroika_backend.desktop_upgrade import prepare_upgrade  # noqa: E402
from kroika_backend.desktop_version import VERSION, RELEASES_URL  # noqa: E402
from scripts.build_desktop import checksums, icon, version_resource  # noqa: E402
from tests.test_desktop_stage2 import seed_source, Vault  # noqa: E402


def test_resources_are_independent_of_cwd_and_executable_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resource_root() == ROOT
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "runtime"), raising=False)
    assert resource_root() == tmp_path / "runtime/kroika_resources"


def test_upgrade_retains_real_patterns_images_history_and_preferences(tmp_path):
    current, _, _ = seed_source(tmp_path / "old data #")
    home = tmp_path / "home"
    home.mkdir()
    (home / "installed-version.json").write_text('{"version":"0.2.0"}')
    preferences = home / "settings.json"
    preferences.write_text('{"keep":"preferences"}')
    before = current.database_path.read_bytes()
    prepare_upgrade(current, home)
    backup = next((home / "backups").iterdir())
    verify_backup(backup)
    assert current.database_path.read_bytes() == before
    assert preferences.read_text() == '{"keep":"preferences"}'
    assert list((backup / "images").iterdir())
    import sqlite3
    with sqlite3.connect(backup / "kroika.db") as database:
        assert database.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM project_revisions").fetchone()[0] >= 2
        assert database.execute("SELECT COUNT(*) FROM physical_validation_records").fetchone()[0] == 1
    assert json.loads((home / "installed-version.json").read_text())["version"] == VERSION
    prepare_upgrade(current, home)
    assert len(list((home / "backups").iterdir())) == 1


def test_backup_failure_never_advances_version_or_changes_data(tmp_path, monkeypatch):
    import kroika_backend.desktop_upgrade as module
    current, _, _ = seed_source(tmp_path / "old")
    home = tmp_path / "home"
    home.mkdir()
    marker = home / "installed-version.json"
    marker.write_text('{"version":"0.2.0"}')
    before = current.database_path.read_bytes()
    monkeypatch.setattr(module, "create_backup", lambda *_: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        prepare_upgrade(current, home)
    assert json.loads(marker.read_text())["version"] == "0.2.0"
    assert current.database_path.read_bytes() == before


def test_release_check_is_guarded_and_sends_no_ai_key(tmp_path, monkeypatch):
    import kroika_backend.desktop_updates as module
    requests = []

    def response(request, timeout):
        requests.append((request, timeout))
        return BytesIO(json.dumps({"tag_name": "desktop-v0.4.0", "assets": [
            {"name": "Kroika-0.4.0-windows-x64-setup.exe"}, {"name": "SHA256SUMS.txt"}],
            "html_url": "https://malicious.example"}).encode())

    monkeypatch.setattr(module, "urlopen", response)
    preferences = Preferences(tmp_path, Vault())
    server = SimpleNamespace(url="http://127.0.0.1:18765", settings=replace(Settings(database_path=tmp_path / "data.db"), gemini_api_key="private-key"))
    bridge = DesktopBridge(server, preferences, None)
    bridge._window = SimpleNamespace(get_current_url=lambda: server.url)
    result = bridge.check_updates()
    assert result["ok"] and result["value"]["available"]
    assert result["value"]["release_url"] == RELEASES_URL
    request, timeout = requests[0]
    assert timeout == 12 and request.full_url == "https://api.github.com/repos/Vechnoilive/Kroika/releases/latest"
    assert "private-key" not in str(request.headers)
    bridge._window = SimpleNamespace(get_current_url=lambda: "https://example.org")
    assert not bridge.check_updates()["ok"]
    assert len(requests) == 1


@pytest.mark.parametrize("release", [
    {"tag_name": "desktop-v0.4.0", "assets": []},
    {"tag_name": "desktop-v0.2.0", "assets": []},
    {"tag_name": "desktop-v0.4.0", "assets": [{"name": "SHA256SUMS.txt"}]},
])
def test_older_or_unfinished_release_never_prompts_installation(monkeypatch, release):
    import kroika_backend.desktop_updates as module
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: BytesIO(json.dumps(release).encode()))
    assert module.check_updates()["available"] is False


@pytest.mark.parametrize("release", [{"tag_name": "v1.0.0"}, {"tag_name": "desktop-v0.4.0", "prerelease": True},
                                     {"tag_name": "desktop-v0.4.0", "assets": None}])
def test_invalid_release_produces_friendly_error(monkeypatch, release):
    import kroika_backend.desktop_updates as module
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: BytesIO(json.dumps(release).encode()))
    with pytest.raises(PreferenceError):
        module.check_updates()


def test_network_failure_and_absent_release(monkeypatch):
    import kroika_backend.desktop_updates as module
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("private-url")))
    with pytest.raises(PreferenceError, match="Проверьте интернет"):
        module.check_updates()
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPError("url", 404, "missing", {}, None)))
    assert module.check_updates()["latest_version"] is None


def test_real_diagnostic_builds_exports_and_reopens_data_in_isolation(tmp_path):
    result = tmp_path / "result.json"
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root">Кройка</div>', encoding="utf-8")
    assert check_bundle(frontend, result) == 0
    report = json.loads(result.read_text())
    assert report["ok"] and "restart" in report["checks"] and "pdf" in report["checks"]
    assert not (tmp_path / "data").exists()


def test_icon_version_and_artifact_checksums(tmp_path):
    from PIL import Image
    image = tmp_path / "kroika.ico"
    icon(image)
    with Image.open(image) as opened:
        assert opened.size == (256, 256)
    version_resource(tmp_path / "version.txt")
    assert VERSION in (tmp_path / "version.txt").read_text(encoding="utf-8")
    checksums([image], tmp_path / "SHA256SUMS.txt")
    import hashlib
    assert (tmp_path / "SHA256SUMS.txt").read_text().strip() == f"{hashlib.sha256(image.read_bytes()).hexdigest()}  kroika.ico"

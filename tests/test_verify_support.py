"""Regression checks for cross-platform stage verifier commands."""

from pathlib import Path

from scripts import verify_support


ROOT = Path(__file__).resolve().parents[1]


def test_windows_npm_cmd_shim_is_resolved_before_subprocess(monkeypatch) -> None:
    windows_path = r"C:\Program Files\nodejs\npm.cmd"
    search_path = r"C:\Program Files\nodejs"

    monkeypatch.setattr(verify_support, "_NPM_EXECUTABLE_NAME", "npm.cmd")
    monkeypatch.setattr(
        verify_support.shutil,
        "which",
        lambda executable, *, path: windows_path
        if executable == "npm.cmd" and path == search_path
        else None,
    )

    assert verify_support.resolve_command(
        ["npm", "run", "test:stage27"], {"PATH": search_path}
    ) == [windows_path, "run", "test:stage27"]


def test_non_npm_command_is_unchanged() -> None:
    command = ["python", "-m", "pytest"]
    assert verify_support.resolve_command(command) == command


def test_local_bootstrap_upgrades_pip_before_installing_pinned_tools() -> None:
    launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")

    upgrade = '[str(python), "-m", "pip", "install", "--upgrade", "pip"]'
    requirements = '[str(python), "-m", "pip", "install", "-r"'
    assert upgrade in launcher
    assert launcher.index(upgrade) < launcher.index(requirements)
    assert 'digest.update(BOOTSTRAP_VERSION.encode("ascii"))' in launcher

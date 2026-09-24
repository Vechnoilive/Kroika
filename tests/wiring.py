"""Assertions shared by historical stage tests for moving project wiring."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib


def current_stage(root: Path) -> int:
    stages = {
        int(path.stem.removeprefix("verify_stage"))
        for path in (root / "scripts").glob("verify_stage*.py")
    }
    if not stages:
        raise AssertionError("No stage verification scripts found")
    return max(stages)


def assert_current_only_workflow(root: Path, workflow: str) -> int:
    """Require the fast CI workflow to call exactly the newest stage gate."""
    stage = current_stage(root)
    commands = re.findall(r"python scripts/verify_stage(\d+)\.py", workflow)
    assert commands == [str(stage)]
    assert "python scripts/verify_all.py" not in workflow
    return stage


def assert_current_versions(root: Path, minimum_stage: int) -> str:
    """Keep package versions aligned while allowing later stages to advance them."""
    frontend_version = json.loads(
        (root / "frontend" / "package.json").read_text(encoding="utf-8")
    )["version"]
    backend_version = tomllib.loads(
        (root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    assert frontend_version == backend_version
    assert tuple(map(int, frontend_version.split("."))) >= (0, minimum_stage, 0)
    return frontend_version

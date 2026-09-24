#!/usr/bin/env python3
"""Run only the manual geometry editor checks introduced at stage 27."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
venv_bin = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
if venv_bin.exists():
    environment["PATH"] = os.pathsep.join([str(venv_bin), environment.get("PATH", "")])
environment["PYTHONPATH"] = os.pathsep.join([
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
    environment.get("PYTHONPATH", ""),
])

commands = [
    ([sys.executable, "-m", "pytest", "-q", "tests/test_stage27_manual_geometry.py"], ROOT),
    ([sys.executable, "-m", "ruff", "check",
      "pattern-engine/src/kroika_pattern_engine/manual_edit.py",
      "pattern-engine/src/kroika_pattern_engine/__init__.py",
      "backend/src/kroika_backend/app.py",
      "backend/src/kroika_backend/manual_editing.py",
      "backend/src/kroika_backend/models.py",
      "backend/src/kroika_backend/repository.py",
      "tests/test_stage27_manual_geometry.py",
      "scripts/start_local.py",
      "scripts/verify_all.py",
      "scripts/verify_stage27.py"], ROOT),
    (["npm", "run", "test:stage27"], ROOT / "frontend"),
    (["npm", "run", "typecheck"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
]

for command, cwd in commands:
    print(f"\n=== {' '.join(command)} ===", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 27 пройден: ручные правки создают новую генерацию, контуры, "
    "припуски и парные швы проверены, TypeScript и сборка прошли."
)

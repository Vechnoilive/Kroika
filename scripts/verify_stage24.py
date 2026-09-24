#!/usr/bin/env python3
"""Run only the backend and UI checks introduced at stage 24."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from verify_support import resolve_command


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
    ([sys.executable, "-m", "pytest", "-q", "tests/test_stage24_project_safety.py"], ROOT),
    ([sys.executable, "-m", "ruff", "check",
      "backend/src/kroika_backend/app.py",
      "tests/test_stage24_project_safety.py",
      "scripts/start_local.py",
      "scripts/verify_all.py",
      "scripts/verify_stage24.py"], ROOT),
    (["npm", "run", "test:stage24"], ROOT / "frontend"),
    (["npm", "run", "typecheck"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
]

for command, cwd in commands:
    print(f"\n=== {' '.join(command)} ===", flush=True)
    completed = subprocess.run(
        resolve_command(command, environment), cwd=cwd, env=environment, check=False
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 24 пройден: автосохранение и аварийные черновики, защита переходов, "
    "поиск и управление проектами, TypeScript и production-сборка проверены."
)

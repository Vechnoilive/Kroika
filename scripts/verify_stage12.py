#!/usr/bin/env python3
"""Run only checks introduced for stage 12."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
venv_bin = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
if venv_bin.exists():
    environment["PATH"] = os.pathsep.join([
        str(venv_bin), environment.get("PATH", ""),
    ])
environment["PYTHONPATH"] = os.pathsep.join([
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
    environment.get("PYTHONPATH", ""),
])

commands = [
    ([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests/test_stage12_garments.py")], ROOT),
    (["npm", "run", "test:stage12"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    (["npm", "run", "e2e:stage12"], ROOT / "frontend"),
]

for command, cwd in commands:
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 12 проверен: пять новых изделий, их отдельные статусы, интерфейс и "
    "полный сценарий юбки прошли; физическая приёмка остаётся pending."
)

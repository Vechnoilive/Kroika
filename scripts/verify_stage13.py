#!/usr/bin/env python3
"""Run only checks introduced for stage 13."""

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
    str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"), environment.get("PYTHONPATH", ""),
])

commands = [
    ([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests/test_stage13_jacket.py")], ROOT),
    (["npm", "run", "test:stage13"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    (["npm", "run", "e2e:stage13"], ROOT / "frontend"),
]

for command, cwd in commands:
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 13 проверен: отдельная методика лёгкого жакета, комплект деталей, "
    "парные интерфейсы и пользовательский сценарий прошли; три макета и "
    "экспертная приёмка остаются pending."
)

#!/usr/bin/env python3
"""Run only checks introduced for stage 14."""

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
    str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"), environment.get("PYTHONPATH", ""),
])

commands = [
    ([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests/test_stage14_lower_garments.py")], ROOT),
    (["npm", "run", "test:stage14"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    (["npm", "run", "e2e:stage14"], ROOT / "frontend"),
]

for command, cwd in commands:
    completed = subprocess.run(
        resolve_command(command, environment), cwd=cwd, env=environment, check=False
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 14 проверен: независимая брючная основа, прямые брюки, шорты, "
    "парные швы и пользовательский сценарий прошли; посадка, свобода движения "
    "и комбинезон остаются заблокированы физическим gate."
)

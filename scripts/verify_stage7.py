#!/usr/bin/env python3
"""Run the stage-7 base-block formula, geometry and API gates."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
paths = [
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
]
environment["PYTHONPATH"] = os.pathsep.join(paths + [environment.get("PYTHONPATH", "")])
commands = [
    [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_stage7_blocks.py")],
    [sys.executable, str(ROOT / "scripts" / "smoke_stage7.py")],
]
for command in commands:
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)
print("Этап 7 проверен: формулы, четыре базовых блока, рукав и API gate прошли.")

#!/usr/bin/env python3
"""Run the stage-8 garment matrix, SVG and HTTP gates."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment["PYTHONPATH"] = os.pathsep.join([
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
    environment.get("PYTHONPATH", ""),
])
commands = [
    [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_stage8_generator.py")],
    [sys.executable, str(ROOT / "scripts" / "smoke_stage8.py")],
]
for command in commands:
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)
print("Этап 8 проверен: матрица вариантов, детали, пары швов и SVG прошли.")

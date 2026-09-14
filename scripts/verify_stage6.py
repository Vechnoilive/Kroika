#!/usr/bin/env python3
"""Run the deterministic geometry and property-based gate for stage 6."""

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
paths = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src")]
environment["PYTHONPATH"] = os.pathsep.join(paths + [environment.get("PYTHONPATH", "")])
commands = [
    [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_stage6_geometry.py")],
    [sys.executable, str(ROOT / "scripts" / "smoke_stage6.py")],
]
for command in commands:
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)
print("Этап 6 проверен: геометрия, property-based тесты и API smoke-test прошли.")

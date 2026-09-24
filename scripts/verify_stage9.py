#!/usr/bin/env python3
"""Run only the automated checks introduced for stage 9."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from verify_support import resolve_command

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment["PYTHONPATH"] = os.pathsep.join([
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
    environment.get("PYTHONPATH", ""),
])
commands = [
    ([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_stage9_printing.py")], ROOT),
    (["npm", "test", "--", "src/PrintingResult.test.tsx"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    ([sys.executable, str(ROOT / "scripts" / "smoke_stage9.py")], ROOT),
]
for command, cwd in commands:
    completed = subprocess.run(
        resolve_command(command, environment), cwd=cwd, env=environment, check=False
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)
print("Этап 9 проверен: припуски, SVG, PDF A4 1:1, интерфейс и HTTP smoke-test прошли.")

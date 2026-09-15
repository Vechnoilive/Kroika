#!/usr/bin/env python3
"""Run only checks introduced for stage 10."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment["PYTHONPATH"] = os.pathsep.join([
    str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"), environment.get("PYTHONPATH", ""),
])
commands = [
    ([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests/test_stage10_vision.py")], ROOT),
    (["npm", "test", "--", "src/VisionAnalyzer.test.tsx"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    ([sys.executable, str(ROOT / "scripts/smoke_stage10.py")], ROOT),
]
for command, cwd in commands:
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)
print("Этап 10 проверен: Qwen/Gemini, строгий ответ, 50 примеров, UI и fallback прошли.")

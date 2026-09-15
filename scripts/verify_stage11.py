#!/usr/bin/env python3
"""Run only checks introduced for stage 11."""

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
    ([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests/test_stage11_workflow.py")], ROOT),
    (["npm", "run", "test:stage11"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    (["npm", "run", "e2e"], ROOT / "frontend"),
]

for command, cwd in commands:
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

if environment.get("QWEN_API_KEY") and environment.get("QWEN_BASE_URL"):
    completed = subprocess.run(
        ["npm", "run", "e2e:qwen"], cwd=ROOT / "frontend", env=environment, check=False,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)
    print("Live E2E Qwen пройден с настроенным серверным ключом.")
else:
    print("Live E2E Qwen подготовлен, но пропущен: QWEN_API_KEY/QWEN_BASE_URL не заданы.")

print("Этап 11 проверен: связанный mock-сценарий, редакторы, история и SVG-слои прошли.")

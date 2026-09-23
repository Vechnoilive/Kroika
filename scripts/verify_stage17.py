#!/usr/bin/env python3
"""Run only the contract and UI checks introduced at stage 17."""

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
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
    environment.get("PYTHONPATH", ""),
])

commands = [
    ([sys.executable, "-m", "pytest", "-q", "tests/test_stage17_design_review.py"], ROOT),
    ([sys.executable, "-m", "ruff", "check",
      "src/kroika_contracts/semantic.py",
      "backend/src/kroika_backend/app.py",
      "tests/test_stage17_design_review.py",
      "scripts/start_local.py",
      "scripts/verify_all.py",
      "scripts/verify_stage17.py"], ROOT),
    (["npm", "run", "test:stage17"], ROOT / "frontend"),
    (["npm", "run", "typecheck"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
]

for command, cwd in commands:
    print(f"\n=== {' '.join(command)} ===", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 17 пройден: ручная проверка деталей, слоёв, пропорций и ответов, "
    "fail-closed размеры, TypeScript и production-сборка проверены."
)

#!/usr/bin/env python3
"""Run only the contract and UI checks introduced at stage 16."""

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
    str(ROOT / "src"),
    str(ROOT / "pattern-engine" / "src"),
    str(ROOT / "backend" / "src"),
    environment.get("PYTHONPATH", ""),
])

commands = [
    ([sys.executable, "-m", "pytest", "-q", "tests/test_stage16_design_intent.py"], ROOT),
    ([sys.executable, "-m", "ruff", "check",
      "src/kroika_contracts/semantic.py",
      "backend/src/kroika_backend/app.py",
      "backend/src/kroika_backend/vision_prompt.py",
      "backend/src/kroika_backend/mock_provider.py",
      "tests/test_stage16_design_intent.py",
      "scripts/start_local.py",
      "scripts/verify_all.py",
      "scripts/verify_stage16.py"], ROOT),
    (["npm", "run", "test:stage16"], ROOT / "frontend"),
    (["npm", "run", "typecheck"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
]

for command, cwd in commands:
    print(f"\n=== {' '.join(command)} ===", flush=True)
    completed = subprocess.run(
        resolve_command(command, environment), cwd=cwd, env=environment, check=False
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Этап 16 пройден: расширенный разбор деталей, fail-closed конструктивный план, "
    "возврат по завершённым шагам, TypeScript и production-сборка проверены."
)

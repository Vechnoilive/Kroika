#!/usr/bin/env python3
"""Run the automated system validation and release gate introduced at stage 15."""

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

python_sources = [
    "src", "backend/src", "pattern-engine/src",
    "scripts/backup_local_data.py", "scripts/restore_local_data.py",
]
commands = [
    ([sys.executable, "-m", "pytest", "-q", "tests/test_stage15_release.py"], ROOT),
    ([sys.executable, "-m", "ruff", "check", "src", "backend/src", "pattern-engine/src", "scripts", "tests"], ROOT),
    ([sys.executable, "-m", "mypy", *python_sources], ROOT),
    ([sys.executable, "-m", "bandit", "-q", "-ll", "-r", "src", "backend/src", "pattern-engine/src"], ROOT),
    ([sys.executable, "-m", "pip", "check"], ROOT),
    ([sys.executable, "-m", "pip_audit", "-r", "requirements-runtime.txt", "--progress-spinner", "off"], ROOT),
    (["npm", "run", "test:stage15"], ROOT / "frontend"),
    (["npm", "run", "typecheck"], ROOT / "frontend"),
    (["npm", "run", "build"], ROOT / "frontend"),
    (["npm", "run", "audit:dependencies"], ROOT / "frontend"),
    (["npm", "run", "e2e"], ROOT / "frontend"),
]

for command, cwd in commands:
    print(f"\n=== {' '.join(command)} ===", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

print(
    "Автоматический gate этапа 15 пройден: release-policy, privacy, backup/recovery, "
    "performance, accessibility, security, зависимости, сборка и mock E2E проверены. "
    "Production gate остаётся BLOCKED до реальных paper/expert/toile записей."
)

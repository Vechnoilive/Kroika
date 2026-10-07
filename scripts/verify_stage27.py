#!/usr/bin/env python3
"""Run the current geometry editor and design-module workflow checks."""

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
    ([sys.executable, "-m", "pytest", "-q",
      "tests/test_stage27_manual_geometry.py",
      "tests/test_design_module_workflow.py",
      "tests/test_design_modules_step1.py",
      "tests/test_design_modules_step2.py",
      "tests/test_design_modules_step3.py",
      "tests/test_design_modules_step4.py",
      "tests/test_design_modules_step4_workflow.py",
      "tests/test_additional_details.py",
      "tests/test_advanced_design.py",
      "tests/test_module_assembly.py",
      "tests/test_back_closure.py",
      "tests/test_verify_support.py"], ROOT),
    ([sys.executable, "-m", "pytest", "-q",
      "tests/test_ai_resilience.py", "tests/test_gemini_modes.py", "tests/test_stage10_vision.py",
      "tests/test_stage23_ai_workspace.py"], ROOT),
    ([sys.executable, "-m", "ruff", "check",
      "pattern-engine/src/kroika_pattern_engine/manual_edit.py",
      "pattern-engine/src/kroika_pattern_engine/back_closure.py",
      "pattern-engine/src/kroika_pattern_engine/details.py",
      "pattern-engine/src/kroika_pattern_engine/advanced.py",
      "pattern-engine/src/kroika_pattern_engine/validation.py",
      "pattern-engine/src/kroika_pattern_engine/coverage.py",
      "pattern-engine/src/kroika_pattern_engine/composites.py",
      "pattern-engine/src/kroika_pattern_engine/modeling.py",
      "pattern-engine/src/kroika_pattern_engine/fullness.py",
      "pattern-engine/src/kroika_pattern_engine/structural.py",
      "pattern-engine/src/kroika_pattern_engine/layers.py",
      "pattern-engine/src/kroika_pattern_engine/topology.py",
      "pattern-engine/src/kroika_pattern_engine/svg.py",
      "pattern-engine/src/kroika_pattern_engine/pdf.py",
      "pattern-engine/src/kroika_pattern_engine/print_layout.py",
      "pattern-engine/src/kroika_pattern_engine/scaffold.py",
      "pattern-engine/src/kroika_pattern_engine/__init__.py",
      "backend/src/kroika_backend/app.py",
      "backend/src/kroika_backend/config.py",
      "backend/src/kroika_backend/vision_providers.py",
      "backend/src/kroika_backend/logging_config.py",
      "backend/src/kroika_backend/errors.py",
      "tests/test_ai_resilience.py",
      "tests/test_gemini_modes.py",
      "scripts/check_gemini.py",
      "backend/src/kroika_backend/manual_editing.py",
      "backend/src/kroika_backend/models.py",
      "backend/src/kroika_backend/repository.py",
      "src/kroika_contracts/design_modules.py",
      "src/kroika_contracts/hashing.py",
      "src/kroika_contracts/semantic.py",
      "tests/test_stage27_manual_geometry.py",
      "tests/test_design_module_workflow.py",
      "tests/test_design_modules_step1.py",
      "tests/test_design_modules_step2.py",
      "tests/test_design_modules_step3.py",
      "tests/test_design_modules_step4.py",
      "tests/test_design_modules_step4_workflow.py",
      "tests/test_additional_details.py",
      "tests/test_advanced_design.py",
      "tests/test_module_assembly.py",
      "tests/test_back_closure.py",
      "tests/test_verify_support.py",
      "scripts/start_local.py",
      "scripts/verify_all.py",
      "scripts/verify_support.py",
      "scripts/verify_stage27.py"], ROOT),
    (["npm", "run", "test:stage27"], ROOT / "frontend"),
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
    "Этап 27 пройден: ручные правки создают новую генерацию, контуры, "
    "припуски и парные швы проверены, TypeScript и сборка прошли."
)

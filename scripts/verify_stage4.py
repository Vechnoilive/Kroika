#!/usr/bin/env python3
"""Run all stage-4 backend, frontend and smoke gates."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        print("Для проверки frontend нужен Node.js 24 с npm.", file=sys.stderr)
        return 2
    run([sys.executable, "-m", "pytest", "-q", "tests/test_stage4_backend.py"])
    run([npm, "run", "test"], ROOT / "frontend")
    run([npm, "run", "build"], ROOT / "frontend")
    run([sys.executable, "scripts/smoke_stage4.py"])
    print("\nЭтап 4 проверен: backend, frontend production build и smoke-test прошли.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

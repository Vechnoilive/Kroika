#!/usr/bin/env python3
"""Run every verification gate implemented in the repository."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
checks = [
    ROOT / 'scripts' / 'verify_stage2.py',
    ROOT / 'scripts' / 'verify_stage3.py',
    ROOT / 'scripts' / 'verify_stage4.py',
    ROOT / 'scripts' / 'verify_stage5.py',
    ROOT / 'scripts' / 'verify_stage6.py',
    ROOT / 'scripts' / 'verify_stage7.py',
    ROOT / 'scripts' / 'verify_stage8.py',
]

for check in checks:
    print(f'\n=== {check.name} ===', flush=True)
    completed = subprocess.run([sys.executable, str(check)], cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)

print('\nВсе доступные проверки Kroika прошли.', flush=True)

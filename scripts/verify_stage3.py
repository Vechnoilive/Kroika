#!/usr/bin/env python3
"""Run the stage-3 schema, semantic, migration and port contract gate."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

try:
    import jsonschema  # noqa: F401
    import openapi_spec_validator  # noqa: F401
except ImportError as exc:
    raise SystemExit(
        'Не найдена зависимость проверки. Создайте окружение и выполните:\n'
        '  python3 -m pip install -r requirements-stage3.txt\n'
        f'Исходная ошибка: {exc}'
    ) from exc


suite = unittest.defaultTestLoader.discover(
    str(ROOT / 'tests'), pattern='test_stage3_*.py', top_level_dir=str(ROOT)
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

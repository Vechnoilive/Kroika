#!/usr/bin/env python3
"""Verify stage-2 mathematical worksheets; this is NOT a pattern generator.

Standard library only. Fixed expected values are read, never rewritten.
Run from any directory with Python 3.12+: python scripts/verify_stage2.py
"""

import ast
import copy
import hashlib
import json
import math
import operator
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


REGISTRY = read_json('references/stage2/formula-registry.json')
CASES = read_json('references/stage2/control-examples.json')['cases']
CONSTANTS = REGISTRY['constants']
MEASUREMENT_KEYS = set(REGISTRY['input_units']) - set(CONSTANTS)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Expected a numeric value, not a string or boolean')
    if not math.isfinite(value):
        raise ValueError('Non-finite number')
    return float(value)


def expression_value(expression, values):
    """Evaluate the small arithmetic notation used by the registry without eval."""
    binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Pow: operator.pow}
    functions = {'radians': math.radians, 'tan': math.tan, 'sqrt': math.sqrt, 'min': min}

    def visit(node):
        if isinstance(node, ast.Constant):
            return number(node.value)
        if isinstance(node, ast.Name) and node.id in values:
            return number(values[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and right != 2:
                raise ValueError('Only squaring is used in this reference notation')
            return number(binary[type(node.op)](left, right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in functions or node.keywords:
                raise ValueError('Unsupported function')
            args = [visit(arg) for arg in node.args]
            if (node.func.id == 'min' and len(args) != 2) or (node.func.id != 'min' and len(args) != 1):
                raise ValueError('Invalid function arity')
            return number(functions[node.func.id](*args))
        if isinstance(node, ast.IfExp):
            condition = node.test
            if not (isinstance(condition, ast.Compare) and len(condition.ops) == 1
                    and isinstance(condition.ops[0], ast.Lt)):
                raise ValueError('Unsupported condition')
            less = visit(condition.left) < visit(condition.comparators[0])
            return visit(node.body if less else node.orelse)
        raise ValueError('Unsupported expression or missing variable')

    return number(visit(ast.parse(expression, mode='eval').body))


def calculate(inputs, units='mm'):
    if units != 'mm':
        raise ValueError('Reference input must already be normalized to mm')
    if set(inputs) != MEASUREMENT_KEYS:
        raise ValueError('Missing or unknown input; no inferred measurements')
    values = {key: number(value) for key, value in inputs.items()}
    for key, value in values.items():
        if REGISTRY['input_units'][key] == 'mm' and value <= 0:
            raise ValueError('Measured lengths must be positive')
    for key in ('shoulder_slope_deg', 'hip_inclination_deg'):
        if not 0 <= values[key] <= 40:
            raise ValueError('Outside the computational angle domain [0, 40] deg')
    for arc, circumference in [('back_bust_arc', 'bust'), ('back_waist_arc', 'waist'),
                               ('back_hip_arc', 'hips')]:
        if values[arc] >= values[circumference]:
            raise ValueError('An arc must be shorter than the full circumference')
    values.update(CONSTANTS)
    outputs = {}
    allow_zero = {'shoulder_tan', 'hip_tan', 'front_adjustment', 'back_adjustment',
                  'back_reduction', 'back_side_take', 'back_each_dart',
                  'skirt_front_side_take', 'skirt_back_side_take',
                  'skirt_front_dart', 'skirt_back_dart_total', 'skirt_back_each_dart'}
    # Adjustments can be signed, unlike actual lengths and dart widths.
    allow_signed = {'front_adjustment', 'back_adjustment'}
    for record in REGISTRY['records']:
        output = record['output']
        value = expression_value(record['expression'], values)
        if output not in allow_signed and (value < 0 or (value == 0 and output not in allow_zero)):
            raise ValueError(f'Outside this block domain: {output}')
        outputs[output] = value
        values[output] = value
    return outputs


def compare_case(case):
    results = calculate(case['inputs'], case['units'])
    if set(results) != set(case['expected']):
        raise AssertionError('Missing or extra expected results')
    for record in REGISTRY['records']:
        name = record['output']
        expected = number(case['expected'][name])
        if abs(results[name] - expected) > record['numeric_tolerance']:
            raise AssertionError(f"{case['id']} {record['formula_id']} {name}: "
                                 f'{results[name]} != {expected}')
    return results


class Stage2References(unittest.TestCase):
    def test_123_fixed_reference_values(self):
        self.assertEqual(len(REGISTRY['records']), 41)
        self.assertEqual([case['id'] for case in CASES], ['S', 'M', 'L'])
        for case in CASES:
            with self.subTest(profile=case['id']):
                compare_case(case)

    def test_registry_has_provenance_units_and_no_fake_approval(self):
        self.assertEqual([r['formula_id'] for r in REGISTRY['records']],
                         [f'F{i:02}' for i in range(1, 42)])
        seen = set(REGISTRY['input_units'])
        for record in REGISTRY['records']:
            self.assertTrue(set(record['inputs']) <= seen)
            self.assertIn(record['output_unit'], {'mm', '1'})
            self.assertFalse(record['production_allowed'])
            self.assertIsNone(record['expected_fit_error_mm'])
            self.assertIsNone(record['expert_review']['author'])
            self.assertIsNone(record['expert_review']['date'])
            self.assertTrue(record['source'])
            self.assertTrue(record['applicability'])
            seen.add(record['output'])

    def test_upstream_snapshots_match_pinned_hashes(self):
        manifest = read_json('references/garmentcode/manifest.json')
        self.assertEqual(manifest['commit'], REGISTRY['source_commit'])
        for item in manifest['files']:
            data = (ROOT / item['snapshot_path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
        self.assertIn('Copyright (c) 2024 Maria Korosteleva',
                      (ROOT / 'LICENSES/GarmentCode-MIT.txt').read_text())

    def test_missing_measurement_is_not_inferred(self):
        for key in MEASUREMENT_KEYS:
            values = dict(CASES[0]['inputs'])
            del values[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                calculate(values)

    def test_nonfinite_boolean_and_string_inputs_fail(self):
        for invalid in (float('nan'), float('inf'), float('-inf'), True, '840', None):
            values = dict(CASES[0]['inputs'], bust=invalid)
            with self.subTest(value=repr(invalid)), self.assertRaises(ValueError):
                calculate(values)

    def test_units_must_be_normalized_explicitly(self):
        with self.assertRaises(ValueError):
            calculate(CASES[0]['inputs'], units='cm')
        self.assertEqual(CONSTANTS['armhole_ease'], 2.5 * 10)
        self.assertEqual(CONSTANTS['sleeve_balance_reduction'], 2 * 10)
        self.assertEqual(CONSTANTS['back_dart_threshold'], 4 * 10)
        self.assertEqual(CONSTANTS['back_hip_factor'], 1.05)

    def test_invalid_domains_are_rejected_without_clamping(self):
        for change in ({'bust': 0}, {'hip_depth': -1}, {'back_bust_arc': 840},
                       {'shoulder_slope_deg': 90}, {'hip_inclination_deg': -1},
                       {'waist': 1200}, {'front_neck_to_waist_over_bust': 300},
                       {'bust_span': 500}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                calculate(dict(CASES[0]['inputs'], **change))

    def test_measurement_semantics_cannot_be_renamed_silently(self):
        values = dict(CASES[0]['inputs'])
        values['across_back_width'] = values.pop('back_bust_arc')
        with self.assertRaises(ValueError):
            calculate(values)

    def test_independent_closed_form_for_bust_dart(self):
        # Algebraically the source expressions cancel to L_front - L_back.
        for case in CASES:
            values = case['inputs']
            result = calculate(values)
            self.assertAlmostEqual(result['side_dart_width'],
                                   values['front_neck_to_waist_over_bust'] - values['back_neck_to_waist'], places=9)

    def test_dart_and_side_reductions_conserve_projected_widths(self):
        for case in CASES:
            r = calculate(case['inputs'])
            self.assertAlmostEqual(2 * r['back_each_dart'] + r['back_side_take'], r['back_reduction'])
            self.assertAlmostEqual(r['skirt_front_waist'] + r['skirt_back_waist'], case['inputs']['waist'])
            self.assertAlmostEqual(r['hip_projection'], case['inputs']['hips'])

    def test_threshold_is_reproduced_and_visible(self):
        expression = next(r['expression'] for r in REGISTRY['records'] if r['output'] == 'back_side_take')
        self.assertEqual(expression_value(expression, {'back_reduction':39.999, 'back_dart_threshold':40}), 0)
        self.assertAlmostEqual(expression_value(expression, {'back_reduction':40, 'back_dart_threshold':40}), 40 / 6)

    def test_changed_reference_value_is_detected(self):
        changed = copy.deepcopy(CASES[0])
        changed['expected']['armhole_depth'] += 1
        with self.assertRaises(AssertionError):
            compare_case(changed)

    def test_expression_language_cannot_execute_python_code(self):
        for expression in ("__import__('os')", '(1).__class__', '[1][0]',
                           '2 ** 1000000000', 'tan(x=0)', 'unknown + 1'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                expression_value(expression, {})

    def test_positive_ease_is_added_to_full_circumference_once(self):
        presets = read_json('references/stage2/fit-presets.json')
        fitted, semi = presets['presets']
        self.assertEqual(920 + fitted['bust_ease'], 960)
        self.assertEqual(920 + semi['bust_ease'], 980)
        self.assertEqual(740 + semi['waist_ease'], 780)
        self.assertEqual(1000 + semi['hip_ease'], 1060)
        self.assertAlmostEqual(((440 + 60 * semi['back_share']) / 2), 235)
        self.assertAlmostEqual(((920 + 60 - (440 + 60 * semi['back_share'])) / 2), 255)
        self.assertEqual(2 * (235 + 255), 980)
        self.assertEqual(presets['seam_allowances']['fold'], 0)

    def test_document_links_and_formula_tables_are_complete(self):
        for path in [ROOT/'README.md', *sorted((ROOT/'docs').glob('*.md')),
                     ROOT/'LICENSES/THIRD_PARTY_NOTICES.md']:
            text = path.read_text(encoding='utf-8')
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                if '://' not in target and not target.startswith('#'):
                    self.assertTrue((path.parent / target.split('#')[0]).is_file(), (path, target))
        registry_md = (ROOT/'docs/FORMULA_REGISTRY.md').read_text()
        values_md = (ROOT/'docs/REFERENCE_CALCULATIONS.md').read_text()
        for record in REGISTRY['records']:
            self.assertIn(f"| {record['formula_id']} ", registry_md)
            self.assertIn(f"| {record['formula_id']} ", values_md)


if __name__ == '__main__':
    unittest.main(verbosity=2)

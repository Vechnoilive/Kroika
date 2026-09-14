#!/usr/bin/env python3
"""Read-only experiment with pinned upstream blocks, NOT a Kroika generator.

Requires a separate GarmentCode checkout and its Python dependencies.
Prints measured raw block interfaces in mm; does not export sewing patterns.
Usage: python scripts/audit_upstream_blocks.py /path/to/GarmentCode
"""

import contextlib
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'd449629979028123a5c4dc9e732a2ec19b7fce31'


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    upstream = Path(sys.argv[1]).resolve()
    actual = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != COMMIT:
        raise SystemExit('Wrong upstream commit')
    dirty = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain', '--untracked-files=no'], text=True)
    if dirty:
        raise SystemExit('Upstream has tracked modifications')
    sys.path.insert(0, str(upstream))
    from assets.garment_programs.bodice import BodiceFrontHalf, BodiceBackHalf
    from assets.garment_programs.skirt_paneled import FittedSkirtPanel

    fixture_bytes = (ROOT / 'references/stage2/control-examples.json').read_bytes()
    cases = json.loads(fixture_bytes)['cases']
    aliases = {'back_bust_arc': 'back_width', 'back_waist_arc': 'waist_back_width',
               'back_hip_arc': 'hip_back_width', 'shoulder_span': 'shoulder_w',
               'back_neck_to_waist': 'waist_line',
               'front_neck_to_waist_over_bust': 'waist_over_bust_line',
               'bust_path_height': 'bust_line', 'bust_vertical_height': 'vert_bust_line',
               'bust_span': 'bust_points'}
    report = {'source_commit': COMMIT, 'units': 'mm', 'experimental': True,
              'fixture_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
              'python_version': sys.version.split()[0],
              'scope': 'Raw bodice and skirt blocks, before neck/armhole cuts and seam reconciliation; zero ease.',
              'dependencies': {name: importlib.metadata.version(name) for name in
                               ['numpy', 'scipy', 'svgpathtools', 'svgwrite', 'cairosvg',
                                'shapely', 'matplotlib', 'PyYAML', 'psutil']},
              'cases': []}
    for index, case in enumerate(cases):
        measured = case['inputs']
        body = {aliases.get(key, key): value / 10 for key, value in measured.items()
                if not key.endswith('_deg')}
        body.update({'_shoulder_incl': measured['shoulder_slope_deg'],
                     '_hip_inclination': measured['hip_inclination_deg'] / 2,
                     '_bust_line': (2 * body['vert_bust_line'] + body['bust_line']) / 3,
                     'height': 160 + index * 10, 'head_l': 23,
                     'bum_points': 18 + index * 2})
        notes = io.StringIO()
        with contextlib.redirect_stdout(notes), contextlib.redirect_stderr(notes):
            front = BodiceFrontHalf('front', body, {})
            back = BodiceBackHalf('back', body, {})
            design = {'low_angle': {'v': 0}, 'flare': {'v': 1.1}}
            common = {'body': body, 'design': design, 'hips_depth': body['hip_depth'],
                      'length': 55 - body['hip_depth']}
            skirt_front = FittedSkirtPanel('skirt_front',
                waist=(body['waist'] - body['waist_back_width']) / 2,
                hips=(body['hips'] - body['hip_back_width']) / 2,
                dart_position=body['bust_points'] / 2, dart_frac=0.8, **common)
            skirt_back = FittedSkirtPanel('skirt_back',
                waist=body['waist_back_width'] / 2, hips=body['hip_back_width'] / 2,
                dart_position=body['bum_points'] / 2, dart_frac=0.85,
                hipline_ext=1.05, double_dart=True, **common)
            panels = {'bodice_front_half': front, 'bodice_back_half': back,
                      'skirt_front_full': skirt_front, 'skirt_back_full': skirt_back}
            measurements = {}
            for name, panel in panels.items():
                measurements[name] = {
                    'self_intersecting_upstream_check': bool(panel.is_self_intersecting()),
                    'interface_lengths_mm': {key: value.edges.length() * 10
                                             for key, value in panel.interfaces.items()
                                             if key in {'bottom', 'top', 'outside', 'right', 'left'}},
                }
        fw = front.interfaces['bottom'].edges.length() * 20
        bw = back.interfaces['bottom'].edges.length() * 20
        swf = skirt_front.interfaces['top'].edges.length() * 10
        swb = skirt_back.interfaces['top'].edges.length() * 10
        report['cases'].append({'id': case['id'],
            'extra_synthetic_inputs_mm': {'height': body['height'] * 10,
                'head_length': 230, 'bum_span': body['bum_points'] * 10,
                'skirt_length_from_waist': 550},
            'skirt_flare_ratio': 1.1, 'diagnostics': notes.getvalue(), 'panels': measurements,
            'raw_waist_residual_front_mm': fw - swf,
            'raw_waist_residual_back_mm': bw - swb,
            'raw_bodice_side_residual_mm': (front.interfaces['outside'].edges.length()
                                          - back.interfaces['outside'].edges.length()) * 10,
            'raw_skirt_side_residual_mm': (skirt_back.interfaces['right'].edges.length()
                                         - skirt_front.interfaces['right'].edges.length()) * 10,
            'seams_reconciled': False, 'expert_reviewed': False})
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()

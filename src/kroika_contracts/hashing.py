"""Stable hash of values that can affect pattern generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_generation_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Remove IDs, labels, timestamps and provenance from an engine request.

    Every retained field can affect geometry or method applicability. Adding a
    new computational field requires an intentional contract/hash version bump.
    """
    measurements = request['body_measurements']
    garment = request['garment_spec']
    fit = request['fit_settings']
    fabric = request['fabric_properties']
    method = request['pattern_method']
    return {
        'hash_contract_version': '1.0.0',
        'pattern_method': {'id': method['id'], 'version': method['version']},
        'body_measurements': {
            'schema_version': measurements['schema_version'],
            'normalized_unit': measurements['normalized_unit'],
            'values': {key: value['value'] for key, value in measurements['values'].items()},
            'angles_deg': measurements.get('angles_deg', {}),
        },
        'garment_spec': {
            'schema_version': garment['schema_version'],
            'garment_type': garment['garment_type'],
            'parameters': garment['parameters'],
        },
        'fit_settings': {
            'schema_version': fit['schema_version'],
            'wearing_ease_mm': fit['wearing_ease_mm'],
            'design_ease_mm': fit['design_ease_mm'],
            'distribution': fit['distribution'],
            'seam_allowance_mode': fit['seam_allowance_mode'],
            'seam_allowances_mm': fit['seam_allowances_mm'],
        },
        'fabric_properties': {
            'schema_version': fabric['schema_version'],
            'intended_use': fabric['intended_use'],
            'structure': fabric['structure'],
            'stretch_percent': fabric['stretch_percent'],
            'weight': fabric['weight'],
            'drape': fabric['drape'],
            'stability': fabric['stability'],
            'directional_nap': fabric['directional_nap'],
            'prewashed': fabric['prewashed'],
        },
    }


def compute_input_hash(request: Mapping[str, Any]) -> str:
    payload = canonical_generation_payload(request)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

import {describe, expect, it} from 'vitest';
import {canonicalGenerationPayload, sha256, stableJson} from './generation';

describe('generation input hashing payload', () => {
  it('sorts nested keys deterministically', () => {
    expect(stableJson({z: 1, aa: 2, a_b: 3, a: {y: 2, b: 3}})).toBe(
      '{"a":{"b":3,"y":2},"a_b":3,"aa":2,"z":1}',
    );
  });

  it('matches Python SHA-256 for UTF-8 canonical JSON', async () => {
    const canonical = stableJson({
      hash_contract_version: '1.0.0',
      garment_spec: {garment_type: 'dress', parameters: {sleeve: 'sleeveless'}},
      measurements: {waist_mm: 700, note: 'мерки'},
    });
    expect(await sha256(canonical)).toBe(
      '1d672e6f444573cc07d2210d49eed286762adcd4aa69cbb3f81e1f6dc884bf64',
    );
  });

  it('keeps geometry inputs and removes labels and identifiers', () => {
    const request = {
      request_id: 'ignored',
      project_id: 'ignored',
      pattern_method: {id: 'method', version: '1.0.0', validation_status: 'experimental'},
      body_measurements: {
        schema_version: '1.0.0',
        profile_id: 'ignored',
        name: 'ignored',
        normalized_unit: 'mm',
        values: {waist: {value: 700, unit: 'mm', source: 'user'}},
        angles_deg: {shoulder_slope: 12},
      },
      garment_spec: {
        schema_version: '1.0.0',
        garment_id: 'ignored',
        garment_type: 'dress',
        parameters: {neckline: {type: 'round'}},
      },
      fit_settings: {
        schema_version: '1.0.0',
        wearing_ease_mm: {waist: 40},
        design_ease_mm: {waist: 0},
        distribution: {front_share: .5, back_share: .5},
        seam_allowance_mode: 'by_edge',
        seam_allowances_mm: {normal: 15},
      },
      fabric_properties: {
        schema_version: '1.0.0',
        intended_use: 'toile',
        structure: 'woven',
        stretch_percent: {warp: 0, weft: 2},
        weight: 'medium',
        drape: 'crisp',
        stability: 'stable',
        directional_nap: false,
        prewashed: true,
      },
    };
    const payload = canonicalGenerationPayload(request);
    expect(payload.body_measurements.values).toEqual({waist: 700});
    expect(stableJson(payload)).not.toContain('ignored');
    expect(stableJson(payload)).not.toContain('source');
  });
});

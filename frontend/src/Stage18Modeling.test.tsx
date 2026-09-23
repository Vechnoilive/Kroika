import {describe, expect, it} from 'vitest';
import {reevaluateDesignIntent} from './designIntent';
import {canonicalGenerationPayload, stableJson} from './generation';
import {makeDemoProject} from './demoProject';
import type {GarmentDesignIntent, StyleAnalysis} from './types';

const analysis = {} as StyleAnalysis;

function intentWith(element: GarmentDesignIntent['elements'][number]): GarmentDesignIntent {
  return {
    schema_version: '1.0.0', source: 'manual', status: 'needs_confirmation',
    review_status: 'proposed', reviewed_at: null, elements: [element],
    layers: [{
      source_layer_id: 'main_fabric', role: 'main', coverage: 'full',
      material_hint_ru: 'Основная ткань.', opacity: 'opaque', drape: 'medium',
      confidence: 1, requires_confirmation: false, included: true,
      confirmed_by_user: true, support_status: 'supported', module_id: 'main_fabric_layer',
    }],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight',
      asymmetry: 'no', confidence: 1, confirmed_by_user: true,
      support_status: 'supported', module_id: 'bounded_visual_proportions',
    },
    pending_questions: [], question_answers: [],
  };
}

function element(overrides: Partial<GarmentDesignIntent['elements'][number]> = {}) {
  return {
    source_element_id: 'front_center_pleat', type: 'pleat' as const,
    variant: 'box' as const, description_ru: 'Центральная бантовая складка.',
    location: 'skirt_front' as const, construction: 'integrated' as const,
    count: 1, symmetry: 'single' as const, confidence: 1,
    evidence_ru: 'Подтверждено по фотографии.', requires_confirmation: false,
    included: true, confirmed_by_user: true,
    dimensions_mm: {width: null, length: 250, depth: 20, spacing: null},
    support_status: 'needs_confirmation' as const, module_id: null,
    ...overrides,
  };
}

describe('stage 18 modeling capability mapping', () => {
  it('marks bounded pleats and flounces as compiled but keeps yokes fail-closed', () => {
    const project = makeDemoProject('Модельные преобразования');
    const pleat = reevaluateDesignIntent(intentWith(element()), project.garment_spec, analysis);
    expect(pleat.elements[0]).toMatchObject({
      support_status: 'supported', module_id: 'center_pleat_v1',
    });
    expect(pleat.status).toBe('ready');

    const flounce = reevaluateDesignIntent(intentWith(element({
      source_element_id: 'hem_flounce', type: 'flounce', variant: 'circular',
      location: 'hem', construction: 'separate_piece',
      dimensions_mm: {width: null, length: null, depth: 90, spacing: null},
    })), project.garment_spec, analysis);
    expect(flounce.elements[0].module_id).toBe('circular_hem_flounce_v1');

    const gather = reevaluateDesignIntent(intentWith(element({
      source_element_id: 'front_gather', type: 'gather', variant: 'gathered',
      dimensions_mm: {width: 120, length: 200, depth: null, spacing: null},
    })), project.garment_spec, analysis);
    expect(gather.elements[0].module_id).toBe('waist_gather_allowance_v1');

    const belt = reevaluateDesignIntent(intentWith(element({
      source_element_id: 'straight_belt', type: 'belt', variant: 'straight',
      location: 'waist', construction: 'separate_piece',
      dimensions_mm: {width: 45, length: 1400, depth: null, spacing: null},
    })), project.garment_spec, analysis);
    expect(belt.elements[0].module_id).toBe('straight_belt_v1');

    const skirtSpec = {...project.garment_spec, garment_type: 'skirt' as const};
    const waistband = reevaluateDesignIntent(intentWith(element({
      source_element_id: 'wide_waistband', type: 'waistband', variant: 'straight',
      location: 'waist', construction: 'separate_piece',
      dimensions_mm: {width: 70, length: null, depth: null, spacing: null},
    })), skirtSpec, analysis);
    expect(waistband.elements[0].module_id).toBe('adjustable_straight_waistband_v1');

    const yoke = reevaluateDesignIntent(intentWith(element({
      source_element_id: 'front_yoke', type: 'yoke', variant: 'straight',
      dimensions_mm: {width: null, length: null, depth: 120, spacing: null},
    })), project.garment_spec, analysis);
    expect(yoke.elements[0]).toMatchObject({support_status: 'planned', module_id: null});
    expect(yoke.status).toBe('partial');
  });

  it('includes only compiled modeling parameters in the deterministic hash payload', () => {
    const project = makeDemoProject('Hash моделирования');
    const reviewed = reevaluateDesignIntent(intentWith(element()), project.garment_spec, analysis);
    const reviewedWithBelt = {
      ...reviewed,
      elements: [...reviewed.elements, element({
        source_element_id: 'hash_belt', type: 'belt', variant: 'straight',
        location: 'waist', construction: 'separate_piece',
        dimensions_mm: {width: 40, length: 1200, depth: null, spacing: null},
        support_status: 'supported', module_id: 'straight_belt_v1',
      })],
    };
    const request = {
      pattern_method: project.pattern_method,
      body_measurements: project.body_measurements,
      garment_spec: {...project.garment_spec, design_intent: reviewedWithBelt},
      fit_settings: project.fit_settings,
      fabric_properties: project.fabric_properties,
    };
    const legacy = canonicalGenerationPayload({
      ...request, garment_spec: project.garment_spec,
    });
    expect(legacy.hash_contract_version).toBe('1.0.0');
    const first = stableJson(canonicalGenerationPayload(request));
    const reordered = stableJson(canonicalGenerationPayload({
      ...request,
      garment_spec: {
        ...request.garment_spec,
        design_intent: {
          ...reviewedWithBelt,
          elements: [...reviewedWithBelt.elements].reverse(),
        },
      },
    }));
    expect(reordered).toBe(first);
    request.garment_spec.design_intent.elements[0].dimensions_mm!.depth = 30;
    const second = stableJson(canonicalGenerationPayload(request));
    expect(first).not.toBe(second);
    expect(first).toContain('"hash_contract_version":"1.1.0"');
    expect(first).toContain('center_pleat_v1');
    expect(first).not.toContain('evidence_ru');
  });
});

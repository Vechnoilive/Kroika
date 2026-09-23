import {describe, expect, it} from 'vitest';
import {finalizeDesignIntent, reevaluateDesignIntent} from './designIntent';
import {canonicalGenerationPayload} from './generation';
import {makeDemoProject} from './demoProject';
import type {GarmentDesignIntent, StyleAnalysis} from './types';

const analysis = {} as StyleAnalysis;
const emptyDimensions = {width: null, length: null, depth: null, spacing: null};

function element(
  overrides: Partial<GarmentDesignIntent['elements'][number]>,
): GarmentDesignIntent['elements'][number] {
  return {
    source_element_id: 'topology', type: 'yoke', variant: 'straight',
    description_ru: 'Топологический элемент.', location: 'waist',
    construction: 'separate_piece', count: 2, symmetry: 'symmetric', confidence: 1,
    evidence_ru: 'Подтверждено по фотографии.', requires_confirmation: false,
    included: true, confirmed_by_user: true, dimensions_mm: {...emptyDimensions, depth: 120},
    support_status: 'needs_confirmation', module_id: null, ...overrides,
  };
}

function intent(...elements: GarmentDesignIntent['elements']): GarmentDesignIntent {
  return {
    schema_version: '1.0.0', coverage_schema_version: '1.0.0', source: 'manual',
    status: 'needs_confirmation', review_status: 'proposed', reviewed_at: null,
    elements,
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
    }, pending_questions: [], question_answers: [],
  };
}

describe('stage 21 topology capability mapping', () => {
  it('compiles bounded yokes, panels and dart transfers', () => {
    const project = makeDemoProject('Топология фасона');
    const yoke = reevaluateDesignIntent(intent(
      element({source_element_id: 'yoke'}),
    ), project.garment_spec, analysis);
    const panels = reevaluateDesignIntent(intent(
      element({
        source_element_id: 'panels', type: 'panel', location: 'full_garment', count: 3,
        dimensions_mm: {...emptyDimensions},
      }),
    ), project.garment_spec, analysis);
    const dart = reevaluateDesignIntent(intent(
      element({
        source_element_id: 'dart_transfer', type: 'dart', variant: 'shaped',
        location: 'bodice_front', construction: 'integrated',
        dimensions_mm: {...emptyDimensions, width: 10},
      }),
    ), project.garment_spec, analysis);

    expect(yoke.elements[0].module_id).toBe('paired_straight_skirt_yoke_v1');
    expect(panels.elements[0].module_id).toBe('paired_equal_skirt_panels_v1');
    expect(dart.elements[0].module_id).toBe('front_waist_to_side_dart_v1');
    expect([yoke.status, panels.status, dart.status]).toEqual(['ready', 'ready', 'ready']);

    const conflict = intent(element({source_element_id: 'yoke'}), element({
      source_element_id: 'panels', type: 'panel', location: 'full_garment', count: 3,
      dimensions_mm: {...emptyDimensions},
    }));
    expect(() => finalizeDesignIntent(conflict, project.garment_spec, analysis))
      .toThrow('выберите либо кокетку, либо панельное членение');
  });

  it('keeps unsupported variants closed and hashes topology as contract 1.4', () => {
    const project = makeDemoProject('Hash топологии');
    const reviewed = reevaluateDesignIntent(intent(element({source_element_id: 'yoke'})),
      project.garment_spec, analysis);
    const request = {
      pattern_method: project.pattern_method,
      body_measurements: project.body_measurements,
      garment_spec: {...project.garment_spec, design_intent: reviewed},
      fit_settings: project.fit_settings,
      fabric_properties: project.fabric_properties,
    };
    const payload = canonicalGenerationPayload(request);
    expect(payload.hash_contract_version).toBe('1.4.0');
    expect(payload.garment_spec.topology_elements[0].module_id)
      .toBe('paired_straight_skirt_yoke_v1');

    const invalid = reevaluateDesignIntent(intent(element({
      source_element_id: 'bad_yoke', variant: 'shaped',
    })), project.garment_spec, analysis);
    expect(invalid.elements[0]).toMatchObject({support_status: 'planned', module_id: null});
    expect(invalid.status).toBe('partial');
  });
});

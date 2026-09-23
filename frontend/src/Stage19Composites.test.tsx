import {describe, expect, it} from 'vitest';
import {reevaluateDesignIntent} from './designIntent';
import {canonicalGenerationPayload, stableJson} from './generation';
import {makeDemoProject} from './demoProject';
import type {GarmentDesignIntent, StyleAnalysis} from './types';

const analysis = {} as StyleAnalysis;

const mainLayer: GarmentDesignIntent['layers'][number] = {
  source_layer_id: 'main_fabric', role: 'main', coverage: 'full',
  material_hint_ru: 'Основная ткань.', opacity: 'opaque', drape: 'medium',
  confidence: 1, requires_confirmation: false, included: true,
  confirmed_by_user: true, support_status: 'supported', module_id: 'main_fabric_layer',
};

function baseIntent(): GarmentDesignIntent {
  return {
    schema_version: '1.0.0', source: 'manual', status: 'needs_confirmation',
    review_status: 'proposed', reviewed_at: null, elements: [], layers: [mainLayer],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight',
      asymmetry: 'no', confidence: 1, confirmed_by_user: true,
      support_status: 'supported', module_id: 'bounded_visual_proportions',
    },
    pending_questions: [], question_answers: [],
  };
}

function element(
  overrides: Partial<GarmentDesignIntent['elements'][number]> = {},
): GarmentDesignIntent['elements'][number] {
  return {
    source_element_id: 'front_pockets', type: 'pocket', variant: 'patch',
    description_ru: 'Парные накладные карманы.', location: 'skirt_front',
    construction: 'applied', count: 2, symmetry: 'symmetric', confidence: 1,
    evidence_ru: 'Подтверждено по фотографии.', requires_confirmation: false,
    included: true, confirmed_by_user: true,
    dimensions_mm: {width: 140, length: null, depth: 170, spacing: null},
    support_status: 'needs_confirmation', module_id: null,
    ...overrides,
  };
}

function layer(
  overrides: Partial<GarmentDesignIntent['layers'][number]> = {},
): GarmentDesignIntent['layers'][number] {
  return {
    source_layer_id: 'skirt_overlay', role: 'overlay', coverage: 'skirt',
    material_hint_ru: 'Прозрачный верхний слой.', opacity: 'semi_transparent',
    drape: 'fluid', confidence: 1, requires_confirmation: false, included: true,
    confirmed_by_user: true, support_status: 'needs_confirmation', module_id: null,
    ...overrides,
  };
}

describe('stage 19 composite capability mapping', () => {
  it('compiles bounded cuffs, collars, pockets and skirt layers but blocks unknown topology', () => {
    const project = makeDemoProject('Составные детали');

    const pocketIntent = baseIntent();
    pocketIntent.elements = [element()];
    const pocket = reevaluateDesignIntent(pocketIntent, project.garment_spec, analysis);
    expect(pocket.elements[0]).toMatchObject({
      support_status: 'supported', module_id: 'paired_patch_pocket_v1',
    });

    const collarIntent = baseIntent();
    collarIntent.elements = [element({
      source_element_id: 'stand_collar', type: 'collar', variant: 'stand',
      location: 'neckline', construction: 'separate_piece', count: 1,
      dimensions_mm: {width: 40, length: null, depth: null, spacing: null},
    })];
    const collar = reevaluateDesignIntent(collarIntent, project.garment_spec, analysis);
    expect(collar.elements[0].module_id).toBe('stand_collar_v1');

    const blouseSpec = {...project.garment_spec, garment_type: 'blouse' as const};
    const cuffIntent = baseIntent();
    cuffIntent.elements = [element({
      source_element_id: 'straight_cuff', type: 'cuff', variant: 'straight',
      location: 'sleeve', construction: 'separate_piece', count: 2,
      dimensions_mm: {width: 55, length: null, depth: null, spacing: null},
    })];
    const cuff = reevaluateDesignIntent(cuffIntent, blouseSpec, analysis);
    expect(cuff.elements[0].module_id).toBe('sleeve_cuff_band_v1');

    const layersIntent = baseIntent();
    layersIntent.layers.push(
      layer(),
      layer({
        source_layer_id: 'skirt_lining', role: 'lining', opacity: 'opaque',
        material_hint_ru: 'Подкладочная ткань.',
      }),
    );
    const layers = reevaluateDesignIntent(layersIntent, project.garment_spec, analysis);
    expect(layers.layers.map((item) => item.module_id)).toEqual([
      'main_fabric_layer', 'skirt_overlay_layer_v1', 'skirt_full_lining_v1',
    ]);

    const hoodIntent = baseIntent();
    hoodIntent.elements = [element({
      source_element_id: 'photo_hood', type: 'hood', variant: 'other',
      location: 'neckline', construction: 'separate_piece', count: 1,
      dimensions_mm: {width: null, length: null, depth: null, spacing: null},
    })];
    const hood = reevaluateDesignIntent(hoodIntent, project.garment_spec, analysis);
    expect(hood.elements[0]).toMatchObject({support_status: 'planned', module_id: null});
    expect(hood.status).toBe('partial');
  });

  it('hashes only compiled composite inputs with an order-independent 1.2 contract', () => {
    const project = makeDemoProject('Hash составных деталей');
    const intent = baseIntent();
    intent.elements = [element()];
    intent.layers.push(layer());
    const reviewed = reevaluateDesignIntent(intent, project.garment_spec, analysis);
    const request = {
      pattern_method: project.pattern_method,
      body_measurements: project.body_measurements,
      garment_spec: {...project.garment_spec, design_intent: reviewed},
      fit_settings: project.fit_settings,
      fabric_properties: project.fabric_properties,
    };
    const payload = canonicalGenerationPayload(request);
    expect(payload.hash_contract_version).toBe('1.2.0');
    expect(payload.garment_spec.composite_elements[0].module_id).toBe(
      'paired_patch_pocket_v1',
    );
    expect(payload.garment_spec.composite_layers[0].module_id).toBe(
      'skirt_overlay_layer_v1',
    );

    const first = stableJson(payload);
    const reordered = stableJson(canonicalGenerationPayload({
      ...request,
      garment_spec: {
        ...request.garment_spec,
        design_intent: {...reviewed, layers: [...reviewed.layers].reverse()},
      },
    }));
    expect(reordered).toBe(first);
    expect(first).not.toContain('evidence_ru');

    reviewed.elements[0].dimensions_mm!.width = 160;
    const changed = stableJson(canonicalGenerationPayload(request));
    expect(changed).not.toBe(first);
  });
});

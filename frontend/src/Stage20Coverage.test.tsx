import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {PatternResultCard} from './App';
import {buildDesignCoverage} from './designCoverage';
import {canonicalGenerationPayload} from './generation';
import {makeDemoProject} from './demoProject';
import type {
  DesignCoverageCatalogue,
  GarmentDesignIntent,
  PatternEngineResult,
  StyleAnalysis,
} from './types';

const evidence = {
  piece_ids: ['front_bodice'],
  seam_pair_ids: [],
  path_ids: [],
  segment_ids: [],
  operation_ids: [],
};

const catalogue: DesignCoverageCatalogue = {
  schema_version: '1.0.0',
  physical_validation_required: true,
  modules: [
    {module_id: 'straight_belt_v1', source_ids: ['photo_belt'], evidence},
    {module_id: 'main_fabric_layer', source_ids: [], evidence},
    {module_id: 'bounded_visual_proportions', source_ids: [], evidence},
  ],
};

const intent: GarmentDesignIntent = {
  schema_version: '1.0.0', coverage_schema_version: '1.0.0', source: 'ai',
  status: 'ready', review_status: 'confirmed', reviewed_at: '2026-09-23T10:00:00Z',
  elements: [
    {
      source_element_id: 'photo_belt', type: 'belt', variant: 'straight',
      description_ru: 'Широкий отдельный пояс.', location: 'waist',
      construction: 'separate_piece', count: 1, symmetry: 'symmetric', confidence: 1,
      evidence_ru: 'Виден на фотографии.', requires_confirmation: false,
      included: true, confirmed_by_user: true,
      dimensions_mm: {width: 50, length: 1100, depth: null, spacing: null},
      support_status: 'supported', module_id: 'straight_belt_v1',
    },
    {
      source_element_id: 'photo_peplum', type: 'peplum', variant: 'other',
      description_ru: 'Баска по линии талии.', location: 'waist',
      construction: 'separate_piece', count: 1, symmetry: 'symmetric', confidence: .9,
      evidence_ru: 'Видна на фотографии.', requires_confirmation: false,
      included: false, confirmed_by_user: true,
      dimensions_mm: {width: null, length: null, depth: null, spacing: null},
      support_status: 'excluded', module_id: null,
    },
  ],
  layers: [{
    source_layer_id: 'main_fabric', role: 'main', coverage: 'full',
    material_hint_ru: 'Основная ткань.', opacity: 'opaque', drape: 'medium', confidence: 1,
    requires_confirmation: false, included: true, confirmed_by_user: true,
    support_status: 'supported', module_id: 'main_fabric_layer',
  }],
  proportions: {
    waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no',
    confidence: 1, confirmed_by_user: true, support_status: 'supported',
    module_id: 'bounded_visual_proportions',
  },
  pending_questions: [], question_answers: [],
};

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress',
  silhouette: {fit: 'regular', confidence: 1},
  neckline: {front: 'round', confidence: 1},
  sleeves: {present: false, length: 'none', confidence: 1},
  lower_part: {type: 'skirt', length_category: 'midi', confidence: 1},
  uncertainties: [], targeted_questions: [],
  design_features: {
    elements: [
      {
        element_id: 'photo_belt', type: 'belt', variant: 'straight',
        description_ru: 'Широкий отдельный пояс.', location: 'waist',
        construction: 'separate_piece', count: 1, symmetry: 'symmetric', confidence: 1,
        evidence_ru: 'Виден на фотографии.', requires_confirmation: false,
      },
      {
        element_id: 'photo_peplum', type: 'peplum', variant: 'other',
        description_ru: 'Баска по линии талии.', location: 'waist',
        construction: 'separate_piece', count: 1, symmetry: 'symmetric', confidence: .9,
        evidence_ru: 'Видна на фотографии.', requires_confirmation: false,
      },
      {
        element_id: 'orphan_ruffle', type: 'ruffle', variant: 'gathered',
        description_ru: 'Оборка на плече.', location: 'shoulder',
        construction: 'applied', count: 2, symmetry: 'symmetric', confidence: .85,
        evidence_ru: 'Видна на фотографии.', requires_confirmation: false,
      },
    ],
    layers: [{
      layer_id: 'main_fabric', role: 'main', coverage: 'full',
      material_hint_ru: 'Основная ткань.', opacity: 'opaque', drape: 'medium',
      confidence: 1, requires_confirmation: false,
    }],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight',
      asymmetry: 'no', confidence: 1,
    },
  },
};

const result: PatternEngineResult = {
  generation_id: '11111111-1111-4111-8111-111111111111',
  engine_version: '0.11.0', status: 'succeeded',
  validation_report: {
    status: 'warnings', issues: [], diagnostic_export_allowed: true,
    production_export_allowed: false,
  },
  pattern: {
    unit: 'mm', pieces: [{id: 'front_bodice', name_ru: 'Перед', cut_quantity: 1, cut_on_fold: true}],
    seam_pairs: [], design_coverage: catalogue,
    print_layout: {page_format: 'A4', overlap_mm: 10, scale: 1, control_square_mm: 50},
  },
};

describe('stage 20 design coverage', () => {
  it('hashes the required coverage modules with the 1.3 contract', () => {
    const project = makeDemoProject('Покрытие фасона');
    const payload = canonicalGenerationPayload({
      pattern_method: project.pattern_method,
      body_measurements: project.body_measurements,
      garment_spec: {...project.garment_spec, design_intent: intent},
      fit_settings: project.fit_settings,
      fabric_properties: project.fabric_properties,
    });

    expect(payload.hash_contract_version).toBe('1.3.0');
    expect(payload.garment_spec.coverage_contract.required_module_ids).toEqual([
      'bounded_visual_proportions', 'main_fabric_layer', 'straight_belt_v1',
    ]);
  });

  it('keeps photo exclusions visible and detects a photo feature lost from the plan', () => {
    const report = buildDesignCoverage(intent, analysis, catalogue);

    expect(report).toMatchObject({
      complete: false, requiredCount: 4, compiledCount: 3,
      excludedCount: 1, missingCount: 1, photoCount: 5,
    });
    expect(report.entries.find((item) => item.sourceId === 'photo_peplum')?.decision)
      .toBe('excluded_by_user');
    expect(report.entries.find((item) => item.sourceId === 'orphan_ruffle')?.decision)
      .toBe('missing_from_plan');
  });

  it('shows evidence, a repair action and the separate physical gate', () => {
    const edit = vi.fn();
    render(
      <PatternResultCard
        result={result}
        designIntent={intent}
        analysis={analysis}
        onEditDesign={edit}
      />,
    );

    expect(screen.getByRole('heading', {name: 'Нужно исправить покрытие: 1'})).toBeInTheDocument();
    expect(screen.getByText('Потеряно между фото и планом')).toBeInTheDocument();
    expect(screen.getByText('Исключено вами')).toBeInTheDocument();
    expect(screen.getByText(/Печатать можно для проверки/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Вернуться к деталям фасона'}));
    expect(edit).toHaveBeenCalledOnce();
  });
});

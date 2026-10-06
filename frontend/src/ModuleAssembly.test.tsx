import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {buildDesignCoverage} from './designCoverage';
import {DesignCoverageSummary} from './DesignCoverageSummary';
import type {DesignCoverageCatalogue, DesignCoverageEvidence, GarmentDesignIntent, PatternData} from './types';

function fixture() {
  const intent: GarmentDesignIntent = {
    schema_version: '1.0.0', source: 'manual', status: 'ready', review_status: 'confirmed',
    reviewed_at: '2026-10-06T12:00:00Z', elements: [], layers: [],
    pending_questions: [], question_answers: [],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no',
      confidence: 1, confirmed_by_user: true, support_status: 'supported',
      module_id: 'bounded_visual_proportions',
    },
  };
  intent.elements = ['first_pocket', 'second_pocket'].map((id) => ({
    source_element_id: id, type: 'pocket', variant: 'patch', description_ru: `Карман ${id}`,
    location: 'skirt_front', construction: 'separate_piece', count: 1, symmetry: 'single',
    confidence: 1, evidence_ru: '', requires_confirmation: false, included: true,
    confirmed_by_user: true, support_status: 'supported', module_id: 'placed_patch_pocket_v1',
    dimensions_mm: {width: 80, length: null, depth: 100, spacing: 50},
  }));
  intent.layers = [];
  intent.proportions.support_status = 'supported';
  intent.proportions.module_id = 'bounded_visual_proportions';
  const evidence = (piece: string): DesignCoverageEvidence => ({
    piece_ids: [piece], seam_pair_ids: [], path_ids: [], segment_ids: [], operation_ids: [],
  });
  const catalogue: DesignCoverageCatalogue = {
    schema_version: '1.0.0', physical_validation_required: true,
    modules: [
      {
        module_id: 'placed_patch_pocket_v1', source_ids: ['first_pocket', 'second_pocket'],
        evidence: {...evidence('first_piece'), piece_ids: ['first_piece', 'second_piece']},
        source_evidence: {first_pocket: evidence('first_piece'), second_pocket: evidence('second_piece')},
      },
      {module_id: 'bounded_visual_proportions', source_ids: [], evidence: evidence('front_skirt')},
    ],
  };
  return {intent, catalogue};
}

describe('combined module coverage', () => {
  it('shows the individual geometry for two instances of one module', () => {
    const {intent, catalogue} = fixture();
    const report = buildDesignCoverage(intent, null, catalogue);
    expect(report.complete).toBe(true);
    expect(report.entries[0].evidence?.piece_ids).toEqual(['first_piece']);
    expect(report.entries[1].evidence?.piece_ids).toEqual(['second_piece']);
  });

  it('does not use another instance as evidence for a missing pocket', () => {
    const {intent, catalogue} = fixture();
    delete catalogue.modules[0].source_evidence!.second_pocket;
    const report = buildDesignCoverage(intent, null, catalogue);
    expect(report.complete).toBe(false);
    expect(report.entries[1].decision).toBe('missing_evidence');
  });

  it('rejects an operation record with no displayed geometry', () => {
    const {intent, catalogue} = fixture();
    catalogue.modules[0].source_evidence!.second_pocket = {
      piece_ids: [], path_ids: [], segment_ids: [], seam_pair_ids: [], operation_ids: ['empty_operation'],
    };
    expect(buildDesignCoverage(intent, null, catalogue).entries[1].decision).toBe('missing_evidence');
  });

  it('keeps legacy source matching and shows readable piece names', () => {
    const {intent, catalogue} = fixture();
    delete catalogue.modules[0].source_evidence;
    catalogue.modules[0].source_ids = ['first_pocket'];
    expect(buildDesignCoverage(intent, null, catalogue).entries[1].decision).toBe('missing_evidence');
    const pattern: PatternData = {
      unit: 'mm', seam_pairs: [], design_coverage: catalogue,
      pieces: [
        {id: 'first_piece', name_ru: 'Левый накладной карман', cut_quantity: 1, cut_on_fold: false},
        {id: 'second_piece', name_ru: 'Правый накладной карман', cut_quantity: 1, cut_on_fold: false},
        {id: 'front_skirt', name_ru: 'Перед юбки', cut_quantity: 1, cut_on_fold: true},
      ],
    };
    render(<DesignCoverageSummary intent={intent} pattern={pattern} />);
    expect(screen.getByText(/Лекала: Левый накладной карман; Правый накладной карман/)).toBeInTheDocument();
    expect(screen.getAllByText(/Показать состав:/)).toHaveLength(2);
  });
});

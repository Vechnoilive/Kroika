import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {api} from './api';
import {GenerationComparison} from './GenerationComparison';
import type {GenerationComparisonResult, GenerationSummary} from './types';

const projectId = '11111111-1111-4111-8111-111111111111';
const oldId = '22222222-2222-4222-8222-222222222222';
const currentId = '33333333-3333-4333-8333-333333333333';

function generation(
  generationId: string,
  createdAt: string,
  isCurrent = false,
): GenerationSummary {
  return {
    generation_id: generationId,
    created_at: createdAt,
    status: 'succeeded',
    validation_status: 'warnings',
    engine_version: '0.12.0',
    method_version: '0.1.0',
    piece_count: 6,
    issue_count: 1,
    blocking_issue_count: 0,
    comparable: true,
    is_current: isCurrent,
  };
}

const oldGeneration = generation(oldId, '2026-09-24T01:00:00Z');
const currentGeneration = generation(currentId, '2026-09-24T02:00:00Z', true);

function comparison(base = oldGeneration, target = currentGeneration): GenerationComparisonResult {
  return {
    project_id: projectId,
    base,
    target,
    measurements: [{
      field_id: 'bust', label_ru: 'Обхват груди', kind: 'changed',
      before: 920, after: 940, delta: 20, unit: 'mm',
    }],
    style: [{
      path: 'garment_spec.parameters.skirt.length_from_waist_mm',
      section: 'Фасон', label_ru: 'Длина от талии', kind: 'changed',
      before: 650, after: 675, delta: 25, unit: 'mm',
    }],
    pattern: {
      piece_count_before: 6,
      piece_count_after: 7,
      sheet_count_before: 18,
      sheet_count_after: 20,
      added_pieces: [{piece_id: 'belt', name_ru: 'Пояс', cut_quantity: 1, cut_on_fold: false}],
      removed_pieces: [],
      changed_pieces: [{
        piece_id: 'front', name_ru: 'Перед', area_delta_mm2: 1200,
        width_delta_mm: 10, height_delta_mm: 25, perimeter_delta_mm: 45,
        segment_count_delta: 2, cut_quantity_before: 1, cut_quantity_after: 1,
      }],
      added_seam_pair_ids: ['belt-front'],
      removed_seam_pair_ids: [],
    },
    validation: {
      status_before: 'warnings',
      status_after: 'warnings',
      added_issues: [],
      removed_issues: [{
        code: 'OLD_WARNING', severity: 'warning',
        message_ru: 'Старое предупреждение устранено.', piece_id: 'front',
      }],
    },
    totals: {
      measurement_changes: 1,
      style_changes: 1,
      added_pieces: 1,
      removed_pieces: 0,
      changed_pieces: 1,
      validation_changes: 1,
    },
    no_changes: false,
  };
}

afterEach(() => vi.restoreAllMocks());

describe('stage 26 generation comparison', () => {
  it('selects the previous and current versions and explains every change', async () => {
    vi.spyOn(api, 'listGenerations').mockResolvedValue({
      project_id: projectId,
      items: [currentGeneration, oldGeneration],
    });
    vi.spyOn(api, 'compareGenerations').mockImplementation(
      async (_project, base, target) => base === oldId
        ? comparison(oldGeneration, currentGeneration)
        : comparison(currentGeneration, oldGeneration),
    );

    render(<GenerationComparison projectId={projectId} currentGenerationId={currentId} />);

    expect(await screen.findByText('Обхват груди')).toBeVisible();
    expect(api.compareGenerations).toHaveBeenCalledWith(projectId, oldId, currentId);
    expect(screen.getByText('+20 мм')).toBeVisible();
    expect(screen.getByText(/Длина от талии/i)).toBeVisible();
    expect(screen.getByText(/Добавлена: Пояс/i)).toBeVisible();
    expect(screen.getByText(/ширина \+10 мм/i)).toBeVisible();
    expect(screen.getByText(/Устранено: OLD_WARNING/i)).toBeVisible();
    expect(screen.getByRole('img', {name: 'Базовая версия выкройки'})).toHaveAttribute(
      'src', expect.stringContaining(oldId),
    );
    expect(screen.getByRole('img', {name: 'Новая версия выкройки'})).toHaveAttribute(
      'src', expect.stringContaining(currentId),
    );

    await userEvent.click(screen.getByRole('button', {name: /поменять версии местами/i}));
    await waitFor(() => expect(api.compareGenerations).toHaveBeenCalledWith(
      projectId, currentId, oldId,
    ));
  });

  it('does not invent a comparison until a second version exists', async () => {
    vi.spyOn(api, 'listGenerations').mockResolvedValue({
      project_id: projectId,
      items: [currentGeneration],
    });
    vi.spyOn(api, 'compareGenerations');

    render(<GenerationComparison projectId={projectId} currentGenerationId={currentId} />);

    expect(await screen.findByText(/после построения второй версии/i)).toBeVisible();
    expect(api.compareGenerations).not.toHaveBeenCalled();
  });
});

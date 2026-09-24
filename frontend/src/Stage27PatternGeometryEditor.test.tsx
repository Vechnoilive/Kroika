import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {api, ApiError} from './api';
import {PatternGeometryEditor} from './PatternGeometryEditor';
import type {PatternEngineResult, PatternPiece} from './types';

const generationId = '11111111-1111-4111-8111-111111111111';

const square: PatternPiece = {
  id: 'front', name_ru: 'Перед', cut_quantity: 1, cut_on_fold: false,
  mirrored_pair: false,
  seam_contour: {
    id: 'front-seam', closed: true, segments: [
      {id: 'top', type: 'line', start: [0, 0], end: [100, 0]},
      {id: 'right', type: 'line', start: [100, 0], end: [100, 100]},
      {id: 'bottom', type: 'line', start: [100, 100], end: [0, 100]},
      {id: 'left', type: 'line', start: [0, 100], end: [0, 0]},
    ],
  },
  cutting_contour: null,
  internal_paths: [], grainline: {start: [50, 10], end: [50, 90]},
  notches: [], annotations: [],
};

const result: PatternEngineResult = {
  generation_id: generationId,
  engine_version: '0.12.0',
  status: 'succeeded',
  pattern: {unit: 'mm', pieces: [square], seam_pairs: []},
  validation_report: {
    status: 'warnings', issues: [], diagnostic_export_allowed: true,
    production_export_allowed: false,
  },
};

afterEach(() => vi.restoreAllMocks());

describe('stage 27 pattern geometry editor', () => {
  it('edits a real contour with undo, redo and immutable save', async () => {
    vi.spyOn(api, 'editPatternGeometry').mockResolvedValue(result);
    const onSaved = vi.fn();
    render(<PatternGeometryEditor result={result} projectRevision={7} onSaved={onSaved} />);

    await userEvent.click(screen.getByRole('button', {name: /открыть редактор/i}));
    expect(screen.getByRole('img', {name: /редактор детали Перед/i})).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText('Точка'), 'right:end');
    await userEvent.click(screen.getByRole('button', {name: 'Сдвинуть вправо'}));
    expect(screen.getByText('Изменено точек: 1')).toBeVisible();

    await userEvent.click(screen.getByRole('button', {name: /отменить/i}));
    expect(screen.getByText('Правок пока нет')).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /повторить/i}));
    expect(screen.getByText('Изменено точек: 1')).toBeVisible();

    await userEvent.type(
      screen.getByLabelText('Комментарий к версии'),
      'Уточнение после макета',
    );
    await userEvent.click(screen.getByRole('button', {name: /проверить и сохранить/i}));
    await waitFor(() => expect(api.editPatternGeometry).toHaveBeenCalledWith(
      generationId,
      7,
      [{piece_id: 'front', segment_id: 'right', handle: 'end', x_mm: 101, y_mm: 100}],
      'Уточнение после макета',
    ));
    expect(onSaved).toHaveBeenCalledWith(result);
  });

  it('shows a safe server rejection without losing the draft', async () => {
    vi.spyOn(api, 'editPatternGeometry').mockRejectedValue(new ApiError(
      'Ручная правка нарушила сопряжение парных швов.',
      422,
      'MANUAL_SEAM_PAIR_MISMATCH',
    ));
    render(<PatternGeometryEditor result={result} projectRevision={7} onSaved={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', {name: /открыть редактор/i}));
    await userEvent.selectOptions(screen.getByLabelText('Точка'), 'right:end');
    await userEvent.click(screen.getByRole('button', {name: 'Сдвинуть вправо'}));
    await userEvent.click(screen.getByRole('button', {name: /проверить и сохранить/i}));

    expect(await screen.findByRole('alert')).toHaveTextContent(/нарушила сопряжение/i);
    expect(screen.getByText('Изменено точек: 1')).toBeVisible();
  });
});

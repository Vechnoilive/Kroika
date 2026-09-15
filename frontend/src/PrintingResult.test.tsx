import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {PatternResultCard} from './App';
import {api, ApiError} from './api';
import type {PatternEngineResult} from './types';

const result: PatternEngineResult = {
  generation_id: '11111111-1111-4111-8111-111111111111',
  engine_version: '0.5.0',
  status: 'succeeded',
  pattern: {
    unit: 'mm',
    pieces: [{id: 'front', name_ru: 'Перед', cut_quantity: 1, cut_on_fold: true}],
    seam_pairs: [{id: 'side'}],
    print_layout: {page_format: 'A4', overlap_mm: 10, scale: 1, control_square_mm: 50},
  },
  validation_report: {
    status: 'warnings',
    issues: [],
    diagnostic_export_allowed: true,
    production_export_allowed: false,
  },
};

afterEach(() => vi.restoreAllMocks());

describe('stage-9 printing result', () => {
  it('explains scale verification before offering clear export actions', () => {
    render(<PatternResultCard result={result} />);
    expect(screen.getByRole('heading', {name: /готова к проверке на бумаге/i})).toBeVisible();
    expect(screen.getByText(/actual size \/ реальный размер/i)).toBeVisible();
    expect(screen.getByText(/50 × 50 мм/i)).toBeVisible();
    expect(screen.getByText(/кроить ткань пока нельзя/i)).toBeVisible();
    expect(screen.getByRole('link', {name: /скачать единый svg/i})).toHaveAttribute(
      'href',
      `/api/v1/patterns/${result.generation_id}/export/print.svg`,
    );
    expect(screen.getByRole('button', {name: /скачать pdf a4/i})).toBeEnabled();
  });

  it('shows a plain-language PDF error without hiding the result', async () => {
    vi.spyOn(api, 'downloadA4Pdf').mockRejectedValue(
      new ApiError('Не удалось подготовить печатные листы.', 409, 'PDF_EXPORT_INVALID'),
    );
    render(<PatternResultCard result={result} />);
    await userEvent.click(screen.getByRole('button', {name: /скачать pdf a4/i}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подготовить печатные листы.');
    expect(screen.getByRole('img')).toBeVisible();
  });

  it('offers a safe rebuild for a result saved by an older engine', async () => {
    const rebuild = vi.fn();
    const legacy: PatternEngineResult = {
      ...result,
      engine_version: '0.4.0',
      pattern: {...result.pattern!, print_layout: undefined},
    };
    render(<PatternResultCard result={legacy} onRebuild={rebuild} />);
    expect(screen.getByText(/мерки сохранены/i)).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /перестроить для печати/i}));
    expect(rebuild).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', {name: /скачать pdf/i})).not.toBeInTheDocument();
  });
});

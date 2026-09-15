import {fireEvent, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it} from 'vitest';
import {PatternResultCard} from './App';
import type {PatternEngineResult} from './types';

const result: PatternEngineResult = {
  generation_id: '77777777-7777-4777-8777-777777777777',
  engine_version: '0.5.0',
  status: 'succeeded',
  pattern: {
    unit: 'mm',
    pieces: [{id: 'front', name_ru: 'Перед', cut_quantity: 1, cut_on_fold: true}],
    seam_pairs: [{id: 'side'}],
    print_layout: {page_format: 'A4', overlap_mm: 10, scale: 1, control_square_mm: 50},
  },
  validation_report: {
    status: 'warnings', issues: [], diagnostic_export_allowed: true,
    production_export_allowed: false,
  },
};

describe('stage 11 interactive SVG preview', () => {
  it('changes only preview layers and zoom while keeping full export links', async () => {
    render(<PatternResultCard result={result} />);
    const image = screen.getByRole('img', {name: /интерактивный предпросмотр/i});
    expect(image).toHaveAttribute('src', expect.stringContaining('dimensions'));
    expect(image).toHaveStyle({width: '100%'});

    await userEvent.click(screen.getByLabelText('Размеры деталей'));
    expect(screen.getByRole('img', {name: /интерактивный предпросмотр/i}))
      .toHaveAttribute('src', expect.not.stringContaining('dimensions'));
    fireEvent.change(screen.getByLabelText(/масштаб просмотра/i), {target: {value: '150'}});
    expect(screen.getByRole('img', {name: /интерактивный предпросмотр/i})).toHaveStyle({width: '150%'});

    expect(screen.getByRole('link', {name: 'Единый SVG'})).toHaveAttribute('href', expect.not.stringContaining('layers='));
    expect(screen.getByRole('link', {name: 'JSON проекта'})).toBeVisible();
  });
});

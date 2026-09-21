import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {configureGarment, easeForGarment} from './garments';
import {makeDemoProject} from './demoProject';
import {ConstructionEditor, StyleEditor} from './ProjectWorkflow';
import type {GarmentAcceptanceStatus, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation', garment_category: 'jacket',
  silhouette: {fit: 'semi_fitted', confidence: 0.8},
  neckline: {front: 'v', confidence: 0.7},
  sleeves: {present: true, length: 'long', confidence: 0.8},
  lower_part: {type: 'straight', length_category: 'hip', confidence: 0.7},
  uncertainties: ['Конструкция воротника требует подтверждения'],
  targeted_questions: [],
};

const acceptance: GarmentAcceptanceStatus = {
  garment_type: 'jacket', name_ru: 'Лёгкий жакет',
  scope_ru: 'Однобортный жакет с лацканом, подкладкой и одношовным рукавом.',
  formula_status: 'implemented', reference_status: 'automated_passed',
  invariant_status: 'automated_passed', paper_status: 'pending',
  expert_status: 'pending', toile_status: 'pending', production_allowed: false,
};

describe('stage 13 light jacket UI', () => {
  it('saves the jacket as a separate bounded method and explains physical pending status', async () => {
    const project = makeDemoProject('Жакет');
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);
    render(<StyleEditor project={project} analysis={analysis} providerName="Qwen" acceptance={acceptance} onSave={onSave} />);

    await userEvent.click(screen.getByRole('radio', {name: /Лёгкий жакет/}));
    expect(screen.getByText('Лацкан и воротник')).toBeVisible();
    expect(screen.getByText('Подкладка')).toBeVisible();
    expect(screen.getByText(/экспертная проверка, бумажная сборка и макет ещё не пройдены/i)).toBeVisible();
    expect(screen.getByLabelText(/ширина лацкана/i)).toHaveValue(7);
    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.garment_type).toBe('jacket');
    expect(saved.garment_spec.parameters.shaping).toBe('princess_seams');
    expect(saved.garment_spec.parameters.jacket).toMatchObject({
      variant: 'light_single_breasted', button_count: 2, lining: 'full',
    });
    expect(saved.pattern_method).toMatchObject({id: 'kroika-light-jacket', version: '0.1.0'});
    expect(saved.fit_settings.preset.id).toBe('woven_light_jacket_trial');
    expect(saved.fit_settings.wearing_ease_mm).toEqual(easeForGarment('jacket', 10));
  });

  it('shows all four jacket ease controls with a distinct lower-layer explanation', () => {
    const project = makeDemoProject('Жакет');
    project.garment_spec = configureGarment(project.garment_spec, 'jacket');
    project.fit_settings.wearing_ease_mm = easeForGarment('jacket', 10);
    render(<ConstructionEditor project={project} onSave={vi.fn()} />);

    expect(screen.getByLabelText(/^По груди/)).toHaveValue(11);
    expect(screen.getByLabelText(/^По талии/)).toHaveValue(13);
    expect(screen.getByLabelText(/^По бёдрам/)).toHaveValue(11);
    expect(screen.getByLabelText(/^По плечу/)).toHaveValue(9);
    expect(screen.getByText(/учитывает одежду нижнего слоя/i)).toBeVisible();
  });
});

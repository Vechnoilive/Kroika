import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {configureGarment, easeForGarment} from './garments';
import {makeDemoProject} from './demoProject';
import {ConstructionEditor, StyleEditor} from './ProjectWorkflow';
import type {GarmentAcceptanceStatus, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'trousers',
  silhouette: {fit: 'semi_fitted', confidence: 0.9},
  neckline: {front: 'unknown', confidence: 0},
  sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'straight', length_category: 'full', confidence: 0.9},
  uncertainties: [], targeted_questions: [],
};

const acceptance: GarmentAcceptanceStatus = {
  garment_type: 'trousers', name_ru: 'Прямые брюки',
  scope_ru: 'Естественная талия, прямые брючины, пояс, карманы и передняя молния.',
  formula_status: 'implemented', reference_status: 'automated_passed',
  invariant_status: 'automated_passed', paper_status: 'pending',
  expert_status: 'pending', toile_status: 'pending', production_allowed: false,
};

describe('stage 14 trousers and shorts UI', () => {
  it('saves the bounded trouser method with understandable fixed components', async () => {
    const project = makeDemoProject('Брюки');
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);
    render(<StyleEditor project={project} analysis={analysis} providerName="Qwen" acceptance={acceptance} onSave={onSave} />);

    await userEvent.click(screen.getByRole('radio', {name: /Прямые брюки/}));
    expect(screen.getByText('Прямая брючина')).toBeVisible();
    expect(screen.getByText('Боковые карманы')).toBeVisible();
    expect(screen.getByLabelText(/длина брюк от талии/i)).toHaveValue(100);
    expect(screen.queryByText('Посадка лифа')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.garment_type).toBe('trousers');
    expect(saved.garment_spec.parameters.trousers).toMatchObject({
      variant: 'straight_trousers', waist_position: 'natural',
      leg_shape: 'straight', pocket_type: 'slash', pleat_count: 0,
    });
    expect(saved.pattern_method).toMatchObject({id: 'kroika-woven-trousers', version: '0.1.0'});
    expect(saved.fit_settings.preset.id).toBe('woven_straight_trousers_trial');
    expect(saved.fit_settings.wearing_ease_mm).toEqual(easeForGarment('trousers'));
  });

  it('shows only waist and hip ease for shorts', () => {
    const project = makeDemoProject('Шорты');
    project.garment_spec = configureGarment(project.garment_spec, 'shorts');
    project.fit_settings.wearing_ease_mm = easeForGarment('shorts');
    render(<ConstructionEditor project={project} onSave={vi.fn()} />);

    expect(screen.getByLabelText(/^По талии/)).toHaveValue(2);
    expect(screen.getByLabelText(/^По бёдрам/)).toHaveValue(5);
    expect(screen.queryByLabelText(/^По груди/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^По плечу/)).not.toBeInTheDocument();
  });

  it('switches to the shorter bounded variant without exposing a fake jumpsuit', async () => {
    const project = makeDemoProject('Шорты');
    render(<StyleEditor project={project} analysis={analysis} providerName="Qwen" onSave={vi.fn()} />);

    await userEvent.click(screen.getByRole('radio', {name: /Классические шорты/}));
    expect(screen.getByLabelText(/длина шорт от талии/i)).toHaveValue(50);
    expect(screen.getByText('Прямой низ')).toBeVisible();
    expect(screen.queryByRole('radio', {name: /Комбинезон/})).not.toBeInTheDocument();
  });
});

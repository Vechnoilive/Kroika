import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {configureGarment, easeForGarment} from './garments';
import {makeDemoProject} from './demoProject';
import {ConstructionEditor, StyleEditor} from './ProjectWorkflow';
import type {GarmentAcceptanceStatus, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation',
  garment_category: 'dress',
  silhouette: {fit: 'semi_fitted', confidence: 0.8},
  neckline: {front: 'round', confidence: 0.8},
  sleeves: {present: false, length: 'sleeveless', confidence: 0.8},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 0.8},
  uncertainties: [],
  targeted_questions: [],
};

const acceptance: GarmentAcceptanceStatus = {
  garment_type: 'shirt',
  name_ru: 'Рубашка',
  scope_ru: 'Планка, стойка, воротник и длинный одношовный рукав.',
  formula_status: 'implemented',
  reference_status: 'automated_passed',
  invariant_status: 'automated_passed',
  paper_status: 'pending',
  expert_status: 'pending',
  toile_status: 'pending',
  production_allowed: false,
};

describe('stage 12 garment catalogue UI', () => {
  it('turns a shirt selection into one bounded, auditable component set', async () => {
    const project = makeDemoProject('Рубашка');
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);
    render(
      <StyleEditor
        project={project}
        analysis={analysis}
        providerName="Qwen"
        acceptance={acceptance}
        onSave={onSave}
      />,
    );

    await userEvent.click(screen.getByRole('radio', {name: /Рубашка/}));
    expect(screen.getByText('Воротник')).toBeVisible();
    expect(screen.getByText(/экспертная проверка, бумажная сборка и макет ещё не пройдены/i)).toBeVisible();
    expect(screen.getByLabelText(/длина рукава/i)).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.garment_type).toBe('shirt');
    expect(saved.garment_spec.parameters.closure).toMatchObject({type: 'buttons', location: 'center_front'});
    expect(saved.garment_spec.parameters.finishing).toMatchObject({front_placket: true, collar: true});
    expect(saved.fit_settings.preset.id).toBe('woven_shirt_trial');
    expect(saved.fit_settings.wearing_ease_mm).toEqual(easeForGarment('shirt'));
  });

  it('shows only waist and hip ease for the independent skirt block', async () => {
    const project = makeDemoProject('Юбка');
    project.garment_spec = configureGarment(project.garment_spec, 'skirt');
    project.fit_settings.wearing_ease_mm = easeForGarment('skirt');
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);
    render(<ConstructionEditor project={project} onSave={onSave} />);

    expect(screen.queryByLabelText(/^По груди/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^По талии/)).toHaveValue(2);
    expect(screen.getByLabelText(/^По бёдрам/)).toHaveValue(4);
    await userEvent.click(screen.getByRole('button', {name: /подтвердить ткань/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].status).toBe('inputs_confirmed');
  });
});

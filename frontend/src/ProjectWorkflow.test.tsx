import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {api} from './api';
import {makeDemoProject} from './demoProject';
import {ConstructionEditor, ProjectHistory, StyleEditor} from './ProjectWorkflow';
import type {ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation',
  garment_category: 'dress',
  silhouette: {fit: 'semi_fitted', confidence: 0.9},
  neckline: {front: 'v', confidence: 0.8},
  sleeves: {present: true, length: 'long', confidence: 0.8},
  lower_part: {type: 'straight', length_category: 'midi', confidence: 0.8},
  uncertainties: ['Спинка не видна'],
  targeted_questions: ['Подтвердите форму спинки.'],
};

function saved(candidate: ProjectDocument): ProjectDocument {
  return {...candidate, revision: candidate.revision + 1};
}

afterEach(() => vi.restoreAllMocks());

describe('stage 11 project editors', () => {
  it('shows unsupported AI guesses and saves only a human-confirmed supported style', async () => {
    const project = makeDemoProject('Платье');
    const onSave = vi.fn(async (candidate: ProjectDocument) => saved(candidate));
    render(<StyleEditor project={project} analysis={analysis} providerName="Qwen" onSave={onSave} />);

    expect(screen.getByText(/пока неподдержанные элементы/i)).toBeVisible();
    expect(screen.getByText(/горловина «v»/i)).toBeVisible();
    await userEvent.clear(screen.getByLabelText(/длина юбки от талии/i));
    await userEvent.type(screen.getByLabelText(/длина юбки от талии/i), '60');
    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const candidate = onSave.mock.calls[0][0];
    expect(candidate.garment_spec.selection_status).toBe('confirmed');
    expect(candidate.garment_spec.parameters.neckline.type).toBe('round');
    expect(candidate.garment_spec.parameters.sleeve.type).toBe('sleeveless');
    expect(candidate.garment_spec.parameters.skirt.length_from_waist_mm).toBe(600);
    expect(candidate.fit_settings.status).toBe('draft');
  });

  it('keeps wearing ease separate from seam allowance and confirms a bounded fabric', async () => {
    const project = makeDemoProject('Платье');
    project.body_measurements.status = 'ready';
    const onSave = vi.fn(async (candidate: ProjectDocument) => saved(candidate));
    render(<ConstructionEditor project={project} onSave={onSave} />);

    await userEvent.clear(screen.getByLabelText(/^По груди/));
    await userEvent.type(screen.getByLabelText(/^По груди/), '7');
    await userEvent.clear(screen.getByLabelText(/^Обычные швы/));
    await userEvent.type(screen.getByLabelText(/^Обычные швы/), '1.2');
    await userEvent.click(screen.getByRole('button', {name: /подтвердить ткань/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const candidate = onSave.mock.calls[0][0];
    expect(candidate.fit_settings.wearing_ease_mm.bust).toBe(70);
    expect(candidate.fit_settings.seam_allowances_mm.normal).toBe(12);
    expect(candidate.fit_settings.status).toBe('confirmed');
    expect(candidate.fabric_properties.structure).toBe('woven');
    expect(candidate.status).toBe('inputs_confirmed');
  });

  it('restores an old revision only after an explicit second click', async () => {
    const project = makeDemoProject('Платье');
    project.revision = 3;
    vi.spyOn(api, 'projectHistory').mockResolvedValue({items: [
      {revision: 3, status: 'draft', updated_at: '2026-09-15T12:00:00Z', change_summary: 'Текущая', is_current: true},
      {revision: 1, status: 'draft', updated_at: '2026-09-15T10:00:00Z', change_summary: 'Проект создан', is_current: false},
    ]});
    vi.spyOn(api, 'restoreProjectRevision').mockResolvedValue({...project, revision: 4});
    const onRestored = vi.fn();
    render(<ProjectHistory project={project} onRestored={onRestored} />);

    await userEvent.click(screen.getByText(/история проекта/i));
    await userEvent.click(await screen.findByRole('button', {name: 'Восстановить'}));
    expect(api.restoreProjectRevision).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', {name: /да, восстановить/i}));
    await waitFor(() => expect(onRestored).toHaveBeenCalledOnce());
    expect(api.restoreProjectRevision).toHaveBeenCalledWith(project, 1);
  });
});

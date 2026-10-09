import {useState} from 'react';
import {act, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {StyleEditor} from './ProjectWorkflow';
import {DesignIntentEditor} from './DesignIntentEditor';
import {buildDesignIntent} from './designIntent';
import {makeDemoProject} from './demoProject';
import type {GarmentDesignIntent, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation', garment_category: 'dress',
  silhouette: {fit: 'semi_fitted', confidence: 0.9}, neckline: {front: 'round', confidence: 0.9},
  sleeves: {present: false, length: 'sleeveless', confidence: 0.9},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 0.9}, uncertainties: [], targeted_questions: [],
  design_features: {
    elements: [{element_id: 'photo_flounce', type: 'flounce', variant: 'circular', location: 'hem',
      construction: 'separate_piece', count: 1, symmetry: 'symmetric', description_ru: 'Волан по низу',
      confidence: 0.9, evidence_ru: 'Расширенный свободный край', requires_confirmation: true}],
    layers: [{layer_id: 'main_fabric', role: 'main', coverage: 'full', opacity: 'opaque', drape: 'fluid', material_hint_ru: 'Основная ткань', confidence: 0.9, requires_confirmation: true}],
    proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 0.9},
  },
};
function fixture() {
  const project = makeDemoProject('Проверка фото');
  project.garment_spec.selection_status = 'proposed'; project.garment_spec.confirmed_at = null;
  project.garment_spec.design_intent = buildDesignIntent(analysis, project.garment_spec);
  return project;
}
function Harness() {
  const project = fixture();
  const [intent, setIntent] = useState<GarmentDesignIntent>(project.garment_spec.design_intent!);
  return <DesignIntentEditor intent={intent} spec={project.garment_spec} analysis={analysis} onChange={setIntent} onSave={vi.fn()} busy={false} />;
}

describe('compact photo review and one save-and-continue action', () => {
  it('shows the list first, reveals the specific unfinished detail and omits unused dimensions', async () => {
    render(<Harness />);
    const settings = screen.getByText('Настроить деталь 1 · конструкция и размеры').closest('details')!;
    expect(settings.open).toBe(false);
    expect(screen.getByLabelText('Глубина детали 1, см')).not.toBeVisible();
    expect(screen.queryByLabelText('Ширина детали 1, см')).not.toBeInTheDocument();
    await userEvent.click(within(screen.getByText(/Перед построением осталось уточнить/).parentElement!).getByRole('button', {name: 'Открыть: Деталь 1: Волан'}));
    expect(settings.open).toBe(true);
    expect(screen.getByLabelText('Глубина детали 1, см')).toBeVisible();
    expect(within(settings).getByText('Обязательно')).toBeVisible();
    expect(screen.getByLabelText('Тип детали 1')).not.toBeVisible();
  });
  it('saves incomplete geometry unchanged and allows measurement entry', async () => {
    const project = fixture();
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({...candidate, revision: candidate.revision + 1}));
    const next = vi.fn();
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} onContinueMeasurements={next} />);
    expect(screen.queryByRole('button', {name: 'Сохранить проверку деталей'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Подтвердить фасон'})).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', {name: /Сохранить и перейти к меркам/}));
    await waitFor(() => expect(next).toHaveBeenCalledOnce());
    expect(onSave).toHaveBeenCalledOnce();
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.selection_status).toBe('proposed');
    expect(saved.garment_spec.design_intent?.elements).toEqual(project.garment_spec.design_intent?.elements);
    expect(saved.garment_spec.design_intent?.elements[0].dimensions_mm?.depth).toBeNull();
    expect(saved.latest_generation).toBeNull();
  });
  it('confirms a complete reviewed design and continues in one save without a separate review-save click', async () => {
    const project = fixture();
    project.garment_spec.design_intent!.elements[0].dimensions_mm!.depth = 80;
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);
    const next = vi.fn();
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} onContinueMeasurements={next} />);
    await userEvent.click(screen.getByRole('button', {name: 'Всё на фото проверено'}));
    await userEvent.click(screen.getByRole('button', {name: /Сохранить и перейти к меркам/}));
    await waitFor(() => expect(next).toHaveBeenCalledOnce());
    expect(onSave).toHaveBeenCalledOnce();
    const saved = onSave.mock.calls[0][0].garment_spec;
    expect(saved.selection_status).toBe('confirmed');
    expect(saved.design_intent).toMatchObject({status: 'ready', review_status: 'confirmed'});
    expect(saved.design_intent!.elements[0]).toMatchObject({module_id: 'circular_hem_flounce_v1', dimensions_mm: {depth: 80}});
  });
  it('keeps the user on the editor when saving fails', async () => {
    const onSave = vi.fn(async () => {throw new Error('Сбой сохранения');});
    const next = vi.fn();
    render(<StyleEditor project={fixture()} analysis={analysis} providerName="Gemini" onSave={onSave} onContinueMeasurements={next} />);
    await userEvent.click(screen.getByRole('button', {name: /Сохранить и перейти к меркам/}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Не удалось сохранить/);
    expect(next).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Глубина детали 1, см')).toHaveValue(null);
  });
  it('locks editable controls during the final save so newer edits cannot be lost', async () => {
    const project = fixture();
    let complete!: (project: ProjectDocument) => void;
    const onSave = vi.fn((_candidate: ProjectDocument) => new Promise<ProjectDocument>(resolve => {complete = resolve;}));
    const next = vi.fn();
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} onContinueMeasurements={next} />);
    await userEvent.click(screen.getByRole('button', {name: /Сохранить и перейти к меркам/}));
    expect(screen.getByLabelText('Глубина детали 1, см')).toBeDisabled();
    expect(screen.getByLabelText('Эта деталь действительно есть на изделии')).toBeDisabled();
    await act(async () => {complete(onSave.mock.calls[0][0]);});
    expect(next).toHaveBeenCalledOnce();
  });
  it('reveals foundation settings when an existing size prevents confirmation', async () => {
    const project = fixture();
    project.garment_spec.design_intent!.elements[0].dimensions_mm!.depth = 80;
    project.garment_spec.parameters.neckline.front_depth_mm = 300;
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);
    const next = vi.fn();
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} onContinueMeasurements={next} />);
    const foundation = screen.getByText('Основа изделия').closest('details')!;
    expect(foundation.open).toBe(false);
    await userEvent.click(screen.getByRole('button', {name: 'Всё на фото проверено'}));
    await userEvent.click(screen.getByRole('button', {name: /Сохранить и перейти к меркам/}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Основа изделия/);
    expect(foundation.open).toBe(true);
    expect(onSave).not.toHaveBeenCalled();
    expect(next).not.toHaveBeenCalled();
  });
  it('bulk confirmation does not invent missing dimensions or retain confirmation after changing a size', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', {name: 'Всё на фото проверено'}));
    expect(screen.getByLabelText('Я проверил(а) эту деталь по фотографии')).toBeChecked();
    expect(screen.getByText('Проверьте размеры')).toBeVisible();
    expect(screen.getByLabelText('Глубина детали 1, см')).toHaveValue(null);
    await userEvent.click(screen.getByText('Настроить деталь 1 · конструкция и размеры'));
    await userEvent.type(screen.getByLabelText('Глубина детали 1, см'), '8');
    expect(screen.getByLabelText('Я проверил(а) эту деталь по фотографии')).not.toBeChecked();
  });
});

import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App from './App';
import {api} from './api';
import {buildDesignIntent, finalizeDesignIntent} from './designIntent';
import {matchingModule} from './designModules';
import {buildEngineRequest, canonicalGenerationPayload} from './generation';
import {makeDemoProject} from './demoProject';
import {StyleEditor} from './ProjectWorkflow';
import type {MeasurementCatalog, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress',
  silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1},
  sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'full', confidence: 1},
  uncertainties: [], targeted_questions: [],
  design_features: {
    elements: [{
      element_id: 'photo_flounce', type: 'flounce', variant: 'circular',
      description_ru: 'Волан по низу.', location: 'hem', construction: 'separate_piece',
      count: 1, symmetry: 'symmetric', confidence: 1, evidence_ru: 'Виден волан.',
      requires_confirmation: false,
    }],
    layers: [{
      layer_id: 'main', role: 'main', coverage: 'full', material_hint_ru: 'Основная ткань.',
      opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false,
    }],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1,
    },
  },
};

function reviewedProject(): ProjectDocument {
  const project = makeDemoProject('Волан');
  project.style_analysis = analysis;
  project.garment_spec.selection_status = 'proposed';
  project.garment_spec.confirmed_at = null;
  const intent = buildDesignIntent(analysis, project.garment_spec)!;
  intent.elements[0].dimensions_mm = {width: null, length: null, depth: 80, spacing: null};
  intent.elements[0].confirmed_by_user = true;
  intent.layers[0].confirmed_by_user = true;
  intent.proportions.confirmed_by_user = true;
  project.garment_spec.design_intent = finalizeDesignIntent(intent, project.garment_spec, analysis);
  return project;
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('design modules and independent measurement entry', () => {
  it('adds crossed draping and persists its measured fullness in the hash', async () => {
    const project = reviewedProject();
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({...candidate, revision: candidate.revision + 1}));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), 'crossed_bodice_drape_v1');
    await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
    await userEvent.type(screen.getByLabelText('Ширина детали 2, см'), '5');
    await userEvent.type(screen.getByLabelText('Глубина детали 2, см'), '10');
    await userEvent.type(screen.getByLabelText('Расстояние детали 2, см'), '3');
    await userEvent.click(screen.getAllByLabelText('Я проверил(а) эту деталь по фотографии')[1]);
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.design_intent?.elements[1]).toMatchObject({module_id: 'crossed_bodice_drape_v1', count: 2, dimensions_mm: {width: 50, depth: 100, spacing: 30}});
    expect(canonicalGenerationPayload(await buildEngineRequest(saved)).hash_contract_version).toBe('1.6.0');
  });

  it('keeps measured arcs at a raised waist through saving', async () => {
    const project = reviewedProject();
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({...candidate, revision: candidate.revision + 1}));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText('Линия талии'), 'high');
    await userEvent.type(screen.getByLabelText('Смещение линии талии, см'), '3');
    await userEvent.type(screen.getByLabelText('Обхват на новой линии талии, см'), '80');
    await userEvent.type(screen.getByLabelText('Задняя дуга на новой линии талии, см'), '40');
    await userEvent.click(screen.getByLabelText('Я проверил(а) пропорции'));
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.design_intent?.proportions).toMatchObject({module_id: 'parametric_visual_proportions_v1', waist_shift_mm: 30, waist_level_circumference_mm: 800, back_waist_level_arc_mm: 400});
    expect(canonicalGenerationPayload(await buildEngineRequest(saved)).hash_contract_version).toBe('1.10.0');
  });

  it('adds a peplum from the catalog and includes its sizes in the saved request', async () => {
    const project = reviewedProject();
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({...candidate, revision: candidate.revision + 1}));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), 'circular_waist_peplum_v1');
    await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
    await userEvent.type(screen.getByLabelText('Глубина детали 2, см'), '12');
    await userEvent.click(screen.getAllByLabelText('Я проверил(а) эту деталь по фотографии')[1]);
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.design_intent?.elements[1]).toMatchObject({
      included: true, support_status: 'supported', module_id: 'circular_waist_peplum_v1',
      dimensions_mm: {depth: 120},
    });
    const payload = canonicalGenerationPayload(await buildEngineRequest(saved));
    expect(payload.hash_contract_version).toBe('1.5.0');
    expect(payload.garment_spec.details.elements[0].dimensions_mm.depth).toBe(120);
  });

  it('keeps a legacy saved intent unchanged when constructing the engine request', async () => {
    const project = reviewedProject();
    delete project.garment_spec.design_intent!.coverage_schema_version;
    const request = await buildEngineRequest(project);
    expect(request.garment_spec.design_intent).not.toHaveProperty('coverage_schema_version');
    expect(canonicalGenerationPayload(request)).toEqual(canonicalGenerationPayload(project));
  });

  it('preserves a confirmed flounce through editing, saving and the hashed engine request', async () => {
    const project = reviewedProject();
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({...candidate, revision: candidate.revision + 1}));
    const rendered = render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    await userEvent.clear(screen.getByLabelText('Глубина детали 1, см'));
    await userEvent.type(screen.getByLabelText('Глубина детали 1, см'), '9');
    await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.design_intent?.elements[0]).toMatchObject({
      included: true, support_status: 'supported', module_id: 'circular_hem_flounce_v1',
      dimensions_mm: {depth: 90},
    });
    rendered.unmount();
    render(<StyleEditor project={saved} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    expect(screen.getByLabelText('Глубина детали 1, см')).toHaveValue(9);
    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    const confirmed = onSave.mock.calls[1][0];
    const request = await buildEngineRequest(confirmed);
    expect(request.garment_spec.design_intent.elements[0].module_id).toBe('circular_hem_flounce_v1');
    expect(canonicalGenerationPayload(request).garment_spec.modeling_elements[0].dimensions_mm.depth).toBe(90);
    expect(canonicalGenerationPayload(request).garment_spec.coverage_contract.required_module_ids)
      .toContain('circular_hem_flounce_v1');
    expect((await buildEngineRequest(project)).input_hash).not.toBe(request.input_hash);
  });

  it('explains missing dimensions separately from an absent geometry module', async () => {
    const project = reviewedProject();
    const intent = project.garment_spec.design_intent!;
    intent.elements[0].dimensions_mm = {width: null, length: null, depth: null, spacing: null};
    intent.elements[0].support_status = 'planned';
    intent.elements[0].module_id = null;
    intent.status = 'partial';
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={vi.fn()} />);
    expect(screen.getByText('Проверьте размеры')).toBeVisible();
    await userEvent.click(screen.getByText('Настроить деталь 1 · конструкция и размеры'));
    expect(screen.getByText(/глубина 3–40 см/)).toBeVisible();
    expect(screen.getByText(/остальные размеры оставьте пустыми/i)).toBeVisible();
    expect(matchingModule('element', intent.elements[0], project.garment_spec)).toBeUndefined();
    intent.elements[0].dimensions_mm = {} as never;
    expect(matchingModule('element', intent.elements[0], project.garment_spec)).toBeUndefined();
  });

  it('lets an unfinished drape project save measurements and stays on the measurement step', async () => {
    const project = reviewedProject();
    const intent = project.garment_spec.design_intent!;
    intent.elements[0] = {...intent.elements[0], type: 'drape', variant: 'soft',
      location: 'bodice_front', support_status: 'planned', module_id: null,
      dimensions_mm: {width: null, length: null, depth: null, spacing: null}};
    intent.status = 'partial';
    localStorage.setItem('kroika:last-project-id', project.project_id);
    vi.spyOn(api, 'readiness').mockResolvedValue({status: 'ok', service: 'kroika-backend',
      version: '0.27.0', database: 'ok', ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.12.0'});
    vi.spyOn(api, 'listProjects').mockResolvedValue({items: []});
    vi.spyOn(api, 'garmentCatalogue').mockResolvedValue({items: []});
    vi.spyOn(api, 'getProject').mockResolvedValue(project);
    vi.spyOn(api, 'projectHistory').mockResolvedValue({items: []});
    const catalog: MeasurementCatalog = {schema_version: '1.0.0', catalog_version: '1.0.0',
      garment_type: 'dress', sleeve_type: 'sleeveless', normalized_unit: 'mm', display_units: ['cm', 'mm'],
      source_options: ['user', 'preset', 'derived'], measurements: [{id: 'bust', label_ru: 'Обхват груди',
        group: 'Обхваты', kind: 'linear', unit: 'mm', minimum: 600, maximum: 1800,
        instruction_ru: 'Измерьте обхват груди.', illustration: 'bust', applicable_to: ['dress'],
        required_for: ['dress'], sleeve_only: false, required: true}]};
    vi.spyOn(api, 'measurementCatalog').mockResolvedValue(catalog);
    vi.spyOn(api, 'listMeasurementProfiles').mockResolvedValue({items: []});
    vi.spyOn(api, 'validateMeasurements').mockResolvedValue({status: 'ready', required_count: 1,
      completed_count: 1, issues: []});
    const save = vi.spyOn(api, 'replaceProject').mockImplementation(async (candidate) =>
      ({...candidate, revision: candidate.revision + 1}));
    const generate = vi.spyOn(api, 'generatePattern');
    render(<App />);
    await userEvent.click(await screen.findByRole('button', {name: 'Перейти к шагу 4: Ввести мерки'}));
    await userEvent.type(await screen.findByLabelText(/Обхват груди, см/), '92');
    await waitFor(() => expect(save).toHaveBeenCalled(), {timeout: 4000});
    expect(screen.getByLabelText(/Обхват груди, см/)).toHaveValue('92');
    expect(screen.getByText('Мерки можно заполнить заранее')).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /проверить и завершить/i}));
    await waitFor(() => expect(save.mock.calls.at(-1)?.[0].body_measurements.status).toBe('ready'));
    expect(save.mock.calls.at(-1)?.[0].garment_spec.design_intent?.elements[0].included).toBe(true);
    expect(save.mock.calls.at(-1)?.[0].garment_spec.selection_status).toBe('proposed');
    expect(screen.getByLabelText(/Обхват груди, см/)).toHaveValue('92');
    expect(generate).not.toHaveBeenCalled();
  });
});

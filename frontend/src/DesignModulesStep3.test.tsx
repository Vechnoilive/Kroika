import {useState} from 'react';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {DesignIntentEditor} from './DesignIntentEditor';
import {StyleEditor} from './ProjectWorkflow';
import {buildDesignIntent, reevaluateDesignIntent} from './designIntent';
import {matchingModule, moduleIds} from './designModules';
import {makeDemoProject} from './demoProject';
import {canonicalGenerationPayload, stableJson} from './generation';
import type {GarmentDesignIntent, GarmentSpec, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 1}, uncertainties: [], targeted_questions: [],
  design_features: {elements: [], layers: [{layer_id: 'fabric', role: 'main', coverage: 'full', material_hint_ru: 'Ткань', opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false}],
    proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1}},
};
function fixture() {
  const project = makeDemoProject('Конструктивные детали');
  const intent = buildDesignIntent(analysis, project.garment_spec)!;
  intent.layers[0].confirmed_by_user = true; intent.proportions.confirmed_by_user = true;
  return {project, spec: project.garment_spec, intent};
}
function Harness({spec, initial, onSave}: {spec: GarmentSpec; initial: GarmentDesignIntent; onSave: (intent: GarmentDesignIntent) => Promise<void>}) {
  const [intent, setIntent] = useState(initial);
  return <DesignIntentEditor intent={intent} spec={spec} analysis={analysis} busy={false} onChange={setIntent} onSave={onSave} />;
}
async function add(id: string) {
  await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), id);
  await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
}
async function save(onSave: ReturnType<typeof vi.fn>) {
  await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
  await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
  return onSave.mock.calls[0][0] as GarmentDesignIntent;
}

describe('structural modules stage 3', () => {
  it('does not offer collar replacement recipes forbidden by the shirt foundation', () => {
    const {spec, intent} = fixture();
    spec.garment_type = 'shirt';
    spec.parameters.sleeve.type = 'long';
    render(<Harness spec={spec} initial={intent} onSave={vi.fn()} />);
    const catalog = screen.getByLabelText('Добавить деталь из каталога') as HTMLSelectElement;
    const ids = Array.from(catalog.options).map((option) => option.value);
    for (const id of ['fitted_two_piece_hood_v3', 'shaped_flat_collar_v3', 'shawl_collar_v3']) {
      expect(ids).not.toContain(id);
    }
    expect(ids).toContain('shaped_cuff_v3');
  });

  it('adds 22 structural recipes to the shared catalogue', () => expect(moduleIds('structural').size).toBe(22));
  it('saves an explicit polygon and its attachment in millimetres and hashes every vertex', async () => {
    const {project, spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await add('explicit_polygon_detail_v3');
    await userEvent.selectOptions(screen.getByLabelText('Расположение детали 1'), 'skirt_front');
    expect(screen.getByLabelText('Срез крепления детали 1')).toHaveValue('hem');
    await userEvent.selectOptions(screen.getByLabelText('Расположение детали 1'), 'bodice_back');
    expect(screen.getByLabelText('Срез крепления детали 1')).toHaveValue('neckline');
    await userEvent.selectOptions(screen.getByLabelText('Расположение детали 1'), 'skirt_front');
    await userEvent.selectOptions(screen.getByLabelText('Срез крепления детали 1'), 'hem');
    fireEvent.change(screen.getByLabelText('Контур детали 1, см'), {target: {value: '[[0,0],[10,0],[8,6],[0,6]]'}});
    await userEvent.type(screen.getByLabelText('Длина детали 1, см'), '10');
    await userEvent.type(screen.getByLabelText('Расстояние детали 1, см'), '3');
    const saved = await save(onSave);
    expect(saved.elements[0]).toMatchObject({module_id: 'explicit_polygon_detail_v3', count: 2,
      outline_mm: [[0,0],[100,0],[80,60],[0,60]], placement: {side: 'both', edge: 'hem', outline_edge_index: 0}});
    project.garment_spec.design_intent = saved;
    const first = stableJson(canonicalGenerationPayload(project));
    expect(canonicalGenerationPayload(project).hash_contract_version).toBe('1.9.0');
    saved.elements[0].outline_mm![2][0] += 5;
    expect(stableJson(canonicalGenerationPayload(project))).not.toBe(first);
  });
  it('keeps missing or mismatched polygon geometry unconfirmed', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />); await add('explicit_polygon_detail_v3');
    await userEvent.type(screen.getByLabelText('Длина детали 1, см'), '10');
    await userEvent.type(screen.getByLabelText('Расстояние детали 1, см'), '3');
    fireEvent.change(screen.getByLabelText('Контур детали 1, см'), {target: {value: '[[0,0],[9,0],[0,6]]'}});
    const result = await save(onSave);
    expect(result.elements[0].support_status).toBe('planned');
    expect(result.elements[0].module_id).toBeNull();
    expect(matchingModule('element', result.elements[0], spec)).toBeUndefined();
  });
  it('preserves decorative orientation and placement without turning a stitch into a cut seam', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />); await add('placed_decorative_stitch_v3');
    await userEvent.selectOptions(screen.getByLabelText('Направление детали 1'), 'horizontal');
    await userEvent.type(screen.getByLabelText('Длина детали 1, см'), '8');
    await userEvent.type(screen.getByLabelText('Расстояние детали 1, см'), '4');
    const result = await save(onSave);
    expect(result.elements[0]).toMatchObject({type: 'decorative_seam', construction: 'applied', module_id: 'placed_decorative_stitch_v3', placement: {orientation: 'horizontal', side: 'both'}});
  });
  it('changes a previously selected lacing recipe to hooks and saves the back answer', async () => {
    const {project, intent} = fixture();
    intent.elements.push({source_element_id: 'back_detail', type: 'closure', variant: 'tie', location: 'bodice_back', construction: 'separate_piece', count: 1, symmetry: 'symmetric', confidence: 1, evidence_ru: 'Спинка', description_ru: 'Шнуровка', requires_confirmation: false, included: true, confirmed_by_user: true, support_status: 'supported', module_id: 'back_lacing_v1', selected_module_id: 'back_lacing_v1'});
    project.garment_spec.parameters.closure = {type: 'lacing', location: 'center_back', length_mm: 350, loop_pitch_mm: 80};
    project.garment_spec.design_intent = reevaluateDesignIntent(intent, project.garment_spec, analysis);
    const onSave = vi.fn(async (p: ProjectDocument) => ({...p, revision: p.revision + 1}));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    await userEvent.click(screen.getByRole('radio', {name: /Крючки и петли/i}));
    await userEvent.click(screen.getByRole('button', {name: /Сохранить проверку деталей/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const saved = onSave.mock.calls.at(-1)![0];
    expect(saved.garment_spec.parameters.closure.type).toBe('hooks');
    expect(saved.garment_spec.design_intent?.elements[0]).toMatchObject({variant: 'hooks', module_id: 'back_hooks_v3', support_status: 'supported'});
    expect(canonicalGenerationPayload(saved).hash_contract_version).toBe('1.9.0');
  });
});

import {useState} from 'react';
import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {DesignIntentEditor} from './DesignIntentEditor';
import {buildDesignIntent, reevaluateDesignIntent, finalizeDesignIntent} from './designIntent';
import {matchingModule} from './designModules';
import {makeDemoProject} from './demoProject';
import {canonicalGenerationPayload, stableJson} from './generation';
import type {GarmentDesignIntent, GarmentSpec, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 1}, uncertainties: [], targeted_questions: [],
  design_features: {elements: [], layers: [{layer_id: 'fabric', role: 'main', coverage: 'full',
    material_hint_ru: 'Ткань', opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false}],
  proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1}},
};
function fixture() {
  const spec = makeDemoProject('Отделка').garment_spec;
  const intent = buildDesignIntent(analysis, spec)!;
  intent.layers[0].confirmed_by_user = true; intent.proportions.confirmed_by_user = true;
  return {spec, intent};
}
function Harness({spec, initial, onSave}: {spec: GarmentSpec; initial: GarmentDesignIntent; onSave: (intent: GarmentDesignIntent) => Promise<void>}) {
  const [intent, setIntent] = useState(initial);
  return <DesignIntentEditor intent={intent} spec={spec} analysis={analysis} busy={false} onChange={setIntent} onSave={onSave} />;
}
async function add(id: string) {
  await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), id);
  await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
}
async function dimensions(values: Record<string, string>) {
  for (const [label, value] of Object.entries(values)) await userEvent.type(screen.getByLabelText(`${label} детали 1, см`), value);
}
async function save(onSave: ReturnType<typeof vi.fn>) {
  await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
  await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
  return onSave.mock.calls[0][0] as GarmentDesignIntent;
}
describe('module expansion step 2', () => {
  it('saves placed multiple tucks with first offset and interval in millimetres', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await add('placed_skirt_tucks_v2');
    await userEvent.clear(screen.getByLabelText('Количество детали 1'));
    await userEvent.type(screen.getByLabelText('Количество детали 1'), '4');
    await dimensions({Ширина: '2.5', Длина: '15', Глубина: '0.5', Расстояние: '3'});
    const result = await save(onSave);
    expect(result.elements[0]).toMatchObject({module_id: 'placed_skirt_tucks_v2', selected_module_id: 'placed_skirt_tucks_v2',
      count: 4, symmetry: 'symmetric', dimensions_mm: {width: 25, length: 150, depth: 5, spacing: 30}});
  });
  it('retains the diagonal recipe through unconfirmed edits, save and reopening', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await add('diagonal_bodice_drape_v2');
    await dimensions({Ширина: '3', Глубина: '6', Расстояние: '1.5'});
    await userEvent.selectOptions(screen.getByLabelText('Сторона детали 1'), 'left');
    await userEvent.clear(screen.getByLabelText('Смещение начала детали 1, см'));
    await userEvent.type(screen.getByLabelText('Смещение начала детали 1, см'), '1.5');
    const result = await save(onSave);
    expect(result.elements[0]).toMatchObject({module_id: 'diagonal_bodice_drape_v2', count: 1,
      symmetry: 'asymmetric', placement: {side: 'left', offset_mm: 15}});
    expect(reevaluateDesignIntent(JSON.parse(JSON.stringify(result)), spec, analysis).elements[0].module_id).toBe('diagonal_bodice_drape_v2');
    const project = makeDemoProject('Размещение'); project.garment_spec.design_intent = result;
    expect(canonicalGenerationPayload(project).hash_contract_version).toBe('1.8.0');
    const before = stableJson(canonicalGenerationPayload(project)); result.elements[0].placement!.side = 'right';
    expect(stableJson(canonicalGenerationPayload(project))).not.toBe(before);
  });
  it('keeps the chosen cascade instead of remapping it to local edge trim', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await add('placed_cascade_flounce_v2');
    await dimensions({Длина: '25', Глубина: '9', Расстояние: '3.5'});
    expect(screen.queryByLabelText('Срез крепления детали 1')).not.toBeInTheDocument();
    expect((await save(onSave)).elements[0].module_id).toBe('placed_cascade_flounce_v2');
  });
  it('offers actual skirt edges and no unused sector angle for a ruffle', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await add('placed_edge_ruffle_v2');
    const select = screen.getByLabelText('Срез крепления детали 1') as HTMLSelectElement;
    expect([...select.options].map((option) => option.value)).toEqual(['hem', 'waist']);
    expect(screen.queryByLabelText('Угол сектора детали 1')).not.toBeInTheDocument();
    await dimensions({Ширина: '6', Длина: '10', Глубина: '8', Расстояние: '1'});
    const result = await save(onSave);
    expect(result.elements[0]).toMatchObject({module_id: 'placed_edge_ruffle_v2', count: 2, placement: {side: 'both', edge: 'hem'}});
    expect(matchingModule('element', {...result.elements[0], location: 'sleeve'}, spec)).toBeUndefined();
    expect(matchingModule('element', {...result.elements[0], placement: {side: 'both', edge: 'neckline'}}, spec)).toBeUndefined();
  });
  it('requires real tiers for the tiered profile and preserves excluded dimensions', async () => {
    const {spec, intent} = fixture(); const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    intent.proportions.hem_shape = 'tiered';
    expect(reevaluateDesignIntent(intent, spec, analysis).status).toBe('partial');
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await add('tiered_hem_ruffle_v2'); await dimensions({Ширина: '6', Глубина: '8'});
    const result = await save(onSave); expect(result.status).toBe('ready');
    expect(result.proportions.module_id).toBe('parametric_visual_proportions_v1');
    const excluded = structuredClone(result); excluded.elements[0].included = false;
    expect(reevaluateDesignIntent(excluded, spec, analysis).status).toBe('partial');
    expect(excluded.elements[0].dimensions_mm?.depth).toBe(80);
  });
  it('blocks unresolved full-front unfolding combinations while allowing back fullness', () => {
    const {spec, intent} = fixture();
    const base = {source_element_id: 'parallel', type: 'drape' as const, variant: 'soft' as const, location: 'bodice_front' as const,
      construction: 'integrated' as const, count: 2, symmetry: 'symmetric' as const, description_ru: 'Драпировка', confidence: 1,
      evidence_ru: 'Фото', requires_confirmation: false, included: true, confirmed_by_user: true,
      support_status: 'supported' as const, module_id: 'integrated_bodice_drape_v2', selected_module_id: 'integrated_bodice_drape_v2',
      dimensions_mm: {width: 20, depth: 40, spacing: 30, length: null}};
    intent.elements = [base, {...base, source_element_id: 'diagonal', construction: 'separate_piece', count: 1, symmetry: 'asymmetric',
      module_id: 'diagonal_bodice_drape_v2', selected_module_id: 'diagonal_bodice_drape_v2',
      dimensions_mm: {width: 30, depth: 60, spacing: 15, length: null}, placement: {side: 'right'}}];
    expect(() => finalizeDesignIntent(intent, spec, analysis)).toThrow('Параллельные раскрытия переда');
    intent.elements[0].location = 'bodice_back';
    expect(finalizeDesignIntent(intent, spec, analysis).status).toBe('ready');
  });

});

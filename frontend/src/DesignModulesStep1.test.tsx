import {useState} from 'react';
import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {DesignIntentEditor} from './DesignIntentEditor';
import {buildDesignIntent, reevaluateDesignIntent} from './designIntent';
import {applicableRule, DESIGN_MODULES, matchingModule, moduleDiagnosis} from './designModules';
import {makeDemoProject} from './demoProject';
import {canonicalGenerationPayload, stableJson} from './generation';
import type {GarmentDesignIntent, GarmentSpec, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 1},
  uncertainties: [], targeted_questions: [],
  design_features: {
    elements: [{element_id: 'photo_drape', type: 'drape', variant: 'soft', location: 'bodice_front',
      construction: 'layered', count: null, symmetry: 'unknown', description_ru: 'Складки на лифе.',
      confidence: 1, evidence_ru: 'Две диагональные полосы.', requires_confirmation: true}],
    layers: [{layer_id: 'fabric', role: 'main', coverage: 'full', material_hint_ru: 'Ткань',
      opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false}],
    proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1},
  },
};

function fixture(source = analysis) {
  const spec = makeDemoProject('Проверка модулей').garment_spec;
  const intent = buildDesignIntent(source, spec)!;
  intent.layers[0].confirmed_by_user = true;
  intent.proportions.confirmed_by_user = true;
  return {spec, intent};
}

function Harness({spec, initial, source = analysis, onSave = vi.fn()}:
  {spec: GarmentSpec; initial: GarmentDesignIntent; source?: StyleAnalysis; onSave?: (intent: GarmentDesignIntent) => Promise<void>}) {
  const [intent, setIntent] = useState(initial);
  return <DesignIntentEditor intent={intent} spec={spec} analysis={source} busy={false} onChange={setIntent} onSave={onSave} />;
}

describe('module expansion step 1', () => {
  it('explains fit restrictions instead of offering a waist dart absent from the loose block', () => {
    const {spec, intent} = fixture();
    spec.parameters.bodice_fit = 'loose';
    const recipe = DESIGN_MODULES.find((m) => m.id === 'front_waist_to_side_dart_v1')!;
    expect(applicableRule(recipe, spec)).toBeUndefined();
    const item = {...intent.elements[0], type: 'dart', variant: 'shaped', location: 'bodice_front',
      construction: 'integrated', count: 2, symmetry: 'symmetric',
      selected_module_id: recipe.id, dimensions_mm: {width: 10, length: null, depth: null, spacing: null}};
    const diagnosis = moduleDiagnosis('element', item, spec);
    expect(diagnosis.label).toBe('Проверьте конструкцию');
    expect(diagnosis.reasons).toContain('посадка: прилегающая / полуприлегающая.');
  });

  it('clears a pinned drape recipe when changing type and saves a flounce', async () => {
    const {spec, intent} = fixture();
    intent.elements[0] = {...intent.elements[0], selected_module_id: 'crossed_bodice_drape_v1',
      module_id: 'crossed_bodice_drape_v1', count: 2, symmetry: 'symmetric',
      dimensions_mm: {width: 50, length: null, depth: 80, spacing: 30}};
    const onSave = vi.fn(async (_intent: GarmentDesignIntent) => undefined);
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText('Тип детали 1'), 'flounce');
    expect(screen.queryByText('Геометрия ещё не реализована')).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Выбрать конструкцию детали 1'), 'circular_hem_flounce_v1');
    expect(screen.getByLabelText('Вариант детали 1')).toHaveDisplayValue('Круговой');
    expect(screen.getByLabelText('Расположение детали 1')).toHaveDisplayValue('Низ изделия');
    expect(screen.getByLabelText('Ширина детали 1, см')).toBeDisabled();
    expect(screen.getByLabelText('Глубина детали 1, см')).toBeEnabled();
    await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].elements[0]).toMatchObject({type: 'flounce',
      selected_module_id: 'circular_hem_flounce_v1', module_id: 'circular_hem_flounce_v1',
      dimensions_mm: {width: null, length: null, depth: 80, spacing: null}});
  });

  it('explains a drape count and symmetry mismatch, then saves the corrected recipe', async () => {
    const {spec, intent} = fixture();
    const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    expect(screen.getByText('Проверьте конструкцию')).toBeVisible();
    expect(screen.getByText('количество: 2.')).toBeVisible();
    expect(screen.getByText('симметрия: симметричная.')).toBeVisible();
    await userEvent.type(screen.getByLabelText('Количество детали 1'), '2');
    await userEvent.selectOptions(screen.getByLabelText('Симметрия детали 1'), 'symmetric');
    expect(screen.getByText('Проверьте размеры')).toBeVisible();
    for (const [label, value] of [['Ширина', '5'], ['Глубина', '10'], ['Расстояние', '3']]) {
      await userEvent.type(screen.getByLabelText(`${label} детали 1, см`), value);
    }
    await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].elements[0]).toMatchObject({source_element_id: 'photo_drape',
      module_id: 'crossed_bodice_drape_v1', count: 2, symmetry: 'symmetric', dimensions_mm: {width: 50, depth: 100, spacing: 30}});
  });

  it('preserves asymmetry until the user explicitly selects another construction', async () => {
    const {spec, intent} = fixture();
    intent.elements[0].symmetry = 'asymmetric';
    intent.elements[0].count = 2;
    const snapshot = JSON.stringify(analysis);
    render(<Harness spec={spec} initial={intent} />);
    expect(screen.getByLabelText('Симметрия детали 1')).toHaveValue('asymmetric');
    await userEvent.selectOptions(screen.getByLabelText('Выбрать конструкцию детали 1'), 'crossed_bodice_drape_v1');
    expect(screen.getByLabelText('Симметрия детали 1')).toHaveValue('symmetric');
    expect(screen.getByLabelText('Я проверил(а) эту деталь по фотографии')).not.toBeChecked();
    expect(JSON.stringify(analysis)).toBe(snapshot);
    expect(screen.getByLabelText('Описание детали 1')).toHaveValue('Складки на лифе.');
  });

  it('allows explicit mapping of an unsupported observation while retaining its source', async () => {
    const source = structuredClone(analysis);
    source.design_features!.elements = [];
    source.unsupported_features = ['Драпировка на переде'];
    const {spec, intent} = fixture(source);
    const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} source={source} onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText('Выбрать конструкцию детали 1'), 'crossed_bodice_drape_v1');
    for (const [label, value] of [['Ширина', '5'], ['Глубина', '10'], ['Расстояние', '3']]) {
      await userEvent.type(screen.getByLabelText(`${label} детали 1, см`), value);
    }
    await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].elements[0]).toMatchObject({source_element_id: 'unsupported_1',
      description_ru: 'Драпировка на переде', type: 'drape', module_id: 'crossed_bodice_drape_v1'});
    expect(source.unsupported_features).toEqual(['Драпировка на переде']);
  });

  it('adds an adjustable waistband even when its rule has no count', async () => {
    const {spec, intent} = fixture();
    spec.garment_type = 'skirt';
    intent.elements = [];
    render(<Harness spec={spec} initial={intent} />);
    await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), 'adjustable_straight_waistband_v1');
    await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
    expect(screen.getByLabelText('Количество детали 1')).toHaveValue(1);
    await userEvent.type(screen.getByLabelText('Ширина детали 1, см'), '7');
    await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
    expect(screen.getAllByText('Будет учтено')).toHaveLength(3);
  });

  it('distinguishes missing, forbidden and out-of-range dimensions', () => {
    const {spec, intent} = fixture();
    const item = {...intent.elements[0], count: 2, symmetry: 'symmetric' as const,
      dimensions_mm: {width: 120, length: 200, depth: null, spacing: 30}};
    const diagnosis = moduleDiagnosis('element', item, spec);
    expect(diagnosis.label).toBe('Проверьте размеры');
    expect(diagnosis.reasons).toEqual(['Ширина: допустимо 3–10 см.',
      'Длина: оставьте пустым для этой конструкции.', 'Глубина: укажите размер.']);
    expect(matchingModule('element', item, spec)).toBeUndefined();
  });

  it('includes the new operations and their dimensions in the cache key', () => {
    const project = makeDemoProject('Новые операции');
    const {spec, intent} = fixture();
    intent.elements = [{...intent.elements[0], type: 'tuck', variant: 'straight', location: 'skirt_front',
      construction: 'integrated', count: 1, symmetry: 'symmetric', confirmed_by_user: true,
      dimensions_mm: {width: null, length: 150, depth: 5, spacing: null}},
    {...intent.elements[0], source_element_id: 'stitch', type: 'decorative_seam', variant: 'straight',
      location: 'skirt_back', construction: 'applied', count: 2, symmetry: 'symmetric', confirmed_by_user: true,
      dimensions_mm: {width: null, length: 150, depth: null, spacing: 30}}];
    project.garment_spec.design_intent = reevaluateDesignIntent(intent, spec, analysis);
    expect(project.garment_spec.design_intent.elements.map((item) => item.module_id))
      .toEqual(['center_stitched_tuck_v1', 'paired_straight_decorative_stitch_v1']);
    const before = stableJson(canonicalGenerationPayload(project));
    project.garment_spec.design_intent.elements[1].dimensions_mm!.spacing = 40;
    expect(stableJson(canonicalGenerationPayload(project))).not.toBe(before);
  });

  it('adds both new modules from the catalog and saves fractional centimetres', async () => {
    const {spec, intent} = fixture();
    intent.elements = [];
    const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={spec} initial={intent} onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), 'center_stitched_tuck_v1');
    await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
    await userEvent.type(screen.getByLabelText('Глубина детали 1, см'), '0.5');
    await userEvent.type(screen.getByLabelText('Длина детали 1, см'), '15');
    await userEvent.click(screen.getByLabelText('Я проверил(а) эту деталь по фотографии'));
    await userEvent.selectOptions(screen.getByLabelText('Добавить деталь из каталога'), 'paired_straight_decorative_stitch_v1');
    await userEvent.click(screen.getByRole('button', {name: 'Добавить выбранную деталь'}));
    await userEvent.selectOptions(screen.getByLabelText('Расположение детали 2'), 'skirt_back');
    await userEvent.selectOptions(screen.getByLabelText('Выбрать конструкцию детали 2'), 'paired_straight_decorative_stitch_v1');
    expect(screen.getByLabelText('Расположение детали 2')).toHaveValue('skirt_back');
    await userEvent.type(screen.getByLabelText('Длина детали 2, см'), '15');
    await userEvent.type(screen.getByLabelText('Расстояние детали 2, см'), '3');
    await userEvent.click(screen.getAllByLabelText('Я проверил(а) эту деталь по фотографии')[1]);
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].elements[0]).toMatchObject({module_id: 'center_stitched_tuck_v1', dimensions_mm: {depth: 5, length: 150}});
    expect(onSave.mock.calls[0][0].elements[1]).toMatchObject({module_id: 'paired_straight_decorative_stitch_v1', count: 2, location: 'skirt_back'});
  });

  it('rejects a neckline ruffle on a skirt without a bodice', () => {
    const {spec, intent} = fixture();
    spec.garment_type = 'skirt';
    const item = {...intent.elements[0], type: 'ruffle', variant: 'gathered', location: 'neckline',
      construction: 'separate_piece', count: 1, symmetry: 'symmetric', dimensions_mm: {depth: 80, width: 150}};
    expect(matchingModule('element', item, spec)).toBeUndefined();
  });
});

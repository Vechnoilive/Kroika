import {useState} from 'react';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {StyleEditor} from './ProjectWorkflow';
import {DesignIntentEditor} from './DesignIntentEditor';
import {buildDesignIntent, reevaluateDesignIntent} from './designIntent';
import {matchingModule, moduleIds} from './designModules';
import {canonicalGenerationPayload, stableJson} from './generation';
import {makeDemoProject} from './demoProject';
import type {GarmentDesignIntent, GarmentSpec, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 1}, uncertainties: [], targeted_questions: [],
  design_features: {elements: [], layers: [{layer_id: 'main_fabric', role: 'main', coverage: 'full', material_hint_ru: 'Ткань', opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false}], proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1}},
};
function fixture() {
  const project = makeDemoProject('Основа и слои');
  const intent = buildDesignIntent(analysis, project.garment_spec)!;
  intent.layers[0].confirmed_by_user = true;
  intent.proportions.confirmed_by_user = true;
  return {project, intent};
}
function Harness({spec, initial, onSave}: {spec: GarmentSpec; initial: GarmentDesignIntent; onSave: (intent: GarmentDesignIntent) => Promise<void>}) {
  const [intent, setIntent] = useState(initial);
  return <DesignIntentEditor spec={{...spec, design_intent: intent}} intent={intent} analysis={analysis} busy={false} onChange={setIntent} onSave={onSave} />;
}

describe('stage 4 foundations and material layers', () => {
  it('offers three real material layer modules', () => expect(moduleIds('foundation_layer').size).toBe(3));
  it('saves free fit, square neckline and short sleeve without resetting type when depth changes', async () => {
    const project = makeDemoProject('Новый фасон');
    const onSave = vi.fn(async (p: ProjectDocument) => ({...p, revision: p.revision + 1}));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);
    await userEvent.click(screen.getByRole('radio', {name: 'Свободная'}));
    await userEvent.click(screen.getByRole('radio', {name: 'Квадратная'}));
    await userEvent.click(screen.getByRole('radio', {name: 'Короткий'}));
    fireEvent.change(screen.getByLabelText(/Глубина горловины спереди/), {target: {value: '12'}});
    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.garment_spec.parameters).toMatchObject({bodice_fit: 'loose', neckline: {type: 'square', front_depth_mm: 120}, sleeve: {type: 'short', length_mm: 180}, finishing: {armhole_facing: false}});
    expect(canonicalGenerationPayload(saved).hash_contract_version).toBe('1.10.0');
  });
  it('reviews and saves a shortened skirt lining with its actual coverage', async () => {
    const {project, intent} = fixture();
    intent.layers.push({...intent.layers[0], source_layer_id: 'short_lining', role: 'lining', coverage: 'skirt', confirmed_by_user: false, support_status: 'planned', module_id: null});
    const onSave = vi.fn(async (_intent: GarmentDesignIntent) => {});
    render(<Harness spec={project.garment_spec} initial={intent} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText('Укорочение низа слоя, см'), {target: {value: '3'}});
    await userEvent.click(screen.getAllByLabelText('Я проверил(а) этот слой')[1]);
    await userEvent.click(screen.getByRole('button', {name: 'Сохранить проверку деталей'}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const result = onSave.mock.calls[0][0];
    expect(result.layers[1]).toMatchObject({module_id: 'foundation_lining_v4', support_status: 'supported', coverage: 'skirt', hem_shortening_mm: 30});
    expect(screen.queryByText(/другие покрытия останутся заблокированы/i)).not.toBeInTheDocument();
  });
  it('retains detail selectors and includes both selectors and shortening in the hash', () => {
    const {project, intent} = fixture();
    intent.elements.push({source_element_id: 'sash_detail', type: 'sash', variant: 'straight', description_ru: 'Кушак', location: 'waist', construction: 'separate_piece', count: 1, symmetry: 'single', confidence: 1, evidence_ru: 'Проверено', requires_confirmation: false, included: true, confirmed_by_user: true, dimensions_mm: {width: 80, length: 1600, depth: null, spacing: null}, module_id: 'straight_sash_v1', support_status: 'supported'});
    intent.layers.push({...intent.layers[0], source_layer_id: 'detail_lining', role: 'lining', coverage: 'detail', detail_source_ids: ['sash_detail'], confirmed_by_user: true, support_status: 'supported', module_id: 'foundation_lining_v4'});
    project.garment_spec.design_intent = intent;
    const reviewed = reevaluateDesignIntent(intent, project.garment_spec, analysis);
    expect(reviewed.layers[1]).toMatchObject({detail_source_ids: ['sash_detail'], module_id: 'foundation_lining_v4'});
    const first = stableJson(canonicalGenerationPayload(project));
    intent.layers[1].detail_source_ids = [];
    expect(stableJson(canonicalGenerationPayload(project))).not.toBe(first);
    expect(matchingModule('layer', intent.layers[1], project.garment_spec)).toBeUndefined();
  });
});

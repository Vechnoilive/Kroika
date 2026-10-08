import {useState} from 'react';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {PlacementGuide} from './PlacementGuide';
import {DesignIntentEditor} from './DesignIntentEditor';
import {makeDemoProject} from './demoProject';
import {buildDesignIntent} from './designIntent';
import type {GarmentDesignIntent, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'ok', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 1}, uncertainties: [], targeted_questions: [],
  design_features: {elements: [], layers: [{layer_id: 'fabric', role: 'main', coverage: 'full', material_hint_ru: 'Ткань', opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false}],
    proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1}},
};
function item(module = 'rounded_patch_pocket_v3'): GarmentDesignIntent['elements'][number] {
  return {source_element_id: 'pocket', type: 'pocket', variant: 'patch', location: 'skirt_front', construction: 'separate_piece', count: 2, symmetry: 'symmetric', description_ru: 'Карман', confidence: 1, evidence_ru: '', requires_confirmation: false, included: true, confirmed_by_user: true, support_status: 'supported', module_id: module, selected_module_id: module, dimensions_mm: {width: 80, depth: 100, length: null, spacing: 60}, placement: {side: 'both', offset_mm: 20}};
}

describe('placement references before generation', () => {
  it('shows the selected partition and updates millimetres as centimetres in the editor', () => {
    const spec = makeDemoProject('Размещение').garment_spec;
    const intent = buildDesignIntent(analysis, spec)!;
    const pocket = item();
    intent.elements = [pocket, {...pocket, source_element_id: 'partition', type: 'panel', variant: 'straight', location: 'full_garment', count: 3, module_id: 'paired_equal_skirt_panels_v1', selected_module_id: 'paired_equal_skirt_panels_v1', dimensions_mm: {width: null, depth: null, length: null, spacing: null}, placement: undefined}];
    function Harness() {
      const [state, setState] = useState(intent);
      return <DesignIntentEditor intent={state} spec={spec} analysis={analysis} busy={false} onChange={setState} onSave={vi.fn()} />;
    }
    render(<Harness />);
    const guide = screen.getByRole('figure');
    expect(within(guide).getByRole('img')).toHaveAccessibleDescription(/Ширина кармана: 8 см/);
    expect(within(guide).getByText(/Сначала стачайте швы членения/)).toBeInTheDocument();
    expect(within(guide).getByText(/без масштаба/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Ширина детали 1, см'), {target: {value: '9.5'}});
    expect(within(guide).getByRole('img')).toHaveAccessibleDescription(/Ширина кармана: 9,5 см/);
    fireEvent.click(screen.getAllByLabelText('Эта деталь действительно есть на изделии', {selector: 'input'})[0]);
    expect(screen.queryByRole('figure')).not.toBeInTheDocument();
  });
  it('distinguishes the bottom-based legacy reference from the top-based welt reference', () => {
    const pocket = {...item('placed_patch_pocket_v1'), placement: undefined};
    const {rerender} = render(<PlacementGuide item={pocket} moduleId={pocket.module_id!} elements={[pocket]} />);
    expect(screen.getByRole('img')).toHaveAccessibleDescription(/От нижней точки основы вверх: 6 см/);
    expect(screen.queryByText('От верхней точки основы вниз')).not.toBeInTheDocument();
    const welt = {...item('welt_pocket_v3'), variant: 'welt' as const, dimensions_mm: {width: 10, length: 90, depth: 140, spacing: 60}};
    rerender(<PlacementGuide item={welt} moduleId={welt.module_id!} elements={[welt]} />);
    expect(screen.getByRole('img')).toHaveAccessibleDescription(/Длина входа: 9 см/);
    expect(screen.getByRole('img')).toHaveAccessibleDescription(/Ширина одной обтачки: 1 см/);
    expect(screen.getByRole('img')).toHaveAccessibleDescription(/От верхней точки основы вниз: 2 см/);
    expect(screen.getByRole('img')).toHaveAccessibleDescription(/Глубина мешковины: 14 см/);
  });
  it('does not present missing measurements as known sizes or duplicate SVG IDs', () => {
    const pocket = {...item(), dimensions_mm: {width: null, length: null, depth: null, spacing: null}};
    render(<><PlacementGuide item={pocket} moduleId={pocket.module_id!} elements={[pocket]} /><PlacementGuide item={pocket} moduleId={pocket.module_id!} elements={[pocket]} /></>);
    expect(screen.getAllByRole('img')[0]).toHaveAccessibleDescription(/Ширина кармана: укажите размер/);
    const ids = [...document.querySelectorAll('svg [id]')].map(node => node.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

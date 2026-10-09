import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {ConstructionPreview} from './ConstructionPreview';
import {RecipeGuide} from './RecipeGuide';
import {api} from './api';
import {makeDemoProject} from './demoProject';
import {DESIGN_MODULES} from './designModules';
import {configureGarment} from './garments';
import type {StyleAnalysis, GarmentDesignIntent} from './types';
const analysis = {status: 'ok', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1}, neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1}, lower_part: {type: 'a_line', length_category: 'midi', confidence: 1}, uncertainties: [], targeted_questions: []} as StyleAnalysis;
const response = {input_hash: 'hash', engine_version: '0.23.0', status: 'succeeded', issues: [], svg: '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L10 10"/></svg>', piece_count: 4};

describe('calculated preview before persistence', () => {
  it('previews the draft without saving and invalidates the result after edits', async () => {
    const preview = vi.spyOn(api, 'previewPattern').mockResolvedValue(response);
    const project = makeDemoProject('Предпросмотр');
    const original = structuredClone(project);
    const {rerender} = render(<ConstructionPreview project={project} analysis={analysis} />);
    fireEvent.click(screen.getByRole('button', {name: 'Проверить размещение по меркам'}));
    await screen.findByRole('img', {name: /Рассчитанные контуры/});
    expect(project).toEqual(original);
    expect(preview.mock.calls[0][0].garment_spec.selection_status).toBe('confirmed');
    fireEvent.change(screen.getByLabelText('Масштаб предварительного вида'), {target: {value: '200'}});
    expect(screen.getByRole('img')).toHaveStyle({width: '200%'});
    const changed = structuredClone(project);
    changed.garment_spec.parameters.neckline.front_depth_mm += 10;
    rerender(<ConstructionPreview project={changed} analysis={analysis} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    preview.mockRestore();
  });
  it('ignores a stale in-flight result when inputs change', async () => {
    let resolve!: (value: typeof response) => void;
    const preview = vi.spyOn(api, 'previewPattern').mockImplementation(() => new Promise(r => {resolve = r;}));
    const project = makeDemoProject('Предпросмотр');
    const {rerender} = render(<ConstructionPreview project={project} analysis={analysis} />);
    fireEvent.click(screen.getByRole('button', {name: 'Проверить размещение по меркам'}));
    await waitFor(() => expect(preview).toHaveBeenCalledOnce());
    const changed = structuredClone(project);
    changed.garment_spec.parameters.neckline.front_depth_mm += 10;
    rerender(<ConstructionPreview project={changed} analysis={analysis} />);
    expect(preview.mock.calls[0][1]?.aborted).toBe(true);
    resolve(response);
    await Promise.resolve();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    preview.mockRestore();
  });
  it('shows the actual geometry reason when a placement is blocked', async () => {
    const preview = vi.spyOn(api, 'previewPattern').mockResolvedValue({...response, status: 'failed', svg: null, piece_count: 0, issues: [{code: 'DETAIL_PLACEMENT_OUTSIDE', message_ru: 'Карман выходит за контур.', severity: 'blocking_error', json_pointer: '/garment_spec'}]});
    render(<ConstructionPreview project={makeDemoProject('Предпросмотр')} analysis={analysis} />);
    fireEvent.click(screen.getByRole('button', {name: 'Проверить размещение по меркам'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Карман выходит за контур.');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    preview.mockRestore();
  });
  it('uses the selected garment method and the defaults that will be saved on confirmation', async () => {
    const preview = vi.spyOn(api, 'previewPattern').mockResolvedValue(response);
    const project = makeDemoProject('Смена изделия');
    project.garment_spec = configureGarment(project.garment_spec, 'jacket');
    const original = structuredClone(project);
    render(<ConstructionPreview project={project} analysis={analysis} />);
    fireEvent.click(screen.getByRole('button', {name: 'Проверить размещение по меркам'}));
    await screen.findByRole('img');
    const candidate = preview.mock.calls[0][0];
    expect(candidate.pattern_method.id).toBe('kroika-light-jacket');
    expect(candidate.fit_settings.preset.id).toBe('woven_light_jacket_trial');
    expect(candidate.fit_settings.wearing_ease_mm).toEqual({bust: 110, waist: 130, hips: 110, upper_arm: 90});
    expect(project).toEqual(original);
    preview.mockRestore();
  });
});

it('explains the yoke depth and princess position using shared parameter labels', () => {
  const item = {type: 'yoke', location: 'bodice_front', dimensions_mm: {depth: 70, width: 15, length: null, spacing: null}} as GarmentDesignIntent['elements'][number];
  const module = DESIGN_MODULES.find(m => m.id === 'front_bodice_yoke_v3')!;
  const {rerender} = render(<RecipeGuide item={item} module={module} />);
  expect(screen.getByText('Глубина от верхней точки')).toBeInTheDocument();
  expect(screen.getByText('7 см')).toBeInTheDocument();
  expect(screen.getByText('Разница высот концов для наклонной кокетки')).toBeInTheDocument();
  rerender(<RecipeGuide item={{...item, type: 'princess_seam', dimensions_mm: {width: null, length: null, depth: null, spacing: 50}}} module={DESIGN_MODULES.find(m => m.id === 'shoulder_princess_seam_v3')} />);
  expect(screen.getByText('Расстояние по плечевому срезу от горловины')).toBeInTheDocument();
  expect(screen.getByText('5 см')).toBeInTheDocument();
});

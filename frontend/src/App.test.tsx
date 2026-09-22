import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App, {errorNavigationTarget} from './App';
import {api, ApiError} from './api';
import {makeDemoProject} from './demoProject';
import {configureGarment} from './garments';
import type {PatternEngineResult, StyleAnalysis} from './types';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('accessible stage flow', () => {
  it.each([
    ['/body_measurements/values/bust', 4],
    ['/garment_spec/parameters/skirt/length_from_waist_mm', 3],
    ['/fit_settings/wearing_ease_mm/hips', 5],
    ['/fabric_properties/stretch_percent/weft', 5],
    ['/image_refs/0', 2],
  ])('maps issue %s to editable step %s', (jsonPointer, step) => {
    const error = new ApiError('Проверьте значение.', 422, 'INVALID_INPUT', undefined, [{
      code: 'INVALID_INPUT',
      severity: 'blocking_error',
      message_ru: 'Проверьте значение.',
      json_pointer: jsonPointer,
    }]);
    expect(errorNavigationTarget(error)?.step).toBe(step);
  });

  it('starts with one clear enabled action after readiness succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes('/health/')
        ? {status: 'ok', service: 'kroika-backend', version: '0.7.0', database: 'ok', ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.3.0'}
        : {items: []};
      return new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
    }));
    render(<App />);

    const action = await screen.findByRole('button', {name: /создать проект/i});
    await waitFor(() => expect(action).toBeEnabled());
    expect(screen.getByLabelText(/название проекта/i)).toBeVisible();
    expect(screen.getByText(/все размеры вводит человек/i)).toBeVisible();
  });

  it('explains a backend outage in plain language', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    expect(await screen.findByText('Backend пока недоступен')).toBeVisible();
    expect(screen.getByRole('button', {name: /создать проект/i})).toBeDisabled();
  });

  it('lets a keyboard user edit the project name', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes('/health/')
        ? {status: 'ok', service: 'kroika-backend', version: '0.7.0', database: 'ok', ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.3.0'}
        : {items: []};
      return new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
    }));
    render(<App />);
    const input = await screen.findByLabelText(/название проекта/i);
    await userEvent.clear(input);
    await userEvent.type(input, 'Летнее платье');
    expect(input).toHaveValue('Летнее платье');
  });

  it('opens the exact editable step named by a pattern validation error', async () => {
    const project = makeDemoProject('Брюки');
    const analysis: StyleAnalysis = {
      status: 'ok',
      garment_category: 'trousers',
      silhouette: {fit: 'semi_fitted', confidence: 0.95},
      neckline: {front: 'unknown', confidence: 0},
      sleeves: {present: false, length: 'sleeveless', confidence: 1},
      lower_part: {type: 'straight', length_category: 'full', confidence: 0.95},
      uncertainties: [],
      targeted_questions: [],
    };
    project.style_analysis_id = crypto.randomUUID();
    project.style_analysis_provider = 'mock';
    project.style_analysis = analysis;
    project.garment_spec = configureGarment(project.garment_spec, 'trousers');
    project.garment_spec.selection_status = 'confirmed';
    project.garment_spec.confirmed_at = new Date().toISOString();
    project.body_measurements.status = 'ready';

    const message = 'Длина изделия не должна превышать снятую длину по боку более чем на 2 см.';
    const rejected: PatternEngineResult = {
      generation_id: crypto.randomUUID(),
      engine_version: '0.8.1',
      status: 'rejected',
      pattern: null,
      validation_report: {
        status: 'failed',
        diagnostic_export_allowed: false,
        production_export_allowed: false,
        issues: [{
          code: 'TROUSER_LENGTH_OUTSIDE_MEASUREMENT',
          severity: 'blocking_error',
          message_ru: message,
          json_pointer: '/garment_spec/parameters/trousers/length_mm',
        }],
      },
    };

    localStorage.setItem('kroika:last-project-id', project.project_id);
    vi.spyOn(api, 'readiness').mockResolvedValue({
      status: 'ok', service: 'kroika-backend', version: '0.15.0', database: 'ok',
      ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.8.1',
    });
    vi.spyOn(api, 'listProjects').mockResolvedValue({items: []});
    vi.spyOn(api, 'garmentCatalogue').mockResolvedValue({items: []});
    vi.spyOn(api, 'getProject').mockResolvedValue(project);
    vi.spyOn(api, 'projectHistory').mockResolvedValue({items: []});
    vi.spyOn(api, 'generatePattern').mockResolvedValue(rejected);

    render(<App />);
    await userEvent.click(await screen.findByRole('button', {name: /построить выкройку/i}));

    const repair = await screen.findByRole('button', {name: /исправить фасон и размеры изделия/i});
    expect(screen.getAllByText(message)).toHaveLength(1);
    await userEvent.click(repair);

    expect(await screen.findByRole('heading', {name: /проверьте фасон своими глазами/i})).toBeVisible();
    expect(screen.getByLabelText(/длина брюк от талии/i)).toBeVisible();
  });
});

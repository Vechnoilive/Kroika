import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App from './App';
import {api} from './api';
import {buildDesignIntent} from './designIntent';
import {makeDemoProject} from './demoProject';
import {StyleEditor} from './ProjectWorkflow';
import type {ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation',
  garment_category: 'skirt',
  silhouette: {fit: 'semi_fitted', confidence: 0.91},
  neckline: {front: 'unknown', confidence: 0},
  sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 0.9},
  uncertainties: ['Спинка не видна'],
  targeted_questions: ['Подтвердите прозрачный верхний слой.'],
  design_features: {
    elements: [
      {
        element_id: 'straight_waistband', type: 'waistband', variant: 'straight',
        description_ru: 'Прямой притачной пояс.', location: 'waist',
        construction: 'separate_piece', count: 1, symmetry: 'symmetric',
        confidence: 0.94, evidence_ru: 'Виден отдельный пояс по линии талии.',
        requires_confirmation: false,
      },
      {
        element_id: 'hem_flounce', type: 'flounce', variant: 'circular',
        description_ru: 'Широкий волан по низу.', location: 'hem',
        construction: 'separate_piece', count: 1, symmetry: 'symmetric',
        confidence: 0.88, evidence_ru: 'По низу видна отдельная расширенная деталь.',
        requires_confirmation: false,
      },
    ],
    layers: [
      {
        layer_id: 'main_fabric', role: 'main', coverage: 'full',
        material_hint_ru: 'Основная ткань.', opacity: 'opaque', drape: 'medium',
        confidence: 0.9, requires_confirmation: false,
      },
      {
        layer_id: 'transparent_overlay', role: 'overlay', coverage: 'skirt',
        material_hint_ru: 'Прозрачный верхний слой.', opacity: 'transparent', drape: 'fluid',
        confidence: 0.75, requires_confirmation: false,
      },
    ],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight',
      asymmetry: 'no', confidence: 0.85,
    },
  },
};

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('stage 16 design intent and workflow navigation', () => {
  it('keeps every visible detail and refuses to silently build the base template', async () => {
    const project = makeDemoProject('Юбка с воланом');
    project.garment_spec.garment_type = 'skirt';
    project.garment_spec.design_intent = buildDesignIntent(analysis, project.garment_spec);
    const onSave = vi.fn(async (candidate: ProjectDocument) => candidate);

    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);

    expect(screen.getByText('Пояс')).toBeVisible();
    expect(screen.getByText('Волан')).toBeVisible();
    expect(screen.getByText('Накладной слой')).toBeVisible();
    expect(screen.getAllByText('Модуль не готов')).toHaveLength(2);
    expect(screen.getByText(/точная выкройка пока заблокирована/i)).toBeVisible();

    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/нельзя подтвердить точный фасон/i);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('lets the user reopen a completed step from the journey', async () => {
    const project = makeDemoProject('Навигация');
    project.style_analysis_id = crypto.randomUUID();
    project.style_analysis_provider = 'mock';
    project.style_analysis = analysis;
    project.garment_spec.selection_status = 'proposed';
    project.garment_spec.design_intent = buildDesignIntent(analysis, project.garment_spec);
    localStorage.setItem('kroika:last-project-id', project.project_id);

    vi.spyOn(api, 'readiness').mockResolvedValue({
      status: 'ok', service: 'kroika-backend', version: '0.16.0', database: 'ok',
      ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.8.1',
    });
    vi.spyOn(api, 'listProjects').mockResolvedValue({items: []});
    vi.spyOn(api, 'garmentCatalogue').mockResolvedValue({items: []});
    vi.spyOn(api, 'getProject').mockResolvedValue(project);
    vi.spyOn(api, 'projectHistory').mockResolvedValue({items: []});
    vi.spyOn(api, 'visionProviders').mockResolvedValue({
      default_provider: 'mock',
      items: [{
        provider_id: 'mock', name: 'Демо-режим', model: 'fixture', configured: true,
        is_default: true, enabled_for_users: true, sends_images_external: false,
        message_ru: 'Не отправляет фото.',
      }],
    });

    render(<App />);
    expect(await screen.findByRole('heading', {name: /проверьте фасон своими глазами/i})).toBeVisible();

    await userEvent.click(screen.getByRole('button', {name: /перейти к шагу 2: добавить эскиз/i}));
    expect(await screen.findByRole('heading', {name: /добавьте эскиз или фотографию/i})).toBeVisible();

    await userEvent.click(screen.getByRole('button', {name: /перейти к шагу 3: подтвердить фасон/i}));
    await waitFor(() => expect(screen.getByRole('heading', {name: /проверьте фасон своими глазами/i})).toBeVisible());
  });
});

import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App from './App';
import {api} from './api';
import {makeDemoProject} from './demoProject';
import {PhysicalValidationJournal} from './PhysicalValidationJournal';
import type {PhysicalValidationSummary} from './types';

const generationId = '11111111-1111-4111-8111-111111111111';

function summary(
  statuses: Array<'pending' | 'passed' | 'failed'> = ['pending', 'pending', 'pending'],
): PhysicalValidationSummary {
  const gates = ['paper', 'expert', 'toile'] as const;
  return {
    project_id: '22222222-2222-4222-8222-222222222222',
    generation_id: generationId,
    gates: gates.map((gate, index) => ({
      gate,
      status: statuses[index],
      latest_record_id: statuses[index] === 'pending' ? null : `record-${gate}`,
      checked_at: statuses[index] === 'pending' ? null : '2026-09-23T18:00:00Z',
      passed_observations: statuses[index] === 'passed' ? ({paper: 2, expert: 1, toile: 3})[gate] : 0,
      required_observations: ({paper: 2, expert: 1, toile: 3})[gate],
    })),
    production_allowed: statuses.every((status) => status === 'passed'),
    policy: 'Допуск относится только к этой версии.',
    records: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('stage 22 physical validation journal', () => {
  it('records measured paper values and displays a derived release state', async () => {
    vi.spyOn(api, 'physicalValidation').mockResolvedValue(summary());
    vi.spyOn(api, 'recordPhysicalValidation').mockResolvedValue(
      summary(['passed', 'passed', 'passed']),
    );

    render(<PhysicalValidationJournal generationId={generationId} garmentName="Платье" />);
    expect(await screen.findByText(/кроить ткань пока нельзя/i)).toBeVisible();
    await userEvent.type(screen.getByLabelText(/^Принтер$/i), 'HP LaserJet M404');
    await userEvent.type(screen.getByLabelText(/ширина квадрата/i), '50');
    await userEvent.type(screen.getByLabelText(/высота квадрата/i), '49,8');
    await userEvent.type(screen.getByLabelText(/линия 200 мм/i), '200');
    await userEvent.type(screen.getByLabelText(/кто проверил/i), 'Анна');
    await userEvent.click(screen.getByRole('button', {name: /записать проверку/i}));

    await waitFor(() => expect(api.recordPhysicalValidation).toHaveBeenCalledWith(
      generationId,
      expect.objectContaining({
        gate: 'paper',
        reviewer_name: 'Анна',
        printer_name: 'HP LaserJet M404',
        square_width_mm: 50,
        square_height_mm: 49.8,
        control_line_mm: 200,
      }),
    ));
    expect(await screen.findByText('Допуск открыт')).toBeVisible();
    expect(screen.getByText(/все три проверки пройдены/i)).toBeVisible();
  });

  it('offers an explicit back button even on the image step', async () => {
    const project = makeDemoProject('Навигация назад');
    localStorage.setItem('kroika:last-project-id', project.project_id);
    vi.spyOn(api, 'readiness').mockResolvedValue({
      status: 'ok', service: 'kroika-backend', version: '0.22.0', database: 'ok',
      ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.14.0',
    });
    vi.spyOn(api, 'listProjects').mockResolvedValue({items: [{
      project_id: project.project_id,
      name: project.name,
      revision: project.revision,
      status: project.status,
      updated_at: project.updated_at,
    }]});
    vi.spyOn(api, 'garmentCatalogue').mockResolvedValue({items: []});
    vi.spyOn(api, 'getProject').mockResolvedValue(project);
    vi.spyOn(api, 'projectHistory').mockResolvedValue({items: []});
    vi.spyOn(api, 'visionProviders').mockResolvedValue({
      default_provider: 'mock',
      items: [{
        provider_id: 'mock', name: 'Демо-режим', model: 'deterministic-fixture',
        configured: true, is_default: true, enabled_for_users: true,
        sends_images_external: false, message_ru: 'Готово.',
      }],
    });

    render(<App />);
    const back = await screen.findByRole('button', {name: /назад: создать проект/i});
    await userEvent.click(back);
    expect(await screen.findByRole('button', {name: /создать проект/i})).toBeVisible();
    expect(screen.getByRole('heading', {name: /ваши проекты/i})).toBeVisible();
  });
});

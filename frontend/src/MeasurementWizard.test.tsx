import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {api} from './api';
import {makeDemoProject} from './demoProject';
import {MeasurementWizard} from './MeasurementWizard';
import type {MeasurementCatalog, ProjectDocument} from './types';

const catalog: MeasurementCatalog = {
  schema_version: '1.0.0',
  catalog_version: '1.0.0',
  garment_type: 'dress',
  sleeve_type: 'sleeveless',
  normalized_unit: 'mm',
  display_units: ['cm', 'mm'],
  source_options: ['user', 'preset', 'derived'],
  measurements: [{
    id: 'bust',
    label_ru: 'Обхват груди',
    group: 'Обхваты',
    kind: 'linear',
    unit: 'mm',
    minimum: 600,
    maximum: 1800,
    instruction_ru: 'Лента проходит горизонтально через выступающие точки груди и лопатки.',
    illustration: 'bust',
    applicable_to: ['dress'],
    required_for: ['dress'],
    sleeve_only: false,
    required: true,
  }],
};

function saved(project: ProjectDocument, profile: ProjectDocument['body_measurements']): ProjectDocument {
  return {...project, revision: project.revision + 1, body_measurements: profile};
}

describe('MeasurementWizard', () => {
  let project: ProjectDocument;

  beforeEach(() => {
    project = makeDemoProject('Платье');
    vi.spyOn(api, 'measurementCatalog').mockResolvedValue(catalog);
    vi.spyOn(api, 'listMeasurementProfiles').mockResolvedValue({items: []});
  });

  afterEach(() => vi.restoreAllMocks());

  it('starts empty and explicitly refuses hidden substitutions', async () => {
    const onSave = vi.fn(async (profile) => saved(project, profile));
    render(<MeasurementWizard project={project} onSaveProject={onSave} />);

    expect(await screen.findByLabelText(/Значение, см/)).toHaveValue(null);
    expect(screen.getByText(/среднее значение не подставится/i)).toBeVisible();
    expect(screen.getByRole('button', {name: /проверить и завершить/i})).toBeDisabled();
  });

  it('normalizes centimetres to millimetres and records manual origin', async () => {
    const onSave = vi.fn(async (profile) => saved(project, profile));
    render(<MeasurementWizard project={project} onSaveProject={onSave} />);
    const input = await screen.findByLabelText(/Значение, см/);
    await userEvent.type(input, '92');
    expect(screen.getByText('Введено вручную')).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /сохранить черновик/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].values.bust).toEqual({
      value: 920,
      unit: 'mm',
      source: 'user',
      original_input: {value: 92, unit: 'cm'},
    });
  });

  it('switches display units without changing the physical value', async () => {
    project.body_measurements.values.bust = {
      value: 925, unit: 'mm', source: 'user', original_input: {value: 92.5, unit: 'cm'},
    };
    render(<MeasurementWizard project={project} onSaveProject={vi.fn()} />);
    expect(await screen.findByLabelText(/Значение, см/)).toHaveValue(92.5);
    await userEvent.click(screen.getByRole('button', {name: 'мм'}));
    expect(screen.getByLabelText(/Значение, мм/)).toHaveValue(925);
  });

  it('blocks out-of-range completion and finishes only after server validation', async () => {
    const onSave = vi.fn(async (profile) => saved(project, profile));
    vi.spyOn(api, 'validateMeasurements').mockResolvedValue({
      status: 'ready', required_count: 1, completed_count: 1, issues: [],
    });
    render(<MeasurementWizard project={project} onSaveProject={onSave} />);
    const input = await screen.findByLabelText(/Значение, см/);
    await userEvent.type(input, '10');
    expect(screen.getByRole('alert')).toHaveTextContent(/рабочий диапазон/i);
    await userEvent.clear(input);
    await userEvent.type(input, '92');
    await userEvent.click(screen.getByRole('button', {name: /проверить и завершить/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].status).toBe('ready');
    expect(api.validateMeasurements).toHaveBeenCalledOnce();
  });
});

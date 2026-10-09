import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {api, ApiError} from './api';
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

    expect(await screen.findByLabelText(/Обхват груди, см/)).toHaveValue('');
    expect(screen.getByText(/пустые поля не заполняются автоматически/i)).toBeVisible();
    expect(screen.getByRole('button', {name: /проверить и завершить/i})).toBeDisabled();
  });

  it('normalizes centimetres to millimetres and records manual origin', async () => {
    const onSave = vi.fn(async (profile) => saved(project, profile));
    render(<MeasurementWizard project={project} onSaveProject={onSave} />);
    const input = await screen.findByLabelText(/Обхват груди, см/);
    await userEvent.type(input, '92');
    expect(screen.getByText('Введено вручную')).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /сохранить сейчас/i}));

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
    expect(await screen.findByLabelText(/Обхват груди, см/)).toHaveValue('92.5');
    await userEvent.click(screen.getByRole('button', {name: 'мм'}));
    expect(screen.getByLabelText(/Обхват груди, мм/)).toHaveValue('925');
  });

  it('blocks out-of-range completion and finishes only after server validation', async () => {
    const onSave = vi.fn(async (profile) => saved(project, profile));
    vi.spyOn(api, 'validateMeasurements').mockResolvedValue({
      status: 'ready', required_count: 1, completed_count: 1, issues: [],
    });
    render(<MeasurementWizard project={project} onSaveProject={onSave} />);
    const input = await screen.findByLabelText(/Обхват груди, см/);
    await userEvent.type(input, '10');
    expect(screen.getByRole('alert')).toHaveTextContent(/рабочий диапазон/i);
    await userEvent.clear(input);
    await userEvent.type(input, '92');
    await userEvent.click(screen.getByRole('button', {name: /проверить и завершить/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].status).toBe('ready');
    expect(api.validateMeasurements).toHaveBeenCalledOnce();
  });

  it('shows every field together and accepts decimal commas and a zero angle', async () => {
    vi.spyOn(api, 'measurementCatalog').mockResolvedValue({...catalog, measurements: [
      ...catalog.measurements,
      {...catalog.measurements[0], id: 'waist', label_ru: 'Обхват талии', minimum: 450},
      {...catalog.measurements[0], id: 'shoulder_slope', label_ru: 'Наклон плеча', kind: 'angle', unit: 'deg', minimum: 0, maximum: 40},
    ]});
    const onSave = vi.fn(async (profile) => saved(project, profile));
    render(<MeasurementWizard project={project} onSaveProject={onSave}/>);
    const bust = await screen.findByLabelText('Обхват груди, см');
    expect(screen.getByLabelText('Обхват талии, см')).toBeVisible();
    expect(screen.getByLabelText('Наклон плеча, °')).toBeVisible();
    expect(screen.queryByRole('button', {name: 'Дальше →'})).not.toBeInTheDocument();
    await userEvent.type(bust, '92,5');
    await userEvent.type(screen.getByLabelText('Наклон плеча, °'), '0');
    await userEvent.click(screen.getByRole('button', {name: /сохранить сейчас/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].values.bust.value).toBe(925);
    expect(onSave.mock.calls[0][0].angles_deg?.shoulder_slope).toBe(0);
  });

  it('stays on measurements when saving the optional reusable profile fails', async () => {
    const onSave = vi.fn(async (profile) => saved(project, profile));
    const onComplete = vi.fn();
    vi.spyOn(api, 'validateMeasurements').mockResolvedValue({status: 'ready', required_count: 1, completed_count: 1, issues: []});
    vi.spyOn(api, 'createMeasurementProfile').mockRejectedValue(new ApiError('Профиль не сохранён', 503, 'UNAVAILABLE'));
    render(<MeasurementWizard project={project} onSaveProject={onSave} onComplete={onComplete} />);
    await userEvent.type(await screen.findByLabelText('Обхват груди, см'), '92');
    await userEvent.click(screen.getByLabelText(/Сохранить отдельный профиль на этом компьютере/));
    await userEvent.click(screen.getByRole('button', {name: /Проверить и завершить/}));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Мерки сохранены в проекте/);
    expect(onSave.mock.calls[0][0].status).toBe('ready');
    expect(onComplete).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Обхват груди, см')).toHaveValue('92');
    await userEvent.click(screen.getByLabelText(/Сохранить отдельный профиль на этом компьютере/));
    await userEvent.click(screen.getByRole('button', {name: /Проверить и завершить/}));
    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    expect(api.createMeasurementProfile).toHaveBeenCalledOnce();
  });
});

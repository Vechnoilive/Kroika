import {act, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {AutosaveIndicator} from './AutosaveIndicator';
import {loadLocalDraft, useDraftAutosave} from './autosave';
import {makeDemoProject} from './demoProject';
import {ProjectHub} from './ProjectHub';
import {duplicateProjectDocument, uniqueCopyName} from './projectManagement';
import {StyleEditor} from './ProjectWorkflow';
import type {ProjectDocument, ProjectSummary, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation',
  garment_category: 'dress',
  silhouette: {fit: 'semi_fitted', confidence: 0.9},
  neckline: {front: 'round', confidence: 0.9},
  sleeves: {present: false, length: 'sleeveless', confidence: 0.9},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 0.9},
  uncertainties: [],
  targeted_questions: [],
};

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function AutosaveHarness({
  save,
  onDirtyChange,
}: {
  save: (value: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const autosave = useDraftAutosave({
    storageKey: 'stage24:draft',
    initialValue: 'исходное',
    delayMs: 500,
    save,
    onDirtyChange,
  });
  return (
    <>
      <label>Параметр<input defaultValue="исходное" onChange={(event) => autosave.markDirty(event.target.value)} /></label>
      <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} error={autosave.error} onRetry={autosave.retry} />
    </>
  );
}

describe('stage 24 autosave and project library', () => {
  it('stores a local recovery draft, debounces the server save, and clears the warning', async () => {
    vi.useFakeTimers();
    const save = vi.fn(async () => undefined);
    const dirty = vi.fn();
    render(<AutosaveHarness save={save} onDirtyChange={dirty} />);

    fireEvent.change(screen.getByLabelText('Параметр'), {target: {value: 'новое'}});
    expect(screen.getByRole('status')).toHaveTextContent('Есть несохранённые изменения');
    expect(localStorage.getItem('stage24:draft')).toContain('новое');
    expect(dirty).toHaveBeenLastCalledWith(true);

    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });

    expect(save).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledWith('новое');
    expect(localStorage.getItem('stage24:draft')).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent(/сохранено в/i);
    expect(dirty).toHaveBeenLastCalledWith(false);
  });

  it('restores only a newer browser draft', () => {
    localStorage.setItem('newer', JSON.stringify({
      updated_at: '2026-09-23T18:01:00Z',
      value: {name: 'Восстановлено'},
    }));
    localStorage.setItem('stale', JSON.stringify({
      updated_at: '2026-09-23T17:59:00Z',
      value: {name: 'Старое'},
    }));

    expect(loadLocalDraft('newer', {name: 'Сервер'}, '2026-09-23T18:00:00Z')).toEqual({
      value: {name: 'Восстановлено'}, restored: true,
    });
    expect(loadLocalDraft('stale', {name: 'Сервер'}, '2026-09-23T18:00:00Z')).toEqual({
      value: {name: 'Сервер'}, restored: false,
    });
    expect(localStorage.getItem('stale')).toBeNull();
  });

  it('autosaves an edited garment parameter as an unconfirmed project draft', async () => {
    vi.useFakeTimers();
    const project = makeDemoProject('Платье');
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({
      ...candidate,
      revision: candidate.revision + 1,
      updated_at: new Date().toISOString(),
    }));
    render(<StyleEditor project={project} analysis={analysis} providerName="Демо" onSave={onSave} />);

    fireEvent.change(screen.getByLabelText(/длина юбки от талии/i), {target: {value: '64'}});
    expect(screen.getByRole('status')).toHaveTextContent('Есть несохранённые изменения');
    await act(async () => {
      vi.advanceTimersByTime(1200);
      await Promise.resolve();
    });

    expect(onSave).toHaveBeenCalledOnce();
    const candidate = onSave.mock.calls[0][0];
    expect(candidate.status).toBe('draft');
    expect(candidate.garment_spec.selection_status).toBe('proposed');
    expect(candidate.garment_spec.parameters.skirt.length_from_waist_mm).toBe(640);
  });

  it('searches, renames, duplicates, and confirms deletion in the project hub', async () => {
    const projects: ProjectSummary[] = [
      {project_id: '11111111-1111-4111-8111-111111111111', name: 'Летнее платье', revision: 3, status: 'draft', updated_at: '2026-09-23T18:00:00Z'},
      {project_id: '22222222-2222-4222-8222-222222222222', name: 'Прямые брюки', revision: 5, status: 'generated', updated_at: '2026-09-23T17:00:00Z'},
    ];
    const onRename = vi.fn(async () => undefined);
    const onDuplicate = vi.fn(async () => undefined);
    const onDelete = vi.fn(async () => undefined);
    render(<ProjectHub projects={projects} onOpen={vi.fn(async () => undefined)} onRename={onRename} onDuplicate={onDuplicate} onDelete={onDelete} />);

    await userEvent.type(screen.getByRole('searchbox'), 'брюки');
    expect(screen.getByText('Прямые брюки')).toBeVisible();
    expect(screen.queryByText('Летнее платье')).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole('searchbox'));

    const dressCard = screen.getByText('Летнее платье').closest('article')!;
    await userEvent.click(within(dressCard).getByRole('button', {name: 'Переименовать'}));
    const rename = within(dressCard).getByLabelText('Новое название');
    await userEvent.clear(rename);
    await userEvent.type(rename, 'Платье для отпуска');
    await userEvent.click(within(dressCard).getByRole('button', {name: 'Сохранить'}));
    await waitFor(() => expect(onRename).toHaveBeenCalledWith(projects[0].project_id, 'Платье для отпуска'));

    const trousersCard = screen.getByText('Прямые брюки').closest('article')!;
    await userEvent.click(within(trousersCard).getByRole('button', {name: 'Создать копию'}));
    await waitFor(() => expect(onDuplicate).toHaveBeenCalledWith(projects[1].project_id));
    await userEvent.click(within(trousersCard).getByRole('button', {name: 'Удалить'}));
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(within(trousersCard).getByRole('button', {name: 'Да, удалить'}));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(projects[1].project_id));
  });

  it('creates a new project identity while preserving editable inputs and dropping generated output', () => {
    const source = makeDemoProject('Платье');
    source.generation_history = [{generation_id: 'gen-old', created_at: source.updated_at, status: 'succeeded'}];
    const name = uniqueCopyName(source.name, [
      source,
      {...source, project_id: crypto.randomUUID(), name: 'Платье — копия'},
    ]);
    const copy = duplicateProjectDocument(source, name);

    expect(name).toBe('Платье — копия 2');
    expect(copy.project_id).not.toBe(source.project_id);
    expect(copy.body_measurements.profile_id).not.toBe(source.body_measurements.profile_id);
    expect(copy.garment_spec.garment_id).not.toBe(source.garment_spec.garment_id);
    expect(copy.fit_settings.settings_id).not.toBe(source.fit_settings.settings_id);
    expect(copy.fabric_properties.fabric_id).not.toBe(source.fabric_properties.fabric_id);
    expect(copy.garment_spec.parameters).toEqual(source.garment_spec.parameters);
    expect(copy.latest_generation).toBeNull();
    expect(copy.generation_history).toEqual([]);
    expect(copy.revision).toBe(1);
  });
});

import {FormEvent, useMemo, useState} from 'react';
import {ApiError} from './api';
import type {ProjectSummary} from './types';

const STATUS_NAMES: Record<string, string> = {
  draft: 'Черновик',
  inputs_confirmed: 'Входы подтверждены',
  generated: 'Выкройка построена',
  validation_failed: 'Нужна проверка',
  ready_for_production_export: 'Готово к экспорту',
};

function actionError(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : 'Не удалось выполнить действие. Попробуйте ещё раз.';
}

export function ProjectHub({
  projects,
  disabled = false,
  onOpen,
  onRename,
  onDuplicate,
  onDelete,
}: {
  projects: ProjectSummary[];
  disabled?: boolean;
  onOpen: (projectId: string) => Promise<void>;
  onRename: (projectId: string, name: string) => Promise<void>;
  onDuplicate: (projectId: string) => Promise<void>;
  onDelete: (projectId: string) => Promise<void>;
}) {
  const [query, setQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('ru-RU');
    if (!needle) return projects;
    return projects.filter((item) => (
      item.name.toLocaleLowerCase('ru-RU').includes(needle)
      || (STATUS_NAMES[item.status] ?? item.status).toLocaleLowerCase('ru-RU').includes(needle)
    ));
  }, [projects, query]);

  async function run(projectId: string, action: () => Promise<void>) {
    setWorkingId(projectId);
    setError('');
    try {
      await action();
    } catch (caught) {
      setError(actionError(caught));
    } finally {
      setWorkingId(null);
    }
  }

  function beginRename(project: ProjectSummary) {
    setDeleteId(null);
    setEditingId(project.project_id);
    setEditingName(project.name);
    setError('');
  }

  async function submitRename(event: FormEvent, projectId: string) {
    event.preventDefault();
    const name = editingName.trim();
    if (!name) {
      setError('Название проекта не может быть пустым.');
      return;
    }
    await run(projectId, async () => {
      await onRename(projectId, name);
      setEditingId(null);
    });
  }

  return (
    <section className="project-hub" aria-labelledby="projects-title">
      <div className="project-hub__heading">
        <div><p className="eyebrow">Локальная библиотека</p><h2 id="projects-title">Ваши проекты</h2></div>
        <label className="project-search">
          <span className="visually-hidden">Найти проект</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Найти по названию или статусу"
          />
        </label>
      </div>
      <p className="project-hub__count">Показано: {filtered.length} из {projects.length}</p>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {filtered.length === 0 ? (
        <div className="project-empty"><strong>Ничего не найдено</strong><span>Попробуйте изменить запрос.</span></div>
      ) : (
        <div className="project-grid">
          {filtered.map((item) => {
            const working = workingId === item.project_id;
            return (
              <article className="project-card" key={item.project_id}>
                {editingId === item.project_id ? (
                  <form className="project-rename" onSubmit={(event) => void submitRename(event, item.project_id)}>
                    <label htmlFor={`rename-${item.project_id}`}>Новое название</label>
                    <input
                      id={`rename-${item.project_id}`}
                      value={editingName}
                      onChange={(event) => setEditingName(event.target.value)}
                      maxLength={120}
                      autoFocus
                      disabled={working}
                    />
                    <span><button type="submit" disabled={working}>Сохранить</button><button type="button" onClick={() => setEditingId(null)} disabled={working}>Отмена</button></span>
                  </form>
                ) : (
                  <>
                    <button className="project-card__open" type="button" onClick={() => void run(item.project_id, () => onOpen(item.project_id))} disabled={disabled || working}>
                      <span><strong>{item.name}</strong><small>{STATUS_NAMES[item.status] ?? item.status} · версия {item.revision}</small></span>
                      <span aria-hidden="true">→</span>
                    </button>
                    <small className="project-card__date">Изменён {new Date(item.updated_at).toLocaleString('ru-RU', {dateStyle: 'medium', timeStyle: 'short'})}</small>
                    {deleteId === item.project_id ? (
                      <div className="project-delete-confirm" role="alert">
                        <strong>Удалить проект без возможности восстановления?</strong>
                        <span><button type="button" onClick={() => void run(item.project_id, async () => { await onDelete(item.project_id); setDeleteId(null); })} disabled={working}>Да, удалить</button><button type="button" onClick={() => setDeleteId(null)} disabled={working}>Отмена</button></span>
                      </div>
                    ) : (
                      <div className="project-card__actions">
                        <button type="button" onClick={() => beginRename(item)} disabled={working}>Переименовать</button>
                        <button type="button" onClick={() => void run(item.project_id, () => onDuplicate(item.project_id))} disabled={working}>Создать копию</button>
                        <button className="danger-text" type="button" onClick={() => { setEditingId(null); setDeleteId(item.project_id); }} disabled={working}>Удалить</button>
                      </div>
                    )}
                  </>
                )}
                {working && <span className="project-card__working" role="status">Выполняем…</span>}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

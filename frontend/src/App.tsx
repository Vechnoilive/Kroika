import {FormEvent, useEffect, useState} from 'react';
import {api, ApiError} from './api';
import {makeDemoProject} from './demoProject';
import {MeasurementWizard} from './MeasurementWizard';
import type {BodyMeasurements} from './types';
import type {ProjectDocument, ProjectSummary, StyleAnalysis} from './types';

const LAST_PROJECT_KEY = 'kroika:last-project-id';

const labels: Record<string, string> = {
  dress: 'Платье',
  semi_fitted: 'Полуприлегающий',
  round: 'Круглая',
  sleeveless: 'Без рукавов',
  a_line: 'А-силуэт',
  midi: 'Миди',
};

function human(value: string): string {
  return labels[value] ?? value;
}

function Logo() {
  return <div className="brand-mark" aria-hidden="true"><span>K</span></div>;
}

function Step({number, title, state}: {number: number; title: string; state: 'done' | 'active' | 'locked'}) {
  return (
    <li className={`step step--${state}`} aria-current={state === 'active' ? 'step' : undefined}>
      <span className="step__number">{state === 'done' ? '✓' : number}</span>
      <span>{title}</span>
    </li>
  );
}

function FriendlyError({error}: {error: ApiError}) {
  return (
    <div className="notice notice--error" role="alert">
      <strong>Не получилось выполнить действие</strong>
      <span>{error.message}</span>
      {error.issues && error.issues.length > 0 && (
        <ul>{error.issues.slice(0, 5).map((item) => (
          <li key={`${item.code}-${item.json_pointer}`}>{item.message_ru}</li>
        ))}</ul>
      )}
      {error.requestId && <small>Код обращения: {error.requestId.slice(0, 8)}</small>}
    </div>
  );
}

export default function App() {
  const [connection, setConnection] = useState<'checking' | 'ready' | 'offline'>('checking');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectDocument | null>(null);
  const [analysis, setAnalysis] = useState<StyleAnalysis | null>(null);
  const [projectName, setProjectName] = useState('Моё первое платье');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        await api.readiness();
        const list = await api.listProjects();
        if (!active) return;
        setConnection('ready');
        setProjects(list.items);
        const remembered = localStorage.getItem(LAST_PROJECT_KEY);
        if (remembered) {
          try {
            setProject(await api.getProject(remembered));
          } catch {
            localStorage.removeItem(LAST_PROJECT_KEY);
          }
        }
      } catch {
        if (active) setConnection('offline');
      }
    }
    void load();
    return () => { active = false; };
  }, []);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createProject(makeDemoProject(projectName));
      setProject(created);
      setProjects((current) => [created, ...current]);
      localStorage.setItem(LAST_PROJECT_KEY, created.project_id);
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught
        : new ApiError('Не удалось создать проект.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  async function openProject(projectId: string) {
    setBusy(true);
    setError(null);
    setAnalysis(null);
    try {
      const loaded = await api.getProject(projectId);
      setProject(loaded);
      localStorage.setItem(LAST_PROJECT_KEY, loaded.project_id);
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught
        : new ApiError('Не удалось открыть проект.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  async function analyzeDemo() {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      setAnalysis(await api.analyzeDemo(project.project_id));
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught
        : new ApiError('Не удалось проверить mock-анализ.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  function startAnother() {
    setProject(null);
    setAnalysis(null);
    setError(null);
    localStorage.removeItem(LAST_PROJECT_KEY);
  }

  async function saveMeasurements(profile: BodyMeasurements): Promise<ProjectDocument> {
    if (!project) throw new ApiError('Сначала откройте проект.', 0, 'PROJECT_REQUIRED');
    const updated = await api.replaceProject({...project, status: 'draft', body_measurements: profile});
    setProject(updated);
    setProjects((items) => items.map((item) => item.project_id === updated.project_id
      ? {
          project_id: updated.project_id,
          name: updated.name,
          revision: updated.revision,
          status: updated.status,
          updated_at: updated.updated_at,
        }
      : item));
    return updated;
  }

  const activeStep = !project ? 1 : !analysis ? 2
    : project.body_measurements.status === 'ready' ? 4 : 3;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Kroika — главная">
          <Logo />
          <span><strong>Kroika</strong><small>Выкройка шаг за шагом</small></span>
        </a>
        <div className={`connection connection--${connection}`} aria-live="polite">
          <span aria-hidden="true" />
          {connection === 'ready' && 'Работает локально'}
          {connection === 'checking' && 'Проверяем запуск…'}
          {connection === 'offline' && 'Нет связи с приложением'}
        </div>
      </header>

      <main className="workspace">
        <aside className="journey" aria-label="Этапы создания выкройки">
          <p className="eyebrow">Ваш путь</p>
          <h2>Пять понятных шагов</h2>
          <ol>
            <Step number={1} title="Создать проект" state={activeStep > 1 ? 'done' : 'active'} />
            <Step number={2} title="Добавить эскиз" state={activeStep > 2 ? 'done' : activeStep === 2 ? 'active' : 'locked'} />
            <Step number={3} title="Ввести мерки" state={activeStep > 3 ? 'done' : activeStep === 3 ? 'active' : 'locked'} />
            <Step number={4} title="Проверить фасон" state={activeStep === 4 ? 'active' : 'locked'} />
            <Step number={5} title="Получить выкройку" state="locked" />
          </ol>
          <div className="privacy-note">
            <span aria-hidden="true">⌂</span>
            <p><strong>Данные остаются на компьютере</strong>Сейчас используется локальная SQLite-база и безопасный mock.</p>
          </div>
        </aside>

        <section className="content">
          <div className="stage-badge">Базовые блоки · этап 7 из 15</div>
          {!project ? (
            <>
              <div className="intro">
                <p className="eyebrow">Начнём спокойно</p>
                <h1>Создадим выкройку<br /><em>последовательно</em></h1>
                <p>На каждом шаге приложение объяснит, что требуется. Ничего не будет рассчитано или отправлено без вашего подтверждения.</p>
              </div>

              {connection === 'offline' && (
                <div className="notice notice--error" role="alert">
                  <strong>Backend пока недоступен</strong>
                  <span>Запустите приложение по инструкции и обновите страницу.</span>
                </div>
              )}
              {error && <FriendlyError error={error} />}

              <form className="action-card" onSubmit={createProject}>
                <div className="action-card__icon" aria-hidden="true">01</div>
                <div className="action-card__body">
                  <h2>Как назовём проект?</h2>
                  <p>Название поможет найти работу позже. Его можно будет изменить.</p>
                  <label htmlFor="project-name">Название проекта</label>
                  <input
                    id="project-name"
                    value={projectName}
                    onChange={(event) => setProjectName(event.target.value)}
                    maxLength={120}
                    autoComplete="off"
                    disabled={busy || connection !== 'ready'}
                  />
                  <button className="primary-button" disabled={busy || connection !== 'ready'}>
                    {busy ? 'Создаём…' : 'Создать проект'} <span aria-hidden="true">→</span>
                  </button>
                  <p className="demo-warning"><strong>Без автозаполнения:</strong> новый профиль мерок будет пустым. Все значения вводятся человеком.</p>
                </div>
              </form>

              {projects.length > 0 && (
                <div className="recent-projects">
                  <h2>Недавние проекты</h2>
                  <div className="project-list">
                    {projects.slice(0, 4).map((item) => (
                      <button key={item.project_id} onClick={() => void openProject(item.project_id)} disabled={busy}>
                        <span><strong>{item.name}</strong><small>Черновик · версия {item.revision}</small></span>
                        <span aria-hidden="true">→</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="project-heading">
                <div>
                  <p className="eyebrow">Проект сохранён</p>
                  <h1>{project.name}</h1>
                  <p>Можно закрыть страницу: проект останется в локальном хранилище.</p>
                </div>
                <button className="text-button" onClick={startAnother}>Другой проект</button>
              </div>
              {error && <FriendlyError error={error} />}

              {!analysis ? (
                <div className="action-card action-card--sketch">
                  <div className="action-card__icon" aria-hidden="true">02</div>
                  <div className="action-card__body">
                    <h2>Проверим анализ эскиза</h2>
                    <p>Настоящий Qwen подключим на этапе 10. Сейчас mock безопасно показывает последовательность работы без передачи фотографии.</p>
                    <div className="mock-preview" aria-hidden="true">
                      <svg viewBox="0 0 240 250" role="img">
                        <path d="M92 23c8 12 48 12 56 0l23 23-19 30-7-8 15 155H80L95 68l-7 8-19-30 23-23Z" />
                        <path d="M95 68c17 9 33 9 50 0M88 126h64M120 35v188" />
                      </svg>
                      <span>Демонстрационный эскиз</span>
                    </div>
                    <button className="primary-button" onClick={() => void analyzeDemo()} disabled={busy}>
                      {busy ? 'Проверяем…' : 'Запустить mock-анализ'} <span aria-hidden="true">→</span>
                    </button>
                    <p className="demo-warning"><strong>Без передачи фото:</strong> это заранее подготовленный ответ для проверки интерфейса.</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="analysis-card analysis-card--compact">
                    <div className="success-mark" aria-hidden="true">✓</div>
                    <div>
                      <p className="eyebrow">Mock ответил</p>
                      <h2>Похоже на платье А-силуэта</h2>
                      <p>Это предложение, а не окончательное решение. Перед построением все признаки нужно будет подтвердить.</p>
                    </div>
                    <dl className="feature-grid">
                      <div><dt>Изделие</dt><dd>{human(analysis.garment_category)}</dd></div>
                      <div><dt>Посадка</dt><dd>{human(analysis.silhouette.fit)}</dd></div>
                      <div><dt>Горловина</dt><dd>{human(analysis.neckline.front)}</dd></div>
                      <div><dt>Рукав</dt><dd>{human(analysis.sleeves.length)}</dd></div>
                      <div><dt>Юбка</dt><dd>{human(analysis.lower_part.type)}</dd></div>
                      <div><dt>Длина</dt><dd>{human(analysis.lower_part.length_category)}</dd></div>
                    </dl>
                    <div className="questions">
                      <strong>Позже приложение уточнит:</strong>
                      <ul>{analysis.targeted_questions.map((item) => <li key={item}>{item}</li>)}</ul>
                    </div>
                  </div>
                  <MeasurementWizard project={project} onSaveProject={saveMeasurements} />
                </>
              )}
            </>
          )}
        </section>
      </main>
      <footer>
        <span>Kroika · локальный прототип</span>
        <span>Методика имеет статус experimental — не для производственного пошива</span>
      </footer>
    </div>
  );
}

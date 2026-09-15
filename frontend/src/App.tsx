import {FormEvent, useEffect, useState} from 'react';
import {api, ApiError} from './api';
import {makeDemoProject} from './demoProject';
import {MeasurementWizard} from './MeasurementWizard';
import type {BodyMeasurements} from './types';
import type {PatternEngineResult, ProjectDocument, ProjectSummary, StyleAnalysis} from './types';

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

export function PatternResultCard({
  result,
  onRebuild,
  busy = false,
}: {
  result: PatternEngineResult;
  onRebuild?: () => void;
  busy?: boolean;
}) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const pattern = result.pattern;
  if (!pattern) return null;
  if (!pattern.print_layout) {
    return (
      <section className="pattern-result" aria-labelledby="pattern-result-title">
        <div className="pattern-result__heading">
          <div className="success-mark" aria-hidden="true">↻</div>
          <div>
            <p className="eyebrow">Сохранённый результат</p>
            <h2 id="pattern-result-title">Выкройку нужно обновить для печати</h2>
            <p>Это результат предыдущей версии. Мерки сохранены — приложение только заново построит линии среза.</p>
          </div>
        </div>
        <div className="notice notice--warning">
          <strong>Старый файл не отправляется на печать</strong>
          <span>Перестройте выкройку, чтобы получить проверяемый SVG и PDF A4 1:1.</span>
        </div>
        {onRebuild && (
          <button className="primary-button" onClick={onRebuild} disabled={busy}>
            {busy ? 'Обновляем…' : 'Перестроить для печати'} <span aria-hidden="true">→</span>
          </button>
        )}
      </section>
    );
  }

  async function downloadPdf() {
    setDownloading(true);
    setDownloadError(null);
    try {
      const file = await api.downloadA4Pdf(result.generation_id);
      const url = URL.createObjectURL(file.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setDownloadError(
        caught instanceof ApiError ? caught.message : 'Не удалось скачать PDF. Попробуйте ещё раз.',
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="pattern-result" aria-labelledby="pattern-result-title">
      <div className="pattern-result__heading">
        <div className="success-mark" aria-hidden="true">✓</div>
        <div>
          <p className="eyebrow">Шаг 5 · пробная печать</p>
          <h2 id="pattern-result-title">Выкройка готова к проверке на бумаге</h2>
          <p>Чёрная линия показывает срез, красный пунктир — шов. Припуски уже отличаются для низа, молнии, горловины, проймы и обычных швов.</p>
        </div>
      </div>
      <div className="preview-frame">
        <img
          src={api.patternPreviewUrl(result.generation_id)}
          alt="Предпросмотр деталей с линиями шва и среза, долевыми и контрольными метками"
        />
      </div>
      <dl className="result-facts">
        <div><dt>Детали</dt><dd>{pattern.pieces.length}</dd></div>
        <div><dt>Пары швов</dt><dd>{pattern.seam_pairs.length}</dd></div>
        <div><dt>Печать</dt><dd>A4 · 1:1</dd></div>
      </dl>
      <div className="notice notice--warning">
        <strong>Печатать можно для проверки — кроить ткань пока нельзя</strong>
        <span>Сначала измерьте контрольный квадрат, соберите бумажные листы и изготовьте макет. Методика и посадка всё ещё имеют статус experimental.</span>
      </div>
      <section className="print-guide" aria-labelledby="print-guide-title">
        <h3 id="print-guide-title">Как распечатать без ошибки</h3>
        <ol>
          <li><span>1</span><p><strong>Выберите 100%</strong>В окне печати включите «Actual size / Реальный размер» и отключите подгонку.</p></li>
          <li><span>2</span><p><strong>Проверьте 50 × 50 мм</strong>Сначала измерьте квадрат на странице с картой. Ошибка даже в 1 мм означает неверный масштаб.</p></li>
          <li><span>3</span><p><strong>Соберите по меткам</strong>Совместите A1, B1 и следующие листы по крестам и области нахлёста {pattern.print_layout.overlap_mm} мм.</p></li>
        </ol>
      </section>
      {downloadError && <div className="inline-error" role="alert">{downloadError}</div>}
      <div className="export-actions">
        <a className="secondary-link" href={api.printSvgUrl(result.generation_id)} download>
          Скачать единый SVG
        </a>
        <button className="primary-button" onClick={() => void downloadPdf()} disabled={downloading}>
          {downloading ? 'Готовим листы…' : 'Скачать PDF A4 для проверки'} <span aria-hidden="true">↓</span>
        </button>
      </div>
    </section>
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

  async function generatePattern() {
    if (!project || project.body_measurements.status !== 'ready') return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.generatePattern(project);
      if (result.status !== 'succeeded' || !result.pattern) {
        const firstIssue = result.validation_report.issues[0];
        throw new ApiError(
          firstIssue?.message_ru ?? 'Построение остановлено проверкой входных данных.',
          422,
          firstIssue?.code ?? 'PATTERN_REJECTED',
          undefined,
          result.validation_report.issues,
        );
      }
      const refreshed = await api.getProject(project.project_id);
      setProject(refreshed);
      setProjects((items) => items.map((item) => item.project_id === refreshed.project_id
        ? {
            project_id: refreshed.project_id,
            name: refreshed.name,
            revision: refreshed.revision,
            status: refreshed.status,
            updated_at: refreshed.updated_at,
          }
        : item));
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught
        : new ApiError('Не удалось построить выкройку.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  const activeStep = !project ? 1
    : project.latest_generation?.status === 'succeeded' ? 5
    : !analysis ? 2
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
            <Step number={4} title="Проверить фасон" state={activeStep > 4 ? 'done' : activeStep === 4 ? 'active' : 'locked'} />
            <Step number={5} title="Получить выкройку" state={activeStep === 5 ? 'active' : 'locked'} />
          </ol>
          <div className="privacy-note">
            <span aria-hidden="true">⌂</span>
            <p><strong>Данные остаются на компьютере</strong>Сейчас используется локальная SQLite-база и безопасный mock.</p>
          </div>
        </aside>

        <section className="content">
          <div className="stage-badge">Припуски и печать · этап 9 из 15</div>
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

              {project.latest_generation?.status === 'succeeded' && project.latest_generation.pattern ? (
                <PatternResultCard
                  result={project.latest_generation}
                  onRebuild={() => void generatePattern()}
                  busy={busy}
                />
              ) : !analysis ? (
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
                  {project.body_measurements.status === 'ready' && (
                    <section className="generation-card" aria-labelledby="generation-title">
                      <div className="action-card__icon" aria-hidden="true">04</div>
                      <div>
                        <p className="eyebrow">Последняя проверка</p>
                        <h2 id="generation-title">Построить выкройку для пробной печати?</h2>
                        <p>Будут созданы лиф, юбка, две обтачки, разные припуски, линии среза, контрольные метки и пары швов. Исходные мерки останутся без изменений.</p>
                        <ul>
                          <li>{project.garment_spec.garment_type === 'sundress' ? 'Сарафан' : 'Платье'} без рукавов</li>
                          <li>Круглая горловина и А-силуэт</li>
                          <li>Молния по центру спинки</li>
                        </ul>
                        <button className="primary-button" onClick={() => void generatePattern()} disabled={busy}>
                          {busy ? 'Строим и проверяем…' : 'Построить линии шва и среза'} <span aria-hidden="true">→</span>
                        </button>
                        <p className="demo-warning"><strong>Пробный режим:</strong> PDF можно печатать на бумаге; раскрой ткани останется заблокирован.</p>
                      </div>
                    </section>
                  )}
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

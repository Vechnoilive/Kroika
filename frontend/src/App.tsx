import {FormEvent, useEffect, useState} from 'react';
import {api, ApiError} from './api';
import {makeDemoProject} from './demoProject';
import {MeasurementWizard} from './MeasurementWizard';
import {ConstructionEditor, ProjectHistory, StyleEditor} from './ProjectWorkflow';
import {VisionAnalyzer} from './VisionAnalyzer';
import {configureGarment, GARMENT_NAMES} from './garments';
import type {
  BodyMeasurements,
  GarmentAcceptanceStatus,
  GarmentType,
  PatternEngineResult,
  PatternLayer,
  ProjectDocument,
  ProjectSummary,
  StyleAnalysis,
  VisionProviderId,
} from './types';

const LAST_PROJECT_KEY = 'kroika:last-project-id';

const PROVIDER_NAMES: Record<VisionProviderId, string> = {
  mock: 'Демо-режим',
  qwen: 'Qwen',
  gemini: 'Gemini',
};

const STATUS_NAMES: Record<string, string> = {
  draft: 'Черновик',
  inputs_confirmed: 'Входы подтверждены',
  generated: 'Выкройка построена',
  validation_failed: 'Нужна проверка',
  ready_for_production_export: 'Готово к экспорту',
};

const LAYERS: Array<{id: PatternLayer; label: string}> = [
  {id: 'cutting', label: 'Линия среза'},
  {id: 'seam', label: 'Линия шва'},
  {id: 'internal', label: 'Вытачки и внутренние'},
  {id: 'fold', label: 'Сгибы'},
  {id: 'grain', label: 'Долевая'},
  {id: 'notches', label: 'Надсечки'},
  {id: 'labels', label: 'Подписи'},
  {id: 'dimensions', label: 'Размеры деталей'},
];

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
  onNewVersion,
  busy = false,
  acceptance,
}: {
  result: PatternEngineResult;
  onRebuild?: () => void;
  onNewVersion?: () => void;
  busy?: boolean;
  acceptance?: GarmentAcceptanceStatus;
}) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(100);
  const [layers, setLayers] = useState<PatternLayer[]>(LAYERS.map((item) => item.id));
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
            <p>Мерки сохранены. Приложение только заново построит линии среза.</p>
          </div>
        </div>
        {onRebuild && <button className="primary-button" onClick={onRebuild} disabled={busy}>{busy ? 'Обновляем…' : 'Перестроить для печати'} <span aria-hidden="true">→</span></button>}
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
      setDownloadError(caught instanceof ApiError ? caught.message : 'Не удалось скачать PDF.');
    } finally {
      setDownloading(false);
    }
  }

  function toggleLayer(layer: PatternLayer) {
    setLayers((current) => current.includes(layer)
      ? current.filter((item) => item !== layer)
      : [...current, layer]);
  }

  return (
    <section className="pattern-result" aria-labelledby="pattern-result-title">
      <div className="pattern-result__heading">
        <div className="success-mark" aria-hidden="true">✓</div>
        <div>
          <p className="eyebrow">Шаг 7 · просмотр и пробная печать</p>
          <h2 id="pattern-result-title">Выкройка готова к проверке</h2>
          <p>Масштабируйте чертёж и оставьте только нужные слои. Скачиваемые SVG и PDF всегда содержат полный комплект.</p>
        </div>
      </div>

      <div className="preview-tools">
        <fieldset>
          <legend>Показывать на чертеже</legend>
          {LAYERS.map((layer) => (
            <label key={layer.id}>
              <input type="checkbox" checked={layers.includes(layer.id)} onChange={() => toggleLayer(layer.id)} />
              <span>{layer.label}</span>
            </label>
          ))}
        </fieldset>
        <label className="zoom-control" htmlFor="pattern-zoom">
          <span>Масштаб просмотра: {zoom}%</span>
          <input id="pattern-zoom" type="range" min="50" max="180" step="10" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} />
        </label>
      </div>
      <div className="preview-frame">
        <img
          key={layers.join(',')}
          style={{width: `${zoom}%`}}
          src={api.patternPreviewUrl(result.generation_id, layers)}
          alt="Интерактивный предпросмотр деталей выкройки"
        />
      </div>

      <dl className="result-facts">
        <div><dt>Детали</dt><dd>{pattern.pieces.length}</dd></div>
        <div><dt>Пары швов</dt><dd>{pattern.seam_pairs.length}</dd></div>
        <div><dt>Печать</dt><dd>A4 · 1:1</dd></div>
      </dl>
      <div className="notice notice--warning">
        <strong>Печатать можно для проверки — кроить ткань пока нельзя</strong>
        <span>{acceptance?.name_ru ?? 'Изделие'}: expert status — {acceptance?.expert_status ?? 'pending'}, toile status — {acceptance?.toile_status ?? 'pending'}. Проверьте квадрат, бумажную сборку и макет.</span>
      </div>
      <section className="print-guide" aria-labelledby="print-guide-title">
        <h3 id="print-guide-title">Как распечатать без ошибки</h3>
        <ol>
          <li><span>1</span><p><strong>Выберите 100%</strong>Отключите подгонку к странице.</p></li>
          <li><span>2</span><p><strong>Проверьте 50 × 50 мм</strong>Измерьте квадрат линейкой.</p></li>
          <li><span>3</span><p><strong>Соберите по меткам</strong>Нахлёст листов — {pattern.print_layout.overlap_mm} мм.</p></li>
        </ol>
      </section>
      {downloadError && <div className="inline-error" role="alert">{downloadError}</div>}
      <div className="export-actions export-actions--three">
        <a className="secondary-link" href={api.printSvgUrl(result.generation_id)} download>Единый SVG</a>
        <a className="secondary-link" href={api.projectJsonUrl(result.generation_id)} download>JSON проекта</a>
        <button className="primary-button" onClick={() => void downloadPdf()} disabled={downloading}>{downloading ? 'Готовим…' : 'PDF A4 для проверки'} <span aria-hidden="true">↓</span></button>
      </div>
      {onNewVersion && (
        <button className="text-button new-version-button" type="button" onClick={onNewVersion} disabled={busy}>
          Изменить параметры и создать новую версию
        </button>
      )}
    </section>
  );
}

function proposalFromAnalysis(project: ProjectDocument, analysis: StyleAnalysis): ProjectDocument['garment_spec'] {
  const current = project.garment_spec;
  const supported: GarmentType[] = [
    'dress', 'sundress', 'skirt', 'top', 'blouse', 'shirt', 'vest', 'jacket',
    'trousers', 'shorts',
  ];
  const garmentType = supported.includes(analysis.garment_category as GarmentType)
    ? analysis.garment_category as GarmentType
    : 'dress';
  const bodiceFit = analysis.silhouette.fit === 'fitted' ? 'fitted' : 'semi_fitted';
  return configureGarment({
    ...current,
    parameters: {
      ...current.parameters,
      bodice_fit: bodiceFit,
    },
    unsupported_features: [],
  }, garmentType);
}

export default function App() {
  const [connection, setConnection] = useState<'checking' | 'ready' | 'offline'>('checking');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectDocument | null>(null);
  const [projectName, setProjectName] = useState('Моё первое платье');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [garmentCatalogue, setGarmentCatalogue] = useState<GarmentAcceptanceStatus[]>([]);

  function remember(updated: ProjectDocument) {
    setProject(updated);
    localStorage.setItem(LAST_PROJECT_KEY, updated.project_id);
    setProjects((items) => {
      const summary: ProjectSummary = {
        project_id: updated.project_id,
        name: updated.name,
        revision: updated.revision,
        status: updated.status,
        updated_at: updated.updated_at,
      };
      return [summary, ...items.filter((item) => item.project_id !== updated.project_id)];
    });
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        await api.readiness();
        const [list, catalogue] = await Promise.all([api.listProjects(), api.garmentCatalogue()]);
        if (!active) return;
        setConnection('ready');
        setProjects(list.items);
        setGarmentCatalogue(catalogue.items);
        const remembered = localStorage.getItem(LAST_PROJECT_KEY);
        if (remembered) {
          try {
            const loaded = await api.getProject(remembered);
            if (active) setProject(loaded);
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
      remember(await api.createProject(makeDemoProject(projectName)));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError('Не удалось создать проект.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  async function openProject(projectId: string) {
    setBusy(true);
    setError(null);
    try {
      remember(await api.getProject(projectId));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError('Не удалось открыть проект.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  function startAnother() {
    setProject(null);
    setError(null);
    localStorage.removeItem(LAST_PROJECT_KEY);
  }

  async function saveProject(candidate: ProjectDocument): Promise<ProjectDocument> {
    const updated = await api.replaceProject(candidate);
    remember(updated);
    return updated;
  }

  async function saveAnalysis(
    analysis: StyleAnalysis,
    details: {providerId: VisionProviderId; providerName: string; imageRefs: string[]},
  ) {
    if (!project) throw new ApiError('Сначала откройте проект.', 0, 'PROJECT_REQUIRED');
    const external = details.providerId !== 'mock';
    const candidate: ProjectDocument = {
      ...project,
      status: 'draft',
      image_refs: details.imageRefs,
      style_analysis_id: crypto.randomUUID(),
      style_analysis_provider: details.providerId,
      style_analysis: analysis,
      garment_spec: proposalFromAnalysis(project, analysis),
      privacy: {
        ...project.privacy,
        allow_external_ai: external,
        consent_recorded_at: external ? new Date().toISOString() : null,
      },
      fit_settings: {...project.fit_settings, status: 'draft', confirmed_at: null},
      fabric_properties: {...project.fabric_properties, status: 'draft', confirmed_at: null},
    };
    await saveProject(candidate);
  }

  async function saveMeasurements(profile: BodyMeasurements): Promise<ProjectDocument> {
    if (!project) throw new ApiError('Сначала откройте проект.', 0, 'PROJECT_REQUIRED');
    return saveProject({...project, status: 'draft', body_measurements: profile});
  }

  async function generatePattern() {
    if (!project
        || project.body_measurements.status !== 'ready'
        || project.garment_spec.selection_status !== 'confirmed'
        || project.fit_settings.status !== 'confirmed'
        || project.fabric_properties.status !== 'confirmed') return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.generatePattern(project);
      if (result.status !== 'succeeded' || !result.pattern) {
        const firstIssue = result.validation_report.issues[0];
        throw new ApiError(firstIssue?.message_ru ?? 'Построение остановлено проверкой входов.', 422, firstIssue?.code ?? 'PATTERN_REJECTED', undefined, result.validation_report.issues);
      }
      remember(await api.getProject(project.project_id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError('Не удалось построить выкройку.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  async function startNewVersion() {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      await saveProject({
        ...project,
        status: 'draft',
        garment_spec: {...project.garment_spec, selection_status: 'proposed', confirmed_at: null},
        fit_settings: {...project.fit_settings, status: 'draft', confirmed_at: null},
        fabric_properties: {...project.fabric_properties, status: 'draft', confirmed_at: null},
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError('Не удалось начать новую версию.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  const analysis = project?.style_analysis ?? null;
  const analysisProvider = project?.style_analysis_provider
    ? PROVIDER_NAMES[project.style_analysis_provider]
    : 'Анализ фасона';
  const currentAcceptance = project
    ? garmentCatalogue.find((item) => item.garment_type === project.garment_spec.garment_type)
    : undefined;
  const activeStep = !project ? 1
    : !analysis ? 2
    : project.garment_spec.selection_status !== 'confirmed' ? 3
    : project.body_measurements.status !== 'ready' ? 4
    : project.fit_settings.status !== 'confirmed' || project.fabric_properties.status !== 'confirmed' ? 5
    : project.latest_generation?.status === 'succeeded' ? 7
    : 6;
  const isLowerGarment = project
    ? ['trousers', 'shorts'].includes(project.garment_spec.garment_type)
    : false;
  const garmentConstruction = project
    ? isLowerGarment
      ? 'прямая основа с поясом'
      : project.garment_spec.garment_type === 'skirt'
        ? 'А-силуэт с поясом'
        : project.garment_spec.parameters.bodice_fit === 'fitted'
          ? 'прилегающая основа'
          : 'полуприлегающая основа'
    : '';
  const garmentLength = project
    ? isLowerGarment
      ? `Длина изделия ${(project.garment_spec.parameters.trousers?.length_mm ?? 0) / 10} см`
      : ['dress', 'sundress', 'skirt'].includes(project.garment_spec.garment_type)
        ? `Длина юбки ${project.garment_spec.parameters.skirt.length_from_waist_mm / 10} см`
        : `Длина ниже талии ${(project.garment_spec.parameters.upper?.length_below_waist_mm ?? 100) / 10} см`
    : '';

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Kroika — главная"><Logo /><span><strong>Kroika</strong><small>Выкройка шаг за шагом</small></span></a>
        <div className={`connection connection--${connection}`} aria-live="polite"><span aria-hidden="true" />{connection === 'ready' && 'Работает локально'}{connection === 'checking' && 'Проверяем запуск…'}{connection === 'offline' && 'Нет связи с приложением'}</div>
      </header>

      <main className="workspace">
        <aside className="journey" aria-label="Этапы создания выкройки">
          <p className="eyebrow">Ваш путь</p>
          <h2>Семь понятных шагов</h2>
          <ol>
            {['Создать проект', 'Добавить эскиз', 'Подтвердить фасон', 'Ввести мерки', 'Ткань и прибавки', 'Построить', 'Проверить и скачать'].map((title, index) => {
              const number = index + 1;
              return <Step key={title} number={number} title={title} state={activeStep > number ? 'done' : activeStep === number ? 'active' : 'locked'} />;
            })}
          </ol>
          <div className="privacy-note"><span aria-hidden="true">⌂</span><p><strong>Мерки остаются на компьютере</strong>Фото отправляется Qwen только после отдельного согласия.</p></div>
        </aside>

        <section className="content">
          <div className="stage-badge">Qwen · 10 типов изделий · этап 15 из 15</div>
          {!project ? (
            <>
              <div className="intro"><p className="eyebrow">Начнём спокойно</p><h1>Создадим выкройку<br /><em>последовательно</em></h1><p>Каждый шаг сохраняется. Никакие мерки не угадываются, а результат AI всегда подтверждает человек.</p></div>
              {connection === 'offline' && <div className="notice notice--error" role="alert"><strong>Backend пока недоступен</strong><span>Запустите приложение по инструкции и обновите страницу.</span></div>}
              {error && <FriendlyError error={error} />}
              <form className="action-card" onSubmit={createProject}>
                <div className="action-card__icon" aria-hidden="true">01</div>
                <div className="action-card__body"><h2>Как назовём проект?</h2><p>Название поможет найти работу позже.</p><label htmlFor="project-name">Название проекта</label><input id="project-name" value={projectName} onChange={(event) => setProjectName(event.target.value)} maxLength={120} autoComplete="off" disabled={busy || connection !== 'ready'} /><button className="primary-button" disabled={busy || connection !== 'ready'}>{busy ? 'Создаём…' : 'Создать проект'} <span aria-hidden="true">→</span></button><p className="demo-warning"><strong>Без автозаполнения мерок:</strong> все размеры вводит человек.</p></div>
              </form>
              {projects.length > 0 && <div className="recent-projects"><h2>Недавние проекты</h2><div className="project-list">{projects.slice(0, 4).map((item) => <button key={item.project_id} onClick={() => void openProject(item.project_id)} disabled={busy}><span><strong>{item.name}</strong><small>{STATUS_NAMES[item.status] ?? item.status} · версия {item.revision}</small></span><span aria-hidden="true">→</span></button>)}</div></div>}
            </>
          ) : (
            <>
              <div className="project-heading"><div><p className="eyebrow">{STATUS_NAMES[project.status]} · версия {project.revision}</p><h1>{project.name}</h1><p>Черновик сохраняется на каждом завершённом шаге.</p></div><button className="text-button" onClick={startAnother}>Другой проект</button></div>
              {error && <FriendlyError error={error} />}

              {activeStep === 2 && <VisionAnalyzer projectId={project.project_id} onComplete={saveAnalysis} />}
              {activeStep === 3 && analysis && <StyleEditor project={project} analysis={analysis as StyleAnalysis} providerName={analysisProvider} acceptance={currentAcceptance} onSave={saveProject} />}
              {activeStep === 4 && <MeasurementWizard key={`${project.project_id}-${project.garment_spec.confirmed_at}`} project={project} onSaveProject={saveMeasurements} />}
              {activeStep === 5 && <ConstructionEditor project={project} onSave={saveProject} />}
              {activeStep === 6 && (
                <section className="generation-card" aria-labelledby="generation-title"><div className="action-card__icon" aria-hidden="true">06</div><div><p className="eyebrow">Все входы подтверждены</p><h2 id="generation-title">Построить выкройку?</h2><p>Формульный движок создаст детали из сохранённых мерок, фасона, ткани и прибавок, затем проверит геометрию.</p><ul><li>{GARMENT_NAMES[project.garment_spec.garment_type]} · {garmentConstruction}</li><li>{garmentLength}</li><li>Стабильная тканая ткань · пробный статус</li><li>Экспертная проверка и макет: ещё не пройдены</li></ul><button className="primary-button" onClick={() => void generatePattern()} disabled={busy}>{busy ? 'Строим и проверяем…' : 'Построить выкройку'} <span aria-hidden="true">→</span></button></div></section>
              )}
              {activeStep === 7 && project.latest_generation && <PatternResultCard result={project.latest_generation} acceptance={currentAcceptance} onRebuild={() => void generatePattern()} onNewVersion={() => void startNewVersion()} busy={busy} />}
              <ProjectHistory project={project} onRestored={remember} />
            </>
          )}
        </section>
      </main>
      <footer><span>Kroika · локальный прототип</span><span>Методика experimental — перед раскроем обязателен макет</span></footer>
    </div>
  );
}

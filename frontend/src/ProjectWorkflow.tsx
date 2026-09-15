import {FormEvent, useEffect, useState} from 'react';
import {api, ApiError} from './api';
import type {
  FabricProperties,
  FitSettings,
  GarmentSpec,
  ProjectDocument,
  ProjectHistoryEntry,
  StyleAnalysis,
} from './types';

type SaveProject = (candidate: ProjectDocument) => Promise<ProjectDocument>;

const bounded = (value: number, minimum: number, maximum: number) => (
  Number.isFinite(value) && value >= minimum && value <= maximum
);

function NumberField({
  id,
  label,
  value,
  min,
  max,
  unit = 'см',
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  unit?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="compact-number" htmlFor={id}>
      <span>{label}</span>
      <span>
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step="0.1"
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <em>{unit}</em>
      </span>
      <small>Допустимо: {min}–{max} {unit}</small>
    </label>
  );
}

export function StyleEditor({
  project,
  analysis,
  providerName,
  onSave,
}: {
  project: ProjectDocument;
  analysis: StyleAnalysis;
  providerName: string;
  onSave: SaveProject;
}) {
  const [spec, setSpec] = useState<GarmentSpec>(() => structuredClone(project.garment_spec));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const suggestedUnsupported = [
    analysis.neckline.front !== 'round' ? `горловина «${analysis.neckline.front}»` : '',
    analysis.sleeves.length !== 'sleeveless' ? `рукав «${analysis.sleeves.length}»` : '',
    analysis.lower_part.type !== 'a_line' ? `юбка «${analysis.lower_part.type}»` : '',
  ].filter(Boolean);

  function updateParameters(next: Partial<GarmentSpec['parameters']>) {
    setSpec({...spec, selection_status: 'proposed', confirmed_at: null, parameters: {
      ...spec.parameters,
      ...next,
    }});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const {neckline, skirt, closure} = spec.parameters;
    if (!bounded(neckline.front_depth_mm, 50, 250)
        || !bounded(neckline.back_depth_mm, 10, 120)
        || !bounded(skirt.length_from_waist_mm, 350, 1200)
        || !bounded(skirt.hem_expansion_each_side_mm, 0, 250)
        || !bounded(closure.length_mm, 300, 900)) {
      setError('Проверьте числовые значения: одно из них вне указанного диапазона.');
      return;
    }
    setBusy(true);
    setError('');
    const now = new Date().toISOString();
    const confirmed: GarmentSpec = {
      ...spec,
      selection_status: 'confirmed',
      unsupported_features: [],
      confirmed_at: now,
    };
    const presetId = confirmed.parameters.bodice_fit === 'fitted'
      ? 'woven_fitted_trial'
      : 'woven_semi_fitted_trial';
    try {
      await onSave({
        ...project,
        status: 'draft',
        garment_spec: confirmed,
        fit_settings: {
          ...project.fit_settings,
          status: 'draft',
          preset: {id: presetId, version: '0.1.0'},
          confirmed_at: null,
        },
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Не удалось сохранить фасон.');
    } finally {
      setBusy(false);
    }
  }

  const {parameters} = spec;
  return (
    <form className="workflow-card" onSubmit={(event) => void submit(event)}>
      <header className="workflow-card__header">
        <span className="action-card__icon" aria-hidden="true">03</span>
        <div>
          <p className="eyebrow">Предложение {providerName}</p>
          <h2>Проверьте фасон своими глазами</h2>
          <p>Модель только подсказала признаки. Выкройка получит именно значения ниже после вашего подтверждения.</p>
        </div>
      </header>

      {suggestedUnsupported.length > 0 && (
        <div className="notice notice--warning">
          <strong>На изображении замечены пока неподдержанные элементы</strong>
          <span>{suggestedUnsupported.join(', ')}. На этапе 11 доступны круглая горловина, изделие без рукавов и А-юбка; замена показана явно.</span>
        </div>
      )}

      <fieldset className="plain-choice">
        <legend>Что строим?</legend>
        <label><input type="radio" checked={spec.garment_type === 'dress'} onChange={() => setSpec({...spec, garment_type: 'dress'})} /> Платье</label>
        <label><input type="radio" checked={spec.garment_type === 'sundress'} onChange={() => setSpec({...spec, garment_type: 'sundress'})} /> Сарафан</label>
      </fieldset>

      <fieldset className="plain-choice">
        <legend>Посадка лифа</legend>
        <label><input type="radio" checked={parameters.bodice_fit === 'semi_fitted'} onChange={() => updateParameters({bodice_fit: 'semi_fitted'})} /> Полуприлегающая</label>
        <label><input type="radio" checked={parameters.bodice_fit === 'fitted'} onChange={() => updateParameters({bodice_fit: 'fitted'})} /> Прилегающая</label>
      </fieldset>

      <div className="locked-features" aria-label="Зафиксированные поддержанные элементы">
        <div><strong>Круглая горловина</strong><span>форма пока фиксирована</span></div>
        <div><strong>Без рукавов</strong><span>с обтачкой проймы</span></div>
        <div><strong>А-силуэт</strong><span>отрезная юбка</span></div>
        <div><strong>Молния сзади</strong><span>по центру спинки</span></div>
      </div>

      <div className="number-grid">
        <NumberField id="front-neck-depth" label="Глубина горловины спереди" value={parameters.neckline.front_depth_mm / 10} min={5} max={25} onChange={(value) => updateParameters({neckline: {...parameters.neckline, type: 'round', front_depth_mm: value * 10}})} />
        <NumberField id="back-neck-depth" label="Глубина горловины сзади" value={parameters.neckline.back_depth_mm / 10} min={1} max={12} onChange={(value) => updateParameters({neckline: {...parameters.neckline, type: 'round', back_depth_mm: value * 10}})} />
        <NumberField id="skirt-length" label="Длина юбки от талии" value={parameters.skirt.length_from_waist_mm / 10} min={35} max={120} onChange={(value) => updateParameters({skirt: {...parameters.skirt, type: 'a_line', length_from_waist_mm: value * 10}})} />
        <NumberField id="hem-expansion" label="Расширение низа с каждой стороны" value={parameters.skirt.hem_expansion_each_side_mm / 10} min={0} max={25} onChange={(value) => updateParameters({skirt: {...parameters.skirt, type: 'a_line', hem_expansion_each_side_mm: value * 10}})} />
        <NumberField id="zipper-length" label="Рабочая длина молнии" value={parameters.closure.length_mm / 10} min={30} max={90} onChange={(value) => updateParameters({closure: {...parameters.closure, length_mm: value * 10}})} />
      </div>

      {analysis.targeted_questions.length > 0 && (
        <div className="questions">
          <strong>Что стоит проверить по исходному изделию</strong>
          <ul>{analysis.targeted_questions.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="primary-button" disabled={busy}>
        {busy ? 'Сохраняем…' : 'Подтвердить фасон'} <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}

const EASE_FIELDS: Array<{key: keyof FitSettings['wearing_ease_mm']; label: string; min: number; max: number}> = [
  {key: 'bust', label: 'По груди', min: 2, max: 12},
  {key: 'waist', label: 'По талии', min: 1, max: 10},
  {key: 'hips', label: 'По бёдрам', min: 2, max: 12},
];

const ALLOWANCE_FIELDS: Array<{key: keyof FitSettings['seam_allowances_mm']; label: string; min: number; max: number}> = [
  {key: 'normal', label: 'Обычные швы', min: 0, max: 3},
  {key: 'neckline', label: 'Горловина', min: 0, max: 2},
  {key: 'armhole', label: 'Пройма', min: 0, max: 2},
  {key: 'zipper', label: 'У молнии', min: 0, max: 4},
  {key: 'hem', label: 'Низ изделия', min: 0, max: 6},
];

export function ConstructionEditor({project, onSave}: {project: ProjectDocument; onSave: SaveProject}) {
  const [fit, setFit] = useState<FitSettings>(() => structuredClone(project.fit_settings));
  const [fabric, setFabric] = useState<FabricProperties>(() => structuredClone(project.fabric_properties));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  function setEase(key: keyof FitSettings['wearing_ease_mm'], valueCm: number) {
    setFit({...fit, status: 'draft', confirmed_at: null, wearing_ease_mm: {
      ...fit.wearing_ease_mm, [key]: valueCm * 10,
    }});
  }

  function setAllowance(key: keyof FitSettings['seam_allowances_mm'], valueCm: number) {
    setFit({...fit, status: 'draft', confirmed_at: null, seam_allowance_mode: 'by_edge', seam_allowances_mm: {
      ...fit.seam_allowances_mm, [key]: valueCm * 10,
    }});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const invalidEase = EASE_FIELDS.some(({key, min, max}) => !bounded(fit.wearing_ease_mm[key] / 10, min, max));
    const invalidAllowance = ALLOWANCE_FIELDS.some(({key, min, max}) => !bounded(fit.seam_allowances_mm[key] / 10, min, max));
    if (invalidEase || invalidAllowance || !fabric.name.trim() || fabric.stretch_percent.weft > 5) {
      setError('Проверьте диапазоны, название ткани и растяжимость не выше 5%.');
      return;
    }
    const now = new Date().toISOString();
    setBusy(true);
    setError('');
    try {
      await onSave({
        ...project,
        status: 'inputs_confirmed',
        fit_settings: {...fit, status: 'confirmed', confirmed_at: now},
        fabric_properties: {
          ...fabric,
          name: fabric.name.trim(),
          status: 'confirmed',
          structure: 'woven',
          stability: 'stable',
          confirmed_at: now,
        },
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Не удалось сохранить настройки.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="workflow-card" onSubmit={(event) => void submit(event)}>
      <header className="workflow-card__header">
        <span className="action-card__icon" aria-hidden="true">05</span>
        <div>
          <p className="eyebrow">Ткань и посадка</p>
          <h2>Подтвердите прибавки и припуски</h2>
          <p>Прибавка даёт свободу телу, припуск остаётся за линией шва для стачивания. Эти величины не смешиваются.</p>
        </div>
      </header>

      <section className="editor-section" aria-labelledby="fabric-title">
        <h3 id="fabric-title">1. Пробная ткань</h3>
        <div className="form-grid">
          <label><span>Название ткани</span><input value={fabric.name} maxLength={120} onChange={(event) => setFabric({...fabric, name: event.target.value, status: 'draft', confirmed_at: null})} /></label>
          <label><span>Плотность</span><select value={fabric.weight} onChange={(event) => setFabric({...fabric, weight: event.target.value as FabricProperties['weight']})}><option value="light">Лёгкая</option><option value="medium">Средняя</option><option value="heavy">Плотная</option></select></label>
          <label><span>Драпируемость</span><select value={fabric.drape} onChange={(event) => setFabric({...fabric, drape: event.target.value as FabricProperties['drape']})}><option value="crisp">Держит форму</option><option value="medium">Средняя</option><option value="fluid">Струящаяся</option></select></label>
          <NumberField id="fabric-stretch" label="Растяжимость по утку" value={fabric.stretch_percent.weft} min={0} max={5} unit="%" onChange={(value) => setFabric({...fabric, stretch_percent: {...fabric.stretch_percent, weft: value}})} />
        </div>
        <label className="consent-row"><input type="checkbox" checked={fabric.prewashed} onChange={(event) => setFabric({...fabric, prewashed: event.target.checked})} /><span>Ткань декатирована или предварительно постирана.</span></label>
        <p className="scope-note">Для проверенной основы сейчас нужна стабильная тканая ткань с растяжимостью до 5%. Трикотаж будет отдельным модулем.</p>
      </section>

      <section className="editor-section" aria-labelledby="ease-title">
        <h3 id="ease-title">2. Прибавка на свободу облегания</h3>
        <div className="number-grid">
          {EASE_FIELDS.map(({key, label, min, max}) => <NumberField key={key} id={`ease-${key}`} label={label} value={fit.wearing_ease_mm[key] / 10} min={min} max={max} onChange={(value) => setEase(key, value)} />)}
        </div>
        <p className="scope-note">Прибавка распределяется поровну между передом и спинкой. Конструктивная прибавка модели сейчас равна 0.</p>
      </section>

      <section className="editor-section" aria-labelledby="allowance-title">
        <h3 id="allowance-title">3. Припуски на швы</h3>
        <div className="number-grid">
          {ALLOWANCE_FIELDS.map(({key, label, min, max}) => <NumberField key={key} id={`allowance-${key}`} label={label} value={fit.seam_allowances_mm[key] / 10} min={min} max={max} onChange={(value) => setAllowance(key, value)} />)}
        </div>
      </section>

      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="primary-button" disabled={busy}>
        {busy ? 'Сохраняем…' : 'Подтвердить ткань и настройки'} <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}

export function ProjectHistory({
  project,
  onRestored,
}: {
  project: ProjectDocument;
  onRestored: (project: ProjectDocument) => void;
}) {
  const [items, setItems] = useState<ProjectHistoryEntry[]>([]);
  const [confirmRevision, setConfirmRevision] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.projectHistory(project.project_id).then((result) => {
      if (active) setItems(result.items);
    }).catch(() => {
      if (active) setError('История временно недоступна. Сам проект сохранён.');
    });
    return () => { active = false; };
  }, [project.project_id, project.revision]);

  async function restore(revision: number) {
    setBusy(true);
    setError('');
    try {
      onRestored(await api.restoreProjectRevision(project, revision));
      setConfirmRevision(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Не удалось восстановить версию.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="history-panel">
      <summary>История проекта <span>{items.length} версий</span></summary>
      <p>Ничего не перезаписывается: восстановленная версия станет новым черновиком.</p>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <ol>
        {items.map((item) => (
          <li key={item.revision}>
            <span><strong>Версия {item.revision}{item.is_current ? ' · текущая' : ''}</strong><small>{item.change_summary} · {new Date(item.updated_at).toLocaleString('ru-RU')}</small></span>
            {!item.is_current && (confirmRevision === item.revision ? (
              <span className="restore-confirm">
                <button type="button" onClick={() => void restore(item.revision)} disabled={busy}>Да, восстановить</button>
                <button type="button" onClick={() => setConfirmRevision(null)} disabled={busy}>Отмена</button>
              </span>
            ) : <button type="button" onClick={() => setConfirmRevision(item.revision)} disabled={busy}>Восстановить</button>)}
          </li>
        ))}
      </ol>
    </details>
  );
}

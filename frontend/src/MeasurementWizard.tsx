import {useEffect, useMemo, useState} from 'react';
import {api, ApiError} from './api';
import {GARMENT_NAMES} from './garments';
import {MeasurementGuide} from './MeasurementGuide';
import type {
  BodyMeasurements,
  MeasurementCatalog,
  MeasurementDefinition,
  MeasurementIssue,
  MeasurementProfileSummary,
  ProjectDocument,
} from './types';

type DisplayUnit = 'cm' | 'mm';

interface Props {
  project: ProjectDocument;
  onSaveProject: (profile: BodyMeasurements) => Promise<ProjectDocument>;
}

function copyProfile(profile: BodyMeasurements): BodyMeasurements {
  return JSON.parse(JSON.stringify(profile)) as BodyMeasurements;
}

function blankProfile(): BodyMeasurements {
  return {
    schema_version: '1.0.0',
    profile_id: crypto.randomUUID(),
    name: 'Новые мерки',
    status: 'draft',
    normalized_unit: 'mm',
    values: {},
    angles_deg: {},
    angle_provenance: {},
  };
}

function sourceLabel(source?: string): string {
  if (source === 'preset') return 'Загружено из профиля';
  if (source === 'derived') return 'Рассчитано по формуле';
  if (source === 'user') return 'Введено вручную';
  return 'Значение не введено';
}

function getNormalized(profile: BodyMeasurements, definition: MeasurementDefinition): number | undefined {
  return definition.kind === 'angle'
    ? profile.angles_deg?.[definition.id]
    : profile.values[definition.id]?.value;
}

function displayValue(
  profile: BodyMeasurements, definition: MeasurementDefinition, displayUnit: DisplayUnit,
): string {
  const normalized = getNormalized(profile, definition);
  if (normalized === undefined) return '';
  if (definition.kind === 'angle' || displayUnit === 'mm') return String(normalized);
  return String(Math.round(normalized * 100) / 1000);
}

function localIssue(
  profile: BodyMeasurements, definition: MeasurementDefinition, displayUnit: DisplayUnit,
): string | null {
  const normalized = getNormalized(profile, definition);
  if (normalized === undefined) return definition.required ? 'Эта мерка обязательна для выбранного изделия.' : null;
  if (normalized < definition.minimum || normalized > definition.maximum) {
    const divisor = definition.kind === 'linear' && displayUnit === 'cm' ? 10 : 1;
    const suffix = definition.kind === 'angle' ? '°' : displayUnit === 'cm' ? 'см' : 'мм';
    return `Рабочий диапазон: ${definition.minimum / divisor}–${definition.maximum / divisor} ${suffix}.`;
  }
  return null;
}

export function MeasurementWizard({project, onSaveProject}: Props) {
  const garmentType = project.garment_spec.garment_type;
  const sleeveType = project.garment_spec.parameters.sleeve.type;
  const [catalog, setCatalog] = useState<MeasurementCatalog | null>(null);
  const [profile, setProfile] = useState(() => copyProfile(project.body_measurements));
  const [savedProfiles, setSavedProfiles] = useState<MeasurementProfileSummary[]>([]);
  const [profileRevision, setProfileRevision] = useState<number | null>(null);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [displayUnit, setDisplayUnit] = useState<DisplayUnit>('cm');
  const [index, setIndex] = useState(0);
  const [saveReusable, setSaveReusable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [serverIssues, setServerIssues] = useState<MeasurementIssue[]>([]);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([
      api.measurementCatalog(garmentType, sleeveType),
      api.listMeasurementProfiles(),
    ]).then(([loadedCatalog, profiles]) => {
      if (!active) return;
      setCatalog(loadedCatalog);
      setSavedProfiles(profiles.items);
      const matching = profiles.items.find(
        (item) => item.profile_id === project.body_measurements.profile_id,
      );
      if (matching) {
        setSelectedProfile(matching.profile_id);
        setProfileRevision(matching.revision);
      }
    }).catch((caught) => {
      if (active) setError(caught instanceof ApiError
        ? caught : new ApiError('Не удалось загрузить справочник мерок.', 0, 'UNKNOWN_ERROR'));
    });
    return () => { active = false; };
  }, [garmentType, sleeveType]);

  const definitions = useMemo(() => {
    if (!catalog) return [];
    return [...catalog.measurements].sort((left, right) => Number(right.required) - Number(left.required));
  }, [catalog]);
  const required = definitions.filter((item) => item.required);
  const completed = required.filter((item) => getNormalized(profile, item) !== undefined).length;
  const current = definitions[Math.min(index, Math.max(0, definitions.length - 1))];
  const currentError = current ? localIssue(profile, current, displayUnit) : null;
  const progress = required.length ? Math.round(completed / required.length * 100) : 0;

  function setMeasurement(definition: MeasurementDefinition, raw: string) {
    const next = copyProfile(profile);
    next.status = 'draft';
    setNotice('');
    setServerIssues([]);
    if (raw === '') {
      if (definition.kind === 'angle') {
        delete next.angles_deg?.[definition.id];
        delete next.angle_provenance?.[definition.id];
      } else {
        delete next.values[definition.id];
      }
      setProfile(next);
      return;
    }
    const parsed = Number(raw.replace(',', '.'));
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    if (definition.kind === 'angle') {
      next.angles_deg = {...next.angles_deg, [definition.id]: parsed};
      next.angle_provenance = {
        ...next.angle_provenance,
        [definition.id]: {source: 'user'},
      };
    } else {
      const normalized = displayUnit === 'cm'
        ? Math.round(parsed * 10 * 1_000_000) / 1_000_000
        : parsed;
      next.values[definition.id] = {
        value: normalized,
        unit: 'mm',
        source: 'user',
        original_input: {value: parsed, unit: displayUnit},
      };
    }
    setProfile(next);
  }

  async function loadProfile(profileId: string) {
    setSelectedProfile(profileId);
    setError(null);
    setNotice('');
    if (!profileId) return;
    setBusy(true);
    try {
      const record = await api.getMeasurementProfile(profileId);
      setProfile(copyProfile(record.profile));
      setProfileRevision(record.revision);
      setIndex(0);
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught : new ApiError('Не удалось открыть профиль.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  function startBlank() {
    setProfile(blankProfile());
    setProfileRevision(null);
    setSelectedProfile('');
    setIndex(0);
    setServerIssues([]);
    setNotice('Создан пустой профиль — значения не подставлены.');
  }

  async function persist(candidate: BodyMeasurements, complete: boolean) {
    let projectSaved = false;
    setBusy(true);
    setError(null);
    setServerIssues([]);
    setNotice('');
    try {
      if (complete) {
        const report = await api.validateMeasurements(candidate, garmentType, sleeveType);
        if (report.status !== 'ready') {
          setServerIssues(report.issues);
          setNotice('Заполните обязательные мерки и исправьте отмеченные значения.');
          return;
        }
      }
      await onSaveProject(candidate);
      projectSaved = true;
      if (saveReusable) {
        const record = profileRevision === null
          ? await api.createMeasurementProfile(candidate)
          : await api.replaceMeasurementProfile(candidate, profileRevision);
        setProfileRevision(record.revision);
        setSelectedProfile(record.profile.profile_id);
        setSavedProfiles((items) => [
          {
            profile_id: record.profile.profile_id,
            name: record.profile.name,
            status: record.profile.status,
            revision: record.revision,
            updated_at: record.updated_at,
          },
          ...items.filter((item) => item.profile_id !== record.profile.profile_id),
        ]);
      }
      setProfile(copyProfile(candidate));
      setNotice(complete
        ? 'Все обязательные мерки проверены и сохранены.'
        : 'Черновик сохранён. Можно продолжить позже.');
    } catch (caught) {
      const original = caught instanceof ApiError
        ? caught : new ApiError('Не удалось сохранить мерки.', 0, 'UNKNOWN_ERROR');
      const apiError = projectSaved
        ? new ApiError(
            'Мерки сохранены в проекте, но отдельный профиль создать не удалось. Повторите позже.',
            original.status, original.code, original.requestId, original.issues,
          )
        : original;
      if (projectSaved) setProfile(copyProfile(candidate));
      setError(apiError);
      setServerIssues(apiError.issues ?? []);
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    const candidate = copyProfile(profile);
    candidate.name = candidate.name.trim() || 'Новые мерки';
    candidate.status = 'draft';
    await persist(candidate, false);
  }

  async function finish() {
    const candidate = copyProfile(profile);
    candidate.name = candidate.name.trim() || 'Новые мерки';
    candidate.status = 'ready';
    await persist(candidate, true);
  }

  if (!catalog || !current) {
    return (
      <div className="measurement-loading" aria-live="polite">
        {error ? <span role="alert">{error.message}</span> : 'Готовим справочник мерок…'}
      </div>
    );
  }

  const source = current.kind === 'angle'
    ? profile.angle_provenance?.[current.id]?.source
    : profile.values[current.id]?.source;
  const formula = current.kind === 'angle'
    ? profile.angle_provenance?.[current.id]?.formula_id
    : profile.values[current.id]?.formula_id;
  const rangeDivisor = current.kind === 'linear' && displayUnit === 'cm' ? 10 : 1;
  const shownUnit = current.kind === 'angle' ? '°' : displayUnit === 'cm' ? 'см' : 'мм';

  return (
    <section className="measurement-wizard" aria-labelledby="measurements-title">
      <header className="measurement-wizard__header">
        <div>
          <p className="eyebrow">Шаг 4 · мерки · {GARMENT_NAMES[garmentType]}</p>
          <h2 id="measurements-title">Снимаем мерки спокойно, по одной</h2>
          <p>Вводите размер тела без прибавок. Приложение ничего не угадывает и хранит расчёты в миллиметрах.</p>
        </div>
        <div className="measurement-progress" aria-label={`Заполнено ${completed} из ${required.length}`}>
          <strong>{completed}/{required.length}</strong>
          <span>обязательных</span>
        </div>
      </header>
      <div className="progress-track" aria-hidden="true"><span style={{width: `${progress}%`}} /></div>

      <div className="profile-tools">
        <label>
          <span>Название профиля</span>
          <input value={profile.name} maxLength={120} onChange={(event) => {
            setProfile({...profile, name: event.target.value, status: 'draft'});
          }} onBlur={() => {
            if (!profile.name.trim()) setProfile({...profile, name: 'Новые мерки'});
          }} />
        </label>
        <label>
          <span>Открыть сохранённый профиль</span>
          <select value={selectedProfile} onChange={(event) => void loadProfile(event.target.value)} disabled={busy}>
            <option value="" disabled>Выберите профиль</option>
            {savedProfiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.name}</option>)}
          </select>
        </label>
        <button type="button" className="secondary-button" onClick={startBlank} disabled={busy}>Новый пустой профиль</button>
      </div>

      <div className="measurement-card">
        <MeasurementGuide variant={current.illustration} label={current.label_ru} />
        <div className="measurement-entry">
          <div className="measurement-meta">
            <span>{current.group}</span>
            <span className={current.required ? 'required-label' : 'optional-label'}>
              {current.required ? 'Обязательно' : 'Дополнительно'}
            </span>
          </div>
          <h3>{current.label_ru}</h3>
          <p className="measurement-instruction">{current.instruction_ru}</p>

          {current.kind === 'linear' && (
            <fieldset className="unit-switch">
              <legend>Единицы ввода</legend>
              <button type="button" aria-pressed={displayUnit === 'cm'} onClick={() => setDisplayUnit('cm')}>см</button>
              <button type="button" aria-pressed={displayUnit === 'mm'} onClick={() => setDisplayUnit('mm')}>мм</button>
            </fieldset>
          )}
          <label className="value-field" htmlFor={`measurement-${current.id}`}>
            <span>Значение, {shownUnit}</span>
            <div>
              <input
                id={`measurement-${current.id}`}
                type="number"
                inputMode="decimal"
                min={current.minimum / rangeDivisor}
                max={current.maximum / rangeDivisor}
                step={current.kind === 'angle' || displayUnit === 'cm' ? 0.1 : 1}
                value={displayValue(profile, current, displayUnit)}
                onChange={(event) => setMeasurement(current, event.target.value)}
                aria-invalid={Boolean(currentError)}
                aria-describedby={`hint-${current.id}${currentError ? ` error-${current.id}` : ''}`}
              />
              <span>{shownUnit}</span>
            </div>
          </label>
          <p id={`hint-${current.id}`} className="range-hint">
            Допустимый рабочий диапазон: {current.minimum / rangeDivisor}–{current.maximum / rangeDivisor} {shownUnit}
          </p>
          {currentError && <p id={`error-${current.id}`} className="field-error" role="alert">{currentError}</p>}
          <p className="source-note"><strong>{sourceLabel(source)}</strong>{formula && ` · формула ${formula}`}</p>
          {!source && <p className="no-guess-note">Если оставить поле пустым, оно так и останется пустым — среднее значение не подставится.</p>}
        </div>
      </div>

      <nav className="measurement-navigation" aria-label="Переход между мерками">
        <button type="button" className="secondary-button" disabled={index === 0} onClick={() => setIndex(index - 1)}>← Назад</button>
        <span>{index + 1} из {definitions.length}</span>
        <button type="button" className="secondary-button" disabled={index >= definitions.length - 1 || Boolean(currentError && getNormalized(profile, current) !== undefined)} onClick={() => setIndex(index + 1)}>Дальше →</button>
      </nav>

      {serverIssues.length > 0 && (
        <div className="notice notice--error" role="alert">
          <strong>Нужно перепроверить мерки</strong>
          <ul>{serverIssues.map((item) => <li key={`${item.code}-${item.json_pointer}`}>{item.message_ru}</li>)}</ul>
        </div>
      )}
      {error && <div className="notice notice--error" role="alert"><strong>Не удалось сохранить</strong><span>{error.message}</span></div>}
      {notice && <div className="notice notice--success" role="status">{notice}</div>}

      <div className="measurement-save">
        <label className="save-profile-choice">
          <input type="checkbox" checked={saveReusable} onChange={(event) => setSaveReusable(event.target.checked)} />
          <span><strong>Сохранить отдельный профиль на этом компьютере</strong>Чтобы использовать эти мерки в другом проекте. По умолчанию они остаются только в текущем проекте.</span>
        </label>
        <div>
          <button type="button" className="secondary-button" onClick={() => void saveDraft()} disabled={busy}>Сохранить черновик</button>
          <button type="button" className="primary-button" onClick={() => void finish()} disabled={busy || completed !== required.length}>
            {busy ? 'Сохраняем…' : 'Проверить и завершить'} <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </section>
  );
}

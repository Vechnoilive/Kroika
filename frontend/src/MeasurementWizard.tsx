import {useEffect, useMemo, useRef, useState} from 'react';
import {api, ApiError} from './api';
import {AutosaveIndicator} from './AutosaveIndicator';
import {loadLocalDraft, useDraftAutosave} from './autosave';
import {GARMENT_NAMES} from './garments';
import {MeasurementAtlas} from './MeasurementAtlas';
import {ATLAS_BY_ID} from './measurementAtlas';
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
  onDirtyChange?: (dirty: boolean) => void;
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

export function MeasurementWizard({project, onSaveProject, onDirtyChange}: Props) {
  const garmentType = project.garment_spec.garment_type;
  const sleeveType = project.garment_spec.parameters.sleeve.type;
  const draftKey = `kroika:draft:${project.project_id}:measurements`;
  const loadedDraft = useRef<ReturnType<typeof loadLocalDraft<BodyMeasurements>> | null>(null);
  if (loadedDraft.current === null) {
    loadedDraft.current = loadLocalDraft(
      draftKey,
      copyProfile(project.body_measurements),
      project.updated_at,
    );
  }
  const [catalog, setCatalog] = useState<MeasurementCatalog | null>(null);
  const [profile, setProfile] = useState(() => copyProfile(loadedDraft.current!.value));
  const [savedProfiles, setSavedProfiles] = useState<MeasurementProfileSummary[]>([]);
  const [profileRevision, setProfileRevision] = useState<number | null>(null);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [displayUnit, setDisplayUnit] = useState<DisplayUnit>('cm');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rawValues, setRawValues] = useState<Record<string, string>>({});
  const [saveReusable, setSaveReusable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [serverIssues, setServerIssues] = useState<MeasurementIssue[]>([]);
  const [notice, setNotice] = useState('');
  const autosave = useDraftAutosave({
    storageKey: draftKey,
    initialValue: profile,
    initiallyDirty: loadedDraft.current.restored,
    save: async (candidate) => {
      await onSaveProject({
        ...candidate,
        name: candidate.name.trim() || 'Новые мерки',
        status: 'draft',
      });
    },
    onDirtyChange,
  });

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
  const invalid = definitions.some((item) => getNormalized(profile, item) !== undefined && Boolean(localIssue(profile, item, displayUnit)))
    || definitions.some((item) => Boolean(rawValues[item.id]?.trim()) && getNormalized(profile, item) === undefined);
  const groups = [...new Set(definitions.map((item) => item.group))];
  const progress = required.length ? Math.round(completed / required.length * 100) : 0;
  const saving = busy || autosave.state === 'saving';

  function updateProfile(next: BodyMeasurements) {
    setProfile(next);
    autosave.markDirty(next);
  }

  function setMeasurement(definition: MeasurementDefinition, raw: string) {
    setRawValues((previous) => ({...previous, [definition.id]: raw}));
    const next = copyProfile(profile);
    next.status = 'draft';
    setNotice('');
    setServerIssues([]);
    const parsed = Number(raw.trim().replace(',', '.'));
    if (raw.trim() === '' || !Number.isFinite(parsed) || parsed < 0 || (definition.kind === 'linear' && parsed === 0)) {
      if (definition.kind === 'angle') {
        delete next.angles_deg?.[definition.id];
        delete next.angle_provenance?.[definition.id];
      } else {
        delete next.values[definition.id];
      }
      updateProfile(next);
      return;
    }
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
    updateProfile(next);
  }

  async function loadProfile(profileId: string) {
    setSelectedProfile(profileId);
    setError(null);
    setNotice('');
    if (!profileId) return;
    setBusy(true);
    try {
      const record = await api.getMeasurementProfile(profileId);
      const loaded = copyProfile(record.profile);
      setProfile(loaded);
      autosave.markDirty(loaded);
      setProfileRevision(record.revision);
      setRawValues({});
      setActiveId(null);
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught : new ApiError('Не удалось открыть профиль.', 0, 'UNKNOWN_ERROR'));
    } finally {
      setBusy(false);
    }
  }

  function startBlank() {
    const blank = blankProfile();
    setProfile(blank);
    autosave.markDirty(blank);
    setProfileRevision(null);
    setSelectedProfile('');
    setRawValues({});
    setActiveId(null);
    setServerIssues([]);
    setNotice('Создан пустой профиль — значения не подставлены.');
  }

  async function persist(candidate: BodyMeasurements, complete: boolean) {
    let projectSaved = false;
    autosave.cancelPending();
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
          autosave.retry();
          return;
        }
      }
      await onSaveProject(candidate);
      projectSaved = true;
      autosave.markSaved(candidate);
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
      else autosave.markDirty(candidate);
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

  if (!catalog || definitions.length === 0) {
    return (
      <div className="measurement-loading" aria-live="polite">
        {error ? <span role="alert">{error.message}</span> : 'Готовим справочник мерок…'}
      </div>
    );
  }

  return (
    <section className="measurement-wizard" aria-labelledby="measurements-title">
      <header className="measurement-wizard__header">
        <div>
          <p className="eyebrow">Шаг 4 · мерки · {GARMENT_NAMES[garmentType]}</p>
          <h2 id="measurements-title">Все мерки на одном экране</h2>
          <p>Заполняйте в удобном порядке. Номер и цвет поля совпадают с линией на рисунке. Вводите размеры тела без прибавок; пустые поля не заполняются автоматически.</p>
        </div>
        <div className="measurement-progress" aria-label={`Заполнено ${completed} из ${required.length}`}>
          <strong>{completed}/{required.length}</strong>
          <span>обязательных</span>
        </div>
      </header>
      <div className="progress-track" aria-hidden="true"><span style={{width: `${progress}%`}} /></div>
      <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} error={autosave.error} onRetry={autosave.retry} />

      <div className="profile-tools">
        <label>
          <span>Название профиля</span>
          <input value={profile.name} disabled={busy} maxLength={120} onChange={(event) => {
            updateProfile({...profile, name: event.target.value, status: 'draft'});
          }} onBlur={() => {
            if (!profile.name.trim()) updateProfile({...profile, name: 'Новые мерки'});
          }} />
        </label>
        <label>
          <span>Открыть сохранённый профиль</span>
          <select value={selectedProfile} onChange={(event) => void loadProfile(event.target.value)} disabled={saving}>
            <option value="" disabled>Выберите профиль</option>
            {savedProfiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.name}</option>)}
          </select>
        </label>
        <button type="button" className="secondary-button" onClick={startBlank} disabled={saving}>Новый пустой профиль</button>
      </div>

      <fieldset className="unit-switch measurement-unit-switch">
        <legend>Единицы ввода всех размеров</legend>
        {(['cm', 'mm'] as const).map((unit) => <button key={unit} type="button" aria-pressed={displayUnit === unit}
          onClick={() => {setDisplayUnit(unit); setRawValues({});}}>{unit === 'cm' ? 'см' : 'мм'}</button>)}
        <span>Углы всегда в градусах</span>
      </fieldset>
      <div className="measurements-workspace">
        <div className="measurements-fields">
          {groups.map((group) => <fieldset key={group} className="measurement-group">
            <legend>{group}</legend>
            <div className="measurement-fields-grid">{definitions.filter((item) => item.group === group).map((item) => {
              const normalized = getNormalized(profile, item);
              const raw = rawValues[item.id];
              const errorText = normalized !== undefined ? localIssue(profile, item, displayUnit)
                : raw?.trim() ? 'Введите допустимое число.' : null;
              const source = item.kind === 'angle' ? profile.angle_provenance?.[item.id]?.source : profile.values[item.id]?.source;
              const formula = item.kind === 'angle' ? profile.angle_provenance?.[item.id]?.formula_id : profile.values[item.id]?.formula_id;
              const divisor = item.kind === 'linear' && displayUnit === 'cm' ? 10 : 1;
              const unit = item.kind === 'angle' ? '°' : displayUnit === 'cm' ? 'см' : 'мм';
              const line = ATLAS_BY_ID.get(item.id);
              return <div key={item.id} className={`measurement-field${activeId === item.id ? ' measurement-field--active' : ''}`}>
                <label htmlFor={`measurement-${item.id}`} className="measurement-field-label">
                  <span className="measurement-number" style={{background: line?.color}}>{line?.number}</span>
                  <span>{item.label_ru}<small>{item.required ? 'Обязательно' : 'Дополнительно'}</small></span>
                </label>
                <div className="measurement-input-row"><input id={`measurement-${item.id}`} disabled={busy} type="text" inputMode="decimal"
                  value={raw ?? displayValue(profile, item, displayUnit)}
                  aria-label={`${item.label_ru}, ${unit}`} aria-required={item.required}
                  onFocus={() => setActiveId(item.id)} onChange={(event) => setMeasurement(item, event.target.value)}
                  aria-invalid={Boolean(errorText)} aria-describedby={`hint-${item.id}${errorText ? ` error-${item.id}` : ''}`}/><span>{unit}</span></div>
                <p id={`hint-${item.id}`} className="range-hint">{item.minimum / divisor}–{item.maximum / divisor} {unit}</p>
                {errorText && <p id={`error-${item.id}`} className="field-error" role="alert">{errorText}</p>}
                {source && <p className="source-note">{sourceLabel(source)}{formula && ` · ${formula}`}</p>}
                <details className="measurement-help"><summary>Как снять мерку</summary><p>{item.instruction_ru}</p></details>
              </div>;
            })}</div>
          </fieldset>)}
        </div>
        <MeasurementAtlas definitions={definitions} activeId={activeId} onSelect={(id) => {
          setActiveId(id);
          const field = document.getElementById(`measurement-${id}`);
          field?.focus({preventScroll: true});
          field?.scrollIntoView?.({behavior: 'smooth', block: 'center'});
        }} />
      </div>

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
          <button type="button" className="secondary-button" onClick={() => void saveDraft()} disabled={saving}>Сохранить сейчас</button>
          <button type="button" className="primary-button" onClick={() => void finish()} disabled={saving || completed !== required.length || invalid}>
            {saving ? 'Сохраняем…' : 'Проверить и завершить'} <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </section>
  );
}

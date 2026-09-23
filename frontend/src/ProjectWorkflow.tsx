import {FormEvent, useEffect, useRef, useState} from 'react';
import {api, ApiError} from './api';
import {AutosaveIndicator} from './AutosaveIndicator';
import {loadLocalDraft, useDraftAutosave} from './autosave';
import {configureGarment, easeForGarment, GARMENT_OPTIONS, methodForGarment, presetForGarment} from './garments';
import {DesignIntentEditor} from './DesignIntentEditor';
import {buildDesignIntent, prepareDesignIntentForReview, reevaluateDesignIntent} from './designIntent';
import type {
  FabricProperties,
  FitSettings,
  GarmentAcceptanceStatus,
  GarmentSpec,
  GarmentType,
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
  acceptance,
  onSave,
  onDirtyChange,
}: {
  project: ProjectDocument;
  analysis: StyleAnalysis;
  providerName: string;
  acceptance?: GarmentAcceptanceStatus;
  onSave: SaveProject;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const draftKey = `kroika:draft:${project.project_id}:style`;
  const loadedDraft = useRef<ReturnType<typeof loadLocalDraft<GarmentSpec>> | null>(null);
  if (loadedDraft.current === null) {
    const initial = structuredClone(project.garment_spec);
    const prepared = initial.design_intent
      ? {...initial, design_intent: prepareDesignIntentForReview(initial.design_intent)}
      : initial;
    loadedDraft.current = loadLocalDraft(draftKey, prepared, project.updated_at);
  }
  const [spec, setSpec] = useState<GarmentSpec>(() => structuredClone(loadedDraft.current!.value));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const autosave = useDraftAutosave({
    storageKey: draftKey,
    initialValue: spec,
    initiallyDirty: loadedDraft.current.restored,
    save: async (candidate) => {
      await onSave({
        ...project,
        status: 'draft',
        garment_spec: {...candidate, selection_status: 'proposed', confirmed_at: null},
        fit_settings: {...project.fit_settings, status: 'draft', confirmed_at: null},
        fabric_properties: {...project.fabric_properties, status: 'draft', confirmed_at: null},
        latest_generation: null,
      });
    },
    onDirtyChange,
  });

  const suggestedUnsupported = [
    analysis.neckline.front !== 'round' ? `горловина «${analysis.neckline.front}»` : '',
    analysis.sleeves.length !== 'sleeveless' ? `рукав «${analysis.sleeves.length}»` : '',
    analysis.lower_part.type !== 'a_line' ? `юбка «${analysis.lower_part.type}»` : '',
  ].filter(Boolean);

  function updateSpec(next: GarmentSpec) {
    setSpec(next);
    autosave.markDirty(next);
  }

  function updateParameters(next: Partial<GarmentSpec['parameters']>) {
    const updated: GarmentSpec = {...spec, selection_status: 'proposed', confirmed_at: null, parameters: {
      ...spec.parameters,
      ...next,
    }};
    updateSpec(updated.design_intent
      ? {...updated, design_intent: reevaluateDesignIntent(updated.design_intent, updated, analysis)}
      : updated);
  }

  function selectGarment(garmentType: GarmentType) {
    const configured = configureGarment(spec, garmentType);
    updateSpec({...configured, design_intent: buildDesignIntent(analysis, configured)});
  }

  async function saveDesignReview(designIntent: NonNullable<GarmentSpec['design_intent']>) {
    autosave.cancelPending();
    setBusy(true);
    setError('');
    try {
      const saved = await onSave({
        ...project,
        status: 'draft',
        garment_spec: {
          ...spec,
          selection_status: 'proposed',
          confirmed_at: null,
          design_intent: designIntent,
        },
        fit_settings: {...project.fit_settings, status: 'draft', confirmed_at: null},
        fabric_properties: {...project.fabric_properties, status: 'draft', confirmed_at: null},
        latest_generation: null,
      });
      setSpec(structuredClone(saved.garment_spec));
      autosave.markSaved(saved.garment_spec);
    } catch (caught) {
      autosave.markDirty({...spec, design_intent: designIntent});
      throw new Error(caught instanceof ApiError ? caught.message : 'Не удалось сохранить проверку деталей.');
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (spec.design_intent?.review_status !== undefined
        && spec.design_intent.review_status !== 'confirmed') {
      setError('Сначала проверьте детали, слои и пропорции, затем нажмите «Сохранить проверку деталей».');
      return;
    }
    if (spec.design_intent && spec.design_intent.status !== 'ready') {
      const unresolved = [
        ...spec.design_intent.elements.filter((item) => item.included !== false),
        ...spec.design_intent.layers.filter((item) => item.included !== false),
        spec.design_intent.proportions,
      ].filter((item) => item.support_status !== 'supported');
      setError(
        `Нельзя подтвердить точный фасон: ${unresolved.length} ${unresolved.length === 1 ? 'деталь ещё не перенесена' : 'детали ещё не перенесены'} в математический движок. Проверьте список выше.`,
      );
      return;
    }
    const {neckline, skirt, upper, sleeve, closure, trousers} = spec.parameters;
    const skirtBased = ['dress', 'sundress', 'skirt'].includes(spec.garment_type);
    const upperOnly = ['top', 'blouse', 'shirt', 'vest', 'jacket'].includes(spec.garment_type);
    const lowerOnly = ['trousers', 'shorts'].includes(spec.garment_type);
    const sleeved = ['blouse', 'shirt', 'jacket'].includes(spec.garment_type);
    const invalid = (!['skirt', 'trousers', 'shorts'].includes(spec.garment_type)
        && (!bounded(neckline.front_depth_mm, 50, 250) || !bounded(neckline.back_depth_mm, 10, 120)))
      || (skirtBased
        && (!bounded(skirt.length_from_waist_mm, 350, 1200)
          || !bounded(skirt.hem_expansion_each_side_mm, -100, 250)))
      || (upperOnly && !bounded(upper?.length_below_waist_mm ?? NaN, 40, 300))
      || (lowerOnly && (
        !bounded(trousers?.length_mm ?? NaN, spec.garment_type === 'trousers' ? 700 : 380, spec.garment_type === 'trousers' ? 1250 : 700)
        || !bounded(trousers?.waistband_width_mm ?? NaN, 30, 55)
        || !bounded(trousers?.fly_length_mm ?? NaN, 120, 240)
        || !bounded(trousers?.pocket_opening_mm ?? NaN, 120, 220)
      ))
      || (sleeved && !bounded(sleeve.length_mm ?? NaN, 250, 900))
      || (closure.type !== 'none' && !bounded(
        closure.length_mm ?? NaN,
        lowerOnly ? 120 : 300,
        lowerOnly ? 240 : 900,
      ));
    if (invalid) {
      setError('Проверьте числовые значения: одно из них вне указанного диапазона.');
      return;
    }
    setBusy(true);
    setError('');
    autosave.cancelPending();
    const now = new Date().toISOString();
    const confirmed: GarmentSpec = {
      ...spec,
      selection_status: 'confirmed',
      unsupported_features: [],
      confirmed_at: now,
    };
    const presetId = presetForGarment(confirmed.garment_type, confirmed.parameters.bodice_fit);
    try {
      await onSave({
        ...project,
        status: 'draft',
        garment_spec: confirmed,
        pattern_method: {
          id: methodForGarment(confirmed.garment_type),
          version: '0.1.0',
          validation_status: 'experimental',
        },
        fit_settings: {
          ...project.fit_settings,
          status: 'draft',
          preset: {id: presetId, version: '0.1.0'},
          wearing_ease_mm: easeForGarment(
            confirmed.garment_type,
            confirmed.parameters.jacket?.underlayer_allowance_mm,
          ),
          design_ease_mm: {bust: 0, waist: 0, hips: 0, upper_arm: 0},
          confirmed_at: null,
        },
      });
      autosave.markSaved(confirmed);
    } catch (caught) {
      autosave.markDirty(spec);
      setError(caught instanceof ApiError ? caught.message : 'Не удалось сохранить фасон.');
    } finally {
      setBusy(false);
    }
  }

  const {parameters} = spec;
  const features: Record<GarmentType, Array<[string, string]>> = {
    dress: [['Круглая горловина', 'обтачка'], ['Без рукавов', 'обтачка проймы'], ['А-юбка', 'отрезная по талии'], ['Молния сзади', 'центр спинки']],
    sundress: [['Круглая горловина', 'обтачка'], ['Без рукавов', 'обтачка проймы'], ['А-юбка', 'отрезная по талии'], ['Молния сзади', 'центр спинки']],
    skirt: [['А-силуэт', 'две основные детали'], ['Прямой пояс', 'перед и спинка'], ['Молния сзади', 'центр спинки'], ['Без лифа', 'только нижние мерки']],
    top: [['Круглая горловина', 'обтачка'], ['Без рукавов', 'обтачка проймы'], ['Ниже талии', 'длина регулируется'], ['Молния сзади', 'центр спинки']],
    blouse: [['Круглая горловина', 'без воротника'], ['Длинный рукав', 'одношовный'], ['Полуприлегающая', 'вытачки основы'], ['Молния сзади', 'центр спинки']],
    shirt: [['Воротник', 'стойка и отлёт'], ['Длинный рукав', 'одношовный'], ['Планка спереди', 'цельнокроеная'], ['Пуговицы', 'центр переда']],
    vest: [['Круглая горловина', 'обтачка'], ['Без рукавов', 'обтачка проймы'], ['Планка спереди', 'цельнокроеная'], ['Пуговицы', 'центр переда']],
    jacket: [['Лацкан и воротник', 'отдельные верхний и нижний'], ['Длинный рукав', 'одношовный'], ['Рельеф переда', 'контрольная линия'], ['Подкладка', 'перед, спинка и рукав']],
    trousers: [['Прямая брючина', 'передняя и задняя половинки'], ['Естественная талия', 'вытачки и прямой пояс'], ['Боковые карманы', 'мешковина и подзор'], ['Молния спереди', 'гульфик и откосок']],
    shorts: [['Прямой низ', 'длина выше колена'], ['Естественная талия', 'вытачки и прямой пояс'], ['Боковые карманы', 'мешковина и подзор'], ['Молния спереди', 'гульфик и откосок']],
  };
  const skirtBased = ['dress', 'sundress', 'skirt'].includes(spec.garment_type);
  const upperOnly = ['top', 'blouse', 'shirt', 'vest', 'jacket'].includes(spec.garment_type);
  const lowerOnly = ['trousers', 'shorts'].includes(spec.garment_type);
  const sleeved = ['blouse', 'shirt', 'jacket'].includes(spec.garment_type);
  const selectedAcceptance = acceptance?.garment_type === spec.garment_type ? acceptance : undefined;
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
      <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} error={autosave.error} onRetry={autosave.retry} />

      {suggestedUnsupported.length > 0 && (
        <div className="notice notice--warning">
          <strong>Анализ изображения нужно сверить</strong>
          <span>{suggestedUnsupported.join(', ')}. Ниже доступны только проверяемые варианты текущего каталога; выбранные замены показаны явно.</span>
        </div>
      )}

      <fieldset className="plain-choice">
        <legend>Что строим?</legend>
        {GARMENT_OPTIONS.map((item) => (
          <label key={item.id}>
            <input type="radio" checked={spec.garment_type === item.id} onChange={() => selectGarment(item.id)} />
            <span><strong>{item.name}</strong><small>{item.short}</small></span>
          </label>
        ))}
      </fieldset>

      {!['skirt', 'trousers', 'shorts'].includes(spec.garment_type) && <fieldset className="plain-choice">
        <legend>Посадка лифа</legend>
        <label><input type="radio" checked={parameters.bodice_fit === 'semi_fitted'} onChange={() => updateParameters({bodice_fit: 'semi_fitted'})} /> Полуприлегающая</label>
        {!['blouse', 'shirt', 'jacket'].includes(spec.garment_type) && <label><input type="radio" checked={parameters.bodice_fit === 'fitted'} onChange={() => updateParameters({bodice_fit: 'fitted'})} /> Прилегающая</label>}
      </fieldset>}

      <div className="locked-features" aria-label="Зафиксированные поддержанные элементы">
        {features[spec.garment_type].map(([title, detail]) => <div key={title}><strong>{title}</strong><span>{detail}</span></div>)}
      </div>

      {spec.design_intent && <DesignIntentEditor
        intent={spec.design_intent}
        spec={spec}
        analysis={analysis}
        busy={busy || autosave.state === 'saving'}
        onChange={(designIntent) => updateSpec({...spec, selection_status: 'proposed', confirmed_at: null, design_intent: designIntent})}
        onSave={saveDesignReview}
      />}

      <div className="notice notice--warning">
        <strong>{selectedAcceptance?.name_ru ?? GARMENT_OPTIONS.find((item) => item.id === spec.garment_type)?.name}: пробный статус</strong>
        <span>{selectedAcceptance?.scope_ru ?? 'Автоматические формулы и инварианты реализованы.'} Экспертная проверка, бумажная сборка и макет ещё не пройдены.</span>
      </div>

      <div className="number-grid">
        {!['skirt', 'jacket', 'trousers', 'shorts'].includes(spec.garment_type) && <NumberField id="front-neck-depth" label="Глубина горловины спереди" value={parameters.neckline.front_depth_mm / 10} min={5} max={25} onChange={(value) => updateParameters({neckline: {...parameters.neckline, type: 'round', front_depth_mm: value * 10}})} />}
        {!['skirt', 'jacket', 'trousers', 'shorts'].includes(spec.garment_type) && <NumberField id="back-neck-depth" label="Глубина горловины сзади" value={parameters.neckline.back_depth_mm / 10} min={1} max={12} onChange={(value) => updateParameters({neckline: {...parameters.neckline, type: 'round', back_depth_mm: value * 10}})} />}
        {skirtBased && <NumberField id="skirt-length" label="Длина юбки от талии" value={parameters.skirt.length_from_waist_mm / 10} min={35} max={120} onChange={(value) => updateParameters({skirt: {...parameters.skirt, type: 'a_line', length_from_waist_mm: value * 10}})} />}
        {skirtBased && <NumberField id="hem-expansion" label="Изменение низа с каждой стороны (+ шире, − уже)" value={parameters.skirt.hem_expansion_each_side_mm / 10} min={-10} max={25} onChange={(value) => updateParameters({skirt: {...parameters.skirt, type: 'a_line', hem_expansion_each_side_mm: value * 10}})} />}
        {upperOnly && <NumberField id="upper-length" label="Длина ниже талии" value={(parameters.upper?.length_below_waist_mm ?? 100) / 10} min={4} max={30} onChange={(value) => updateParameters({upper: {length_below_waist_mm: value * 10}})} />}
        {sleeved && <NumberField id="sleeve-length" label="Длина рукава" value={(parameters.sleeve.length_mm ?? 580) / 10} min={25} max={90} onChange={(value) => updateParameters({sleeve: {...parameters.sleeve, type: 'long', length_mm: value * 10}})} />}
        {parameters.jacket && <NumberField id="jacket-lapel" label="Ширина лацкана" value={parameters.jacket.lapel_width_mm / 10} min={4.5} max={10} onChange={(value) => updateParameters({jacket: {...parameters.jacket!, lapel_width_mm: value * 10}})} />}
        {parameters.jacket && <NumberField id="jacket-underlayer" label="Запас на нижний слой" value={parameters.jacket.underlayer_allowance_mm / 10} min={0} max={3} onChange={(value) => updateParameters({jacket: {...parameters.jacket!, underlayer_allowance_mm: value * 10}})} />}
        {parameters.jacket && <NumberField id="jacket-vent" label="Длина шлицы" value={parameters.jacket.vent_length_mm / 10} min={10} max={30} onChange={(value) => updateParameters({jacket: {...parameters.jacket!, vent_length_mm: value * 10}})} />}
        {parameters.trousers && <NumberField id="trouser-length" label={spec.garment_type === 'trousers' ? 'Длина брюк от талии' : 'Длина шорт от талии'} value={parameters.trousers.length_mm / 10} min={spec.garment_type === 'trousers' ? 70 : 38} max={spec.garment_type === 'trousers' ? 125 : 70} onChange={(value) => updateParameters({trousers: {...parameters.trousers!, length_mm: value * 10}})} />}
        {parameters.trousers && <NumberField id="trouser-waistband" label="Ширина готового пояса" value={parameters.trousers.waistband_width_mm / 10} min={3} max={5.5} onChange={(value) => updateParameters({trousers: {...parameters.trousers!, waistband_width_mm: value * 10}})} />}
        {parameters.trousers && <NumberField id="trouser-pocket" label="Длина входа в карман" value={parameters.trousers.pocket_opening_mm / 10} min={12} max={22} onChange={(value) => updateParameters({trousers: {...parameters.trousers!, pocket_opening_mm: value * 10}})} />}
        {parameters.closure.type !== 'none' && <NumberField id="closure-length" label={parameters.closure.type === 'buttons' ? 'Длина застёжки' : 'Рабочая длина молнии'} value={(parameters.closure.length_mm ?? 550) / 10} min={lowerOnly ? 12 : 30} max={lowerOnly ? 24 : 90} onChange={(value) => updateParameters({closure: {...parameters.closure, length_mm: value * 10}, ...(parameters.trousers ? {trousers: {...parameters.trousers, fly_length_mm: value * 10}} : {})})} />}
      </div>

      {!spec.design_intent && analysis.targeted_questions.length > 0 && (
        <div className="questions">
          <strong>Что стоит проверить по исходному изделию</strong>
          <ul>{analysis.targeted_questions.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="primary-button" disabled={busy || autosave.state === 'saving'}>
        {busy || autosave.state === 'saving' ? 'Сохраняем…' : 'Подтвердить фасон'} <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}

const EASE_FIELDS: Array<{key: keyof FitSettings['wearing_ease_mm']; label: string; min: number; max: number}> = [
  {key: 'bust', label: 'По груди', min: 0, max: 16},
  {key: 'waist', label: 'По талии', min: 0, max: 16},
  {key: 'hips', label: 'По бёдрам', min: 0, max: 16},
  {key: 'upper_arm', label: 'По плечу', min: 0, max: 12},
];

const ALLOWANCE_FIELDS: Array<{key: keyof FitSettings['seam_allowances_mm']; label: string; min: number; max: number}> = [
  {key: 'normal', label: 'Обычные швы', min: 0, max: 3},
  {key: 'neckline', label: 'Горловина', min: 0, max: 2},
  {key: 'armhole', label: 'Пройма', min: 0, max: 2},
  {key: 'zipper', label: 'У молнии', min: 0, max: 4},
  {key: 'hem', label: 'Низ изделия', min: 0, max: 6},
];

interface ConstructionDraft {
  fit: FitSettings;
  fabric: FabricProperties;
}

export function ConstructionEditor({
  project,
  onSave,
  onDirtyChange,
}: {
  project: ProjectDocument;
  onSave: SaveProject;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const draftKey = `kroika:draft:${project.project_id}:construction`;
  const loadedDraft = useRef<ReturnType<typeof loadLocalDraft<ConstructionDraft>> | null>(null);
  if (loadedDraft.current === null) {
    loadedDraft.current = loadLocalDraft(draftKey, {
      fit: structuredClone(project.fit_settings),
      fabric: structuredClone(project.fabric_properties),
    }, project.updated_at);
  }
  const [fit, setFit] = useState<FitSettings>(() => structuredClone(loadedDraft.current!.value.fit));
  const [fabric, setFabric] = useState<FabricProperties>(() => structuredClone(loadedDraft.current!.value.fabric));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const autosave = useDraftAutosave({
    storageKey: draftKey,
    initialValue: {fit, fabric},
    initiallyDirty: loadedDraft.current.restored,
    save: async (candidate) => {
      await onSave({
        ...project,
        status: 'draft',
        fit_settings: {...candidate.fit, status: 'draft', confirmed_at: null},
        fabric_properties: {...candidate.fabric, status: 'draft', confirmed_at: null},
      });
    },
    onDirtyChange,
  });
  const easeFields = EASE_FIELDS.filter(({key}) => {
    if (['skirt', 'trousers', 'shorts'].includes(project.garment_spec.garment_type)) return key === 'waist' || key === 'hips';
    if (['blouse', 'shirt', 'jacket'].includes(project.garment_spec.garment_type)) return true;
    return key !== 'upper_arm';
  }).map((field) => {
    if (project.garment_spec.garment_type !== 'jacket') return field;
    const layer = (project.garment_spec.parameters.jacket?.underlayer_allowance_mm ?? 10) / 10;
    const base = field.key === 'waist' ? 11 : field.key === 'upper_arm' ? 7 : 9;
    return {...field, min: base + layer};
  });

  function updateFit(next: FitSettings) {
    setFit(next);
    autosave.markDirty({fit: next, fabric});
  }

  function updateFabric(next: FabricProperties) {
    setFabric(next);
    autosave.markDirty({fit, fabric: next});
  }

  function setEase(key: keyof FitSettings['wearing_ease_mm'], valueCm: number) {
    updateFit({...fit, status: 'draft', confirmed_at: null, wearing_ease_mm: {
      ...fit.wearing_ease_mm, [key]: valueCm * 10,
    }});
  }

  function setAllowance(key: keyof FitSettings['seam_allowances_mm'], valueCm: number) {
    updateFit({...fit, status: 'draft', confirmed_at: null, seam_allowance_mode: 'by_edge', seam_allowances_mm: {
      ...fit.seam_allowances_mm, [key]: valueCm * 10,
    }});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const invalidEase = easeFields.some(({key, min, max}) => !bounded(fit.wearing_ease_mm[key] / 10, min, max));
    const invalidAllowance = ALLOWANCE_FIELDS.some(({key, min, max}) => !bounded(fit.seam_allowances_mm[key] / 10, min, max));
    if (invalidEase || invalidAllowance || !fabric.name.trim() || fabric.stretch_percent.weft > 5) {
      setError('Проверьте диапазоны, название ткани и растяжимость не выше 5%.');
      return;
    }
    const now = new Date().toISOString();
    const confirmedFit: FitSettings = {...fit, status: 'confirmed', confirmed_at: now};
    const confirmedFabric: FabricProperties = {
      ...fabric,
      name: fabric.name.trim(),
      status: 'confirmed',
      structure: 'woven',
      stability: 'stable',
      confirmed_at: now,
    };
    setBusy(true);
    setError('');
    autosave.cancelPending();
    try {
      await onSave({
        ...project,
        status: 'inputs_confirmed',
        fit_settings: confirmedFit,
        fabric_properties: confirmedFabric,
      });
      autosave.markSaved({fit: confirmedFit, fabric: confirmedFabric});
    } catch (caught) {
      autosave.markDirty({fit, fabric});
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
      <AutosaveIndicator state={autosave.state} savedAt={autosave.savedAt} error={autosave.error} onRetry={autosave.retry} />

      <section className="editor-section" aria-labelledby="fabric-title">
        <h3 id="fabric-title">1. Пробная ткань</h3>
        <div className="form-grid">
          <label><span>Название ткани</span><input value={fabric.name} maxLength={120} onChange={(event) => updateFabric({...fabric, name: event.target.value, status: 'draft', confirmed_at: null})} /></label>
          <label><span>Плотность</span><select value={fabric.weight} onChange={(event) => updateFabric({...fabric, weight: event.target.value as FabricProperties['weight']})}><option value="light">Лёгкая</option><option value="medium">Средняя</option><option value="heavy">Плотная</option></select></label>
          <label><span>Драпируемость</span><select value={fabric.drape} onChange={(event) => updateFabric({...fabric, drape: event.target.value as FabricProperties['drape']})}><option value="crisp">Держит форму</option><option value="medium">Средняя</option><option value="fluid">Струящаяся</option></select></label>
          <NumberField id="fabric-stretch" label="Растяжимость по утку" value={fabric.stretch_percent.weft} min={0} max={5} unit="%" onChange={(value) => updateFabric({...fabric, stretch_percent: {...fabric.stretch_percent, weft: value}})} />
        </div>
        <label className="consent-row"><input type="checkbox" checked={fabric.prewashed} onChange={(event) => updateFabric({...fabric, prewashed: event.target.checked})} /><span>Ткань декатирована или предварительно постирана.</span></label>
        <p className="scope-note">Для проверенной основы сейчас нужна стабильная тканая ткань с растяжимостью до 5%. Трикотаж будет отдельным модулем.</p>
      </section>

      <section className="editor-section" aria-labelledby="ease-title">
        <h3 id="ease-title">2. Прибавка на свободу облегания</h3>
        <div className="number-grid">
          {easeFields.map(({key, label, min, max}) => <NumberField key={key} id={`ease-${key}`} label={label} value={fit.wearing_ease_mm[key] / 10} min={min} max={max} onChange={(value) => setEase(key, value)} />)}
        </div>
        <p className="scope-note">{project.garment_spec.garment_type === 'jacket' ? 'Для жакета действует отдельный диапазон: он уже учитывает одежду нижнего слоя и не совпадает с прибавками платья.' : 'Прибавка распределяется поровну между передом и спинкой. Конструктивная прибавка модели сейчас равна 0.'}</p>
      </section>

      <section className="editor-section" aria-labelledby="allowance-title">
        <h3 id="allowance-title">3. Припуски на швы</h3>
        <div className="number-grid">
          {ALLOWANCE_FIELDS.map(({key, label, min, max}) => <NumberField key={key} id={`allowance-${key}`} label={label} value={fit.seam_allowances_mm[key] / 10} min={min} max={max} onChange={(value) => setAllowance(key, value)} />)}
        </div>
      </section>

      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="primary-button" disabled={busy || autosave.state === 'saving'}>
        {busy || autosave.state === 'saving' ? 'Сохраняем…' : 'Подтвердить ткань и настройки'} <span aria-hidden="true">→</span>
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

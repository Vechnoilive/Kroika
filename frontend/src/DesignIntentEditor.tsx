import {useState} from 'react';
import {DESIGN_ELEMENT_NAMES, finalizeDesignIntent, reevaluateDesignIntent} from './designIntent';
import {applicableRule, DESIGN_MODULES, matchingModule, moduleDiagnosis, type DesignModule} from './designModules';
import {isBackQuestion} from './backDesign';
import type {
  DesignElementType,
  DesignLocation,
  GarmentDesignIntent,
  GarmentSpec,
  StyleAnalysis,
  VisualDesignElement,
} from './types';

const ELEMENT_TYPES = Object.keys(DESIGN_ELEMENT_NAMES) as DesignElementType[];
const VARIANTS: VisualDesignElement['variant'][] = [
  'standard', 'straight', 'shaped', 'elastic', 'tie', 'knife', 'box', 'inverted',
  'accordion', 'soft', 'circular', 'gathered', 'patch', 'slash', 'welt', 'zipper',
  'buttons', 'hooks', 'concealed', 'single', 'double', 'shirt', 'notched', 'shawl',
  'stand', 'other', 'unknown',
];
const LOCATIONS: DesignLocation[] = [
  'bodice_front', 'bodice_back', 'neckline', 'shoulder', 'waist', 'skirt_front',
  'skirt_back', 'trouser_front', 'trouser_back', 'sleeve', 'hem', 'full_garment',
  'unknown',
];
const EMPTY_DIMENSIONS = {width: null, length: null, depth: null, spacing: null};

type Element = GarmentDesignIntent['elements'][number];
type Layer = GarmentDesignIntent['layers'][number];
type Dimension = keyof NonNullable<Element['dimensions_mm']>;

const SUPPORT_LABELS = {
  supported: 'Будет учтено',
  planned: 'Нужен модуль',
  needs_confirmation: 'Нужно подтвердить',
  excluded: 'Исключено вами',
};

function manualId(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function modelingHint(item: Element, spec: GarmentSpec): string | null {
  const module = matchingModule('element', item, spec, false);
  if (!module?.dimensions) return null;
  const labels: Record<string, string> = {
    width: 'ширина', length: 'длина', depth: 'глубина', spacing: 'расстояние',
  };
  const describe = (dimensions: typeof module.dimensions.required) => Object.entries(dimensions)
    .map(([field, bounds]) => {
      const max = bounds[1] === 'skirt_length_minus_20'
        ? spec.parameters.skirt.length_from_waist_mm - 20 : bounds[1];
      return `${module.parameter_labels_ru?.[field] ?? labels[field]} ${bounds[0] / 10}–${max / 10} см`;
    }).join(', ');
  const required = describe(module.dimensions.required);
  const optional = describe(module.dimensions.optional);
  const extension = item.location === 'hem' && ['ruffle', 'flounce'].includes(item.type)
    ? ' Глубина отделки добавляется к длине основной юбки.' : '';
  const hemRoom = ['ruffle', 'flounce', 'peplum'].includes(item.type)
    ? ' Глубина должна превышать выбранный припуск на низ минимум на 1 см.' : '';
  return `${module.title_ru}. ${required ? `Обязательно: ${required}. ` : ''}${optional ? `По желанию: ${optional}. ` : ''}Остальные размеры оставьте пустыми.${extension}${hemRoom}`;
}

export function DesignIntentEditor({
  intent,
  spec,
  analysis,
  busy,
  onChange,
  onSave,
}: {
  intent: GarmentDesignIntent;
  spec: GarmentSpec;
  analysis: StyleAnalysis;
  busy: boolean;
  onChange: (intent: GarmentDesignIntent) => void;
  onSave: (intent: GarmentDesignIntent) => Promise<void>;
}) {
  const [error, setError] = useState('');
  const [catalogModule, setCatalogModule] = useState('');
  const catalog = DESIGN_MODULES.filter((module) => module.kind === 'element'
    && Object.keys(module.dimensions?.required ?? {}).length > 0
    && applicableRule(module, spec));

  function defaultPlacement(module: DesignModule, symmetry: Element['symmetry'], location: Element['location'], previous?: Element['placement']): Element['placement'] {
    if (!module.placement) return undefined;
    const placement: NonNullable<Element['placement']> = {};
    for (const key of Object.keys(module.placement) as Array<keyof NonNullable<Element['placement']>>) {
      if (key === 'side') placement.side = symmetry === 'symmetric' ? 'both' : previous?.side === 'left' ? 'left' : 'right';
      if (key === 'edge') {
        const available = (module.placement.edge ?? []).filter((edge) => location.startsWith('skirt') ? ['hem', 'waist'].includes(String(edge)) : location.startsWith('bodice') ? ['neckline', 'waist', 'shoulder'].includes(String(edge)) : edge === 'hem');
        const preferred = location.startsWith('bodice') ? 'neckline' : 'hem';
        placement.edge = previous?.edge && available.includes(previous.edge) ? previous.edge : (available.includes(preferred) ? preferred : available[0]) as NonNullable<Element['placement']>['edge'];
      }
      if (key === 'offset_mm') placement.offset_mm = previous?.offset_mm ?? Number(module.placement?.offset_mm?.[0] ?? 0);
      if (key === 'orientation') placement.orientation = previous?.orientation ?? 'vertical';
      if (key === 'outline_edge_index') placement.outline_edge_index = previous?.outline_edge_index ?? 0;
      if (key === 'sweep_angle_deg') placement.sweep_angle_deg = previous?.sweep_angle_deg ?? 180;
    }
    return placement;
  }

  function addCatalogElement() {
    const module = catalog.find((entry) => entry.id === catalogModule);
    if (!module) return;
    const rule = applicableRule(module, spec)!;
    const symmetry = (rule.symmetry?.[0] ?? 'symmetric') as Element['symmetry'];
    const count = module.placement?.side && symmetry === 'symmetric' ? 2 : (rule.count?.[0] ?? 1) as number;
    const element: Element = {
      source_element_id: manualId('catalog'), type: rule.type[0] as Element['type'],
      variant: rule.variant[0] as Element['variant'], location: rule.location[0] as Element['location'],
      construction: rule.construction[0] as Element['construction'], count,
      symmetry, placement: defaultPlacement(module, symmetry, rule.location[0] as Element['location']), description_ru: module.title_ru,
      confidence: 1, evidence_ru: 'Добавлено пользователем из каталога деталей.',
      requires_confirmation: false, included: true, confirmed_by_user: false,
      dimensions_mm: {...EMPTY_DIMENSIONS}, support_status: 'needs_confirmation', module_id: null, selected_module_id: module.id,
    };
    change({...intent, source: 'manual', elements: [...intent.elements, element]});
  }

  function change(candidate: GarmentDesignIntent) {
    setError('');
    onChange(reevaluateDesignIntent(candidate, spec, analysis));
  }

  function updateElement(sourceId: string, update: Partial<Element>) {
    change({
      ...intent,
      elements: intent.elements.map((item) => (
        item.source_element_id === sourceId ? {...item, ...update} : item
      )),
    });
  }

  function selectConstruction(item: Element, moduleId: string) {
    const module = DESIGN_MODULES.find((entry) => entry.id === moduleId);
    if (!module) return;
    const rule = applicableRule(module, spec);
    if (!rule) return;
    const choose = (key: 'type' | 'variant' | 'location' | 'construction' | 'count' | 'symmetry', fallback?: unknown) =>
      rule[key]?.includes(item[key]) ? item[key] : rule[key]?.[0] ?? fallback;
    const dimensions: NonNullable<Element['dimensions_mm']> = {...EMPTY_DIMENSIONS};
    for (const key of Object.keys(dimensions) as Dimension[]) {
      if (module.dimensions && (key in module.dimensions.required || key in module.dimensions.optional)) {
        dimensions[key] = item.dimensions_mm?.[key] ?? null;
      }
    }
    const symmetry = choose('symmetry', item.symmetry) as Element['symmetry'];
    const location = choose('location') as Element['location'];
    updateElement(item.source_element_id, {
      type: choose('type') as Element['type'], variant: choose('variant') as Element['variant'],
      location, construction: choose('construction') as Element['construction'],
      count: module.placement?.side ? symmetry === 'symmetric' ? 2 : 1 : choose('count', item.count ?? 1) as number, symmetry,
      placement: defaultPlacement(module, symmetry, location, item.placement),
      outline_mm: module.custom_outline ? item.outline_mm ?? null : null, selected_module_id: module.id, dimensions_mm: dimensions, confirmed_by_user: false,
    });
  }

  function updateLayer(sourceId: string, update: Partial<Layer>) {
    change({
      ...intent,
      layers: intent.layers.map((item) => (
        item.source_layer_id === sourceId ? {...item, ...update} : item
      )),
    });
  }

  function addElement() {
    const element: Element = {
      source_element_id: manualId('manual_element'),
      type: 'other',
      variant: 'unknown',
      description_ru: 'Пропущенная деталь',
      location: 'unknown',
      construction: 'unknown',
      count: null,
      symmetry: 'unknown',
      confidence: 1,
      evidence_ru: 'Добавлено пользователем при проверке фотографии.',
      requires_confirmation: false,
      included: true,
      confirmed_by_user: false,
      dimensions_mm: {...EMPTY_DIMENSIONS},
      support_status: 'needs_confirmation',
      module_id: null,
    };
    change({...intent, source: 'manual', elements: [...intent.elements, element]});
  }

  function addLayer() {
    const layer: Layer = {
      source_layer_id: manualId('manual_layer'),
      role: 'overlay',
      coverage: 'detail',
      material_hint_ru: 'Дополнительный слой',
      opacity: 'unknown',
      drape: 'unknown',
      confidence: 1,
      requires_confirmation: false,
      included: true,
      confirmed_by_user: false,
      support_status: 'needs_confirmation',
      module_id: null,
    };
    change({...intent, source: 'manual', layers: [...intent.layers, layer]});
  }

  function setDimension(item: Element, key: Dimension, raw: string) {
    const dimensions = item.dimensions_mm ?? {...EMPTY_DIMENSIONS};
    const value = raw === '' ? null : Number(raw) * 10;
    updateElement(item.source_element_id, {
      dimensions_mm: {...dimensions, [key]: value},
      confirmed_by_user: false,
    });
  }

  function setLocation(item: Element, location: DesignLocation) {
    const module = DESIGN_MODULES.find((entry) => entry.id === (item.selected_module_id ?? item.module_id));
    updateElement(item.source_element_id, {
      location, confirmed_by_user: false,
      ...(module?.placement?.edge ? {placement: defaultPlacement(module, item.symmetry, location, item.placement)} : {}),
    });
  }

  async function saveReview() {
    setError('');
    try {
      await onSave(finalizeDesignIntent(intent, spec, analysis));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось проверить план фасона.');
    }
  }

  const reviewLabel = intent.review_status === 'confirmed'
    ? 'Проверка сохранена'
    : intent.status === 'needs_confirmation' ? 'Ждёт вашей проверки'
      : intent.status === 'partial' ? 'Есть ограничения построения' : 'Готово к подтверждению';

  return (
    <section className="design-intent" aria-labelledby="design-intent-title">
      <div className="design-intent__heading">
        <div>
          <p className="eyebrow">Разбор фотографии</p>
          <h3 id="design-intent-title">Проверьте конструктивные элементы</h3>
        </div>
        <span className={`design-intent__status design-intent__status--${intent.status}`}>
          {reviewLabel}
        </span>
      </div>
      <p>Исправьте распознавание, исключите лишнее и укажите известные размеры. Сайт сохранит и ваш выбор, и исходную подсказку модели.</p>
      <div className="review-fields">
        <label><span>Добавить деталь из каталога</span><select value={catalogModule} onChange={(event) => setCatalogModule(event.target.value)}>
          <option value="">Выберите конструкцию</option>
          {catalog.map((module) => <option key={module.id} value={module.id}>{module.title_ru}</option>)}
        </select></label>
        <button type="button" disabled={!catalogModule || busy} onClick={addCatalogElement}>Добавить выбранную деталь</button>
      </div>

      <div className="design-review-list">
        {intent.elements.map((item, index) => {
          const included = item.included !== false;
          const dimensions = item.dimensions_mm ?? EMPTY_DIMENSIONS;
          const diagnosis = moduleDiagnosis('element', item, spec);
          const module = diagnosis.module;
          const recipes = DESIGN_MODULES.filter((module) => module.kind === 'element'
            && applicableRule(module, spec)
            && (item.type === 'other' || module.rules.some((rule) => rule.type?.includes(item.type))));
          return (
            <article className={`design-review-card${included ? '' : ' design-review-card--excluded'}`} key={item.source_element_id}>
              <header>
                <div>
                  <strong>Деталь {index + 1}: {DESIGN_ELEMENT_NAMES[item.type]}</strong>
                  <small>{item.evidence_ru}</small>
                </div>
                <span className={`design-support design-support--${item.support_status}`}>
                  {diagnosis.label}
                </span>
              </header>
              <label className="review-check">
                <input
                  type="checkbox"
                  checked={included}
                  onChange={(event) => updateElement(item.source_element_id, {
                    included: event.target.checked,
                    confirmed_by_user: event.target.checked ? false : item.confirmed_by_user,
                  })}
                />
                <span>Эта деталь действительно есть на изделии</span>
              </label>
              {included && diagnosis.reasons.length > 0 && <div className="field-hint" aria-label={`Причина блокировки детали ${index + 1}`}>
                {diagnosis.module && <p>Доступная конструкция: {diagnosis.module.title_ru}.</p>}
                <ul>{diagnosis.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              </div>}
              {included && recipes.length > 0 && <label className="field-hint"><span>Выбрать готовую конструкцию</span>
                <select aria-label={`Выбрать конструкцию детали ${index + 1}`} value={item.selected_module_id ?? item.module_id ?? ''} onChange={(event) => selectConstruction(item, event.target.value)}>
                  <option value="">Выберите, если соответствует фотографии</option>
                  {recipes.map((module) => <option key={module.id} value={module.id}>{module.title_ru}</option>)}
                </select>
                <small>Выбор задаёт вариант, расположение, конструкцию, количество и симметрию. Неиспользуемые размеры очищаются. После выбора проверьте деталь по фотографии.</small>
              </label>}
              <div className="design-review-grid">
                <label><span>Название и описание</span><input aria-label={`Описание детали ${index + 1}`} disabled={!included} maxLength={240} value={item.description_ru} onChange={(event) => updateElement(item.source_element_id, {description_ru: event.target.value, confirmed_by_user: false})} /></label>
                <label><span>Тип детали</span><select aria-label={`Тип детали ${index + 1}`} disabled={!included} value={item.type} onChange={(event) => updateElement(item.source_element_id, {type: event.target.value as DesignElementType, confirmed_by_user: false})}>{ELEMENT_TYPES.map((value) => <option value={value} key={value}>{DESIGN_ELEMENT_NAMES[value]}</option>)}</select></label>
                <label><span>Вариант</span><select aria-label={`Вариант детали ${index + 1}`} disabled={!included} value={item.variant} onChange={(event) => updateElement(item.source_element_id, {variant: event.target.value as Element['variant'], confirmed_by_user: false})}>{VARIANTS.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
                <label><span>Расположение</span><select aria-label={`Расположение детали ${index + 1}`} disabled={!included} value={item.location} onChange={(event) => setLocation(item, event.target.value as DesignLocation)}>{LOCATIONS.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
                <label><span>Конструкция</span><select aria-label={`Конструкция детали ${index + 1}`} disabled={!included} value={item.construction} onChange={(event) => updateElement(item.source_element_id, {construction: event.target.value as Element['construction'], confirmed_by_user: false})}><option value="integrated">Цельнокроеная</option><option value="separate_piece">Отдельная деталь</option><option value="applied">Настрочная</option><option value="layered">Слой</option><option value="unknown">Не знаю</option></select></label>
                <label><span>Количество</span><input aria-label={`Количество детали ${index + 1}`} disabled={!included} type="number" min="1" max="32" value={item.count ?? ''} onChange={(event) => updateElement(item.source_element_id, {count: event.target.value === '' ? null : Number(event.target.value), confirmed_by_user: false})} /></label>
                <label><span>Симметрия</span><select aria-label={`Симметрия детали ${index + 1}`} disabled={!included} value={item.symmetry} onChange={(event) => updateElement(item.source_element_id, {symmetry: event.target.value as Element['symmetry'], confirmed_by_user: false})}><option value="symmetric">Симметричная</option><option value="asymmetric">Асимметричная</option><option value="single">Одиночная</option><option value="unknown">Не знаю</option></select></label>
              </div>
              <fieldset className="dimension-fields" disabled={!included}>
                <legend>Параметры построения, см — заполняйте только известные</legend>
                {module?.group === 'fullness' && <p className="field-hint">{module.id.startsWith('tiered_') ? 'Количество — число ярусов. Каждый ярус добавляет свою глубину к длине изделия.' : module.id.startsWith('placed_skirt_') || module.id.startsWith('integrated_bodice_') ? 'Количество указано на всё изделие: половина операций строится на каждой зеркальной половине.' : 'Правая и левая стороны указаны относительно человека, который носит изделие.'}</p>}
                {modelingHint(item, spec) && <p className="field-hint">{modelingHint(item, spec)}</p>}
                {([
                  ['width', 'Ширина'], ['length', 'Длина'], ['depth', 'Глубина'], ['spacing', 'Расстояние'],
                ] as Array<[Dimension, string]>).map(([key, label]) => (
                  <label key={key}><span>{module?.parameter_labels_ru?.[key] ?? label}</span><input aria-label={`${label} детали ${index + 1}, см`} type="number" inputMode="decimal" min="0.1" max="1000" step="0.1" value={dimensions[key] == null ? '' : dimensions[key] / 10} onChange={(event) => setDimension(item, key, event.target.value)} /></label>
                ))}
              </fieldset>
              {included && module?.custom_outline && <label><span>Контур детали: координаты точек в сантиметрах</span><textarea aria-label={`Контур детали ${index + 1}, см`} placeholder="[[0,0],[10,0],[8,6],[0,6]]" defaultValue={item.outline_mm ? JSON.stringify(item.outline_mm.map((p) => p.map((v) => v / 10))) : ''} onChange={(event) => {
                let outline: number[][] | null = null;
                try { const parsed: unknown = JSON.parse(event.target.value); if (Array.isArray(parsed) && parsed.length >= 3 && parsed.length <= 24 && parsed.every((p) => Array.isArray(p) && p.length === 2 && p.every((v) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 200))) outline = (parsed as number[][]).map((p) => p.map((v) => v * 10)); } catch { /* Keep the text while the polygon is being entered. */ }
                updateElement(item.source_element_id, {outline_mm: outline, confirmed_by_user: false});
              }} /><small>Последняя точка соединяется с первой. Номер ребра крепления — от 1. Длина этого ребра должна совпадать с длиной крепления.</small></label>}
              {included && module?.placement && <fieldset className="dimension-fields"><legend>Размещение детали</legend>
                {module.placement.side && <label><span>Сторона изделия</span><select aria-label={`Сторона детали ${index + 1}`} value={item.placement?.side ?? ''} onChange={(event) => updateElement(item.source_element_id, {placement: {...item.placement, side: event.target.value as 'both' | 'left' | 'right'}, confirmed_by_user: false})}><option value="" disabled>Укажите сторону</option>{module.placement.side.map((side) => <option key={side} value={side}>{side === 'both' ? 'Обе стороны' : side === 'right' ? 'Правая' : 'Левая'}</option>)}</select></label>}
                {module.placement.edge && <label><span>Срез крепления</span><select aria-label={`Срез крепления детали ${index + 1}`} value={item.placement?.edge ?? (item.location.startsWith('bodice') ? 'neckline' : 'hem')} onChange={(event) => updateElement(item.source_element_id, {placement: {...item.placement, edge: event.target.value as 'hem' | 'neckline' | 'waist' | 'shoulder'}, confirmed_by_user: false})}>{module.placement.edge.filter((edge) => item.location.startsWith('skirt') ? ['hem', 'waist'].includes(String(edge)) : item.location.startsWith('bodice') ? ['neckline', 'waist', 'shoulder'].includes(String(edge)) : edge === 'hem').map((edge) => <option key={edge} value={edge}>{({hem: 'Низ', neckline: 'Горловина', waist: 'Талия', shoulder: 'Плечо'} as Record<string, string>)[edge]}</option>)}</select></label>}
                {module.placement.offset_mm && <label><span>Смещение начала вниз, см</span><input aria-label={`Смещение начала детали ${index + 1}, см`} type="number" min="0" step="0.1" value={(item.placement?.offset_mm ?? 0) / 10} onChange={(event) => updateElement(item.source_element_id, {placement: {...item.placement, offset_mm: Number(event.target.value) * 10}, confirmed_by_user: false})} /></label>}
                {module.placement.orientation && <label><span>Направление строчки</span><select aria-label={`Направление детали ${index + 1}`} value={item.placement?.orientation ?? 'vertical'} onChange={(event) => updateElement(item.source_element_id, {placement: {...item.placement, orientation: event.target.value as 'vertical' | 'horizontal'}, confirmed_by_user: false})}><option value="vertical">Вертикальное</option><option value="horizontal">Горизонтальное</option></select></label>}
                {module.placement.outline_edge_index && <label><span>Номер ребра крепления</span><input aria-label={`Ребро крепления детали ${index + 1}`} type="number" min="1" max="24" value={(item.placement?.outline_edge_index ?? 0) + 1} onChange={(event) => updateElement(item.source_element_id, {placement: {...item.placement, outline_edge_index: Number(event.target.value) - 1}, confirmed_by_user: false})} /></label>}
                {module.placement.sweep_angle_deg && <label><span>Угол сектора волана, °</span><input aria-label={`Угол сектора детали ${index + 1}`} type="number" min="90" max="270" value={item.placement?.sweep_angle_deg ?? 180} onChange={(event) => updateElement(item.source_element_id, {placement: {...item.placement, sweep_angle_deg: Number(event.target.value)}, confirmed_by_user: false})} /></label>}
              </fieldset>}
              {included && <label className="review-check review-check--confirm"><input type="checkbox" checked={item.confirmed_by_user === true} onChange={(event) => updateElement(item.source_element_id, {confirmed_by_user: event.target.checked})} /><span>Я проверил(а) эту деталь по фотографии</span></label>}
            </article>
          );
        })}
      </div>
      <button className="secondary-button review-add" type="button" disabled={intent.elements.length >= 24} onClick={addElement}>+ Добавить пропущенную деталь</button>

      <div className="design-review-list">
        {intent.layers.map((item, index) => {
          const included = item.included !== false;
          const diagnosis = moduleDiagnosis('layer', item, spec);
          return (
            <article className={`design-review-card${included ? '' : ' design-review-card--excluded'}`} key={item.source_layer_id}>
              <header><strong>Слой {index + 1}</strong><span className={`design-support design-support--${item.support_status}`}>{diagnosis.label}</span></header>
              {included && diagnosis.reasons.length > 0 && <ul className="field-hint">{diagnosis.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
              <label className="review-check"><input type="checkbox" checked={included} disabled={item.role === 'main'} onChange={(event) => updateLayer(item.source_layer_id, {included: event.target.checked, confirmed_by_user: event.target.checked ? false : item.confirmed_by_user})} /><span>{item.role === 'main' ? 'Основной слой обязателен' : 'Этот слой действительно есть'}</span></label>
              <div className="design-review-grid">
                <label><span>Назначение</span><select aria-label={`Назначение слоя ${index + 1}`} disabled={!included} value={item.role} onChange={(event) => updateLayer(item.source_layer_id, {role: event.target.value as Layer['role'], confirmed_by_user: false})}><option value="main">Основной</option><option value="lining">Подкладка</option><option value="interfacing">Прокладка</option><option value="overlay">Накладной</option></select></label>
                <label><span>Материал или описание</span><input aria-label={`Описание слоя ${index + 1}`} disabled={!included} maxLength={160} value={item.material_hint_ru} onChange={(event) => updateLayer(item.source_layer_id, {material_hint_ru: event.target.value, confirmed_by_user: false})} /></label>
                <label><span>Покрытие</span><select disabled={!included} value={item.coverage} onChange={(event) => updateLayer(item.source_layer_id, {coverage: event.target.value as Layer['coverage'], confirmed_by_user: false})}><option value="full">Всё изделие</option><option value="bodice">Лиф</option><option value="skirt">Юбка</option><option value="sleeves">Рукава</option><option value="detail">Отдельная деталь</option><option value="unknown">Не знаю</option></select></label>
                <label><span>Прозрачность</span><select disabled={!included} value={item.opacity} onChange={(event) => updateLayer(item.source_layer_id, {opacity: event.target.value as Layer['opacity'], confirmed_by_user: false})}><option value="opaque">Непрозрачный</option><option value="semi_transparent">Полупрозрачный</option><option value="transparent">Прозрачный</option><option value="unknown">Не знаю</option></select></label>
                <label><span>Пластика</span><select disabled={!included} value={item.drape} onChange={(event) => updateLayer(item.source_layer_id, {drape: event.target.value as Layer['drape'], confirmed_by_user: false})}><option value="crisp">Держит форму</option><option value="medium">Средняя</option><option value="fluid">Струящаяся</option><option value="unknown">Не знаю</option></select></label>
              </div>
              {included && item.role === 'lining' && <p className="field-hint">Сейчас отдельные лекала подкладки строятся для юбочной части; другие покрытия останутся заблокированы.</p>}
              {included && item.role === 'overlay' && <p className="field-hint">Верхний юбочный слой получит собственные детали и соединения по талии и боковым швам.</p>}
              {included && <label className="review-check review-check--confirm"><input type="checkbox" checked={item.confirmed_by_user === true} onChange={(event) => updateLayer(item.source_layer_id, {confirmed_by_user: event.target.checked})} /><span>Я проверил(а) этот слой</span></label>}
            </article>
          );
        })}
      </div>
      <button className="secondary-button review-add" type="button" disabled={intent.layers.length >= 6} onClick={addLayer}>+ Добавить слой</button>

      <article className="design-review-card">
        <header><strong>Пропорции и асимметрия</strong><span className={`design-support design-support--${intent.proportions.support_status}`}>{intent.proportions.support_status === 'planned' && matchingModule('proportions', intent.proportions, spec, false) ? 'Проверьте параметры' : SUPPORT_LABELS[intent.proportions.support_status]}</span></header>
        <div className="design-review-grid">
          <label><span>Линия талии</span><select value={intent.proportions.waist_position} onChange={(event) => change({...intent, proportions: {...intent.proportions, waist_position: event.target.value as GarmentDesignIntent['proportions']['waist_position'], waist_shift_mm: null, waist_level_circumference_mm: null, back_waist_level_arc_mm: null, confirmed_by_user: false}})}><option value="low">Заниженная</option><option value="natural">Естественная</option><option value="high">Завышенная</option><option value="unknown">Не знаю</option></select></label>
          <label><span>Объём</span><select value={intent.proportions.volume} onChange={(event) => change({...intent, proportions: {...intent.proportions, volume: event.target.value as GarmentDesignIntent['proportions']['volume'], confirmed_by_user: false}})}><option value="fitted">Прилегающий</option><option value="regular">Обычный</option><option value="relaxed">Свободный</option><option value="voluminous">Объёмный</option><option value="unknown">Не знаю</option></select></label>
          <label><span>Форма низа</span><select value={intent.proportions.hem_shape} onChange={(event) => change({...intent, proportions: {...intent.proportions, hem_shape: event.target.value as GarmentDesignIntent['proportions']['hem_shape'], hem_delta_mm: null, confirmed_by_user: false}})}><option value="straight">Прямая</option><option value="curved">Скруглённая</option><option value="asymmetric">Асимметричная</option><option value="tiered">Ярусная</option><option value="unknown">Не знаю</option></select></label>
          <label><span>Асимметрия</span><select value={intent.proportions.asymmetry} onChange={(event) => change({...intent, proportions: {...intent.proportions, asymmetry: event.target.value as GarmentDesignIntent['proportions']['asymmetry'], confirmed_by_user: false}})}><option value="no">Нет</option><option value="yes">Есть</option><option value="unknown">Не знаю</option></select></label>
        </div>
        {intent.proportions.hem_shape === 'tiered' && <p className="field-hint">Добавьте из каталога ярусную оборку или волан, укажите число ярусов и глубину каждого. Итоговая длина увеличится на сумму глубин.</p>}
        {intent.proportions.waist_position !== 'natural' && intent.proportions.waist_position !== 'unknown' && <div className="design-review-grid">
          {([['waist_shift_mm', 'Смещение линии талии, см'], ['waist_level_circumference_mm', 'Обхват на новой линии талии, см'], ['back_waist_level_arc_mm', 'Задняя дуга на новой линии талии, см']] as const).map(([key, label]) => <label key={key}><span>{label}</span><input type="number" step="0.1" value={intent.proportions[key] == null ? '' : intent.proportions[key]! / 10} onChange={(event) => change({...intent, proportions: {...intent.proportions, [key]: event.target.value === '' ? null : Number(event.target.value) * 10, confirmed_by_user: false}})} /></label>)}
        </div>}
        {['curved', 'asymmetric'].includes(intent.proportions.hem_shape) && <label><span>Подъём низа по центру, см</span><input type="number" min="2" max="25" step="0.1" value={intent.proportions.hem_delta_mm == null ? '' : intent.proportions.hem_delta_mm / 10} onChange={(event) => change({...intent, proportions: {...intent.proportions, hem_delta_mm: event.target.value === '' ? null : Number(event.target.value) * 10, confirmed_by_user: false}})} /></label>}
        <p className="field-hint">Свободный объём добавляет минимум 6 см модельной прибавки, объёмный — 12 см; по руке вдвое меньше. Асимметричный низ: перед короче по центру, боковые швы сохраняются. Смещённая талия доступна для платья и сарафана и требует мерок на новой высоте.</p>
        <label className="review-check review-check--confirm"><input type="checkbox" checked={intent.proportions.confirmed_by_user === true} onChange={(event) => change({...intent, proportions: {...intent.proportions, confirmed_by_user: event.target.checked}})} /><span>Я проверил(а) пропорции</span></label>
      </article>

      {intent.pending_questions.some((question) => !isBackQuestion(question)) && <div className="review-questions">
        <strong>Ответьте на вопросы модели</strong>
        {intent.pending_questions.filter((question) => !isBackQuestion(question)).map((question, index) => {
          const answer = intent.question_answers?.find((item) => item.question === question)?.answer_ru ?? '';
          return <label key={question}><span>{question}</span><textarea aria-label={`Ответ на вопрос ${index + 1}`} maxLength={1000} value={answer} onChange={(event) => change({...intent, question_answers: intent.pending_questions.map((item) => ({question: item, answer_ru: item === question ? event.target.value : intent.question_answers?.find((previous) => previous.question === item)?.answer_ru ?? ''}))})} /></label>;
        })}
      </div>}

      {intent.status === 'partial' && <div className="notice notice--warning"><strong>Проверка сохранится, но построение останется закрытым</strong><span>Для включённых деталей нужно проверить параметры или реализовать геометрию. Мерки можно вводить и сохранять уже сейчас.</span></div>}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="secondary-button review-save" type="button" disabled={busy} onClick={() => void saveReview()}>{busy ? 'Сохраняем проверку…' : 'Сохранить проверку деталей'}</button>
    </section>
  );
}

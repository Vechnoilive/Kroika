import {useState} from 'react';
import {DESIGN_ELEMENT_NAMES, finalizeDesignIntent, reevaluateDesignIntent} from './designIntent';
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

function modelingHint(item: Element): string | null {
  if (item.type === 'pleat') return 'Для центральной складки: глубина обязательна, длина контрольных линий — по желанию.';
  if (item.type === 'gather') return 'Для сборки: ширина — сколько добавить к срезу, длина контрольной линии — по желанию.';
  if (item.type === 'flounce') return 'Для кругового волана по низу заполните глубину.';
  if (item.type === 'waistband') return 'Для отдельного прямого пояса заполните ширину готового пояса.';
  if (item.type === 'belt') return 'Для отдельного прямого ремня заполните ширину и полную длину.';
  if (item.type === 'cuff') return 'Для прямой манжеты укажите готовую ширину; длина соединения берётся со среза рукава.';
  if (item.type === 'collar') return 'Для стойки укажите готовую высоту; длина строится точно по горловине.';
  if (item.type === 'pocket') return 'Для парных накладных карманов укажите ширину и глубину.';
  if (['yoke', 'panel', 'dart'].includes(item.type)) {
    return 'Формула сохранится в плане, но эта топология пока не меняет сопрягаемые детали и останется заблокированной.';
  }
  return null;
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
      : intent.status === 'partial' ? 'Проверено, нужны модули' : 'Готово к подтверждению';

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

      <div className="design-review-list">
        {intent.elements.map((item, index) => {
          const included = item.included !== false;
          const dimensions = item.dimensions_mm ?? EMPTY_DIMENSIONS;
          return (
            <article className={`design-review-card${included ? '' : ' design-review-card--excluded'}`} key={item.source_element_id}>
              <header>
                <div>
                  <strong>Деталь {index + 1}: {DESIGN_ELEMENT_NAMES[item.type]}</strong>
                  <small>{item.evidence_ru}</small>
                </div>
                <span className={`design-support design-support--${item.support_status}`}>
                  {SUPPORT_LABELS[item.support_status]}
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
              <div className="design-review-grid">
                <label><span>Название и описание</span><input aria-label={`Описание детали ${index + 1}`} disabled={!included} maxLength={240} value={item.description_ru} onChange={(event) => updateElement(item.source_element_id, {description_ru: event.target.value, confirmed_by_user: false})} /></label>
                <label><span>Тип детали</span><select aria-label={`Тип детали ${index + 1}`} disabled={!included} value={item.type} onChange={(event) => updateElement(item.source_element_id, {type: event.target.value as DesignElementType, confirmed_by_user: false})}>{ELEMENT_TYPES.map((value) => <option value={value} key={value}>{DESIGN_ELEMENT_NAMES[value]}</option>)}</select></label>
                <label><span>Вариант</span><select aria-label={`Вариант детали ${index + 1}`} disabled={!included} value={item.variant} onChange={(event) => updateElement(item.source_element_id, {variant: event.target.value as Element['variant'], confirmed_by_user: false})}>{VARIANTS.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
                <label><span>Расположение</span><select aria-label={`Расположение детали ${index + 1}`} disabled={!included} value={item.location} onChange={(event) => updateElement(item.source_element_id, {location: event.target.value as DesignLocation, confirmed_by_user: false})}>{LOCATIONS.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
                <label><span>Конструкция</span><select aria-label={`Конструкция детали ${index + 1}`} disabled={!included} value={item.construction} onChange={(event) => updateElement(item.source_element_id, {construction: event.target.value as Element['construction'], confirmed_by_user: false})}><option value="integrated">Цельнокроеная</option><option value="separate_piece">Отдельная деталь</option><option value="applied">Настрочная</option><option value="layered">Слой</option><option value="unknown">Не знаю</option></select></label>
                <label><span>Количество</span><input aria-label={`Количество детали ${index + 1}`} disabled={!included} type="number" min="1" max="32" value={item.count ?? ''} onChange={(event) => updateElement(item.source_element_id, {count: event.target.value === '' ? null : Number(event.target.value), confirmed_by_user: false})} /></label>
              </div>
              <fieldset className="dimension-fields" disabled={!included}>
                <legend>Параметры построения, см — заполняйте только известные</legend>
                {modelingHint(item) && <p className="field-hint">{modelingHint(item)}</p>}
                {([
                  ['width', 'Ширина'], ['length', 'Длина'], ['depth', 'Глубина'], ['spacing', 'Расстояние'],
                ] as Array<[Dimension, string]>).map(([key, label]) => (
                  <label key={key}><span>{label}</span><input aria-label={`${label} детали ${index + 1}, см`} type="number" inputMode="decimal" min="0.1" max="1000" step="0.1" value={dimensions[key] === null ? '' : dimensions[key] / 10} onChange={(event) => setDimension(item, key, event.target.value)} /></label>
                ))}
              </fieldset>
              {included && <label className="review-check review-check--confirm"><input type="checkbox" checked={item.confirmed_by_user === true} onChange={(event) => updateElement(item.source_element_id, {confirmed_by_user: event.target.checked})} /><span>Я проверил(а) эту деталь по фотографии</span></label>}
            </article>
          );
        })}
      </div>
      <button className="secondary-button review-add" type="button" disabled={intent.elements.length >= 24} onClick={addElement}>+ Добавить пропущенную деталь</button>

      <div className="design-review-list">
        {intent.layers.map((item, index) => {
          const included = item.included !== false;
          return (
            <article className={`design-review-card${included ? '' : ' design-review-card--excluded'}`} key={item.source_layer_id}>
              <header><strong>Слой {index + 1}</strong><span className={`design-support design-support--${item.support_status}`}>{SUPPORT_LABELS[item.support_status]}</span></header>
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
        <header><strong>Пропорции и асимметрия</strong><span className={`design-support design-support--${intent.proportions.support_status}`}>{SUPPORT_LABELS[intent.proportions.support_status]}</span></header>
        <div className="design-review-grid">
          <label><span>Линия талии</span><select value={intent.proportions.waist_position} onChange={(event) => change({...intent, proportions: {...intent.proportions, waist_position: event.target.value as GarmentDesignIntent['proportions']['waist_position'], confirmed_by_user: false}})}><option value="low">Заниженная</option><option value="natural">Естественная</option><option value="high">Завышенная</option><option value="unknown">Не знаю</option></select></label>
          <label><span>Объём</span><select value={intent.proportions.volume} onChange={(event) => change({...intent, proportions: {...intent.proportions, volume: event.target.value as GarmentDesignIntent['proportions']['volume'], confirmed_by_user: false}})}><option value="fitted">Прилегающий</option><option value="regular">Обычный</option><option value="relaxed">Свободный</option><option value="voluminous">Объёмный</option><option value="unknown">Не знаю</option></select></label>
          <label><span>Форма низа</span><select value={intent.proportions.hem_shape} onChange={(event) => change({...intent, proportions: {...intent.proportions, hem_shape: event.target.value as GarmentDesignIntent['proportions']['hem_shape'], confirmed_by_user: false}})}><option value="straight">Прямая</option><option value="curved">Скруглённая</option><option value="asymmetric">Асимметричная</option><option value="tiered">Ярусная</option><option value="unknown">Не знаю</option></select></label>
          <label><span>Асимметрия</span><select value={intent.proportions.asymmetry} onChange={(event) => change({...intent, proportions: {...intent.proportions, asymmetry: event.target.value as GarmentDesignIntent['proportions']['asymmetry'], confirmed_by_user: false}})}><option value="no">Нет</option><option value="yes">Есть</option><option value="unknown">Не знаю</option></select></label>
        </div>
        <label className="review-check review-check--confirm"><input type="checkbox" checked={intent.proportions.confirmed_by_user === true} onChange={(event) => change({...intent, proportions: {...intent.proportions, confirmed_by_user: event.target.checked}})} /><span>Я проверил(а) пропорции</span></label>
      </article>

      {intent.pending_questions.length > 0 && <div className="review-questions">
        <strong>Ответьте на вопросы модели</strong>
        {intent.pending_questions.map((question, index) => {
          const answer = intent.question_answers?.find((item) => item.question === question)?.answer_ru ?? '';
          return <label key={question}><span>{question}</span><textarea aria-label={`Ответ на вопрос ${index + 1}`} maxLength={1000} value={answer} onChange={(event) => change({...intent, question_answers: (intent.question_answers ?? []).map((item) => item.question === question ? {...item, answer_ru: event.target.value} : item)})} /></label>;
        })}
      </div>}

      {intent.status === 'partial' && <div className="notice notice--warning"><strong>Проверка сохранится, но построение останется закрытым</strong><span>Одна или несколько подтверждённых деталей пока не имеют геометрического модуля. Они не будут потеряны или заменены молча.</span></div>}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="secondary-button review-save" type="button" disabled={busy} onClick={() => void saveReview()}>{busy ? 'Сохраняем проверку…' : 'Сохранить проверку деталей'}</button>
    </section>
  );
}

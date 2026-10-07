import {structuralConflicts, matchingModule, moduleIds} from './designModules';
import {answerBackQuestions} from './backDesign';
import type {
  DesignElementType,
  GarmentDesignIntent,
  GarmentSpec,
  StyleAnalysis,
  VisualDesignElement,
  VisualDesignLayer,
  VisualProportions,
} from './types';

type Support = {status: 'supported'; moduleId: string} | {status: 'planned'; moduleId: null};
type IntentElement = GarmentDesignIntent['elements'][number];

function elementSupport(
  element: VisualDesignElement | IntentElement, spec: GarmentSpec,
): Support {
  const module = matchingModule('element', element, spec);
  return module ? {status: 'supported', moduleId: module.id} : {status: 'planned', moduleId: null};
}

function layerSupport(layer: VisualDesignLayer, spec: GarmentSpec): Support {
  const module = matchingModule('layer', layer, spec);
  return module ? {status: 'supported', moduleId: module.id} : {status: 'planned', moduleId: null};
}

function proportionsSupport(
  proportions: VisualProportions, spec: GarmentSpec,
): {status: 'supported' | 'planned' | 'needs_confirmation'; moduleId: string | null} {
  if ([proportions.waist_position, proportions.volume, proportions.hem_shape, proportions.asymmetry]
      .includes('unknown')) return {status: 'needs_confirmation', moduleId: null};
  const module = matchingModule('proportions', proportions, spec);
  return module ? {status: 'supported', moduleId: module.id} : {status: 'planned', moduleId: null};
}

const EMPTY_DIMENSIONS = {width: null, length: null, depth: null, spacing: null};

export function buildDesignIntent(
  analysis: StyleAnalysis,
  _spec: GarmentSpec,
): GarmentDesignIntent | undefined {
  if (!analysis.design_features) return undefined;
  const unsupportedElements: VisualDesignElement[] = (analysis.unsupported_features ?? []).map(
    (description, index) => ({
      element_id: `unsupported_${index + 1}`,
      type: 'other',
      variant: 'unknown',
      description_ru: description.slice(0, 240),
      location: 'unknown',
      construction: 'unknown',
      count: null,
      symmetry: 'unknown',
      confidence: 0.5,
      evidence_ru: 'Модель отдельно отметила эту особенность как неподдержанную.',
      requires_confirmation: false,
    }),
  );
  const elements = [...analysis.design_features.elements, ...unsupportedElements].map((element) => {
    const {element_id: sourceElementId, ...details} = element;
    return {
      ...details,
      source_element_id: sourceElementId,
      included: true,
      confirmed_by_user: false,
      dimensions_mm: {...EMPTY_DIMENSIONS},
      support_status: 'needs_confirmation' as const,
      module_id: null,
    };
  });
  const layers = analysis.design_features.layers.map((layer) => {
    const {layer_id: sourceLayerId, ...details} = layer;
    return {
      ...details,
      source_layer_id: sourceLayerId,
      included: true,
      confirmed_by_user: false,
      support_status: 'needs_confirmation' as const,
      module_id: null,
    };
  });
  const proportions = {
    ...analysis.design_features.proportions,
    confirmed_by_user: false,
    support_status: 'needs_confirmation' as const,
    module_id: null,
  };
  const pendingQuestions = [...new Set(analysis.targeted_questions)];
  return {
    schema_version: '1.0.0',
    coverage_schema_version: '1.0.0',
    source: 'ai',
    status: 'needs_confirmation',
    review_status: 'proposed',
    reviewed_at: null,
    elements,
    layers,
    proportions,
    pending_questions: pendingQuestions,
    question_answers: pendingQuestions.map((question) => ({question, answer_ru: ''})),
  };
}

export function prepareDesignIntentForReview(
  intent: GarmentDesignIntent,
): GarmentDesignIntent {
  if (intent.review_status !== undefined) return intent;
  return {
    ...intent,
    coverage_schema_version: '1.0.0',
    status: 'needs_confirmation',
    review_status: 'proposed',
    reviewed_at: null,
    elements: intent.elements.map((item) => ({
      ...item,
      included: true,
      confirmed_by_user: false,
      dimensions_mm: item.dimensions_mm ?? {...EMPTY_DIMENSIONS},
      support_status: 'needs_confirmation',
      module_id: null,
    })),
    layers: intent.layers.map((item) => ({
      ...item,
      included: true,
      confirmed_by_user: false,
      support_status: 'needs_confirmation',
      module_id: null,
    })),
    proportions: {
      ...intent.proportions,
      confirmed_by_user: false,
      support_status: 'needs_confirmation',
      module_id: null,
    },
    question_answers: intent.pending_questions.map((question) => ({question, answer_ru: ''})),
  };
}

function asVisualLayer(layer: GarmentDesignIntent['layers'][number]): VisualDesignLayer {
  return {
    layer_id: layer.source_layer_id,
    role: layer.role,
    coverage: layer.coverage,
    material_hint_ru: layer.material_hint_ru,
    opacity: layer.opacity,
    drape: layer.drape,
    confidence: layer.confidence,
    requires_confirmation: layer.requires_confirmation,
  };
}

function alignedAnswers(intent: GarmentDesignIntent) {
  const previous = new Map(
    (intent.question_answers ?? []).map((item) => [item.question, item.answer_ru]),
  );
  return intent.pending_questions.map((question) => ({
    question,
    answer_ru: previous.get(question) ?? '',
  }));
}

function deriveStatus(intent: GarmentDesignIntent) {
  const active = [
    ...intent.elements.filter((item) => item.included !== false),
    ...intent.layers.filter((item) => item.included !== false),
    intent.proportions,
  ];
  const unanswered = (intent.question_answers ?? []).some((item) => !item.answer_ru.trim());
  if (unanswered || active.some((item) => item.confirmed_by_user !== true)
      || active.some((item) => item.support_status === 'needs_confirmation')) {
    return 'needs_confirmation' as const;
  }
  return active.some((item) => item.support_status === 'planned') ? 'partial' as const : 'ready' as const;
}

export function reevaluateDesignIntent(
  intent: GarmentDesignIntent,
  spec: GarmentSpec,
  _analysis: StyleAnalysis,
): GarmentDesignIntent {
  intent = answerBackQuestions(intent, spec);
  const next: GarmentDesignIntent = {
    ...intent,
    coverage_schema_version: '1.0.0',
    review_status: 'proposed',
    reviewed_at: null,
    elements: intent.elements.map((element) => {
      if (element.included === false) {
        return {...element, support_status: 'excluded' as const, module_id: null};
      }
      if (element.confirmed_by_user !== true) {
        return {...element, included: true, support_status: 'needs_confirmation' as const, module_id: null};
      }
      const support = elementSupport(element, spec);
      return {...element, included: true, support_status: support.status, module_id: support.moduleId};
    }),
    layers: intent.layers.map((layer) => {
      if (layer.included === false) {
        return {...layer, support_status: 'excluded' as const, module_id: null};
      }
      if (layer.confirmed_by_user !== true) {
        return {...layer, included: true, support_status: 'needs_confirmation' as const, module_id: null};
      }
      const support = layerSupport(asVisualLayer(layer), spec);
      return {...layer, included: true, support_status: support.status, module_id: support.moduleId};
    }),
    proportions: intent.proportions.confirmed_by_user === true
      ? (() => {
          const support = proportionsSupport(intent.proportions, spec);
          return {...intent.proportions, support_status: support.status, module_id: support.moduleId};
        })()
      : {...intent.proportions, support_status: 'needs_confirmation', module_id: null},
    question_answers: alignedAnswers(intent),
  };
  if (intent.proportions.confirmed_by_user === true) {
    const support = proportionsSupport(intent.proportions, {...spec, design_intent: next});
    next.proportions = {...next.proportions, support_status: support.status, module_id: support.moduleId};
  }
  return {...next, status: deriveStatus(next)};
}

export function finalizeDesignIntent(
  intent: GarmentDesignIntent,
  spec: GarmentSpec,
  analysis: StyleAnalysis,
  reviewedAt = new Date().toISOString(),
): GarmentDesignIntent {
  const evaluated = reevaluateDesignIntent(intent, spec, analysis);
  const includedLayers = evaluated.layers.filter((item) => item.included !== false);
  const includedElements = evaluated.elements.filter((item) => item.included !== false);
  const structuralErrors = structuralConflicts({...spec, design_intent: evaluated});
  if (structuralErrors.length) throw new Error(structuralErrors[0]);
  const activeModules = new Set(
    includedElements.map((item) => item.module_id).filter((item): item is string => item !== null),
  );
  if (['diagonal_bodice_drape_v2', 'crossed_bodice_drape_v1'].some((id) => activeModules.has(id))
      && includedElements.some((item) => item.location === 'bodice_front' && ['integrated_bodice_drape_v2', 'integrated_bodice_gather_v2'].includes(item.module_id ?? ''))) {
    throw new Error('Параллельные раскрытия переда пока нельзя совмещать с драпировкой полного переда. Выберите одну конструкцию переда; раскрытия спинки допустимы.');
  }
  if (['paired_straight_skirt_yoke_v1', 'paired_equal_skirt_panels_v1'].some((id) => activeModules.has(id))
      && [...moduleIds('fullness')].some((id) => activeModules.has(id))) {
    throw new Error('Новые распределённые операции и отделка пока требуют юбку без кокетки и панелей.');
  }
  if (includedElements.filter((item) => ['center_pleat_v1', 'waist_gather_allowance_v1',
    'center_stitched_tuck_v1'].includes(item.module_id ?? '')).length > 1) {
    throw new Error('Для центра переда юбки выберите одну добавку ширины: складку, сборку или защип.');
  }
  if (activeModules.has('paired_straight_skirt_yoke_v1')
      && ['center_stitched_tuck_v1', 'paired_straight_decorative_stitch_v1'].some((id) => activeModules.has(id))) {
    throw new Error('Защип и декоративная строчка пока строятся на юбке без кокетки.');
  }
  if (activeModules.has('paired_straight_skirt_yoke_v1')
      && activeModules.has('paired_equal_skirt_panels_v1')) {
    throw new Error('Для одной юбки выберите либо кокетку, либо панельное членение.');
  }
  const incompatibleTopologyModules = [
    'center_pleat_v1', 'waist_gather_allowance_v1',
    'center_stitched_tuck_v1', 'paired_straight_decorative_stitch_v1', 'circular_hem_flounce_v1',
    'paired_patch_pocket_v1',
  ];
  if (activeModules.has('paired_equal_skirt_panels_v1')
      && incompatibleTopologyModules.some((moduleId) => activeModules.has(moduleId))) {
    throw new Error(
      'Панели пока нельзя совмещать со складкой, сборкой, воланом, защипом, декоративной строчкой или накладными карманами.',
    );
  }
  if (includedLayers.filter((item) => item.role === 'main').length !== 1) {
    throw new Error('Оставьте ровно один основной слой изделия.');
  }
  if (includedElements.some((item) => !item.description_ru.trim())) {
    throw new Error('У каждой оставленной детали должно быть название или описание.');
  }
  if (includedLayers.some((item) => !item.material_hint_ru.trim())) {
    throw new Error('Опишите материал или назначение каждого оставленного слоя.');
  }
  const invalidElementNumber = includedElements.some((item) => (
    (item.count !== null && (!Number.isInteger(item.count) || item.count < 1 || item.count > 32))
    || Object.values(item.dimensions_mm ?? {}).some((value) => (
      value !== null && (!Number.isFinite(value) || value <= 0 || value > 10000)
    ))
  ));
  if (invalidElementNumber) {
    throw new Error('Проверьте количество и размеры деталей: указано недопустимое число.');
  }
  const unconfirmedCount = [
    ...includedElements,
    ...includedLayers,
    evaluated.proportions,
  ].filter((item) => item.confirmed_by_user !== true).length;
  if (unconfirmedCount > 0) {
    throw new Error(`Подтвердите все оставленные детали, слои и пропорции (${unconfirmedCount}).`);
  }
  if ((evaluated.question_answers ?? []).some((item) => !item.answer_ru.trim())) {
    throw new Error('Ответьте на все вопросы модели или исключите неверную деталь.');
  }
  return {
    ...evaluated,
    review_status: 'confirmed',
    reviewed_at: reviewedAt,
  };
}

export const DESIGN_ELEMENT_NAMES: Record<DesignElementType, string> = {
  waistband: 'Пояс', belt: 'Ремень', sash: 'Пояс-кушак', pleat: 'Складка',
  tuck: 'Защип', gather: 'Сборка', ruffle: 'Оборка', flounce: 'Волан',
  peplum: 'Баска', yoke: 'Кокетка', panel: 'Панель', overlay: 'Накладной слой',
  drape: 'Драпировка', pocket: 'Карман', closure: 'Застёжка', slit: 'Разрез',
  vent: 'Шлица', hood: 'Капюшон', collar: 'Воротник', cuff: 'Манжета',
  strap: 'Бретель', dart: 'Вытачка', princess_seam: 'Рельефный шов',
  decorative_seam: 'Декоративный шов', other: 'Дополнительная деталь',
};

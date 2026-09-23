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

const EMPTY_DIMENSIONS = {width: null, length: null, depth: null, spacing: null};

function elementSupport(
  element: VisualDesignElement,
  spec: GarmentSpec,
): Support {
  const garment = spec.garment_type;
  if (element.type === 'closure') {
    const configured = spec.parameters.closure;
    const locationMatches = (
      (configured.location === 'center_back' && element.location === 'bodice_back')
      || (configured.location === 'center_front'
        && ['bodice_front', 'trouser_front'].includes(element.location))
      || (configured.location === 'side' && element.location === 'waist')
    );
    if (element.variant === configured.type && locationMatches) {
      return {status: 'supported', moduleId: 'bounded_closure'};
    }
    return {status: 'planned', moduleId: null};
  }
  if (element.type === 'waistband'
      && ['skirt', 'trousers', 'shorts'].includes(garment)
      && element.variant === 'straight'
      && element.construction === 'separate_piece') {
    return {status: 'supported', moduleId: 'straight_waistband'};
  }
  if (element.type === 'dart' && element.variant === 'standard') {
    const upper = ['dress', 'sundress', 'top', 'blouse', 'shirt', 'vest'];
    const locationMatches = (
      (upper.includes(garment) && ['bodice_front', 'bodice_back'].includes(element.location))
      || (garment === 'skirt' && ['skirt_front', 'skirt_back'].includes(element.location))
      || (['trousers', 'shorts'].includes(garment)
        && ['trouser_front', 'trouser_back'].includes(element.location))
    );
    if (locationMatches) return {status: 'supported', moduleId: 'base_dart_shaping'};
  }
  if (element.type === 'princess_seam'
      && garment === 'jacket'
      && ['bodice_front', 'bodice_back'].includes(element.location)) {
    return {status: 'supported', moduleId: 'jacket_princess_seam'};
  }
  if (element.type === 'collar'
      && ((garment === 'shirt' && element.variant === 'shirt')
        || (garment === 'jacket' && element.variant === 'notched'))) {
    return {status: 'supported', moduleId: 'bounded_collar'};
  }
  if (element.type === 'pocket'
      && ((garment === 'jacket' && element.variant === 'patch')
        || (['trousers', 'shorts'].includes(garment) && element.variant === 'slash'))) {
    return {status: 'supported', moduleId: 'bounded_pocket'};
  }
  if (element.type === 'vent' && element.variant === 'single'
      && garment === 'jacket' && element.location === 'bodice_back') {
    return {status: 'supported', moduleId: 'jacket_back_vent'};
  }
  return {status: 'planned', moduleId: null};
}

function layerSupport(layer: VisualDesignLayer, spec: GarmentSpec): Support {
  if (layer.role === 'main') return {status: 'supported', moduleId: 'main_fabric_layer'};
  if (layer.role === 'lining' && spec.garment_type === 'jacket') {
    return {status: 'supported', moduleId: 'jacket_full_lining'};
  }
  return {status: 'planned', moduleId: null};
}

function proportionsSupport(
  proportions: VisualProportions,
): {status: 'supported' | 'planned' | 'needs_confirmation'; moduleId: string | null} {
  const values = [
    proportions.waist_position,
    proportions.volume,
    proportions.hem_shape,
    proportions.asymmetry,
  ];
  if (values.includes('unknown')) return {status: 'needs_confirmation', moduleId: null};
  const supported = (
    proportions.waist_position === 'natural'
    && ['fitted', 'regular'].includes(proportions.volume)
    && proportions.hem_shape === 'straight'
    && proportions.asymmetry === 'no'
  );
  return supported
    ? {status: 'supported', moduleId: 'bounded_visual_proportions'}
    : {status: 'planned', moduleId: null};
}

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

function asVisualElement(
  element: GarmentDesignIntent['elements'][number],
): VisualDesignElement {
  return {
    element_id: element.source_element_id,
    type: element.type,
    variant: element.variant,
    description_ru: element.description_ru,
    location: element.location,
    construction: element.construction,
    count: element.count,
    symmetry: element.symmetry,
    confidence: element.confidence,
    evidence_ru: element.evidence_ru,
    requires_confirmation: element.requires_confirmation,
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
  const next: GarmentDesignIntent = {
    ...intent,
    review_status: 'proposed',
    reviewed_at: null,
    elements: intent.elements.map((element) => {
      if (element.included === false) {
        return {...element, support_status: 'excluded' as const, module_id: null};
      }
      if (element.confirmed_by_user !== true) {
        return {...element, included: true, support_status: 'needs_confirmation' as const, module_id: null};
      }
      if (Object.values(element.dimensions_mm ?? {}).some((value) => value !== null)) {
        return {...element, included: true, support_status: 'planned' as const, module_id: null};
      }
      const support = elementSupport(asVisualElement(element), spec);
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
          const support = proportionsSupport(intent.proportions);
          return {...intent.proportions, support_status: support.status, module_id: support.moduleId};
        })()
      : {...intent.proportions, support_status: 'needs_confirmation', module_id: null},
    question_answers: alignedAnswers(intent),
  };
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

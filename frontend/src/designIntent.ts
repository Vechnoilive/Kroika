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

function elementSupport(
  element: VisualDesignElement,
  spec: GarmentSpec,
  analysis: StyleAnalysis,
): Support {
  const garment = spec.garment_type;
  if (element.type === 'closure') {
    const observed = analysis.closure;
    const configured = spec.parameters.closure;
    if (observed
        && observed.type === configured.type
        && observed.location === configured.location) {
      return {status: 'supported', moduleId: 'bounded_closure'};
    }
    return {status: 'planned', moduleId: null};
  }
  if (element.type === 'waistband'
      && ['skirt', 'trousers', 'shorts'].includes(garment)
      && element.variant === 'straight'
      && (garment === 'skirt' || analysis.trousers?.waistband === 'straight')
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
      && ((garment === 'shirt' && element.variant === 'shirt' && analysis.neckline.collar === 'shirt')
        || (garment === 'jacket' && element.variant === 'notched'
          && analysis.neckline.collar === 'notched'))) {
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
  spec: GarmentSpec,
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
    if (element.requires_confirmation) {
      return {
        ...details,
        source_element_id: sourceElementId,
        support_status: 'needs_confirmation' as const,
        module_id: null,
      };
    }
    const support = elementSupport(element, spec, analysis);
    return {
      ...details,
      source_element_id: sourceElementId,
      support_status: support.status,
      module_id: support.moduleId,
    };
  });
  const layers = analysis.design_features.layers.map((layer) => {
    const {layer_id: sourceLayerId, ...details} = layer;
    if (layer.requires_confirmation) {
      return {
        ...details,
        source_layer_id: sourceLayerId,
        support_status: 'needs_confirmation' as const,
        module_id: null,
      };
    }
    const support = layerSupport(layer, spec);
    return {
      ...details,
      source_layer_id: sourceLayerId,
      support_status: support.status,
      module_id: support.moduleId,
    };
  });
  const proportionSupport = proportionsSupport(analysis.design_features.proportions);
  const proportions = {
    ...analysis.design_features.proportions,
    support_status: proportionSupport.status,
    module_id: proportionSupport.moduleId,
  };
  const statuses = [
    ...elements.map((item) => item.support_status),
    ...layers.map((item) => item.support_status),
    proportions.support_status,
  ];
  const status = statuses.includes('needs_confirmation')
    ? 'needs_confirmation'
    : statuses.includes('planned')
      ? 'partial'
      : 'ready';
  return {
    schema_version: '1.0.0',
    source: 'ai',
    status,
    elements,
    layers,
    proportions,
    pending_questions: [...new Set(analysis.targeted_questions)],
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

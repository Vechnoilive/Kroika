import registry from '../../src/kroika_contracts/design_modules.json';
import type {GarmentSpec} from './types';

type Bounds = [number, number | 'skirt_length_minus_20'];
export type Rule = Record<string, unknown[]> & {configured_closure?: boolean};
export interface DesignModule {
  id: string;
  group: string;
  kind: string;
  title_ru: string;
  rules: Rule[];
  dimensions?: {required: Record<string, Bounds>; optional: Record<string, Bounds>};
}

export const DESIGN_MODULES = registry.modules as unknown as DesignModule[];
const DIMENSIONS = ['width', 'length', 'depth', 'spacing'] as const;
type Item = Record<string, unknown>;

export function moduleIds(group: string): Set<string> {
  return new Set(DESIGN_MODULES.filter((module) => module.group === group).map((module) => module.id));
}

function ruleMatches(rule: Rule, item: Item, spec: GarmentSpec): boolean {
  return Object.entries(rule).every(([field, allowed]) => {
    if (field === 'configured_closure') {
      const closure = spec.parameters.closure;
      const locations: Record<string, string[]> = {
        center_back: ['bodice_back'], center_front: ['bodice_front', 'trouser_front'], side: ['waist'],
      };
      return item.variant === (closure.type === 'lacing' ? 'tie' : closure.type)
        && (locations[closure.location] ?? []).includes(String(item.location));
    }
    const value = field === 'garment_type' ? spec.garment_type
      : field === 'sleeve_type' ? spec.parameters.sleeve.type : item[field];
    if (field === 'count' && (typeof value !== 'number' || !Number.isInteger(value))) return false;
    return Array.isArray(allowed) && allowed.includes(value);
  });
}

export function applicableRule(module: DesignModule, spec: GarmentSpec): Rule | undefined {
  return module.rules.find((rule) => (!rule.garment_type || rule.garment_type.includes(spec.garment_type))
    && (!rule.sleeve_type || rule.sleeve_type.includes(spec.parameters.sleeve.type))
    && rule.type?.length && rule.variant?.length && rule.location?.length && rule.construction?.length
    && !rule.configured_closure);
}

const FIELD_NAMES: Record<string, string> = {
  garment_type: 'вид изделия', sleeve_type: 'тип рукава', variant: 'вариант',
  location: 'расположение', construction: 'конструкция', count: 'количество',
  symmetry: 'симметрия', coverage: 'покрытие', opacity: 'прозрачность', drape: 'пластика',
};
const VALUE_NAMES: Record<string, string> = {
  symmetric: 'симметричная', asymmetric: 'асимметричная', single: 'одиночная',
  layered: 'слой', integrated: 'цельнокроеная', applied: 'настрочная',
  separate_piece: 'отдельная деталь', bodice_front: 'перед лифа', bodice_back: 'спинка лифа',
  skirt_front: 'перед юбки', skirt_back: 'спинка юбки', hem: 'низ', waist: 'талия',
  sleeveless: 'без рукавов', soft: 'мягкая', straight: 'прямая', full: 'всё изделие',
  skirt: 'юбка', bodice: 'лиф', opaque: 'непрозрачный', fluid: 'струящаяся', medium: 'средняя',
};
const DIMENSION_NAMES: Record<string, string> = {
  width: 'Ширина', length: 'Длина', depth: 'Глубина', spacing: 'Расстояние',
};

/** Explain the nearest recipe without changing the photographic observations. */
export function moduleDiagnosis(kind: string, item: object, spec: GarmentSpec): {
  label: string; reasons: string[]; module?: DesignModule;
} {
  const source = item as Item;
  if (source.included === false) return {label: 'Исключено вами', reasons: []};
  const candidates = DESIGN_MODULES.filter((module) => module.kind === kind)
    .flatMap((module) => module.rules.filter((rule) => kind === 'element'
      ? rule.type?.includes(source.type) : rule.role?.includes(source.role)).map((rule) => {
      const reasons = Object.entries(rule).flatMap(([field, allowed]) => {
        if (field === 'type' || field === 'role') return [];
        if (field === 'configured_closure') return ruleMatches({configured_closure: true} as Rule, source, spec)
          ? [] : ['Согласуйте застёжку с настройками изделия.'];
        const value = field === 'garment_type' ? spec.garment_type
          : field === 'sleeve_type' ? spec.parameters.sleeve.type : source[field];
        if (Array.isArray(allowed) && allowed.includes(value)) return [];
        return [`${FIELD_NAMES[field] ?? field}: ${(Array.isArray(allowed) ? allowed : []).map((entry) => VALUE_NAMES[String(entry)] ?? String(entry)).join(' / ')}.`];
      });
      return {module, reasons};
    })).sort((a, b) => a.reasons.length - b.reasons.length);
  const supported = matchingModule(kind, item, spec);
  if (supported) return {label: source.confirmed_by_user ? 'Будет учтено' : 'Нужно подтвердить', reasons: [], module: supported};
  const structural = matchingModule(kind, item, spec, false);
  if (structural?.dimensions && kind === 'element') {
    const dimensions = (source.dimensions_mm ?? {}) as Item;
    const reasons = DIMENSIONS.flatMap((field) => {
      const bounds = structural.dimensions!.required[field] ?? structural.dimensions!.optional[field];
      const value = dimensions[field];
      if (value == null) return field in structural.dimensions!.required ? [`${DIMENSION_NAMES[field]}: укажите размер.`] : [];
      if (!bounds) return [`${DIMENSION_NAMES[field]}: оставьте пустым для этой конструкции.`];
      const maximum = bounds[1] === 'skirt_length_minus_20' ? spec.parameters.skirt.length_from_waist_mm - 20 : bounds[1];
      return typeof value === 'number' && Number.isFinite(value) && value >= bounds[0] && value <= maximum
        ? [] : [`${DIMENSION_NAMES[field]}: допустимо ${bounds[0] / 10}–${maximum / 10} см.`];
    });
    return {label: 'Проверьте размеры', reasons, module: structural};
  }
  return candidates.length ? {label: 'Проверьте конструкцию', ...candidates[0]}
    : {label: 'Геометрия ещё не реализована', reasons: ['Выберите готовую конструкцию, если она соответствует фотографии.']};
}

export function matchingModule(
  kind: string, item: object, spec: GarmentSpec, checkDimensions = true,
): DesignModule | undefined {
  const source = item as Item;
  return DESIGN_MODULES.find((module) => {
    if (module.kind !== kind || !module.rules.some((rule) => ruleMatches(rule, source, spec))) return false;
    if (kind === 'proportions' && module.id === 'bounded_visual_proportions') return ['waist_shift_mm', 'waist_level_circumference_mm', 'back_waist_level_arc_mm', 'hem_delta_mm'].every((key) => source[key] == null);
    if (kind === 'proportions' && module.id === 'parametric_visual_proportions_v1') return proportionDimensionsMatch(source, spec, checkDimensions);
    if (kind !== 'element' || !checkDimensions) return true;
    const dimensions = (source.dimensions_mm ?? {}) as Item;
    return DIMENSIONS.every((field) => {
      const required = module.dimensions!.required;
      const bounds = required[field] ?? module.dimensions!.optional[field];
      const value = dimensions[field];
      if (value === null || value === undefined) return !(field in required);
      if (!bounds || typeof value !== 'number' || !Number.isFinite(value)) return false;
      const maximum = bounds[1] === 'skirt_length_minus_20'
        ? spec.parameters.skirt.length_from_waist_mm - 20 : bounds[1];
      return bounds[0] <= value && value <= maximum;
    });
  });
}

function proportionDimensionsMatch(item: Item, spec: GarmentSpec, checkDimensions = true): boolean {
  const bounded = (key: string, min: number, max: number) => typeof item[key] === 'number' && Number.isFinite(item[key]) && min <= (item[key] as number) && (item[key] as number) <= max;
  const waistKeys = ['waist_shift_mm', 'waist_level_circumference_mm', 'back_waist_level_arc_mm'];
  if (item.waist_position !== 'natural') {
    if (!['dress', 'sundress'].includes(spec.garment_type) || (checkDimensions && (!bounded(waistKeys[0], 10, 100) || !bounded(waistKeys[1], 400, 1800) || !bounded(waistKeys[2], 100, 1000) || (item[waistKeys[2]] as number) >= (item[waistKeys[1]] as number)))) return false;
  } else if (checkDimensions && waistKeys.some((key) => item[key] != null)) return false;
  if (item.hem_shape !== 'straight') {
    if (!['dress', 'sundress', 'skirt'].includes(spec.garment_type) || (checkDimensions && !bounded('hem_delta_mm', 20, 250)) || (item.hem_shape === 'asymmetric' && item.asymmetry !== 'yes')) return false;
  } else if (checkDimensions && item.hem_delta_mm != null) return false;
  return true;
}

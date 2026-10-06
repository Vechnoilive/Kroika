import registry from '../../src/kroika_contracts/design_modules.json';
import type {GarmentSpec} from './types';

type Bounds = [number, number | 'skirt_length_minus_20'];
type Rule = Record<string, unknown[]> & {configured_closure?: boolean};
interface DesignModule {
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
      return item.variant === closure.type
        && (locations[closure.location] ?? []).includes(String(item.location));
    }
    const value = field === 'garment_type' ? spec.garment_type
      : field === 'sleeve_type' ? spec.parameters.sleeve.type : item[field];
    if (field === 'count' && (typeof value !== 'number' || !Number.isInteger(value))) return false;
    return Array.isArray(allowed) && allowed.includes(value);
  });
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

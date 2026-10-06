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

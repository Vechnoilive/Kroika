import type {ProjectDocument} from './types';

type JsonObject = Record<string, any>;

const STAGE18_MODELING_MODULES = new Set([
  'adjustable_straight_waistband_v1',
  'center_pleat_v1',
  'waist_gather_allowance_v1',
  'circular_hem_flounce_v1',
  'straight_belt_v1',
]);

const STAGE19_ELEMENT_MODULES = new Set([
  'sleeve_cuff_band_v1',
  'stand_collar_v1',
  'paired_patch_pocket_v1',
]);

const STAGE19_LAYER_MODULES = new Set([
  'skirt_full_lining_v1',
  'skirt_overlay_layer_v1',
]);

function coverageContract(garment: JsonObject): JsonObject | null {
  const intent = garment.design_intent;
  if (!intent || intent.coverage_schema_version !== '1.0.0') return null;
  const modules = new Set<string>();
  for (const group of ['elements', 'layers']) {
    for (const item of intent[group] ?? []) {
      if (item.included !== false
          && item.support_status === 'supported'
          && typeof item.module_id === 'string') modules.add(item.module_id);
    }
  }
  if (intent.proportions?.support_status === 'supported'
      && typeof intent.proportions.module_id === 'string') {
    modules.add(intent.proportions.module_id);
  }
  return {schema_version: '1.0.0', required_module_ids: [...modules].sort()};
}

function normalized(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalized);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        // Python's json.dumps(sort_keys=True) compares these ASCII contract
        // keys by code point. Avoid locale-dependent browser collation here.
        .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
        .map(([key, item]) => [key, normalized(item)]),
    );
  }
  return value;
}

export function stableJson(value: unknown): string {
  return JSON.stringify(normalized(value));
}

export function canonicalGenerationPayload(request: JsonObject): JsonObject {
  const measurements = request.body_measurements;
  const garment = request.garment_spec;
  const fit = request.fit_settings;
  const fabric = request.fabric_properties;
  const method = request.pattern_method;
  const garmentSpec: JsonObject = {
    schema_version: garment.schema_version,
    garment_type: garment.garment_type,
    parameters: garment.parameters,
  };
  const modelingElements = (garment.design_intent?.elements ?? [])
    .filter((element: JsonObject) => element.included !== false
      && element.support_status === 'supported'
      && STAGE18_MODELING_MODULES.has(element.module_id))
    .map((element: JsonObject) => ({
      source_element_id: element.source_element_id,
      type: element.type,
      variant: element.variant,
      location: element.location,
      construction: element.construction,
      count: element.count,
      dimensions_mm: element.dimensions_mm ?? null,
      module_id: element.module_id,
    }))
    .sort((left: JsonObject, right: JsonObject) => {
      const leftKey = `${left.module_id}\u0000${left.source_element_id}`;
      const rightKey = `${right.module_id}\u0000${right.source_element_id}`;
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    });
  if (modelingElements.length > 0) garmentSpec.modeling_elements = modelingElements;
  const compositeElements = (garment.design_intent?.elements ?? [])
    .filter((element: JsonObject) => element.included !== false
      && element.support_status === 'supported'
      && STAGE19_ELEMENT_MODULES.has(element.module_id))
    .map((element: JsonObject) => ({
      source_element_id: element.source_element_id,
      type: element.type,
      variant: element.variant,
      location: element.location,
      construction: element.construction,
      count: element.count,
      dimensions_mm: element.dimensions_mm ?? null,
      module_id: element.module_id,
    }))
    .sort((left: JsonObject, right: JsonObject) => {
      const leftKey = `${left.module_id}\u0000${left.source_element_id}`;
      const rightKey = `${right.module_id}\u0000${right.source_element_id}`;
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    });
  const compositeLayers = (garment.design_intent?.layers ?? [])
    .filter((layer: JsonObject) => layer.included !== false
      && layer.support_status === 'supported'
      && STAGE19_LAYER_MODULES.has(layer.module_id))
    .map((layer: JsonObject) => ({
      source_layer_id: layer.source_layer_id,
      role: layer.role,
      coverage: layer.coverage,
      opacity: layer.opacity,
      drape: layer.drape,
      module_id: layer.module_id,
    }))
    .sort((left: JsonObject, right: JsonObject) => {
      const leftKey = `${left.module_id}\u0000${left.source_layer_id}`;
      const rightKey = `${right.module_id}\u0000${right.source_layer_id}`;
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    });
  if (compositeElements.length > 0) garmentSpec.composite_elements = compositeElements;
  if (compositeLayers.length > 0) garmentSpec.composite_layers = compositeLayers;
  const coverage = coverageContract(garment);
  if (coverage) garmentSpec.coverage_contract = coverage;
  const hasComposites = compositeElements.length > 0 || compositeLayers.length > 0;
  return {
    hash_contract_version: coverage
      ? '1.3.0'
      : hasComposites
      ? '1.2.0'
      : modelingElements.length > 0 ? '1.1.0' : '1.0.0',
    pattern_method: {id: method.id, version: method.version},
    body_measurements: {
      schema_version: measurements.schema_version,
      normalized_unit: measurements.normalized_unit,
      values: Object.fromEntries(
        Object.entries(measurements.values as Record<string, {value: number}>)
          .map(([key, item]) => [key, item.value]),
      ),
      angles_deg: measurements.angles_deg ?? {},
    },
    garment_spec: garmentSpec,
    fit_settings: {
      schema_version: fit.schema_version,
      wearing_ease_mm: fit.wearing_ease_mm,
      design_ease_mm: fit.design_ease_mm,
      distribution: fit.distribution,
      seam_allowance_mode: fit.seam_allowance_mode,
      seam_allowances_mm: fit.seam_allowances_mm,
    },
    fabric_properties: {
      schema_version: fabric.schema_version,
      intended_use: fabric.intended_use,
      structure: fabric.structure,
      stretch_percent: fabric.stretch_percent,
      weight: fabric.weight,
      drape: fabric.drape,
      stability: fabric.stability,
      directional_nap: fabric.directional_nap,
      prewashed: fabric.prewashed,
    },
  };
}

export async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

export async function buildEngineRequest(project: ProjectDocument): Promise<JsonObject> {
  const source = project as ProjectDocument & JsonObject;
  const request: JsonObject = {
    schema_version: '1.0.0',
    request_id: crypto.randomUUID(),
    project_id: project.project_id,
    input_hash: '0'.repeat(64),
    pattern_method: source.pattern_method,
    body_measurements: project.body_measurements,
    garment_spec: project.garment_spec.design_intent
      ? {
          ...project.garment_spec,
          design_intent: {
            ...project.garment_spec.design_intent,
            coverage_schema_version: '1.0.0',
          },
        }
      : project.garment_spec,
    fit_settings: source.fit_settings,
    fabric_properties: source.fabric_properties,
  };
  request.input_hash = await sha256(stableJson(canonicalGenerationPayload(request)));
  return request;
}

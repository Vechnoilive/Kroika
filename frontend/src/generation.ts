import type {ProjectDocument} from './types';

type JsonObject = Record<string, any>;

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
  return {
    hash_contract_version: '1.0.0',
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
    garment_spec: {
      schema_version: garment.schema_version,
      garment_type: garment.garment_type,
      parameters: garment.parameters,
    },
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
    garment_spec: project.garment_spec,
    fit_settings: source.fit_settings,
    fabric_properties: source.fabric_properties,
  };
  request.input_hash = await sha256(stableJson(canonicalGenerationPayload(request)));
  return request;
}

export type ProjectStatus =
  | 'draft'
  | 'inputs_confirmed'
  | 'generated'
  | 'validation_failed'
  | 'ready_for_production_export';

export interface ProjectSummary {
  project_id: string;
  name: string;
  revision: number;
  status: ProjectStatus;
  updated_at: string;
}

export interface ProjectDocument extends ProjectSummary {
  schema_version: '1.0.0';
  locale: 'ru-RU';
  body_measurements: BodyMeasurements;
  garment_spec: {
    garment_type: 'dress' | 'sundress';
    parameters: {
      sleeve: {type: 'sleeveless' | 'short' | 'long'; length_mm?: number | null};
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export type MeasurementSource = 'user' | 'preset' | 'derived';

export interface MeasurementValue {
  value: number;
  unit: 'mm';
  source: MeasurementSource;
  formula_id?: string;
  original_input?: {value: number; unit: 'cm' | 'mm'};
}

export interface BodyMeasurements {
  schema_version: '1.0.0';
  profile_id: string;
  name: string;
  status: 'draft' | 'ready';
  normalized_unit: 'mm';
  values: Record<string, MeasurementValue>;
  angles_deg?: Record<string, number>;
  angle_provenance?: Record<string, {source: MeasurementSource; formula_id?: string}>;
}

export interface MeasurementDefinition {
  id: string;
  label_ru: string;
  group: string;
  kind: 'linear' | 'angle';
  unit: 'mm' | 'deg';
  minimum: number;
  maximum: number;
  instruction_ru: string;
  illustration: string;
  applicable_to: string[];
  required_for: string[];
  sleeve_only: boolean;
  required: boolean;
}

export interface MeasurementCatalog {
  schema_version: '1.0.0';
  catalog_version: string;
  garment_type: string;
  sleeve_type: string;
  normalized_unit: 'mm';
  display_units: ['cm', 'mm'];
  source_options: MeasurementSource[];
  measurements: MeasurementDefinition[];
}

export interface MeasurementIssue {
  code: string;
  severity: 'blocking_error' | 'warning' | 'info';
  message_ru: string;
  json_pointer: string;
}

export interface MeasurementValidation {
  status: 'ready' | 'incomplete' | 'invalid';
  required_count: number;
  completed_count: number;
  issues: MeasurementIssue[];
}

export interface MeasurementProfileSummary {
  profile_id: string;
  name: string;
  status: 'draft' | 'ready';
  revision: number;
  updated_at: string;
}

export interface MeasurementProfileRecord {
  revision: number;
  updated_at: string;
  profile: BodyMeasurements;
}

export interface ProjectList {
  items: ProjectSummary[];
}

export interface Readiness {
  status: 'ok';
  service: string;
  version: string;
  database: 'ok';
  ai_provider: string;
  pattern_engine: string;
}

export interface StyleAnalysis {
  status: 'ok' | 'needs_confirmation' | 'insufficient_input';
  garment_category: string;
  silhouette: {fit: string; confidence: number};
  neckline: {front: string; confidence: number};
  sleeves: {present: boolean; length: string; confidence: number};
  lower_part: {type: string; length_category: string; confidence: number};
  uncertainties: string[];
  targeted_questions: string[];
}

export interface ApiErrorBody {
  code?: string;
  message_ru?: string;
  request_id?: string;
  issues?: MeasurementIssue[];
}

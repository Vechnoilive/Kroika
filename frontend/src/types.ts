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
  pattern_method: Record<string, unknown>;
  privacy: {
    storage: 'local';
    image_retention_days: number;
    allow_external_ai: boolean;
    consent_recorded_at: string | null;
  };
  image_refs: string[];
  style_analysis_id: string | null;
  style_analysis_provider?: VisionProviderId | null;
  style_analysis?: StyleAnalysis | null;
  fit_settings: FitSettings;
  fabric_properties: FabricProperties;
  latest_generation: PatternEngineResult | null;
  generation_history: Array<{generation_id: string; created_at: string; status: string}>;
  garment_spec: GarmentSpec;
  [key: string]: unknown;
}

export interface GarmentSpec {
  schema_version: '1.0.0';
  garment_id: string;
  selection_status: 'proposed' | 'confirmed';
  garment_type: 'dress' | 'sundress';
  parameters: {
    symmetry: 'symmetric';
    bodice_fit: 'fitted' | 'semi_fitted';
    shaping: 'darts';
    neckline: {type: 'round' | 'v' | 'square'; front_depth_mm: number; back_depth_mm: number};
    sleeve: {type: 'sleeveless' | 'short' | 'long'; length_mm: number | null};
    skirt: {type: 'straight' | 'a_line'; length_from_waist_mm: number; hem_expansion_each_side_mm: number};
    closure: {type: 'zipper'; location: 'center_back'; length_mm: number};
    finishing: {neckline_facing: boolean; armhole_facing: boolean};
  };
  unsupported_features: string[];
  confirmed_at: string | null;
}

export interface FitSettings {
  schema_version: '1.0.0';
  settings_id: string;
  status: 'draft' | 'confirmed';
  preset: {id: string; version: string};
  wearing_ease_mm: Record<'bust' | 'waist' | 'hips' | 'upper_arm', number>;
  design_ease_mm: Record<'bust' | 'waist' | 'hips' | 'upper_arm', number>;
  distribution: {front_share: number; back_share: number};
  seam_allowance_mode: 'none' | 'by_edge';
  seam_allowances_mm: Record<'normal' | 'neckline' | 'armhole' | 'zipper' | 'hem' | 'sleeve_hem' | 'fold', number>;
  confirmed_at: string | null;
}

export interface FabricProperties {
  schema_version: '1.0.0';
  fabric_id: string;
  status: 'draft' | 'confirmed';
  name: string;
  intended_use: 'toile' | 'final';
  structure: 'woven' | 'knit' | 'unknown';
  stretch_percent: {warp: number; weft: number};
  weight: 'light' | 'medium' | 'heavy' | 'unknown';
  drape: 'crisp' | 'medium' | 'fluid' | 'unknown';
  stability: 'stable' | 'moderate' | 'unstable' | 'unknown';
  directional_nap: boolean;
  prewashed: boolean;
  confirmed_at: string | null;
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
  schema_version?: '1.0.0';
  status: 'ok' | 'needs_confirmation' | 'insufficient_input';
  garment_category: string;
  silhouette: {fit: string; confidence: number};
  neckline: {front: string; confidence: number};
  sleeves: {present: boolean; length: string; confidence: number};
  lower_part: {type: string; length_category: string; confidence: number};
  uncertainties: string[];
  targeted_questions: string[];
  unsupported_features?: string[];
  [key: string]: unknown;
}

export type VisionProviderId = 'mock' | 'qwen' | 'gemini';

export interface VisionProviderStatus {
  provider_id: VisionProviderId;
  name: string;
  model: string;
  configured: boolean;
  is_default: boolean;
  enabled_for_users: boolean;
  sends_images_external: boolean;
  message_ru: string;
}

export interface VisionProviderList {
  default_provider: VisionProviderId;
  items: VisionProviderStatus[];
}

export interface ImageUploadResult {
  image_ref: string;
  media_type: 'image/jpeg' | 'image/png' | 'image/webp';
  size_bytes: number;
}

export interface ProjectHistoryEntry {
  revision: number;
  status: ProjectStatus;
  updated_at: string;
  change_summary: string;
  is_current: boolean;
}

export type PatternLayer =
  | 'cutting' | 'seam' | 'internal' | 'fold'
  | 'grain' | 'notches' | 'labels' | 'dimensions';

export interface ApiErrorBody {
  code?: string;
  message_ru?: string;
  request_id?: string;
  issues?: MeasurementIssue[];
}


export interface PatternPieceSummary {
  id: string;
  name_ru: string;
  cut_quantity: number;
  cut_on_fold: boolean;
}

export interface PatternData {
  unit: 'mm';
  pieces: PatternPieceSummary[];
  seam_pairs: Array<{id: string}>;
  print_layout?: {
    page_format: 'A4';
    overlap_mm: number;
    scale: 1;
    control_square_mm: 50;
  };
}

export interface ValidationReport {
  status: 'passed' | 'warnings' | 'failed';
  issues: MeasurementIssue[];
  diagnostic_export_allowed: boolean;
  production_export_allowed: boolean;
}

export interface PatternEngineResult {
  generation_id: string;
  engine_version: string;
  status: 'succeeded' | 'rejected';
  pattern: PatternData | null;
  validation_report: ValidationReport;
}

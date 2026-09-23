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
  garment_type: GarmentType;
  parameters: {
    symmetry: 'symmetric';
    bodice_fit: 'fitted' | 'semi_fitted';
    shaping: 'darts' | 'princess_seams';
    neckline: {type: 'round' | 'v' | 'square'; front_depth_mm: number; back_depth_mm: number};
    sleeve: {type: 'sleeveless' | 'short' | 'long'; length_mm: number | null};
    skirt: {type: 'straight' | 'a_line'; length_from_waist_mm: number; hem_expansion_each_side_mm: number};
    upper?: {length_below_waist_mm: number};
    jacket?: {
      variant: 'light_single_breasted';
      front_extension_mm: number;
      lapel_width_mm: number;
      roll_line_from_waist_mm: number;
      collar_stand_mm: number;
      collar_fall_mm: number;
      underlayer_allowance_mm: number;
      vent_length_mm: number;
      pocket_width_mm: number;
      pocket_depth_mm: number;
      button_count: 2;
      pocket_type: 'patch';
      sleeve_construction: 'one_piece';
      lining: 'full';
    };
    trousers?: {
      variant: 'straight_trousers' | 'tailored_shorts';
      waist_position: 'natural';
      length_mm: number;
      leg_shape: 'straight';
      rise_ease_mm: number;
      waistband_width_mm: number;
      fly_length_mm: number;
      pocket_opening_mm: number;
      pocket_type: 'slash';
      pleat_count: 0;
    };
    closure: {
      type: 'zipper' | 'buttons' | 'none';
      location: 'center_back' | 'center_front' | 'side' | 'none';
      length_mm: number | null;
    };
    finishing: {
      neckline_facing: boolean;
      armhole_facing: boolean;
      waistband?: boolean;
      front_placket?: boolean;
      collar?: boolean;
      front_facing?: boolean;
      lining?: boolean;
      pockets?: boolean;
      vent?: boolean;
      fly_front?: boolean;
    };
  };
  design_intent?: GarmentDesignIntent;
  unsupported_features: string[];
  confirmed_at: string | null;
}

export type DesignElementType =
  | 'waistband' | 'belt' | 'sash' | 'pleat' | 'tuck' | 'gather' | 'ruffle'
  | 'flounce' | 'peplum' | 'yoke' | 'panel' | 'overlay' | 'drape' | 'pocket'
  | 'closure' | 'slit' | 'vent' | 'hood' | 'collar' | 'cuff' | 'strap' | 'dart'
  | 'princess_seam' | 'decorative_seam' | 'other';

export type DesignLocation =
  | 'bodice_front' | 'bodice_back' | 'neckline' | 'shoulder' | 'waist'
  | 'skirt_front' | 'skirt_back' | 'trouser_front' | 'trouser_back' | 'sleeve'
  | 'hem' | 'full_garment' | 'unknown';

export interface VisualDesignElement {
  element_id: string;
  type: DesignElementType;
  variant: 'standard' | 'straight' | 'shaped' | 'elastic' | 'tie' | 'knife' | 'box'
    | 'inverted' | 'accordion' | 'soft' | 'circular' | 'gathered' | 'patch' | 'slash'
    | 'welt' | 'zipper' | 'buttons' | 'hooks' | 'concealed' | 'single' | 'double'
    | 'shirt' | 'notched' | 'shawl' | 'stand' | 'other' | 'unknown';
  description_ru: string;
  location: DesignLocation;
  construction: 'integrated' | 'separate_piece' | 'applied' | 'layered' | 'unknown';
  count: number | null;
  symmetry: 'symmetric' | 'asymmetric' | 'single' | 'unknown';
  confidence: number;
  evidence_ru: string;
  requires_confirmation: boolean;
}

export interface VisualDesignLayer {
  layer_id: string;
  role: 'main' | 'lining' | 'interfacing' | 'overlay';
  coverage: 'full' | 'bodice' | 'skirt' | 'sleeves' | 'detail' | 'unknown';
  material_hint_ru: string;
  opacity: 'opaque' | 'semi_transparent' | 'transparent' | 'unknown';
  drape: 'crisp' | 'medium' | 'fluid' | 'unknown';
  confidence: number;
  requires_confirmation: boolean;
}

export interface VisualProportions {
  waist_position: 'low' | 'natural' | 'high' | 'unknown';
  volume: 'fitted' | 'regular' | 'relaxed' | 'voluminous' | 'unknown';
  hem_shape: 'straight' | 'curved' | 'asymmetric' | 'tiered' | 'unknown';
  asymmetry: 'yes' | 'no' | 'unknown';
  confidence: number;
}

export interface GarmentDesignIntent {
  schema_version: '1.0.0';
  coverage_schema_version?: '1.0.0';
  source: 'ai' | 'manual';
  status: 'ready' | 'partial' | 'needs_confirmation';
  review_status?: 'proposed' | 'confirmed';
  reviewed_at?: string | null;
  elements: Array<Omit<VisualDesignElement, 'element_id'> & {
    source_element_id: string;
    included?: boolean;
    confirmed_by_user?: boolean;
    dimensions_mm?: {
      width: number | null;
      length: number | null;
      depth: number | null;
      spacing: number | null;
    };
    support_status: 'supported' | 'planned' | 'needs_confirmation' | 'excluded';
    module_id: string | null;
  }>;
  layers: Array<Omit<VisualDesignLayer, 'layer_id'> & {
    source_layer_id: string;
    included?: boolean;
    confirmed_by_user?: boolean;
    support_status: 'supported' | 'planned' | 'needs_confirmation' | 'excluded';
    module_id: string | null;
  }>;
  proportions: VisualProportions & {
    confirmed_by_user?: boolean;
    support_status: 'supported' | 'planned' | 'needs_confirmation' | 'excluded';
    module_id: string | null;
  };
  pending_questions: string[];
  question_answers?: Array<{question: string; answer_ru: string}>;
}

export type GarmentType =
  | 'dress' | 'sundress' | 'skirt' | 'top' | 'blouse' | 'shirt' | 'vest' | 'jacket'
  | 'trousers' | 'shorts';

export interface GarmentAcceptanceStatus {
  garment_type: GarmentType;
  name_ru: string;
  scope_ru: string;
  formula_status: 'implemented';
  reference_status: 'automated_passed';
  invariant_status: 'automated_passed';
  paper_status: 'pending' | 'passed';
  expert_status: 'pending' | 'passed';
  toile_status: 'pending' | 'passed';
  production_allowed: boolean;
}

export interface GarmentCatalogue {
  items: GarmentAcceptanceStatus[];
}

export type PhysicalValidationGate = 'paper' | 'expert' | 'toile';
export type PhysicalValidationOutcome = 'passed' | 'failed';

export interface PhysicalValidationCreate {
  gate: PhysicalValidationGate;
  outcome?: PhysicalValidationOutcome;
  reviewer_name: string;
  notes: string;
  printer_name?: string;
  square_width_mm?: number;
  square_height_mm?: number;
  control_line_mm?: number;
  figure_label?: string;
}

export interface PhysicalValidationRecord {
  record_id: string;
  project_id: string;
  generation_id: string;
  gate: PhysicalValidationGate;
  outcome: PhysicalValidationOutcome;
  reviewer_name: string;
  notes: string;
  printer_name: string | null;
  square_width_mm: number | null;
  square_height_mm: number | null;
  control_line_mm: number | null;
  figure_label: string | null;
  created_at: string;
}

export interface PhysicalValidationSummary {
  project_id: string;
  generation_id: string;
  gates: Array<{
    gate: PhysicalValidationGate;
    status: 'pending' | PhysicalValidationOutcome;
    latest_record_id: string | null;
    checked_at: string | null;
    passed_observations: number;
    required_observations: number;
  }>;
  production_allowed: boolean;
  policy: string;
  records: PhysicalValidationRecord[];
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
  neckline: {front: string; collar?: string; confidence: number};
  sleeves: {present: boolean; length: string; confidence: number};
  lower_part: {type: string; length_category: string; confidence: number};
  trousers?: {waistband?: string; [key: string]: unknown};
  closure?: {type: string; location: string; confidence: number};
  design_features?: {
    elements: VisualDesignElement[];
    layers: VisualDesignLayer[];
    proportions: VisualProportions;
  };
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

export interface DesignCoverageEvidence {
  piece_ids: string[];
  seam_pair_ids: string[];
  path_ids: string[];
  segment_ids: string[];
  operation_ids: string[];
}

export interface DesignCoverageCatalogue {
  schema_version: '1.0.0';
  modules: Array<{
    module_id: string;
    source_ids: string[];
    evidence: DesignCoverageEvidence;
  }>;
  physical_validation_required: true;
}

export interface PatternData {
  unit: 'mm';
  pieces: PatternPieceSummary[];
  seam_pairs: Array<{id: string}>;
  design_coverage?: DesignCoverageCatalogue;
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

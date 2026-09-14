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
  [key: string]: unknown;
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
}

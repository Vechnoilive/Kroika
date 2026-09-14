import type {
  ApiErrorBody,
  BodyMeasurements,
  MeasurementCatalog,
  MeasurementProfileRecord,
  MeasurementProfileSummary,
  MeasurementValidation,
  ProjectDocument,
  ProjectList,
  Readiness,
  StyleAnalysis,
} from './types';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly requestId?: string,
    public readonly issues: ApiErrorBody['issues'] = [],
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {'Content-Type': 'application/json', ...init?.headers},
    });
  } catch {
    throw new ApiError(
      'Не удалось связаться с приложением. Проверьте, что оно запущено.',
      0,
      'NETWORK_ERROR',
    );
  }

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // A proxy may return non-JSON. Do not show its technical body to the user.
    }
    throw new ApiError(
      body.message_ru ?? 'Не удалось выполнить действие. Попробуйте ещё раз.',
      response.status,
      body.code ?? 'UNKNOWN_ERROR',
      body.request_id,
      body.issues ?? [],
    );
  }
  return (await response.json()) as T;
}

export const api = {
  readiness: () => request<Readiness>('/health/ready'),
  listProjects: () => request<ProjectList>('/api/v1/projects'),
  getProject: (projectId: string) =>
    request<ProjectDocument>(`/api/v1/projects/${encodeURIComponent(projectId)}`),
  createProject: (project: ProjectDocument) =>
    request<ProjectDocument>('/api/v1/projects', {
      method: 'POST',
      body: JSON.stringify(project),
    }),
  replaceProject: (project: ProjectDocument) =>
    request<ProjectDocument>(`/api/v1/projects/${encodeURIComponent(project.project_id)}`, {
      method: 'PUT',
      headers: {'If-Match': String(project.revision)},
      body: JSON.stringify(project),
    }),
  measurementCatalog: (garmentType: string, sleeveType: string) =>
    request<MeasurementCatalog>(
      `/api/v1/measurements/catalog?garment_type=${encodeURIComponent(garmentType)}&sleeve_type=${encodeURIComponent(sleeveType)}`,
    ),
  validateMeasurements: (profile: BodyMeasurements, garmentType: string, sleeveType: string) =>
    request<MeasurementValidation>(
      `/api/v1/measurements/validate?garment_type=${encodeURIComponent(garmentType)}&sleeve_type=${encodeURIComponent(sleeveType)}`,
      {method: 'POST', body: JSON.stringify(profile)},
    ),
  listMeasurementProfiles: () =>
    request<{items: MeasurementProfileSummary[]}>('/api/v1/measurement-profiles'),
  getMeasurementProfile: (profileId: string) =>
    request<MeasurementProfileRecord>(
      `/api/v1/measurement-profiles/${encodeURIComponent(profileId)}`,
    ),
  createMeasurementProfile: (profile: BodyMeasurements) =>
    request<MeasurementProfileRecord>('/api/v1/measurement-profiles', {
      method: 'POST', body: JSON.stringify(profile),
    }),
  replaceMeasurementProfile: (profile: BodyMeasurements, revision: number) =>
    request<MeasurementProfileRecord>(
      `/api/v1/measurement-profiles/${encodeURIComponent(profile.profile_id)}`,
      {method: 'PUT', headers: {'If-Match': String(revision)}, body: JSON.stringify(profile)},
    ),
  analyzeDemo: (projectId: string) =>
    request<StyleAnalysis>('/api/v1/garments/analyze-image', {
      method: 'POST',
      body: JSON.stringify({
        schema_version: '1.0.0',
        request_id: crypto.randomUUID(),
        project_id: projectId,
        locale: 'ru-RU',
        image_refs: ['img_demo_front_12345678'],
        supported_garment_categories: ['dress', 'sundress'],
        supported_features: {
          neckline: ['round', 'v', 'square'],
          sleeve: ['sleeveless', 'short', 'long'],
          skirt: ['straight', 'a_line'],
        },
        image_transmission_confirmed: true,
      }),
    }),
};

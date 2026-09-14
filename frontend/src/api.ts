import type {
  ApiErrorBody,
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

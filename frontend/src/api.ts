import type {
  ApiErrorBody,
  BodyMeasurements,
  GarmentCatalogue,
  MeasurementCatalog,
  MeasurementProfileRecord,
  MeasurementProfileSummary,
  MeasurementValidation,
  ProjectDocument,
  ProjectList,
  PatternEngineResult,
  PatternLayer,
  ProjectHistoryEntry,
  Readiness,
  StyleAnalysis,
  VisionProviderId,
  VisionProviderList,
  ImageUploadResult,
} from './types';
import {buildEngineRequest} from './generation';

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

async function requestBlob(path: string, init?: RequestInit): Promise<{blob: Blob; filename: string}> {
  let response: Response;
  try {
    response = await fetch(path, init);
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
      body.message_ru ?? 'Не удалось подготовить файл. Попробуйте ещё раз.',
      response.status,
      body.code ?? 'UNKNOWN_ERROR',
      body.request_id,
      body.issues ?? [],
    );
  }
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return {blob: await response.blob(), filename: match?.[1] ?? 'kroika-pattern-a4.pdf'};
}

function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new ApiError(
      'Не удалось прочитать изображение. Выберите файл ещё раз.', 0, 'FILE_READ_ERROR',
    ));
    reader.onload = () => {
      const result = String(reader.result ?? '');
      const marker = result.indexOf(',');
      if (marker < 0) reject(new ApiError(
        'Не удалось прочитать изображение. Выберите файл ещё раз.', 0, 'FILE_READ_ERROR',
      ));
      else resolve(result.slice(marker + 1));
    };
    reader.readAsDataURL(file);
  });
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
  projectHistory: (projectId: string) =>
    request<{items: ProjectHistoryEntry[]}>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/history`,
    ),
  restoreProjectRevision: (project: ProjectDocument, revision: number) =>
    request<ProjectDocument>(
      `/api/v1/projects/${encodeURIComponent(project.project_id)}/history/${revision}/restore`,
      {method: 'POST', headers: {'If-Match': String(project.revision)}},
    ),
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
  generatePattern: async (project: ProjectDocument) =>
    request<PatternEngineResult>('/api/v1/patterns/generate', {
      method: 'POST',
      body: JSON.stringify(await buildEngineRequest(project)),
    }),
  patternPreviewUrl: (generationId: string, layers?: PatternLayer[]) => {
    const path = `/api/v1/patterns/${encodeURIComponent(generationId)}/preview.svg`;
    return layers ? `${path}?layers=${encodeURIComponent(layers.join(','))}` : path;
  },
  printSvgUrl: (generationId: string) =>
    `/api/v1/patterns/${encodeURIComponent(generationId)}/export/print.svg`,
  projectJsonUrl: (generationId: string) =>
    `/api/v1/patterns/${encodeURIComponent(generationId)}/export/project-json`,
  downloadA4Pdf: (generationId: string) =>
    requestBlob(`/api/v1/patterns/${encodeURIComponent(generationId)}/export/a4-pdf`, {
      method: 'POST',
    }),
  visionProviders: () => request<VisionProviderList>('/api/v1/ai/providers'),
  garmentCatalogue: () => request<GarmentCatalogue>('/api/v1/garments/catalog'),
  uploadImage: async (file: File) => request<ImageUploadResult>('/api/v1/images', {
    method: 'POST',
    body: JSON.stringify({
      file_name: file.name,
      media_type: file.type,
      data_base64: await fileBase64(file),
    }),
  }),
  analyzeImages: (
    projectId: string,
    imageRefs: string[],
    provider: VisionProviderId,
  ) =>
    request<StyleAnalysis>(`/api/v1/garments/analyze-image?provider=${provider}`, {
      method: 'POST',
      body: JSON.stringify({
        schema_version: '1.0.0',
        request_id: crypto.randomUUID(),
        project_id: projectId,
        locale: 'ru-RU',
        image_refs: imageRefs,
        supported_garment_categories: [
          'dress', 'sundress', 'skirt', 'top', 'blouse', 'shirt', 'vest', 'jacket',
          'trousers', 'shorts',
        ],
        supported_features: {
          neckline: ['round', 'v', 'square'],
          sleeve: ['sleeveless', 'short', 'long'],
          skirt: ['straight', 'a_line'],
          trousers: ['natural_waist', 'straight_leg', 'slash_pocket', 'front_fly'],
          design_elements: [
            'waistband', 'belt', 'sash', 'pleat', 'tuck', 'gather', 'ruffle',
            'flounce', 'peplum', 'yoke', 'panel', 'overlay', 'drape', 'pocket',
            'closure', 'slit', 'vent', 'hood', 'collar', 'cuff', 'strap', 'dart',
            'princess_seam', 'decorative_seam', 'other',
          ],
          layers: ['main', 'lining', 'interfacing', 'overlay'],
        },
        image_transmission_confirmed: true,
      }),
    }),
  analyzeDemo: (projectId: string) => api.analyzeImages(
    projectId, ['img_demo_front_12345678'], 'mock',
  ),
};

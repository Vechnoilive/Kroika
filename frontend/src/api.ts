import type {
  ApiErrorBody,
  BodyMeasurements,
  GarmentCatalogue,
  GenerationComparisonResult,
  GenerationSummary,
  MeasurementCatalog,
  MeasurementProfileRecord,
  MeasurementProfileSummary,
  MeasurementValidation,
  ProjectDocument,
  ProjectList,
  PatternEngineResult,
  PatternLayer,
  PhysicalValidationCreate,
  PhysicalValidationSummary,
  PrintPlan,
  ProjectHistoryEntry,
  Readiness,
  StyleAnalysis,
  VisionProviderId,
  VisionProviderList,
  VisionProviderCheck,
  ImageViewRole,
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

function isAbortError(caught: unknown): boolean {
  return typeof caught === 'object'
    && caught !== null
    && 'name' in caught
    && caught.name === 'AbortError';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {'Content-Type': 'application/json', ...init?.headers},
    });
  } catch (caught) {
    if (isAbortError(caught)) {
      throw new ApiError('Запрос отменён. Загруженные изображения сохранены для повтора.', 0, 'REQUEST_CANCELLED');
    }
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
  if (response.status === 204) return undefined as T;
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
  deleteProject: (projectId: string) =>
    request<void>(`/api/v1/projects/${encodeURIComponent(projectId)}`, {method: 'DELETE'}),
  projectHistory: (projectId: string) =>
    request<{items: ProjectHistoryEntry[]}>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/history`,
    ),
  restoreProjectRevision: (project: ProjectDocument, revision: number) =>
    request<ProjectDocument>(
      `/api/v1/projects/${encodeURIComponent(project.project_id)}/history/${revision}/restore`,
      {method: 'POST', headers: {'If-Match': String(project.revision)}},
    ),
  listGenerations: (projectId: string) =>
    request<{project_id: string; items: GenerationSummary[]}>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/generations`,
    ),
  compareGenerations: (projectId: string, baseGenerationId: string, targetGenerationId: string) =>
    request<GenerationComparisonResult>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/generations/compare?base_generation_id=${encodeURIComponent(baseGenerationId)}&target_generation_id=${encodeURIComponent(targetGenerationId)}`,
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
  printPlan: (generationId: string) =>
    request<PrintPlan>(
      `/api/v1/patterns/${encodeURIComponent(generationId)}/print-plan`,
    ),
  downloadScaleCheckPdf: (generationId: string) =>
    requestBlob(
      `/api/v1/patterns/${encodeURIComponent(generationId)}/export/scale-check-pdf`,
      {method: 'POST'},
    ),
  downloadAcceptanceReport: (generationId: string) =>
    requestBlob(
      `/api/v1/patterns/${encodeURIComponent(generationId)}/physical-validation/report.pdf`,
    ),
  physicalValidation: (generationId: string) =>
    request<PhysicalValidationSummary>(
      `/api/v1/patterns/${encodeURIComponent(generationId)}/physical-validation`,
    ),
  recordPhysicalValidation: (generationId: string, record: PhysicalValidationCreate) =>
    request<PhysicalValidationSummary>(
      `/api/v1/patterns/${encodeURIComponent(generationId)}/physical-validation`,
      {method: 'POST', body: JSON.stringify(record)},
    ),
  visionProviders: () => request<VisionProviderList>('/api/v1/ai/providers'),
  garmentCatalogue: () => request<GarmentCatalogue>('/api/v1/garments/catalog'),
  uploadImage: async (file: File, signal?: AbortSignal) => request<ImageUploadResult>('/api/v1/images', {
    method: 'POST',
    signal,
    body: JSON.stringify({
      file_name: file.name,
      media_type: file.type,
      data_base64: await fileBase64(file),
    }),
  }),
  deleteImage: (imageRef: string) => request<void>(
    `/api/v1/images/${encodeURIComponent(imageRef)}`,
    {method: 'DELETE'},
  ),
  imageUrl: (imageRef: string) => `/api/v1/images/${encodeURIComponent(imageRef)}`,
  checkVisionProvider: (provider: VisionProviderId, signal?: AbortSignal) =>
    request<VisionProviderCheck>(
      `/api/v1/ai/providers/${encodeURIComponent(provider)}/check`,
      {method: 'POST', signal},
    ),
  analyzeImages: (
    projectId: string,
    imageRefs: string[],
    imageViews: ImageViewRole[],
    provider: VisionProviderId,
    signal?: AbortSignal,
  ) =>
    request<StyleAnalysis>(`/api/v1/garments/analyze-image?provider=${provider}`, {
      method: 'POST',
      signal,
      body: JSON.stringify({
        schema_version: '1.0.0',
        request_id: crypto.randomUUID(),
        project_id: projectId,
        locale: 'ru-RU',
        image_refs: imageRefs,
        image_views: imageViews,
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
    projectId, ['img_demo_front_12345678'], ['front'], 'mock',
  ),
};

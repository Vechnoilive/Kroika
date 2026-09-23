import type {ProjectDocument, ProjectSummary} from './types';

export function projectSummary(project: ProjectDocument): ProjectSummary {
  return {
    project_id: project.project_id,
    name: project.name,
    revision: project.revision,
    status: project.status,
    updated_at: project.updated_at,
  };
}

export function uniqueCopyName(sourceName: string, projects: ProjectSummary[]): string {
  const used = new Set(projects.map((item) => item.name.trim().toLocaleLowerCase('ru-RU')));
  const base = `${sourceName.trim()} — копия`;
  if (!used.has(base.toLocaleLowerCase('ru-RU'))) return base;
  let sequence = 2;
  while (used.has(`${base} ${sequence}`.toLocaleLowerCase('ru-RU'))) sequence += 1;
  return `${base} ${sequence}`;
}

export function duplicateProjectDocument(source: ProjectDocument, name: string): ProjectDocument {
  const copy = structuredClone(source);
  const now = new Date().toISOString();
  return {
    ...copy,
    project_id: crypto.randomUUID(),
    revision: 1,
    name,
    status: 'draft',
    created_at: now,
    updated_at: now,
    style_analysis_id: copy.style_analysis ? crypto.randomUUID() : null,
    body_measurements: {
      ...copy.body_measurements,
      profile_id: crypto.randomUUID(),
    },
    garment_spec: {
      ...copy.garment_spec,
      garment_id: crypto.randomUUID(),
    },
    fit_settings: {
      ...copy.fit_settings,
      settings_id: crypto.randomUUID(),
    },
    fabric_properties: {
      ...copy.fabric_properties,
      fabric_id: crypto.randomUUID(),
    },
    latest_generation: null,
    generation_history: [],
  };
}

import type {
  DesignCoverageCatalogue,
  DesignCoverageEvidence,
  GarmentDesignIntent,
  StyleAnalysis,
} from './types';

export type CoverageDecision =
  | 'compiled'
  | 'excluded_by_user'
  | 'missing_evidence'
  | 'missing_from_plan';

export interface DesignCoverageEntry {
  sourceKind: 'element' | 'layer' | 'proportions';
  sourceId: string;
  label: string;
  origin: 'photo' | 'manual';
  decision: CoverageDecision;
  moduleId: string | null;
  evidence: DesignCoverageEvidence | null;
}

export interface DesignCoverageReport {
  complete: boolean;
  requiredCount: number;
  compiledCount: number;
  excludedCount: number;
  missingCount: number;
  photoCount: number;
  entries: DesignCoverageEntry[];
  physicalValidationRequired: boolean;
}

export function evidenceCount(evidence: DesignCoverageEvidence | null): number {
  if (!evidence) return 0;
  return Object.values(evidence).reduce((total, ids) => total + ids.length, 0);
}

export function buildDesignCoverage(
  intent: GarmentDesignIntent,
  analysis: StyleAnalysis | null | undefined,
  catalogue: DesignCoverageCatalogue | null | undefined,
): DesignCoverageReport {
  const featureElements = analysis?.design_features?.elements ?? [];
  const unsupported = analysis?.unsupported_features ?? [];
  const featureLayers = analysis?.design_features?.layers ?? [];
  const photoElementIds = new Set([
    ...featureElements.map((item) => item.element_id),
    ...unsupported.map((_item, index) => `unsupported_${index + 1}`),
  ]);
  const photoLayerIds = new Set(featureLayers.map((item) => item.layer_id));
  const modules = new Map((catalogue?.modules ?? []).map((item) => [item.module_id, item]));
  const entries: DesignCoverageEntry[] = [];

  const decisionFor = (
    included: boolean,
    supportStatus: string,
    moduleId: string | null,
  ): {decision: CoverageDecision; evidence: DesignCoverageEvidence | null} => {
    if (!included || supportStatus === 'excluded') {
      return {decision: 'excluded_by_user', evidence: null};
    }
    const proof = moduleId ? modules.get(moduleId)?.evidence : null;
    if (supportStatus === 'supported' && proof && evidenceCount(proof) > 0) {
      return {decision: 'compiled', evidence: proof};
    }
    return {decision: 'missing_evidence', evidence: proof ?? null};
  };

  for (const element of intent.elements) {
    const status = decisionFor(
      element.included !== false, element.support_status, element.module_id,
    );
    entries.push({
      sourceKind: 'element',
      sourceId: element.source_element_id,
      label: element.description_ru,
      origin: photoElementIds.has(element.source_element_id) ? 'photo' : 'manual',
      decision: status.decision,
      moduleId: element.module_id,
      evidence: status.evidence,
    });
  }

  for (const layer of intent.layers) {
    const status = decisionFor(layer.included !== false, layer.support_status, layer.module_id);
    entries.push({
      sourceKind: 'layer',
      sourceId: layer.source_layer_id,
      label: layer.material_hint_ru,
      origin: photoLayerIds.has(layer.source_layer_id) ? 'photo' : 'manual',
      decision: status.decision,
      moduleId: layer.module_id,
      evidence: status.evidence,
    });
  }

  const proportionsStatus = decisionFor(
    true, intent.proportions.support_status, intent.proportions.module_id,
  );
  entries.push({
    sourceKind: 'proportions',
    sourceId: 'visual_proportions',
    label: 'Общие пропорции и силуэт',
    origin: analysis?.design_features ? 'photo' : 'manual',
    decision: proportionsStatus.decision,
    moduleId: intent.proportions.module_id,
    evidence: proportionsStatus.evidence,
  });

  const plannedElements = new Set(intent.elements.map((item) => item.source_element_id));
  for (const element of featureElements) {
    if (plannedElements.has(element.element_id)) continue;
    entries.push({
      sourceKind: 'element', sourceId: element.element_id, label: element.description_ru,
      origin: 'photo', decision: 'missing_from_plan', moduleId: null, evidence: null,
    });
  }
  unsupported.forEach((label, index) => {
    const sourceId = `unsupported_${index + 1}`;
    if (plannedElements.has(sourceId)) return;
    entries.push({
      sourceKind: 'element', sourceId, label, origin: 'photo',
      decision: 'missing_from_plan', moduleId: null, evidence: null,
    });
  });
  const plannedLayers = new Set(intent.layers.map((item) => item.source_layer_id));
  for (const layer of featureLayers) {
    if (plannedLayers.has(layer.layer_id)) continue;
    entries.push({
      sourceKind: 'layer', sourceId: layer.layer_id, label: layer.material_hint_ru,
      origin: 'photo', decision: 'missing_from_plan', moduleId: null, evidence: null,
    });
  }

  const compiledCount = entries.filter((item) => item.decision === 'compiled').length;
  const excludedCount = entries.filter((item) => item.decision === 'excluded_by_user').length;
  const missingCount = entries.filter((item) => (
    item.decision === 'missing_evidence' || item.decision === 'missing_from_plan'
  )).length;
  const requiredCount = entries.length - excludedCount;
  return {
    complete: missingCount === 0,
    requiredCount,
    compiledCount,
    excludedCount,
    missingCount,
    photoCount: entries.filter((item) => item.origin === 'photo').length,
    entries,
    physicalValidationRequired: catalogue?.physical_validation_required ?? true,
  };
}

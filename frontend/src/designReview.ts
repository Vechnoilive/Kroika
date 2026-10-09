import {DESIGN_ELEMENT_NAMES, reevaluateDesignIntent} from './designIntent';
import {matchingModule, moduleDiagnosis, structuralConflicts} from './designModules';
import {isBackQuestion} from './backDesign';
import type {GarmentDesignIntent, GarmentSpec, StyleAnalysis} from './types';

export interface ReviewIssue {id: string; title: string; reasons: string[]}

export function reviewIssues(intent: GarmentDesignIntent, spec: GarmentSpec, analysis: StyleAnalysis): ReviewIssue[] {
  const evaluated = reevaluateDesignIntent(intent, spec, analysis);
  const issues: ReviewIssue[] = [];
  for (const [index, item] of evaluated.elements.entries()) {
    if (item.included === false) continue;
    const reasons = [...moduleDiagnosis('element', item, spec).reasons];
    if (!item.description_ru.trim()) reasons.push('Добавьте название или описание.');
    if (item.count !== null && (!Number.isInteger(item.count) || item.count < 1 || item.count > 32)) reasons.push('Количество должно быть целым числом от 1 до 32.');
    if (!item.confirmed_by_user) reasons.push('Подтвердите, что эта деталь проверена по фото.');
    if (reasons.length) issues.push({id: 'element-' + item.source_element_id, title: `Деталь ${index + 1}: ${DESIGN_ELEMENT_NAMES[item.type]}`, reasons});
  }
  for (const [index, item] of evaluated.layers.entries()) {
    if (item.included === false) continue;
    const reasons = [...moduleDiagnosis('layer', item, {...spec, design_intent: evaluated}).reasons];
    if (!item.material_hint_ru.trim()) reasons.push('Укажите материал или описание слоя.');
    if (!item.confirmed_by_user) reasons.push('Подтвердите слой по фото.');
    if (reasons.length) issues.push({id: 'layer-' + item.source_layer_id, title: `Слой ${index + 1}`, reasons});
  }
  const p = evaluated.proportions;
  const proportions: string[] = [];
  if (!moduleDiagnosis('proportions', p, {...spec, design_intent: evaluated}).module) {
    if (p.waist_position === 'unknown') proportions.push('Укажите положение талии.');
    if (p.volume === 'unknown') proportions.push('Выберите объём изделия.');
    if (p.hem_shape === 'unknown') proportions.push('Выберите форму низа.');
    if (p.asymmetry === 'unknown') proportions.push('Уточните наличие асимметрии.');
    if (!proportions.length) proportions.push('Проверьте размеры смещения талии или формы низа и выбранную конструкцию ярусов.');
  } else if (!matchingModule('proportions', p, {...spec, design_intent: evaluated})) {
    proportions.push('Проверьте размеры смещения талии или подъёма низа; для ярусного низа добавьте ярусы отделки.');
  }
  if (!evaluated.proportions.confirmed_by_user) proportions.push('Подтвердите пропорции изделия.');
  if (proportions.length) issues.push({id: 'proportions', title: 'Пропорции', reasons: proportions});
  if (evaluated.layers.filter(item => item.included !== false && item.role === 'main').length !== 1) issues.push({id: 'layers', title: 'Материалы', reasons: ['Оставьте ровно один основной слой.']});
  const conflicts = structuralConflicts({...spec, design_intent: evaluated});
  if (conflicts.length) issues.push({id: 'elements', title: 'Сочетание деталей', reasons: conflicts});
  if ((evaluated.question_answers ?? []).some(item => !isBackQuestion(item.question) && !item.answer_ru.trim())) issues.push({id: 'questions', title: 'Уточнения по фото', reasons: ['Заполните ответы на оставшиеся вопросы.']});
  return issues;
}

export function revealReviewItem(id: string) {
  const target = document.getElementById(`review-${id}`);
  if (!target) return;
  for (let parent: HTMLElement | null = target; parent; parent = parent.parentElement) {
    if (parent instanceof HTMLDetailsElement) parent.open = true;
  }
  const details = target.querySelector('details');
  if (details) details.open = true;
  const control = target.querySelector<HTMLElement>('[data-review-needed="true"]') ?? target.querySelector<HTMLElement>('details > summary') ?? target.querySelector<HTMLElement>('input:not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled)');
  control?.focus({preventScroll: true});
  (control ?? target).scrollIntoView?.({behavior: 'smooth', block: 'center'});
}

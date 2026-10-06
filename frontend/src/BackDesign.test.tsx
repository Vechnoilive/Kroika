import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {StyleEditor} from './ProjectWorkflow';
import {makeDemoProject} from './demoProject';
import {buildDesignIntent} from './designIntent';
import {canonicalGenerationPayload} from './generation';
import type {ProjectDocument, StyleAnalysis} from './types';
import {isBackQuestion} from './backDesign';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation', garment_category: 'dress', silhouette: {fit: 'semi_fitted', confidence: 1},
  neckline: {front: 'round', confidence: 1}, sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 1}, uncertainties: [],
  targeted_questions: ['Какую конструкцию спинки сделать: вырез, средний шов, молния?'],
  design_features: {
    elements: [{element_id: 'back_ai', type: 'closure', variant: 'unknown', description_ru: 'Застёжка спинки не видна', location: 'bodice_back', construction: 'unknown', count: 1, symmetry: 'symmetric', confidence: 0.3, evidence_ru: 'Фото спереди', requires_confirmation: true}], layers: [{layer_id: 'main', role: 'main', coverage: 'full', material_hint_ru: 'Основная ткань', opacity: 'opaque', drape: 'medium', confidence: 1, requires_confirmation: false}],
    proportions: {waist_position: 'natural', volume: 'regular', hem_shape: 'straight', asymmetry: 'no', confidence: 1},
  },
};

describe('structured back design', () => {
  it('keeps unrelated AI questions available for review', () => {
    expect(isBackQuestion('Какую конструкцию спинки сделать: вырез, средний шов, молния?')).toBe(true);
    expect(isBackQuestion('Планируется молния спереди?')).toBe(false);
    expect(isBackQuestion('Есть ли карман на задней части юбки?')).toBe(false);
  });
  it('replaces the back question with a saved closure choice that affects the input hash', async () => {
    const project = makeDemoProject('Спинка');
    project.garment_spec.design_intent = buildDesignIntent(analysis, project.garment_spec);
    const intent = project.garment_spec.design_intent!;
    intent.layers[0].confirmed_by_user = true;
    intent.proportions.confirmed_by_user = true;
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({...candidate, revision: candidate.revision + 1}));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave}/>);
    expect(screen.queryByLabelText(/Ответ на вопрос/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', {name: /Шнуровка лентой/i}));
    expect(screen.getByLabelText(/Расстояние между петлями/)).toHaveValue(8);
    await userEvent.click(screen.getByRole('button', {name: /Сохранить проверку деталей/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const saved = onSave.mock.calls.at(-1)![0];
    expect(saved.garment_spec.parameters.closure).toEqual({type: 'lacing', location: 'center_back', length_mm: 550, loop_pitch_mm: 80});
    expect(saved.garment_spec.design_intent?.question_answers?.[0].answer_ru).toContain('Шнуровка лентой');
    expect(saved.garment_spec.design_intent?.review_status).toBe('confirmed');
    expect(saved.garment_spec.design_intent?.elements[0]).toMatchObject({variant: 'tie', confirmed_by_user: true, support_status: 'supported', module_id: 'back_lacing_v1'});
    expect(canonicalGenerationPayload(saved).hash_contract_version).toBe('1.7.0');
  });
});

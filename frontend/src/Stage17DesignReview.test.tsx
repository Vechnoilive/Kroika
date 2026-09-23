import {useState} from 'react';
import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {buildDesignIntent} from './designIntent';
import {DesignIntentEditor} from './DesignIntentEditor';
import {makeDemoProject} from './demoProject';
import {StyleEditor} from './ProjectWorkflow';
import type {GarmentDesignIntent, ProjectDocument, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status: 'needs_confirmation',
  garment_category: 'skirt',
  silhouette: {fit: 'semi_fitted', confidence: 0.91},
  neckline: {front: 'unknown', confidence: 0},
  sleeves: {present: false, length: 'sleeveless', confidence: 1},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: 0.9},
  uncertainties: ['Верхний слой виден не полностью.'],
  targeted_questions: ['Есть ли прозрачный верхний слой?'],
  design_features: {
    elements: [
      {
        element_id: 'straight_waistband', type: 'waistband', variant: 'straight',
        description_ru: 'Прямой притачной пояс.', location: 'waist',
        construction: 'separate_piece', count: 1, symmetry: 'symmetric',
        confidence: 0.94, evidence_ru: 'Виден отдельный пояс по линии талии.',
        requires_confirmation: false,
      },
      {
        element_id: 'hem_flounce', type: 'flounce', variant: 'circular',
        description_ru: 'Широкий волан по низу.', location: 'hem',
        construction: 'separate_piece', count: 1, symmetry: 'symmetric',
        confidence: 0.88, evidence_ru: 'По низу видна отдельная расширенная деталь.',
        requires_confirmation: true,
      },
    ],
    layers: [
      {
        layer_id: 'main_fabric', role: 'main', coverage: 'full',
        material_hint_ru: 'Основная ткань.', opacity: 'opaque', drape: 'medium',
        confidence: 0.9, requires_confirmation: false,
      },
      {
        layer_id: 'transparent_overlay', role: 'overlay', coverage: 'skirt',
        material_hint_ru: 'Прозрачный верхний слой.', opacity: 'transparent', drape: 'fluid',
        confidence: 0.75, requires_confirmation: true,
      },
    ],
    proportions: {
      waist_position: 'natural', volume: 'regular', hem_shape: 'straight',
      asymmetry: 'no', confidence: 0.85,
    },
  },
};

function skirtProject() {
  const project = makeDemoProject('Юбка после ручной проверки');
  project.garment_spec.garment_type = 'skirt';
  project.garment_spec.selection_status = 'proposed';
  project.garment_spec.confirmed_at = null;
  project.garment_spec.design_intent = buildDesignIntent(analysis, project.garment_spec);
  return project;
}

function ReviewHarness({
  project,
  onSave,
}: {
  project: ProjectDocument;
  onSave: (intent: GarmentDesignIntent) => Promise<void>;
}) {
  const [intent, setIntent] = useState(
    project.garment_spec.design_intent as GarmentDesignIntent,
  );
  return <DesignIntentEditor
    intent={intent}
    spec={project.garment_spec}
    analysis={analysis}
    busy={false}
    onChange={setIntent}
    onSave={onSave}
  />;
}

describe('stage 17 design review editor', () => {
  it('excludes false detections, saves a ready review and then confirms the style', async () => {
    const project = skirtProject();
    const onSave = vi.fn(async (candidate: ProjectDocument) => ({
      ...candidate,
      revision: candidate.revision + 1,
    }));
    render(<StyleEditor project={project} analysis={analysis} providerName="Gemini" onSave={onSave} />);

    const detectedChecks = screen.getAllByRole('checkbox', {
      name: /эта деталь действительно есть на изделии/i,
    });
    await userEvent.click(detectedChecks[1]);
    await userEvent.click(screen.getByRole('checkbox', {name: /этот слой действительно есть/i}));
    await userEvent.click(screen.getByRole('checkbox', {name: /проверил.*эту деталь/i}));
    await userEvent.click(screen.getByRole('checkbox', {name: /проверил.*этот слой/i}));
    await userEvent.click(screen.getByRole('checkbox', {name: /проверил.*пропорции/i}));
    await userEvent.type(screen.getByLabelText('Ответ на вопрос 1'), 'Нет, это блик на ткани.');
    await userEvent.click(screen.getByRole('button', {name: /сохранить проверку деталей/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const reviewed = onSave.mock.calls[0][0].garment_spec.design_intent;
    expect(reviewed?.review_status).toBe('confirmed');
    expect(reviewed?.status).toBe('ready');
    expect(reviewed?.elements[1]).toMatchObject({included: false, support_status: 'excluded'});
    expect(reviewed?.layers[1]).toMatchObject({included: false, support_status: 'excluded'});

    await userEvent.click(screen.getByRole('button', {name: /подтвердить фасон/i}));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0].garment_spec.selection_status).toBe('confirmed');
  });

  it('edits dimensions, adds a missing detail and keeps unsupported geometry blocked', async () => {
    const project = skirtProject();
    const onSave = vi.fn(async (_saved: GarmentDesignIntent) => undefined);
    render(<ReviewHarness project={project} onSave={onSave} />);

    await userEvent.clear(screen.getByLabelText('Описание детали 2'));
    await userEvent.type(screen.getByLabelText('Описание детали 2'), 'Двойной съёмный волан');
    await userEvent.type(screen.getByLabelText('Ширина детали 2, см'), '12.5');
    await userEvent.click(screen.getByRole('button', {name: /добавить пропущенную деталь/i}));
    expect(screen.getByDisplayValue('Пропущенная деталь')).toBeVisible();

    const includedChecks = screen.getAllByRole('checkbox', {
      name: /эта деталь действительно есть на изделии/i,
    });
    await userEvent.click(includedChecks[2]);
    for (const checkbox of screen.getAllByRole('checkbox', {name: /проверил.*эту деталь/i})) {
      await userEvent.click(checkbox);
    }
    for (const checkbox of screen.getAllByRole('checkbox', {name: /проверил.*этот слой/i})) {
      await userEvent.click(checkbox);
    }
    await userEvent.click(screen.getByRole('checkbox', {name: /проверил.*пропорции/i}));
    await userEvent.type(screen.getByLabelText('Ответ на вопрос 1'), 'Да, слой и волан есть.');
    await userEvent.click(screen.getByRole('button', {name: /сохранить проверку деталей/i}));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].status).toBe('partial');
    expect(onSave.mock.calls[0][0].elements[1].description_ru).toBe('Двойной съёмный волан');
    expect(onSave.mock.calls[0][0].elements[1].dimensions_mm?.width).toBe(125);
    expect(onSave.mock.calls[0][0].elements[2].support_status).toBe('excluded');
    expect(screen.getByText(/построение останется закрытым/i)).toBeVisible();
  });
});

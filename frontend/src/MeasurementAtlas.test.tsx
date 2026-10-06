import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {MeasurementAtlas} from './MeasurementAtlas';
import {ATLAS_LINES} from './measurementAtlas';
import type {MeasurementDefinition} from './types';

const definitions = ['bust', 'waist', 'hips'].map((id) => ({id, label_ru: id, instruction_ru: `Инструкция ${id}`} as MeasurementDefinition));

describe('measurement atlas', () => {
  it('maps all 37 measures to stable numbers and distinct anatomical paths', () => {
    expect(ATLAS_LINES).toHaveLength(37);
    expect(new Set(ATLAS_LINES.map((line) => line.id)).size).toBe(37);
    expect(new Set(ATLAS_LINES.map((line) => line.path)).size).toBe(37);
    expect(ATLAS_LINES.map((line) => line.number)).toEqual(Array.from({length: 37}, (_, i) => i + 1));
  });
  it('shows all applicable lines over a lifelike figure and selects them from the legend', async () => {
    const onSelect = vi.fn();
    const {container} = render(<MeasurementAtlas definitions={definitions} activeId={null} onSelect={onSelect}/>);
    expect(screen.getByRole('img', {name: /вид спереди, сзади и сбоку/i})).toBeVisible();
    expect(container.querySelector('image')).toHaveAttribute('href', '/images/measurements-body.png');
    expect(container.querySelectorAll('[data-measurement]')).toHaveLength(6);
    await userEvent.click(screen.getByRole('button', {name: /waist/}));
    expect(onSelect).toHaveBeenCalledWith('waist');
  });
});

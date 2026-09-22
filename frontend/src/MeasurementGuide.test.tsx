import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {MeasurementGuide} from './MeasurementGuide';

describe('MeasurementGuide', () => {
  it('uses mirrored limbs so the explanatory figure stays symmetrical', () => {
    const {container} = render(<MeasurementGuide variant="bust" label="Обхват груди" />);

    expect(screen.getByRole('img', {name: /схема: обхват груди/i})).toBeVisible();
    const mirroredParts = container.querySelectorAll('.guide-body--mirror');
    expect(mirroredParts).toHaveLength(2);
    mirroredParts.forEach((part) => {
      expect(part).toHaveAttribute('transform', 'translate(220 0) scale(-1 1)');
    });
    expect(container.querySelector('.guide-measure')).toBeInTheDocument();
  });
});

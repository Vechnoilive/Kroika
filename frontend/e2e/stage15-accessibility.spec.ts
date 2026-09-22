import {expect, test} from '@playwright/test';
import axe from 'axe-core';

type AxeWindow = Window & typeof globalThis & {
  axe: {
    run: () => Promise<{
      violations: Array<{
        id: string;
        impact: string | null;
        nodes: Array<{target: string[]}>;
      }>;
    }>;
  };
};

test('основной экран не содержит серьёзных accessibility-нарушений', async ({page}) => {
  await page.goto('/');
  await expect(page.getByRole('button', {name: /создать проект/i})).toBeVisible();
  await page.addScriptTag({content: axe.source});
  const violations = await page.evaluate(async () => {
    const result = await (window as AxeWindow).axe.run();
    return result.violations
      .filter((item) => item.impact === 'serious' || item.impact === 'critical')
      .map((item) => ({
        id: item.id,
        impact: item.impact,
        targets: item.nodes.flatMap((node) => node.target),
      }));
  });
  expect(violations).toEqual([]);
});

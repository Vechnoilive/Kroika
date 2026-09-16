import {expect, test, type Page} from '@playwright/test';

const SKIRT_VALUES: Record<string, number> = {
  waist: 74,
  hips: 100,
  back_waist_arc: 36,
  back_hip_arc: 52,
  hip_depth: 20,
  hip_inclination: 11.4,
};

async function fillSkirtMeasurements(page: Page) {
  const response = await page.request.get(
    '/api/v1/measurements/catalog?garment_type=skirt&sleeve_type=sleeveless',
  );
  expect(response.ok()).toBeTruthy();
  const catalog = await response.json() as {
    measurements: Array<{id: string; required: boolean}>;
  };
  const required = catalog.measurements.filter((item) => item.required);
  expect(required.map((item) => item.id)).toEqual(Object.keys(SKIRT_VALUES));
  for (let index = 0; index < required.length; index += 1) {
    const item = required[index];
    await page.locator(`#measurement-${item.id}`).fill(String(SKIRT_VALUES[item.id]));
    if (index < required.length - 1) {
      await page.getByRole('button', {name: 'Дальше →'}).click();
    }
  }
  await page.getByRole('button', {name: /проверить и завершить/i}).click();
}

test('юбка проходит отдельный понятный сценарий этапа 12', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Название проекта').fill(`E2E юбка этап 12 ${Date.now()}`);
  await page.getByRole('button', {name: /создать проект/i}).click();
  await page.getByRole('button', {name: /продолжить в демо-режиме/i}).click();

  await page.getByRole('radio', {name: /Юбка/}).check();
  await expect(page.getByText('Без лифа')).toBeVisible();
  await expect(page.getByLabel('Длина юбки от талии')).toBeVisible();
  await expect(page.getByLabel(/глубина горловины спереди/i)).toHaveCount(0);
  await page.getByRole('button', {name: /подтвердить фасон/i}).click();

  await expect(page.getByRole('heading', {name: /снимаем мерки/i})).toBeVisible();
  await fillSkirtMeasurements(page);
  await expect(page.getByRole('heading', {name: /подтвердите прибавки/i})).toBeVisible();
  await expect(page.getByLabel(/^По груди/)).toHaveCount(0);
  await page.getByRole('button', {name: /подтвердить ткань и настройки/i}).click();

  await expect(page.getByText(/Юбка · А-силуэт с поясом/i)).toBeVisible();
  const generation = page.waitForResponse(
    (response) => response.url().includes('/api/v1/patterns/generate')
      && response.request().method() === 'POST',
    {timeout: 60_000},
  );
  await page.getByRole('button', {name: 'Построить выкройку'}).click();
  const response = await generation;
  expect(response.status(), await response.text()).toBe(200);
  await expect(page.getByRole('heading', {name: /выкройка готова к проверке/i}))
    .toBeVisible({timeout: 60_000});
  await expect(page.getByText(/expert status — pending, toile status — pending/i)).toBeVisible();
});

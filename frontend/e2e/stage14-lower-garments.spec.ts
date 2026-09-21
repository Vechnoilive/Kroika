import {expect, test, type Page} from '@playwright/test';

const VALUES: Record<string, number> = {
  waist: 74, hips: 100, sitting_height: 27, crotch_length: 72,
  outside_leg_length: 104, inseam_length: 78, thigh_circumference: 59,
  knee_circumference: 40, trouser_hem_circumference: 38, knee_height: 56,
};

async function fillTrouserMeasurements(page: Page) {
  const response = await page.request.get(
    '/api/v1/measurements/catalog?garment_type=trousers&sleeve_type=sleeveless',
  );
  expect(response.ok()).toBeTruthy();
  const catalog = await response.json() as {measurements: Array<{id: string; required: boolean}>};
  const required = catalog.measurements.filter((item) => item.required);
  expect(required.length).toBe(10);
  for (let index = 0; index < required.length; index += 1) {
    const item = required[index];
    expect(VALUES[item.id], `Нет E2E-значения для ${item.id}`).toBeDefined();
    await page.locator(`#measurement-${item.id}`).fill(String(VALUES[item.id]));
    if (index < required.length - 1) await page.getByRole('button', {name: 'Дальше →'}).click();
  }
  await page.getByRole('button', {name: /проверить и завершить/i}).click();
}

test('прямые брюки проходят последовательный сценарий этапа 14', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Название проекта').fill(`E2E брюки этап 14 ${Date.now()}`);
  await page.getByRole('button', {name: /создать проект/i}).click();
  await page.getByRole('button', {name: /продолжить в демо-режиме/i}).click();

  await page.getByRole('radio', {name: /Прямые брюки/}).check();
  await expect(page.getByText('Боковые карманы')).toBeVisible();
  await expect(page.getByLabel('Длина брюк от талии')).toHaveValue('100');
  await page.getByRole('button', {name: /подтвердить фасон/i}).click();

  await expect(page.getByRole('heading', {name: /снимаем мерки/i})).toBeVisible();
  await fillTrouserMeasurements(page);
  await expect(page.getByRole('heading', {name: /подтвердите прибавки/i})).toBeVisible();
  await expect(page.getByLabel(/^По талии/)).toHaveValue('2');
  await expect(page.getByLabel(/^По бёдрам/)).toHaveValue('5');
  await page.getByRole('button', {name: /подтвердить ткань и настройки/i}).click();

  await expect(page.getByText(/прямая основа с поясом/i)).toBeVisible();
  const generation = page.waitForResponse(
    (response) => response.url().includes('/api/v1/patterns/generate')
      && response.request().method() === 'POST',
    {timeout: 60_000},
  );
  await page.getByRole('button', {name: 'Построить выкройку'}).click();
  const result = await generation;
  expect(result.status(), await result.text()).toBe(200);
  await expect(page.getByRole('heading', {name: /выкройка готова к проверке/i}))
    .toBeVisible({timeout: 60_000});
  await expect(page.getByText(/expert status — pending, toile status — pending/i)).toBeVisible();
});

import {expect, test, type Page} from '@playwright/test';

const VALUES: Record<string, number> = {
  bust: 92, waist: 74, hips: 100, neck_circumference: 38,
  back_bust_arc: 44, back_waist_arc: 36, back_hip_arc: 52,
  shoulder_span: 38, shoulder_length: 13, back_neck_to_waist: 41,
  front_neck_to_waist_over_bust: 46, bust_path_height: 26,
  bust_vertical_height: 23, bust_span: 20, hip_depth: 20, armscye_depth: 19,
  upper_arm_circumference: 30, wrist_circumference: 16, hand_circumference: 21,
  sleeve_length: 58, elbow_circumference: 26, elbow_length: 33,
  front_diagonal_shoulder_height: 43, back_diagonal_shoulder_height: 42,
  shoulder_slope: 11.3, hip_inclination: 11.4,
};

async function fillJacketMeasurements(page: Page) {
  const response = await page.request.get(
    '/api/v1/measurements/catalog?garment_type=jacket&sleeve_type=long',
  );
  expect(response.ok()).toBeTruthy();
  const catalog = await response.json() as {measurements: Array<{id: string; required: boolean}>};
  const required = catalog.measurements.filter((item) => item.required);
  expect(required.length).toBeGreaterThan(20);
  for (let index = 0; index < required.length; index += 1) {
    const item = required[index];
    expect(VALUES[item.id], `Нет E2E-значения для ${item.id}`).toBeDefined();
    await page.locator(`#measurement-${item.id}`).fill(String(VALUES[item.id]));
    if (index < required.length - 1) await page.getByRole('button', {name: 'Дальше →'}).click();
  }
  await page.getByRole('button', {name: /проверить и завершить/i}).click();
}

test('лёгкий жакет проходит последовательный сценарий этапа 13', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Название проекта').fill(`E2E жакет этап 13 ${Date.now()}`);
  await page.getByRole('button', {name: /создать проект/i}).click();
  await page.getByRole('button', {name: /продолжить в демо-режиме/i}).click();

  await page.getByRole('radio', {name: /Лёгкий жакет/}).check();
  await expect(page.getByText('Лацкан и воротник')).toBeVisible();
  await expect(page.getByLabel('Ширина лацкана')).toHaveValue('7');
  await page.getByRole('button', {name: /подтвердить фасон/i}).click();

  await expect(page.getByRole('heading', {name: /снимаем мерки/i})).toBeVisible();
  await fillJacketMeasurements(page);
  await expect(page.getByRole('heading', {name: /подтвердите прибавки/i})).toBeVisible();
  await expect(page.getByText(/учитывает одежду нижнего слоя/i)).toBeVisible();
  await page.getByRole('button', {name: /подтвердить ткань и настройки/i}).click();

  await expect(page.getByText(/Лёгкий жакет/i).first()).toBeVisible();
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

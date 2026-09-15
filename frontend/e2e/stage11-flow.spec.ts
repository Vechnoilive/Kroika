import path from 'node:path';
import {expect, test, type Page} from '@playwright/test';

const VALUES: Record<string, number> = {
  bust: 92,
  waist: 74,
  hips: 100,
  back_bust_arc: 44,
  back_waist_arc: 36,
  back_hip_arc: 52,
  shoulder_span: 38,
  back_neck_to_waist: 41,
  front_neck_to_waist_over_bust: 46,
  bust_path_height: 26,
  bust_vertical_height: 23,
  bust_span: 20,
  hip_depth: 20,
  armscye_depth: 19,
  shoulder_length: 13,
  shoulder_slope: 11.3,
  hip_inclination: 11.4,
};

async function fillRequiredMeasurements(page: Page) {
  const response = await page.request.get(
    '/api/v1/measurements/catalog?garment_type=dress&sleeve_type=sleeveless',
  );
  expect(response.ok()).toBeTruthy();
  const catalog = await response.json() as {
    measurements: Array<{id: string; kind: 'linear' | 'angle'; required: boolean}>;
  };
  const required = catalog.measurements.filter((item) => item.required);
  for (let index = 0; index < required.length; index += 1) {
    const definition = required[index];
    await page.locator(`#measurement-${definition.id}`).fill(String(VALUES[definition.id]));
    if (index < required.length - 1) {
      await page.getByRole('button', {name: 'Дальше →'}).click();
    }
  }
  await page.getByRole('button', {name: /проверить и завершить/i}).click();
}

async function completeFlow(page: Page, provider: 'mock' | 'qwen') {
  await page.goto('/');
  const name = `E2E этап 11 ${provider} ${Date.now()}`;
  await page.getByLabel('Название проекта').fill(name);
  await page.getByRole('button', {name: /создать проект/i}).click();

  if (provider === 'qwen') {
    await page.getByRole('radio', {name: /^Qwen/}).check();
    await page.locator('#garment-image').setInputFiles(
      path.resolve('../evaluation/stage10/images/synthetic-01.png'),
    );
    await page.getByLabel(/я разрешаю отправить только это изображение/i).check();
    await page.getByRole('button', {name: /проанализировать изображение/i}).click();
  } else {
    await page.getByRole('button', {name: /продолжить в демо-режиме/i}).click();
  }

  await expect(page.getByRole('heading', {name: /проверьте фасон/i})).toBeVisible();
  await page.getByRole('button', {name: /подтвердить фасон/i}).click();
  await expect(page.getByRole('heading', {name: /снимаем мерки/i})).toBeVisible();
  await fillRequiredMeasurements(page);

  await expect(page.getByRole('heading', {name: /подтвердите прибавки/i})).toBeVisible();
  await page.getByRole('button', {name: /подтвердить ткань и настройки/i}).click();
  await expect(page.getByRole('heading', {name: 'Построить выкройку?'})).toBeVisible();
  const generationResponsePromise = page.waitForResponse(
    (response) => response.url().includes('/api/v1/patterns/generate')
      && response.request().method() === 'POST',
    {timeout: 60_000},
  );
  await page.getByRole('button', {name: 'Построить выкройку'}).click();
  const generationResponse = await generationResponsePromise;
  const generationBody = await generationResponse.text();
  expect(generationResponse.status(), generationBody).toBe(200);
  expect((JSON.parse(generationBody) as {status: string}).status, generationBody).toBe('succeeded');

  await expect(page.getByRole('heading', {name: /выкройка готова к проверке/i}))
    .toBeVisible({timeout: 30_000});
  await expect(page.getByRole('link', {name: 'Единый SVG'})).toBeVisible();
  await expect(page.getByRole('link', {name: 'JSON проекта'})).toBeVisible();
  await expect(page.getByRole('button', {name: /pdf a4/i})).toBeVisible();

  await page.getByLabel('Размеры деталей').uncheck();
  await expect(page.getByRole('img', {name: /интерактивный предпросмотр/i}))
    .not.toHaveAttribute('src', /dimensions/);
  await page.getByLabel(/масштаб просмотра/i).fill('150');
  await expect(page.getByRole('img', {name: /интерактивный предпросмотр/i}))
    .toHaveCSS('width', /.+/);

  await page.getByText(/история проекта/i).click();
  await expect(page.getByText(/выкройка построена и проверена/i)).toBeVisible();
}

test('полный сохранённый сценарий в mock', async ({page}) => {
  await completeFlow(page, 'mock');
});

test('полный сохранённый сценарий @qwen-live', async ({page}) => {
  test.skip(
    !process.env.QWEN_API_KEY || !process.env.QWEN_BASE_URL,
    'Для честного live E2E нужны QWEN_API_KEY и региональный QWEN_BASE_URL.',
  );
  await completeFlow(page, 'qwen');
});

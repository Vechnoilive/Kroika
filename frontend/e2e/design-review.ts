import {expect, type Page} from '@playwright/test';


export async function completeDesignReview(
  page: Page,
  {excludeElements = false}: {excludeElements?: boolean} = {},
) {
  const detectedElements = page.getByRole('checkbox', {
    name: /эта деталь действительно есть на изделии/i,
  });
  if (excludeElements) {
    for (let index = 0; index < await detectedElements.count(); index += 1) {
      await detectedElements.nth(index).uncheck();
    }
  } else {
    const elementConfirmations = page.getByRole('checkbox', {
      name: /проверил.*эту деталь/i,
    });
    for (let index = 0; index < await elementConfirmations.count(); index += 1) {
      await elementConfirmations.nth(index).check();
    }
  }

  const layerConfirmations = page.getByRole('checkbox', {
    name: /проверил.*этот слой/i,
  });
  for (let index = 0; index < await layerConfirmations.count(); index += 1) {
    await layerConfirmations.nth(index).check();
  }
  await page.getByRole('checkbox', {name: /проверил.*пропорции/i}).check();

  const answers = page.getByLabel(/ответ на вопрос \d+/i);
  for (let index = 0; index < await answers.count(); index += 1) {
    await answers.nth(index).fill('Проверено пользователем в E2E-сценарии.');
  }

  await page.getByRole('button', {name: /сохранить проверку деталей/i}).click();
  await expect(page.getByText('Проверка сохранена')).toBeVisible({timeout: 15_000});
}

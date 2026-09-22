import axe from 'axe-core';
import {render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App from './App';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('stage 15 accessibility gate', () => {
  it('has named landmarks and no automatically detectable WCAG violations', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes('/health/')
        ? {
            status: 'ok', service: 'kroika-backend', version: '0.15.0',
            database: 'ok', ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.8.1',
          }
        : {items: []};
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: {'Content-Type': 'application/json'},
      });
    }));

    render(<App />);
    await screen.findByRole('button', {name: /создать проект/i});
    expect(screen.getByRole('main')).toBeVisible();
    expect(screen.getByRole('complementary', {name: /этапы создания выкройки/i})).toBeVisible();
    expect(screen.getByRole('link', {name: /Kroika — главная/i})).toBeVisible();
    expect(screen.getByRole('heading', {level: 1})).toBeVisible();

    document.documentElement.lang = 'ru';
    document.title = 'Kroika — выкройка шаг за шагом';
    const result = await axe.run(document);
    expect(result.violations.map((violation) => violation.id)).toEqual([]);
  });
});

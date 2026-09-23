import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {VisionAnalyzer} from './VisionAnalyzer';

const providers = {
  default_provider: 'qwen',
  items: [
    {provider_id: 'mock', name: 'Демо-режим', model: 'fixture', configured: true, is_default: false, enabled_for_users: true, sends_images_external: false, message_ru: 'Локально.'},
    {provider_id: 'qwen', name: 'Qwen', model: 'qwen-test', configured: true, is_default: true, enabled_for_users: true, sends_images_external: true, message_ru: 'Готов.'},
    {provider_id: 'gemini', name: 'Gemini', model: 'gemini-test', configured: false, is_default: false, enabled_for_users: false, sends_images_external: true, message_ru: 'Нет ключа.'},
  ],
};

const analysis = {
  status: 'needs_confirmation', garment_category: 'dress', source_image_views: ['front', 'detail'],
  silhouette: {fit: 'semi_fitted', confidence: .9},
  neckline: {front: 'round', confidence: .9},
  sleeves: {present: false, length: 'sleeveless', confidence: .9},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: .9},
  uncertainties: ['Не видна спинка'], targeted_questions: ['Какая застёжка?'],
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('stage 23 photo and AI workspace', () => {
  it('labels and reorders previews, checks the provider without images', async () => {
    const requests: Array<{url: string; body?: string}> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({url, body: typeof init?.body === 'string' ? init.body : undefined});
      if (url.endsWith('/api/v1/ai/providers')) {
        return new Response(JSON.stringify(providers), {status: 200});
      }
      if (url.includes('/check')) {
        return new Response(JSON.stringify({
          provider_id: 'qwen', model: 'qwen-test', status: 'ready', latency_ms: 42,
          message_ru: 'Соединение и ключ работают. Изображения не отправлялись.',
        }), {status: 200});
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<VisionAnalyzer projectId="11111111-1111-4111-8111-111111111111" onComplete={vi.fn()} />);

    const picker = await screen.findByLabelText(/выбрать изображения/i);
    const front = new File([new Uint8Array([1])], 'front.png', {type: 'image/png'});
    const detail = new File([new Uint8Array([2])], 'detail.png', {type: 'image/png'});
    await userEvent.upload(picker, [front, detail]);

    expect(screen.getByRole('combobox', {name: /вид изображения 1/i})).toHaveValue('front');
    expect(screen.getByRole('combobox', {name: /вид изображения 2/i})).toHaveValue('back');
    await userEvent.selectOptions(screen.getByRole('combobox', {name: /вид изображения 2/i}), 'detail');
    await userEvent.click(screen.getByRole('button', {name: /поднять изображение 2/i}));
    expect(screen.getByText(/1\. detail\.png/i)).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /повернуть изображение 1/i}));
    await userEvent.click(screen.getByRole('button', {name: /проверить соединение/i}));

    expect(await screen.findByText(/соединение и ключ работают/i)).toBeVisible();
    const check = requests.find((request) => request.url.includes('/check'));
    expect(check?.body).toBeUndefined();
    expect(requests.some((request) => request.url.includes('/images'))).toBe(false);
  });

  it('retries analysis with stored refs and sends ordered view labels only once', async () => {
    let uploadCount = 0;
    let analysisCount = 0;
    const analysisBodies: Array<Record<string, unknown>> = [];
    const completed = vi.fn(async () => undefined);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/api/v1/ai/providers')) {
        return new Response(JSON.stringify(providers), {status: 200});
      }
      if (url.endsWith('/api/v1/images')) {
        uploadCount += 1;
        return new Response(JSON.stringify({
          image_ref: `img_1234567${uploadCount}`,
          media_type: 'image/png', size_bytes: 1,
        }), {status: 201});
      }
      if (url.includes('/garments/analyze-image')) {
        analysisCount += 1;
        analysisBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        if (analysisCount === 1) {
          return new Response(JSON.stringify({
            code: 'TIMEOUT', message_ru: 'Сервис не успел ответить.', request_id: 'abcdef12-0000',
          }), {status: 504});
        }
        return new Response(JSON.stringify(analysis), {status: 200});
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<VisionAnalyzer projectId="11111111-1111-4111-8111-111111111111" onComplete={completed} />);

    const first = new File([new Uint8Array([1])], 'front.png', {type: 'image/png'});
    const second = new File([new Uint8Array([2])], 'detail.png', {type: 'image/png'});
    await userEvent.upload(await screen.findByLabelText(/выбрать изображения/i), [first, second]);
    await userEvent.selectOptions(screen.getByRole('combobox', {name: /вид изображения 2/i}), 'detail');
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', {name: /проанализировать изображения/i}));

    expect(await screen.findByRole('alert')).toHaveTextContent('Фотографии повторно загружать не нужно');
    expect(screen.getAllByText(/уже сохранено/i)).toHaveLength(2);
    expect(uploadCount).toBe(2);

    await userEvent.click(screen.getByRole('button', {name: /проанализировать изображения/i}));
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));
    expect(uploadCount).toBe(2);
    expect(analysisCount).toBe(2);
    expect(analysisBodies[0].image_views).toEqual(['front', 'detail']);
    expect(analysisBodies[1].image_refs).toEqual(['img_12345671', 'img_12345672']);
  });

  it('cancels a long analysis and can retry without uploading the photo again', async () => {
    let uploadCount = 0;
    let analysisCount = 0;
    const completed = vi.fn(async () => undefined);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/api/v1/ai/providers')) {
        return new Response(JSON.stringify(providers), {status: 200});
      }
      if (url.endsWith('/api/v1/images')) {
        uploadCount += 1;
        return new Response(JSON.stringify({
          image_ref: 'img_12345678', media_type: 'image/png', size_bytes: 1,
        }), {status: 201});
      }
      if (url.includes('/garments/analyze-image')) {
        analysisCount += 1;
        if (analysisCount > 1) return new Response(JSON.stringify(analysis), {status: 200});
        return await new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          }, {once: true});
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
    render(<VisionAnalyzer projectId="11111111-1111-4111-8111-111111111111" onComplete={completed} />);

    const file = new File([new Uint8Array([1])], 'front.png', {type: 'image/png'});
    await userEvent.upload(await screen.findByLabelText(/выбрать изображения/i), file);
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', {name: /проанализировать изображения/i}));
    expect(await screen.findByRole('status')).toHaveTextContent('Модель анализирует фасон');
    await userEvent.click(screen.getByRole('button', {name: /^отменить$/i}));

    expect(await screen.findByRole('alert')).toHaveTextContent('Запрос отменён');
    expect(screen.getByText(/уже сохранено/i)).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /проанализировать изображения/i}));
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));
    expect(uploadCount).toBe(1);
    expect(analysisCount).toBe(2);
  });
});

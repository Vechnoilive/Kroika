import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {VisionAnalyzer} from './VisionAnalyzer';

const providers = {
  default_provider: 'mock',
  items: [
    {provider_id: 'mock', name: 'Демо-режим', model: 'fixture', configured: true, is_default: true, enabled_for_users: true, sends_images_external: false, message_ru: 'Не отправляет фото.'},
    {provider_id: 'qwen', name: 'Qwen', model: 'qwen-test', configured: true, is_default: false, enabled_for_users: true, sends_images_external: true, message_ru: 'Отправляет после согласия.'},
    {provider_id: 'gemini', name: 'Gemini', model: 'gemini-test', configured: false, is_default: false, enabled_for_users: false, sends_images_external: true, message_ru: 'Нужен ключ.'},
  ],
};

const analysis = {
  status: 'needs_confirmation', garment_category: 'dress',
  silhouette: {fit: 'semi_fitted', confidence: .9},
  neckline: {front: 'round', confidence: .9},
  sleeves: {present: false, length: 'sleeveless', confidence: .9},
  lower_part: {type: 'a_line', length_category: 'midi', confidence: .9},
  uncertainties: ['Не видна спинка'], targeted_questions: ['Какая застёжка?'],
};

afterEach(() => vi.restoreAllMocks());

describe('stage 10 vision choice', () => {
  it('keeps offline demo as a one-click safe path', async () => {
    const completed = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/ai/providers')) {
        return new Response(JSON.stringify(providers), {status: 200});
      }
      return new Response(JSON.stringify(analysis), {status: 200});
    }));
    render(<VisionAnalyzer projectId="11111111-1111-4111-8111-111111111111" onComplete={completed} />);
    const button = await screen.findByRole('button', {name: /продолжить в демо/i});
    await userEvent.click(button);
    await waitFor(() => expect(completed).toHaveBeenCalledWith(analysis, {
      providerId: 'mock', providerName: 'Демо-режим', imageRefs: [],
    }));
    expect(fetch).not.toHaveBeenCalledWith('/api/v1/images', expect.anything());
  });

  it('requires a supported file and explicit consent before Qwen', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/ai/providers')) return new Response(JSON.stringify(providers), {status: 200});
      if (url.includes('/images')) return new Response(JSON.stringify({image_ref: 'img_12345678', media_type: 'image/png', size_bytes: 12}), {status: 201});
      return new Response(JSON.stringify(analysis), {status: 200});
    }));
    render(<VisionAnalyzer projectId="11111111-1111-4111-8111-111111111111" onComplete={vi.fn()} />);
    await userEvent.click(await screen.findByRole('radio', {name: /Qwen/i}));
    await userEvent.click(screen.getByRole('button', {name: /проанализировать/i}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Сначала выберите фотографию');
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'dress.png', {type: 'image/png'});
    await userEvent.upload(screen.getByLabelText(/выбрать изображения/i), file);
    await userEvent.click(screen.getByRole('button', {name: /проанализировать/i}));
    expect(await screen.findByText(/подтвердите отправку/i)).toBeVisible();
    expect(screen.getByRole('checkbox')).toBeVisible();
  });

  it('keeps disabled providers out of the user-facing choice', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(providers), {status: 200})));
    render(<VisionAnalyzer projectId="11111111-1111-4111-8111-111111111111" onComplete={vi.fn()} />);
    expect(await screen.findByRole('radio', {name: /Qwen/i})).toBeEnabled();
    expect(screen.queryByRole('radio', {name: /Gemini/i})).not.toBeInTheDocument();
    expect(screen.queryByText('Нужен ключ.')).not.toBeInTheDocument();
  });
});

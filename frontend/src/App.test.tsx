import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import App from './App';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('accessible stage flow', () => {
  it('starts with one clear enabled action after readiness succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes('/health/')
        ? {status: 'ok', service: 'kroika-backend', version: '0.6.0', database: 'ok', ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.2.0'}
        : {items: []};
      return new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
    }));
    render(<App />);

    const action = await screen.findByRole('button', {name: /создать проект/i});
    await waitFor(() => expect(action).toBeEnabled());
    expect(screen.getByLabelText(/название проекта/i)).toBeVisible();
    expect(screen.getByText(/будет пустым/i)).toBeVisible();
  });

  it('explains a backend outage in plain language', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    render(<App />);
    expect(await screen.findByText('Backend пока недоступен')).toBeVisible();
    expect(screen.getByRole('button', {name: /создать проект/i})).toBeDisabled();
  });

  it('lets a keyboard user edit the project name', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes('/health/')
        ? {status: 'ok', service: 'kroika-backend', version: '0.6.0', database: 'ok', ai_provider: 'mock', pattern_engine: 'kroika-geometry:0.2.0'}
        : {items: []};
      return new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
    }));
    render(<App />);
    const input = await screen.findByLabelText(/название проекта/i);
    await userEvent.clear(input);
    await userEvent.type(input, 'Летнее платье');
    expect(input).toHaveValue('Летнее платье');
  });
});

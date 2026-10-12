import {act, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {DesktopSettingsButton, DesktopSettingsPanel} from './DesktopSettings';
import {chooseDesktopImages, type DesktopApi, type DesktopSettings} from './desktop';
import type {StyleAnalysis} from './types';
import {saveExport} from './fileActions';
import {api} from './api';
import {VisionAnalyzer} from './VisionAnalyzer';

const values: DesktopSettings = {
  provider: 'gemini', model: 'gemini-3.6-flash', thinking: 'auto', timeout: 300,
  max_output_tokens: 16384, attempts: 3, api_mode: 'generate_content', has_key: true,
  key_storage: 'system', secure_storage_available: true,
  data_dir: 'C:\\Users\\test\\Kroika\\data', images_dir: 'images', logs_dir: 'logs',
};

function bridge(overrides: Partial<DesktopApi> = {}): DesktopApi {
  const result: DesktopApi = {
    check_updates: vi.fn(async () => ({ok: true as const, value: {current_version: '0.3.0', latest_version: '0.3.0', available: false, release_url: 'https://github.com/Vechnoilive/Kroika/releases'}})),
    get_settings: vi.fn(async () => ({ok: true as const, value: values})),
    save_settings: vi.fn(async () => ({ok: true as const, value: values})),
    choose_images: vi.fn(async () => ({ok: true as const, value: []})),
    save_export: vi.fn(async () => ({ok: true as const, value: {cancelled: false, path: 'pattern.pdf'}})),
    import_data: vi.fn(async () => ({ok: true as const, value: {cancelled: false, projects: 2, generations: 3, measurement_profiles: 1}})),
    open_folder: vi.fn(async () => ({ok: true as const, value: null})),
    ...overrides,
  };
  window.pywebview = {api: result};
  return result;
}

afterEach(() => {delete window.pywebview; vi.restoreAllMocks();});

describe('desktop controls preserve web behavior and private credentials', () => {
  it('checks updates only on request and preserves an unsaved key', async () => {
    const native = bridge({check_updates: vi.fn(async () => ({ok: true as const, value: {
      current_version: '0.3.0', latest_version: '0.4.0', available: true,
      release_url: 'https://github.com/Vechnoilive/Kroika/releases',
    }}))});
    render(<DesktopSettingsPanel allowImport onImport={vi.fn()} onClose={vi.fn()} />);
    await userEvent.type(await screen.findByLabelText('API-ключ Gemini'), 'unsaved-key');
    expect(native.check_updates).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', {name: 'Проверить обновления'}));
    expect(await screen.findByRole('status')).toHaveTextContent('Доступна версия 0.4.0');
    expect(screen.getByLabelText('API-ключ Gemini')).toHaveValue('unsaved-key');
    expect(native.save_settings).not.toHaveBeenCalled();
  });

  it('keeps settings available when GitHub update check fails', async () => {
    bridge({check_updates: vi.fn(async () => ({ok: false as const, message: 'Проверьте интернет'}))});
    render(<DesktopSettingsPanel allowImport onImport={vi.fn()} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', {name: 'Проверить обновления'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Проверьте интернет');
    expect(screen.getByRole('button', {name: 'Применить настройки'})).toBeEnabled();
  });

  it('does not expose desktop settings in the ordinary web application', () => {
    render(<DesktopSettingsButton allowImport onImport={vi.fn()} />);
    expect(screen.queryByRole('button', {name: 'Настройки приложения'})).toBeNull();
  });

  it('recognizes the native bridge after its delayed ready event', async () => {
    render(<DesktopSettingsButton allowImport onImport={vi.fn()} />);
    await act(async () => {bridge(); window.dispatchEvent(new Event('pywebviewready'));});
    expect(screen.getByRole('button', {name: 'Настройки приложения'})).toBeVisible();
  });

  it('applies settings without reading or displaying an existing key', async () => {
    const native = bridge();
    render(<DesktopSettingsPanel allowImport onImport={vi.fn()} onClose={vi.fn()} />);
    const input = await screen.findByLabelText('API-ключ Gemini');
    expect(input).toHaveValue('');
    await userEvent.type(input, 'new-private-key');
    const model = screen.getByLabelText('Модель Gemini');
    await userEvent.clear(model);
    await userEvent.type(model, 'gemini-3.5-flash');
    await userEvent.click(screen.getByRole('button', {name: 'Применить настройки'}));
    await screen.findByText(/Настройки применены/);
    expect(native.save_settings).toHaveBeenCalledWith(expect.objectContaining({api_key: 'new-private-key', key_action: 'set', model: 'gemini-3.5-flash'}));
    expect(input).toHaveValue('');
    expect(localStorage.getItem('GEMINI_API_KEY')).toBeNull();
  });

  it('offers session keys when the system vault is unavailable', async () => {
    bridge({get_settings: vi.fn(async () => ({ok: true as const, value: {...values, secure_storage_available: false}}))});
    render(<DesktopSettingsPanel allowImport onImport={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByLabelText(/Запомнить новый ключ/)).toBeDisabled();
    expect(screen.getByText(/только до закрытия приложения/)).toBeVisible();
  });

  it('keeps the dialog and unsaved key open when applying settings fails', async () => {
    bridge({save_settings: vi.fn(async () => ({ok: false as const, message: 'Системное хранилище недоступно'}))});
    const close = vi.fn();
    render(<DesktopSettingsPanel allowImport onImport={vi.fn()} onClose={close} />);
    await userEvent.type(await screen.findByLabelText('API-ключ Gemini'), 'retry-key');
    await userEvent.click(screen.getByRole('button', {name: 'Применить настройки'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Системное хранилище недоступно');
    expect(screen.getByLabelText('API-ключ Gemini')).toHaveValue('retry-key');
    expect(close).not.toHaveBeenCalled();
  });

  it('blocks import when the current project has unsaved changes and refreshes after success', async () => {
    const native = bridge();
    const imported = vi.fn(async () => {});
    const {rerender} = render(<DesktopSettingsPanel allowImport={false} onImport={imported} onClose={vi.fn()} />);
    expect(await screen.findByRole('button', {name: 'Импортировать проекты из папки'})).toBeDisabled();
    rerender(<DesktopSettingsPanel allowImport onImport={imported} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', {name: 'Импортировать проекты из папки'}));
    await screen.findByText(/Импорт завершён: проектов 2, построений 3/);
    expect(imported).toHaveBeenCalledOnce();
    expect(native.import_data).toHaveBeenCalledOnce();
  });

  it('saves desktop exports natively and keeps the web PDF export available', async () => {
    const native = bridge();
    const webDownload = vi.spyOn(api, 'downloadA4Pdf').mockResolvedValue({blob: new Blob(['%PDF']), filename: 'pattern.pdf'});
    await saveExport('generation', 'a4-pdf');
    expect(native.save_export).toHaveBeenCalledWith('generation', 'a4-pdf');
    expect(webDownload).not.toHaveBeenCalled();
    delete window.pywebview;
    const url = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:pdf');
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await saveExport('generation', 'a4-pdf');
    expect(webDownload).toHaveBeenCalledOnce();
    expect(url).toHaveBeenCalledOnce();
  });

  it('treats cancellation as a completed action without falling back to a web download', async () => {
    bridge({save_export: vi.fn(async () => ({ok: true as const, value: {cancelled: true}}))});
    const webDownload = vi.spyOn(api, 'downloadA4Pdf');
    await saveExport('generation', 'a4-pdf');
    expect(webDownload).not.toHaveBeenCalled();
  });

  it('turns selected native photos into the same File objects as web uploads', async () => {
    bridge({choose_images: vi.fn(async () => ({ok: true as const, value: [{name: 'front.png', type: 'image/png', data_base64: btoa('image-bytes')}]}))});
    const files = await chooseDesktopImages();
    expect(files[0].name).toBe('front.png');
    expect(files[0].type).toBe('image/png');
    expect(files[0].size).toBe(11);
  });

  it('reloads provider settings without cancelling analysis or removing selected photos', async () => {
    bridge({choose_images: vi.fn(async () => ({ok: true as const, value: [{name: 'front.png', type: 'image/png', data_base64: btoa('image-bytes'), last_modified: 1000}]}))});
    const providers = vi.spyOn(api, 'visionProviders').mockResolvedValue({default_provider: 'gemini', items: [{provider_id: 'gemini', name: 'Gemini', model: 'gemini-3.6-flash', configured: true, is_default: true, enabled_for_users: true, sends_images_external: true, message_ru: 'ok'}]});
    vi.spyOn(api, 'uploadImage').mockResolvedValue({image_ref: 'img_test', media_type: 'image/png', size_bytes: 11});
    const analysis = vi.spyOn(api, 'analyzeImages').mockImplementation(() => new Promise<StyleAnalysis>(() => {}));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:photo');
    const revoked = vi.spyOn(URL, 'revokeObjectURL');
    render(<VisionAnalyzer projectId="project" onComplete={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', {name: 'Открыть фотографии с компьютера'}));
    await screen.findByRole('img', {name: /front.png/});
    await userEvent.click(screen.getByRole('checkbox', {name: /Я разрешаю отправить/}));
    await userEvent.click(screen.getByRole('button', {name: /Проанализировать изображения/}));
    await waitFor(() => expect(analysis).toHaveBeenCalledOnce());
    const signal = analysis.mock.calls[0][4];
    await act(async () => {window.dispatchEvent(new Event('kroika:ai-settings-changed'));});
    await waitFor(() => expect(providers).toHaveBeenCalledTimes(2));
    expect(signal?.aborted).toBe(false);
    expect(revoked).not.toHaveBeenCalled();
    expect(screen.getByRole('img', {name: /front.png/})).toBeVisible();
  });
});

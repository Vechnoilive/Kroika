import {useEffect, useState} from 'react';
import type {VisionProviderId} from './types';

export interface DesktopSettings {
  provider: VisionProviderId;
  model: string;
  thinking: 'auto' | 'minimal' | 'low';
  timeout: number;
  max_output_tokens: number;
  api_mode: 'generate_content' | 'interactions';
  attempts: number;
  has_key: boolean;
  key_storage: string;
  secure_storage_available: boolean;
  key_cleanup_warning?: boolean;
  data_dir: string;
  images_dir: string;
  logs_dir: string;
  app_version?: string;
  packaged?: boolean;
  releases_url?: string;
}

export type SettingsInput = Pick<DesktopSettings,
  'provider' | 'model' | 'thinking' | 'timeout' | 'max_output_tokens' | 'api_mode' | 'attempts'
> & {key_action: 'keep' | 'set' | 'remove'; api_key: string; remember: boolean};

export type ExportKind = 'a4-pdf' | 'scale-check-pdf' | 'print-svg' | 'project-json' | 'acceptance-report';
export type NativeResult<T> = {ok: true; value: T} | {ok: false; message: string};
export interface ImportResult {
  cancelled: boolean;
  projects?: number;
  generations?: number;
  measurement_profiles?: number;
  skipped?: number;
}

export interface DesktopApi {
  check_updates(): Promise<NativeResult<{current_version: string; latest_version: string | null; available: boolean; release_url: string}>>;
  get_settings(): Promise<NativeResult<DesktopSettings>>;
  save_settings(value: SettingsInput): Promise<NativeResult<DesktopSettings>>;
  choose_images(): Promise<NativeResult<Array<{name: string; type: string; data_base64: string; last_modified?: number}>>>;
  save_export(id: string, kind: ExportKind): Promise<NativeResult<{cancelled: boolean; path?: string}>>;
  import_data(): Promise<NativeResult<ImportResult>>;
  open_folder(kind: 'data' | 'logs' | 'backups'): Promise<NativeResult<null>>;
}

declare global {
  interface Window {pywebview?: {api?: DesktopApi}}
}

export function desktopApi(): DesktopApi | null {
  const candidate = window.pywebview?.api;
  return candidate && typeof candidate.get_settings === 'function' ? candidate : null;
}

export function useDesktopAvailable(): boolean {
  const [available, setAvailable] = useState(Boolean(desktopApi()));
  useEffect(() => {
    const ready = () => setAvailable(Boolean(desktopApi()));
    window.addEventListener('pywebviewready', ready);
    ready();
    return () => window.removeEventListener('pywebviewready', ready);
  }, []);
  return available;
}

export function nativeValue<T>(result: NativeResult<T>): T {
  if (!result.ok) throw new Error(result.message);
  return result.value;
}

export async function chooseDesktopImages(): Promise<File[]> {
  const bridge = desktopApi();
  if (!bridge) return [];
  const images = nativeValue(await bridge.choose_images());
  return images.map((item) => {
    const bytes = Uint8Array.from(atob(item.data_base64), (character) => character.charCodeAt(0));
    return new File([bytes], item.name, {type: item.type, lastModified: item.last_modified});
  });
}

import {useEffect, useRef, useState, type FormEvent} from 'react';
import {api} from './api';
import {desktopApi, nativeValue, useDesktopAvailable, type DesktopSettings, type SettingsInput} from './desktop';

export function DesktopSettingsButton({allowImport, onImport}: {
  allowImport: boolean;
  onImport: () => Promise<void>;
}) {
  const available = useDesktopAvailable();
  const [open, setOpen] = useState(false);
  const [connectGemini, setConnectGemini] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!available) return;
    const connect = () => {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setConnectGemini(true); setOpen(true);
    };
    window.addEventListener('kroika:configure-gemini', connect);
    return () => window.removeEventListener('kroika:configure-gemini', connect);
  }, [available]);
  if (!available) return null;
  return <>
    <button type="button" className="text-button" ref={button} onClick={() => {
      returnFocus.current = button.current; setConnectGemini(false); setOpen(true);
    }}>Настройки приложения</button>
    {open && <DesktopSettingsPanel allowImport={allowImport} onImport={onImport} connectGemini={connectGemini} onClose={() => {
      setOpen(false); returnFocus.current?.focus();
    }} />}
  </>;
}

export function DesktopSettingsPanel({allowImport, onImport, onClose, connectGemini = false}: {
  allowImport: boolean; onImport: () => Promise<void>; onClose: () => void; connectGemini?: boolean;
}) {
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [key, setKey] = useState('');
  const [remove, setRemove] = useState(false);
  const [remember, setRemember] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const container = useRef<HTMLDivElement>(null);
  const keyInput = useRef<HTMLInputElement>(null);
  const ready = settings !== null;
  useEffect(() => {if (ready && connectGemini) keyInput.current?.focus();}, [ready, connectGemini]);
  useEffect(() => {
    let active = true;
    const bridge = desktopApi();
    if (bridge) bridge.get_settings().then(nativeValue).then((value) => {
      if (active) {setSettings(connectGemini ? {...value, provider: 'gemini'} : value); setRemember(value.secure_storage_available);}
    }).catch(() => {if (active) setError('Не удалось загрузить настройки приложения.');});
    container.current?.focus();
    return () => {active = false;};
  }, [connectGemini]);

  async function run(action: () => Promise<void>) {
    setWorking(true); setError(''); setNotice('');
    try {await action();}
    catch (caught) {setError(caught instanceof Error ? caught.message : 'Действие не выполнено.');}
    finally {setWorking(false);}
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const bridge = desktopApi();
    if (!bridge || !settings) return;
    const payload: SettingsInput = {
      provider: settings.provider, model: settings.model, thinking: settings.thinking,
      timeout: settings.timeout, max_output_tokens: settings.max_output_tokens,
      api_mode: settings.api_mode, attempts: settings.attempts,
      key_action: remove ? 'remove' : key.trim() ? 'set' : 'keep', api_key: key, remember,
    };
    await run(async () => {
      const value = nativeValue(await bridge.save_settings(payload));
      setSettings(value); setKey(''); setRemove(false);
      window.dispatchEvent(new Event('kroika:ai-settings-changed'));
      setNotice(value.key_cleanup_warning
        ? 'Настройки применены, старый ключ больше не используется. Системное хранилище не позволило удалить старую запись ключа; удалите её в диспетчере учётных данных.'
        : 'Настройки применены. Новые запросы используют выбранную модель.');
    });
  }

  function change<K extends keyof DesktopSettings>(field: K, value: DesktopSettings[K]) {
    setSettings((current) => current ? {...current, [field]: value} : current);
  }

  return <div className="desktop-modal-backdrop">
    <div className="desktop-settings" role="dialog" aria-modal="true" aria-labelledby="desktop-settings-title"
      ref={container} tabIndex={-1} onKeyDown={(event) => {
        if (event.key === 'Escape' && !working) {event.preventDefault(); onClose();}
        if (event.key === 'Tab') {
          const focusable = Array.from(container.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary') ?? []);
          const first = focusable[0]; const last = focusable[focusable.length - 1];
          if (event.shiftKey && (document.activeElement === first || document.activeElement === container.current)) {event.preventDefault(); last?.focus();}
          else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
        }
      }}>
      <header><div><p className="eyebrow">Кройка на компьютере</p><h2 id="desktop-settings-title">{connectGemini ? 'Подключение Gemini' : 'Настройки приложения'}</h2></div><button type="button" onClick={onClose} disabled={working} aria-label="Закрыть настройки">✕</button></header>
      {error && <p className="notice notice--error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {!settings && !error && <p role="status">Загружаем настройки…</p>}
      {settings && <>
        <form onSubmit={(event) => void save(event)}>
          <fieldset disabled={working}><legend>Анализ фотографий</legend>
            <label>Сервис анализа<select value={settings.provider} onChange={(event) => change('provider', event.target.value as DesktopSettings['provider'])}><option value="mock">Демо-режим</option><option value="gemini">Gemini</option><option value="qwen">Qwen из настроек запуска</option></select></label>
            <label>Модель Gemini<input value={settings.model} maxLength={100} onChange={(event) => change('model', event.target.value)} autoComplete="off" /></label>
            {connectGemini && <p>Вставьте свой ключ и нажмите «Применить настройки». После закрытия настроек можно выбрать фотографии и запустить анализ.</p>}
            <label>API-ключ Gemini<input ref={keyInput} type="password" value={key} onChange={(event) => {setKey(event.target.value); setRemove(false);}} autoComplete="new-password" maxLength={2048} placeholder={settings.has_key ? 'Ключ задан. Оставьте пустым, чтобы сохранить его.' : 'Вставьте ключ'} /></label>
            <a href="https://aistudio.google.com/api-keys" target="_blank" rel="noreferrer">Получить API-ключ в Google AI Studio</a>
            <small>{settings.has_key ? `Ключ задан · ${settings.key_storage === 'system' ? 'системное хранилище' : settings.key_storage === 'session' ? 'только текущий сеанс' : 'из настроек запуска'}` : 'Ключ не задан'}</small>
            <label className="desktop-checkbox"><input type="checkbox" checked={remember} disabled={!settings.secure_storage_available} onChange={(event) => setRemember(event.target.checked)} />Запомнить новый ключ в системном хранилище</label>
            {!settings.secure_storage_available && <small>Системное хранилище недоступно. Новый ключ будет действовать только до закрытия приложения.</small>}
            {settings.has_key && <label className="desktop-checkbox"><input type="checkbox" checked={remove} onChange={(event) => {setRemove(event.target.checked); setKey('');}} />Удалить сохранённый ключ при применении</label>}
            <details><summary>Параметры ответа модели</summary><div className="desktop-advanced">
              <label>Размышление<select value={settings.thinking} onChange={(event) => change('thinking', event.target.value as DesktopSettings['thinking'])}><option value="auto">Автоматически</option><option value="minimal">Минимальное</option><option value="low">Низкое</option></select></label>
              <label>Ожидание ответа, секунды<input type="number" min={0} max={1800} value={settings.timeout} onChange={(event) => change('timeout', Number(event.target.value))} /></label><small>0 — ждать без ограничения. Повторы при 503 остаются ограниченными.</small>
              <label>Максимум выходных токенов<input type="number" min={1024} max={65536} value={settings.max_output_tokens} onChange={(event) => change('max_output_tokens', Number(event.target.value))} /></label>
              <label>Число попыток<input type="number" min={1} max={3} value={settings.attempts} onChange={(event) => change('attempts', Number(event.target.value))} /></label>
              <label>API Gemini<select value={settings.api_mode} onChange={(event) => change('api_mode', event.target.value as DesktopSettings['api_mode'])}><option value="generate_content">Generate content</option><option value="interactions">Interactions</option></select></label>
            </div></details>
            <button className="primary-button" type="submit">{working ? 'Применяем…' : 'Применить настройки'}</button>
            <button className="text-button" type="button" onClick={() => void run(async () => {
              const result = await api.checkVisionProvider('gemini'); setNotice(result.message_ru);
            })}>Проверить сохранённое подключение Gemini</button>
            <small>Проверка отправляет короткий текст без фотографий. Ключ не включается в файлы проектов.</small>
          </fieldset>
        </form>
        <section className="desktop-data"><h3>Проекты и файлы</h3><p className="desktop-path">{settings.data_dir}</p>
          <button type="button" disabled={working} onClick={() => void run(async () => {nativeValue(await desktopApi()!.open_folder('data'));})}>Открыть папку проектов</button>
          <button type="button" disabled={working || !allowImport} onClick={() => void run(async () => {
            const result = nativeValue(await desktopApi()!.import_data());
            if (result.cancelled) return;
            await onImport();
            setNotice(`Импорт завершён: проектов ${result.projects ?? 0}, построений ${result.generations ?? 0}, профилей ${result.measurement_profiles ?? 0}. Существующие записи сохранены.`);
          })}>Импортировать проекты из папки</button>
          <small>{allowImport ? 'Выберите прежнюю папку data или корень старой Кройки. Перенесутся фото, история, результаты и профили. При конфликте импорт будет отменён.' : 'Сначала сохраните текущие изменения проекта.'}</small>
          <button type="button" disabled={working} onClick={() => void run(async () => {nativeValue(await desktopApi()!.open_folder('backups'));})}>Исходные копии импорта</button>
          <button type="button" disabled={working} onClick={() => void run(async () => {nativeValue(await desktopApi()!.open_folder('logs'));})}>Открыть папку журналов</button>
        </section>
        <section className="desktop-data"><h3>Версия и обновления</h3>
          <p>Кройка {settings.app_version ?? 'из исходников'}{settings.packaged ? ' · приложение Windows' : ''}</p>
          <button type="button" disabled={working} onClick={() => void run(async () => {
            const result = nativeValue(await desktopApi()!.check_updates());
            setNotice(result.available
              ? `Доступна версия ${result.latest_version}. Сохраните проект, закройте Кройку и запустите новый установщик со страницы выпусков.`
              : result.latest_version ? 'Новых готовых выпусков не найдено.' : 'Выпуски приложения пока не опубликованы.');
          })}>Проверить обновления</button>
          <a href="https://github.com/Vechnoilive/Kroika/releases" target="_blank" rel="noreferrer">Открыть страницу выпусков</a>
          <small>Проверка обращается к GitHub без фотографий и API-ключа. Обновление устанавливается после закрытия приложения; проекты и настройки сохраняются.</small>
        </section>
      </>}
    </div>
  </div>;
}

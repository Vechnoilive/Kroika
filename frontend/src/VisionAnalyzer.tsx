import {FormEvent, useEffect, useMemo, useState} from 'react';
import {api, ApiError} from './api';
import type {StyleAnalysis, VisionProviderId, VisionProviderStatus} from './types';

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const FALLBACK_MOCK: VisionProviderStatus = {
  provider_id: 'mock', name: 'Демо-режим', model: 'offline fixture',
  configured: true, is_default: true, enabled_for_users: true, sends_images_external: false,
  message_ru: 'Работает без интернета и не отправляет фото.',
};

export function VisionAnalyzer({
  projectId,
  onComplete,
}: {
  projectId: string;
  onComplete: (
    analysis: StyleAnalysis,
    details: {providerId: VisionProviderId; providerName: string; imageRefs: string[]},
  ) => Promise<void>;
}) {
  const [providers, setProviders] = useState<VisionProviderStatus[]>([FALLBACK_MOCK]);
  const [providerId, setProviderId] = useState<VisionProviderId>('mock');
  const [files, setFiles] = useState<File[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.visionProviders().then((result) => {
      if (!active) return;
      const visible = result.items.filter((item) => item.enabled_for_users);
      setProviders(visible.length ? visible : [FALLBACK_MOCK]);
      const preferred = visible.find(
        (item) => item.provider_id === result.default_provider && item.configured,
      );
      setProviderId(preferred?.provider_id ?? 'mock');
    }).catch(() => {
      if (active) setError('Не удалось получить список сервисов. Демо-режим остаётся доступен.');
    });
    return () => { active = false; };
  }, []);

  const selected = useMemo(
    () => providers.find((item) => item.provider_id === providerId),
    [providerId, providers],
  );
  const isExternal = selected?.sends_images_external ?? false;

  function chooseFiles(chosen: FileList | null) {
    setError(null);
    if (!chosen || chosen.length === 0) {
      setFiles([]);
      return;
    }
    const selectedFiles = Array.from(chosen);
    if (selectedFiles.length > 4) {
      setFiles([]);
      setError('Можно добавить от одного до четырёх изображений.');
      return;
    }
    if (selectedFiles.some((item) => !ALLOWED_TYPES.includes(item.type))) {
      setFiles([]);
      setError('Выберите изображение JPEG, PNG или WebP.');
      return;
    }
    if (selectedFiles.some((item) => item.size > MAX_IMAGE_BYTES)) {
      setFiles([]);
      setError('Один из файлов слишком большой. Максимум — 10 МБ на изображение.');
      return;
    }
    setFiles(selectedFiles);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (isExternal && files.length === 0) {
      setError('Сначала выберите фотографию или эскиз изделия.');
      return;
    }
    if (isExternal && !consent) {
      setError('Подтвердите отправку изображения выбранному сервису.');
      return;
    }
    setBusy(true);
    try {
      const storedImageRefs = isExternal
        ? await Promise.all(files.map(async (item) => (await api.uploadImage(item)).image_ref))
        : [];
      const analysisImageRefs = storedImageRefs.length
        ? storedImageRefs
        : ['img_demo_front_12345678'];
      const result = await api.analyzeImages(projectId, analysisImageRefs, providerId);
      await onComplete(result, {
        providerId,
        providerName: selected?.name ?? 'Демо-режим',
        imageRefs: storedImageRefs,
      });
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught.message
        : 'Не удалось проанализировать изображение. Попробуйте ещё раз.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="vision-card" onSubmit={(event) => void submit(event)}>
      <div className="action-card__icon" aria-hidden="true">02</div>
      <div className="vision-card__body">
        <p className="eyebrow">Анализ фасона</p>
        <h2>Добавьте эскиз или фотографию</h2>
        <p>Сначала выберите способ анализа. Мерки и чертежи никогда не отправляются модели.</p>

        <fieldset className="provider-choice">
          <legend>Кто проанализирует изображение?</legend>
          {providers.map((provider) => (
            <label key={provider.provider_id} className={!provider.configured ? 'provider--disabled' : ''}>
              <input
                type="radio"
                name="vision-provider"
                value={provider.provider_id}
                checked={providerId === provider.provider_id}
                disabled={!provider.configured || busy}
                onChange={() => {
                  setProviderId(provider.provider_id);
                  setConsent(false);
                  setError(null);
                }}
              />
              <span>
                <strong>{provider.name}</strong>
                <small>{provider.message_ru}</small>
              </span>
              {provider.is_default && <em>по умолчанию</em>}
            </label>
          ))}
        </fieldset>

        {isExternal && (
          <div className="image-fields">
            <label className="file-picker" htmlFor="garment-image">
              <strong>{files.length ? `Выбрано изображений: ${files.length}` : 'Выбрать изображения'}</strong>
              <small>1–4 файла · JPEG, PNG или WebP · до 10 МБ каждый</small>
            </label>
            <input
              id="garment-image"
              className="visually-hidden"
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={busy}
              onChange={(event) => chooseFiles(event.target.files)}
            />
            {files.length > 0 && (
              <ul className="selected-files" aria-label="Выбранные изображения">
                {files.map((item) => <li key={`${item.name}-${item.size}`}>{item.name}</li>)}
              </ul>
            )}
            <label className="consent-row">
              <input
                type="checkbox"
                checked={consent}
                disabled={busy}
                onChange={(event) => setConsent(event.target.checked)}
              />
              <span>Я разрешаю отправить только это изображение в {selected?.name}. Мерки останутся локально.</span>
            </label>
          </div>
        )}

        {!isExternal && (
          <div className="mock-preview" aria-hidden="true">
            <svg viewBox="0 0 240 250" role="img">
              <path d="M92 23c8 12 48 12 56 0l23 23-19 30-7-8 15 155H80L95 68l-7 8-19-30 23-23Z" />
              <path d="M95 68c17 9 33 9 50 0M88 126h64M120 35v188" />
            </svg>
            <span>Без отправки фотографии</span>
          </div>
        )}

        {error && (
          <div className="inline-error" role="alert">
            {error}
            {isExternal && (
              <button type="button" onClick={() => { setProviderId('mock'); setError(null); }}>
                Перейти в демо-режим
              </button>
            )}
          </div>
        )}
        <button className="primary-button" type="submit" disabled={busy || !selected?.configured}>
          {busy ? 'Анализируем…' : isExternal ? 'Проанализировать изображение' : 'Продолжить в демо-режиме'}
          <span aria-hidden="true">→</span>
        </button>
        <p className="demo-warning">
          {isExternal
            ? <><strong>Важно:</strong> результат — подсказка. Все сомнения модель превратит в вопросы.</>
            : <><strong>Без передачи фото:</strong> используется заранее подготовленный ответ.</>}
        </p>
      </div>
    </form>
  );
}

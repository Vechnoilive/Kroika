import {FormEvent, useEffect, useMemo, useRef, useState} from 'react';
import {api, ApiError} from './api';
import type {
  ImageViewRole,
  StyleAnalysis,
  VisionProviderCheck,
  VisionProviderId,
  VisionProviderStatus,
} from './types';

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const DEFAULT_VIEWS: ImageViewRole[] = ['front', 'back', 'side', 'detail'];
const VIEW_OPTIONS: Array<{value: ImageViewRole; label: string}> = [
  {value: 'front', label: 'Вид спереди'},
  {value: 'back', label: 'Вид сзади'},
  {value: 'side', label: 'Вид сбоку'},
  {value: 'detail', label: 'Крупная деталь'},
  {value: 'flat_sketch', label: 'Плоский эскиз'},
  {value: 'unknown', label: 'Другой вид'},
];
const FALLBACK_MOCK: VisionProviderStatus = {
  provider_id: 'mock', name: 'Демо-режим', model: 'offline fixture',
  configured: true, is_default: true, enabled_for_users: true, sends_images_external: false,
  message_ru: 'Работает без интернета и не отправляет фото.',
};

type Rotation = 0 | 90 | 180 | 270;
type AnalysisPhase = 'idle' | 'uploading' | 'analyzing' | 'saving';

interface SelectedImage {
  id: string;
  file: File;
  previewUrl: string;
  view: ImageViewRole;
  rotation: Rotation;
  imageRef?: string;
}

function phaseLabel(phase: AnalysisPhase): string {
  if (phase === 'uploading') return 'Сохраняем изображения локально';
  if (phase === 'analyzing') return 'Модель анализирует фасон';
  if (phase === 'saving') return 'Проверяем и сохраняем результат';
  return '';
}

function errorHint(error: ApiError): string | null {
  if (error.code === 'TIMEOUT') return 'Сервис не успел ответить. Фотографии повторно загружать не нужно.';
  if (error.code === 'RATE_LIMIT') return 'Подождите немного и нажмите повтор — выбранные фото сохранятся.';
  if (error.code === 'AUTH') return 'Проверьте API-ключ в окне backend и перезапустите приложение.';
  if (error.code === 'PAYMENT_REQUIRED') return 'Проверьте баланс или лимит ключа у провайдера.';
  if (error.code === 'INVALID_SCHEMA') return 'Связь работает, но ответ модели не прошёл строгую проверку Kroika.';
  if (error.code === 'PROVIDER_UNAVAILABLE') return 'Проверьте соединение отдельной кнопкой или временно используйте демо-режим.';
  if (error.code === 'REQUEST_CANCELLED') return 'Можно исправить порядок или подписи и запустить анализ снова.';
  return null;
}

function isAbortError(caught: unknown): boolean {
  return typeof caught === 'object'
    && caught !== null
    && 'name' in caught
    && caught.name === 'AbortError';
}

function createPreviewUrl(file: File): string {
  return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : '';
}

function revokePreviewUrl(url: string): void {
  if (url && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(url);
}

async function rotatedFile(image: SelectedImage): Promise<File> {
  if (image.rotation === 0) return image.file;
  if (typeof createImageBitmap !== 'function') {
    throw new ApiError(
      'Этот браузер не смог повернуть изображение. Поверните файл заранее или выберите исходную ориентацию.',
      0,
      'IMAGE_ROTATION_UNAVAILABLE',
    );
  }
  const bitmap = await createImageBitmap(image.file);
  const swap = image.rotation === 90 || image.rotation === 270;
  const canvas = document.createElement('canvas');
  canvas.width = swap ? bitmap.height : bitmap.width;
  canvas.height = swap ? bitmap.width : bitmap.height;
  const context = canvas.getContext('2d');
  if (!context) {
    bitmap.close();
    throw new ApiError('Не удалось подготовить повёрнутое изображение.', 0, 'IMAGE_ROTATION_FAILED');
  }
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate(image.rotation * Math.PI / 180);
  context.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
  bitmap.close();
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) resolve(result);
      else reject(new ApiError('Не удалось подготовить повёрнутое изображение.', 0, 'IMAGE_ROTATION_FAILED'));
    }, image.file.type, 0.94);
  });
  return new File([blob], image.file.name, {type: image.file.type, lastModified: Date.now()});
}

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
  const [images, setImages] = useState<SelectedImage[]>([]);
  const imagesRef = useRef<SelectedImage[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [phase, setPhase] = useState<AnalysisPhase>('idle');
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [checkResult, setCheckResult] = useState<VisionProviderCheck | null>(null);

  useEffect(() => {
    imagesRef.current = images;
  }, [images]);

  useEffect(() => () => {
    imagesRef.current.forEach((image) => revokePreviewUrl(image.previewUrl));
    abortRef.current?.abort();
  }, []);

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
      if (active) setError(new ApiError(
        'Не удалось получить список сервисов. Демо-режим остаётся доступен.',
        0,
        'PROVIDER_LIST_UNAVAILABLE',
      ));
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!busy) {
      setElapsedSeconds(0);
      return undefined;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const selected = useMemo(
    () => providers.find((item) => item.provider_id === providerId),
    [providerId, providers],
  );
  const isExternal = selected?.sends_images_external ?? false;

  function chooseFiles(chosen: FileList | null) {
    setError(null);
    if (!chosen || chosen.length === 0) return;
    const selectedFiles = Array.from(chosen);
    if (images.length + selectedFiles.length > 4) {
      setError(new ApiError('Можно добавить не больше четырёх изображений.', 0, 'TOO_MANY_IMAGES'));
      return;
    }
    if (selectedFiles.some((item) => !ALLOWED_TYPES.includes(item.type))) {
      setError(new ApiError('Выберите изображение JPEG, PNG или WebP.', 0, 'IMAGE_TYPE_INVALID'));
      return;
    }
    if (selectedFiles.some((item) => item.size > MAX_IMAGE_BYTES)) {
      setError(new ApiError('Один из файлов слишком большой. Максимум — 10 МБ на изображение.', 0, 'IMAGE_TOO_LARGE'));
      return;
    }
    const existingKeys = new Set(images.map((item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`));
    const unique = selectedFiles.filter(
      (item) => !existingKeys.has(`${item.name}:${item.size}:${item.lastModified}`),
    );
    if (!unique.length) {
      setError(new ApiError('Эти изображения уже выбраны.', 0, 'IMAGE_DUPLICATE'));
      return;
    }
    setImages((current) => [...current, ...unique.map((file, offset) => ({
      id: crypto.randomUUID(),
      file,
      previewUrl: createPreviewUrl(file),
      view: DEFAULT_VIEWS[current.length + offset] ?? 'unknown',
      rotation: 0 as Rotation,
    }))]);
    setConsent(false);
    setCheckResult(null);
  }

  function discardUploaded(imageRef?: string) {
    if (!imageRef) return;
    void api.deleteImage(imageRef).catch(() => {
      // A cleanup failure must not block editing; unused files can still be removed locally.
    });
  }

  function removeImage(id: string) {
    setImages((current) => current.filter((image) => {
      if (image.id !== id) return true;
      revokePreviewUrl(image.previewUrl);
      discardUploaded(image.imageRef);
      return false;
    }));
    setConsent(false);
    setError(null);
  }

  function updateView(id: string, view: ImageViewRole) {
    setImages((current) => current.map((image) => image.id === id ? {...image, view} : image));
  }

  function rotate(id: string) {
    setImages((current) => current.map((image) => {
      if (image.id !== id) return image;
      discardUploaded(image.imageRef);
      return {...image, rotation: ((image.rotation + 90) % 360) as Rotation, imageRef: undefined};
    }));
    setConsent(false);
  }

  function move(id: string, direction: -1 | 1) {
    setImages((current) => {
      const index = current.findIndex((image) => image.id === id);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const reordered = [...current];
      [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
      return reordered;
    });
  }

  async function checkProvider() {
    if (!selected || checking) return;
    setChecking(true);
    setError(null);
    setCheckResult(null);
    try {
      setCheckResult(await api.checkVisionProvider(selected.provider_id));
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught
        : new ApiError('Не удалось проверить соединение.', 0, 'PROVIDER_CHECK_FAILED'));
    } finally {
      setChecking(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (isExternal && images.length === 0) {
      setError(new ApiError('Сначала выберите фотографию или эскиз изделия.', 0, 'IMAGE_REQUIRED'));
      return;
    }
    if (isExternal && !consent) {
      setError(new ApiError('Подтвердите отправку изображений выбранному сервису.', 0, 'CONSENT_REQUIRED'));
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setPhase(isExternal ? 'uploading' : 'analyzing');
    try {
      const storedImageRefs: string[] = [];
      if (isExternal) {
        for (const image of images) {
          let imageRef = image.imageRef;
          if (!imageRef) {
            const prepared = await rotatedFile(image);
            if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
            imageRef = (await api.uploadImage(prepared, controller.signal)).image_ref;
            const storedRef = imageRef;
            setImages((current) => current.map((item) => (
              item.id === image.id ? {...item, imageRef: storedRef} : item
            )));
          }
          storedImageRefs.push(imageRef);
        }
      }
      setPhase('analyzing');
      const analysisImageRefs = storedImageRefs.length
        ? storedImageRefs
        : ['img_demo_front_12345678'];
      const imageViews: ImageViewRole[] = isExternal
        ? images.map((image) => image.view)
        : ['front'];
      const result = await api.analyzeImages(
        projectId,
        analysisImageRefs,
        imageViews,
        providerId,
        controller.signal,
      );
      setPhase('saving');
      if (!isExternal) {
        images.forEach((image) => discardUploaded(image.imageRef));
      }
      await onComplete(result, {
        providerId,
        providerName: selected?.name ?? 'Демо-режим',
        imageRefs: storedImageRefs,
      });
    } catch (caught) {
      if (isAbortError(caught)) {
        setError(new ApiError(
          'Запрос отменён. Загруженные изображения сохранены для повтора.',
          0,
          'REQUEST_CANCELLED',
        ));
      } else {
        setError(caught instanceof ApiError
          ? caught
          : new ApiError('Не удалось проанализировать изображение. Попробуйте ещё раз.', 0, 'UNKNOWN_ERROR'));
      }
    } finally {
      setBusy(false);
      setPhase('idle');
      abortRef.current = null;
    }
  }

  return (
    <form className="vision-card" onSubmit={(event) => void submit(event)}>
      <div className="action-card__icon" aria-hidden="true">02</div>
      <div className="vision-card__body">
        <p className="eyebrow">Анализ фасона</p>
        <h2>Добавьте эскиз или фотографию</h2>
        <p>Лучший результат дают виды спереди, сзади и крупные снимки важных деталей.</p>

        <fieldset className="provider-choice">
          <legend>Кто проанализирует изображение?</legend>
          {providers.map((provider) => (
            <label key={provider.provider_id} className={!provider.configured ? 'provider--disabled' : ''}>
              <input
                type="radio"
                name="vision-provider"
                value={provider.provider_id}
                checked={providerId === provider.provider_id}
                disabled={!provider.configured || busy || checking}
                onChange={() => {
                  setProviderId(provider.provider_id);
                  setConsent(false);
                  setError(null);
                  setCheckResult(null);
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

        {isExternal && selected && (
          <div className="provider-diagnostic">
            <span><strong>Модель:</strong> {selected.model}</span>
            <button type="button" className="text-button" disabled={busy || checking} onClick={() => void checkProvider()}>
              {checking ? 'Проверяем…' : 'Проверить соединение'}
            </button>
            <small>Отправится короткий текстовый запрос без фотографий; он может учитываться в лимите API.</small>
            {checkResult && (
              <p className="provider-check provider-check--ready" role="status">
                ✓ {checkResult.message_ru} · {checkResult.latency_ms} мс
              </p>
            )}
          </div>
        )}

        {isExternal && (
          <div className="image-fields">
            <label className="file-picker" htmlFor="garment-image">
              <strong>{images.length ? `Добавить ещё · выбрано ${images.length}` : 'Выбрать изображения'}</strong>
              <small>1–4 файла · JPEG, PNG или WebP · до 10 МБ каждый</small>
            </label>
            <input
              id="garment-image"
              className="visually-hidden"
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={busy || images.length >= 4}
              onChange={(event) => {
                chooseFiles(event.target.files);
                event.target.value = '';
              }}
            />
            {images.length > 0 && (
              <ol className="image-queue" aria-label="Выбранные изображения">
                {images.map((image, index) => (
                  <li key={image.id} className="image-queue__item">
                    <div className="image-thumbnail">
                      {image.previewUrl
                        ? <img src={image.previewUrl} alt={`Предпросмотр: ${image.file.name}`} style={{transform: `rotate(${image.rotation}deg)`}} />
                        : <span aria-hidden="true">Фото {index + 1}</span>}
                    </div>
                    <div className="image-queue__details">
                      <strong title={image.file.name}>{index + 1}. {image.file.name}</strong>
                      <label>
                        <span>Что изображено</span>
                        <select
                          value={image.view}
                          disabled={busy}
                          aria-label={`Вид изображения ${index + 1}`}
                          onChange={(event) => updateView(image.id, event.target.value as ImageViewRole)}
                        >
                          {VIEW_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      </label>
                      {image.imageRef && <small className="image-uploaded">✓ Уже сохранено — повторно не загрузится</small>}
                    </div>
                    <div className="image-queue__actions">
                      <button type="button" disabled={busy || index === 0} aria-label={`Поднять изображение ${index + 1}`} onClick={() => move(image.id, -1)}>↑</button>
                      <button type="button" disabled={busy || index === images.length - 1} aria-label={`Опустить изображение ${index + 1}`} onClick={() => move(image.id, 1)}>↓</button>
                      <button type="button" disabled={busy} aria-label={`Повернуть изображение ${index + 1}`} onClick={() => rotate(image.id)}>↻</button>
                      <button type="button" disabled={busy} aria-label={`Удалить изображение ${index + 1}`} onClick={() => removeImage(image.id)}>×</button>
                    </div>
                  </li>
                ))}
              </ol>
            )}
            <label className="consent-row">
              <input
                type="checkbox"
                checked={consent}
                disabled={busy}
                onChange={(event) => setConsent(event.target.checked)}
              />
              <span>Я разрешаю отправить только выбранные изображения в {selected?.name}. Мерки останутся локально.</span>
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

        {busy && (
          <div className="analysis-progress" role="status" aria-live="polite">
            <span className="analysis-progress__spinner" aria-hidden="true" />
            <div><strong>{phaseLabel(phase)}</strong><small>Прошло {elapsedSeconds} сек. Не закрывайте страницу.</small></div>
            <button type="button" className="text-button" onClick={() => abortRef.current?.abort()}>Отменить</button>
          </div>
        )}

        {error && (
          <div className="inline-error" role="alert">
            <span><strong>{error.message}</strong>{errorHint(error) && <small>{errorHint(error)}</small>}</span>
            {error.requestId && <small>Код обращения: {error.requestId.slice(0, 8)}</small>}
            {isExternal && error.code !== 'REQUEST_CANCELLED' && (
              <button type="button" onClick={() => { setProviderId('mock'); setError(null); }}>
                Перейти в демо-режим
              </button>
            )}
          </div>
        )}
        <button className="primary-button" type="submit" disabled={busy || checking || !selected?.configured}>
          {busy ? phaseLabel(phase) : isExternal ? 'Проанализировать изображения' : 'Продолжить в демо-режиме'}
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

import type {AutosaveState} from './autosave';

export function AutosaveIndicator({
  state,
  savedAt,
  error,
  onRetry,
}: {
  state: AutosaveState;
  savedAt: Date | null;
  error?: string;
  onRetry?: () => void;
}) {
  const message = state === 'saving'
    ? 'Сохраняем изменения…'
    : state === 'unsaved'
      ? 'Есть несохранённые изменения'
      : state === 'error'
        ? 'Автосохранение не сработало — черновик остался в браузере'
        : savedAt
          ? `Сохранено в ${savedAt.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'})}`
          : 'Все изменения сохранены';
  return (
    <div className={`autosave-status autosave-status--${state}`} role="status" aria-live="polite">
      <span aria-hidden="true" />
      <p><strong>{message}</strong>{state === 'error' && error && <small>{error}</small>}</p>
      {state === 'error' && onRetry && (
        <button type="button" onClick={onRetry}>Повторить</button>
      )}
    </div>
  );
}

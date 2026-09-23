import {useEffect, useRef, useState} from 'react';

export type AutosaveState = 'saved' | 'unsaved' | 'saving' | 'error';

interface StoredDraft<T> {
  updated_at: string;
  value: T;
}

export interface LoadedDraft<T> {
  value: T;
  restored: boolean;
}

export function loadLocalDraft<T>(
  storageKey: string,
  fallback: T,
  remoteUpdatedAt: string,
): LoadedDraft<T> {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return {value: fallback, restored: false};
    const stored = JSON.parse(raw) as Partial<StoredDraft<T>>;
    const localTime = Date.parse(stored.updated_at ?? '');
    const remoteTime = Date.parse(remoteUpdatedAt);
    if (stored.value === undefined || !Number.isFinite(localTime) || localTime <= remoteTime) {
      localStorage.removeItem(storageKey);
      return {value: fallback, restored: false};
    }
    return {value: stored.value, restored: true};
  } catch {
    localStorage.removeItem(storageKey);
    return {value: fallback, restored: false};
  }
}

export function useDraftAutosave<T>({
  storageKey,
  initialValue,
  initiallyDirty = false,
  delayMs = 1200,
  save,
  onDirtyChange,
}: {
  storageKey: string;
  initialValue: T;
  initiallyDirty?: boolean;
  delayMs?: number;
  save: (value: T) => Promise<unknown>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [state, setState] = useState<AutosaveState>(initiallyDirty ? 'unsaved' : 'saved');
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [error, setError] = useState('');
  const latestValue = useRef(initialValue);
  const version = useRef(initiallyDirty ? 1 : 0);
  const savedVersion = useRef(0);
  const timer = useRef<number | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const saveRef = useRef(save);
  const dirtyRef = useRef(onDirtyChange);
  const delayRef = useRef(delayMs);

  saveRef.current = save;
  dirtyRef.current = onDirtyChange;
  delayRef.current = delayMs;

  function clearTimer() {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }

  function schedule(wait = delayRef.current) {
    clearTimer();
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void flush();
    }, wait);
  }

  async function flush() {
    if (inFlight.current) {
      schedule(150);
      return;
    }
    if (version.current === savedVersion.current) return;
    const savingVersion = version.current;
    const candidate = latestValue.current;
    inFlight.current = true;
    if (mounted.current) {
      setState('saving');
      setError('');
    }
    try {
      await saveRef.current(candidate);
      if (savingVersion === version.current) {
        savedVersion.current = savingVersion;
        localStorage.removeItem(storageKey);
        if (mounted.current) {
          setState('saved');
          setSavedAt(new Date());
          dirtyRef.current?.(false);
        }
      }
    } catch (caught) {
      if (mounted.current) {
        setState('error');
        setError(caught instanceof Error ? caught.message : 'Не удалось сохранить изменения.');
        dirtyRef.current?.(true);
      }
    } finally {
      inFlight.current = false;
      if (mounted.current && version.current !== savedVersion.current && savingVersion !== version.current) {
        setState('unsaved');
        schedule();
      }
    }
  }

  function markDirty(value: T) {
    latestValue.current = value;
    version.current += 1;
    try {
      const stored: StoredDraft<T> = {updated_at: new Date().toISOString(), value};
      localStorage.setItem(storageKey, JSON.stringify(stored));
    } catch {
      // Server autosave still protects the draft when browser storage is unavailable.
    }
    setState('unsaved');
    setError('');
    dirtyRef.current?.(true);
    schedule();
  }

  function markSaved(value: T) {
    clearTimer();
    latestValue.current = value;
    version.current += 1;
    savedVersion.current = version.current;
    localStorage.removeItem(storageKey);
    setState('saved');
    setSavedAt(new Date());
    setError('');
    dirtyRef.current?.(false);
  }

  function cancelPending() {
    clearTimer();
  }

  function retry() {
    dirtyRef.current?.(true);
    schedule(0);
  }

  useEffect(() => {
    mounted.current = true;
    if (initiallyDirty) {
      dirtyRef.current?.(true);
      schedule(0);
    }
    return () => {
      mounted.current = false;
      clearTimer();
    };
  }, []);

  return {state, savedAt, error, markDirty, markSaved, cancelPending, retry};
}

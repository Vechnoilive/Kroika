import {FormEvent, useEffect, useState} from 'react';
import {api, ApiError} from './api';
import type {
  PhysicalValidationCreate,
  PhysicalValidationGate,
  PhysicalValidationOutcome,
  PhysicalValidationSummary,
} from './types';

const GATE_LABELS: Record<PhysicalValidationGate, string> = {
  paper: 'Печать 1:1',
  expert: 'Конструктор',
  toile: 'Макет',
};

const STATUS_LABELS = {
  pending: 'Не проверено',
  passed: 'Пройдено',
  failed: 'Есть замечания',
} as const;

function numberValue(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value.replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function PhysicalValidationJournal({
  generationId,
  garmentName,
  onSummary,
}: {
  generationId: string;
  garmentName?: string;
  onSummary?: (summary: PhysicalValidationSummary) => void;
}) {
  const [summary, setSummary] = useState<PhysicalValidationSummary | null>(null);
  const [gate, setGate] = useState<PhysicalValidationGate>('paper');
  const [outcome, setOutcome] = useState<PhysicalValidationOutcome>('passed');
  const [reviewer, setReviewer] = useState('');
  const [notes, setNotes] = useState('');
  const [printer, setPrinter] = useState('');
  const [squareWidth, setSquareWidth] = useState('');
  const [squareHeight, setSquareHeight] = useState('');
  const [controlLine, setControlLine] = useState('');
  const [figureLabel, setFigureLabel] = useState('');
  const [evidenceFiles, setEvidenceFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.physicalValidation(generationId)
      .then((loaded) => {
        if (!active) return;
        setSummary(loaded);
        onSummary?.(loaded);
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof ApiError ? caught.message : 'Не удалось загрузить журнал.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [generationId, onSummary]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const record: PhysicalValidationCreate = {
      gate,
      reviewer_name: reviewer,
      notes,
      ...(gate === 'paper' ? {
        printer_name: printer,
        square_width_mm: numberValue(squareWidth),
        square_height_mm: numberValue(squareHeight),
        control_line_mm: numberValue(controlLine),
      } : {outcome}),
      ...(gate === 'toile' ? {figure_label: figureLabel} : {}),
    };
    if (gate === 'paper' && (
      record.square_width_mm === undefined
      || record.square_height_mm === undefined
      || record.control_line_mm === undefined
    )) {
      setError('Введите все три измерения с распечатанного листа.');
      return;
    }
    setSaving(true);
    const uploadedRefs: string[] = [];
    try {
      for (const file of evidenceFiles) {
        uploadedRefs.push((await api.uploadImage(file)).image_ref);
      }
      record.evidence_image_refs = uploadedRefs;
      const updated = await api.recordPhysicalValidation(generationId, record);
      setSummary(updated);
      onSummary?.(updated);
      setNotes('');
      if (gate === 'paper') {
        setPrinter('');
        setSquareWidth('');
        setSquareHeight('');
        setControlLine('');
      }
      if (gate === 'toile') setFigureLabel('');
      setEvidenceFiles([]);
    } catch (caught) {
      await Promise.allSettled(uploadedRefs.map((imageRef) => api.deleteImage(imageRef)));
      setError(caught instanceof ApiError ? caught.message : 'Не удалось сохранить проверку.');
    } finally {
      setSaving(false);
    }
  }

  async function downloadReport() {
    setReporting(true);
    setError(null);
    try {
      const file = await api.downloadAcceptanceReport(generationId);
      const url = URL.createObjectURL(file.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Не удалось скачать отчёт.');
    } finally {
      setReporting(false);
    }
  }

  return (
    <section className="physical-journal" aria-labelledby="physical-journal-title">
      <header>
        <div>
          <p className="eyebrow">Этап 25 · физическая приёмка</p>
          <h3 id="physical-journal-title">Журнал проверки этой версии</h3>
          <p>{garmentName ?? 'Изделие'} · записи не перезаписываются, повторная проверка добавляется в историю.</p>
        </div>
        <span className={`physical-release physical-release--${summary?.production_allowed ? 'ready' : 'blocked'}`}>
          {summary?.production_allowed ? 'Допуск открыт' : 'Только проверка'}
        </span>
      </header>

      <div className={`notice ${summary?.production_allowed ? 'notice--success' : 'notice--warning'}`}>
        <strong>{summary?.production_allowed
          ? 'Все три проверки пройдены для этой версии'
          : 'Печатать можно для проверки — кроить ткань пока нельзя'}</strong>
        <span>{summary?.production_allowed
          ? 'Экспорт этой генерации будет помечен как production. Новая версия потребует новых проверок.'
          : 'Нужны точная печать на двух принтерах, заключение конструктора и три успешных макета на разных фигурах.'}</span>
      </div>

      <button className="secondary-button physical-report-download" type="button" onClick={() => void downloadReport()} disabled={reporting || loading}>
        {reporting ? 'Готовим отчёт…' : 'Скачать PDF-отчёт приёмки'} <span aria-hidden="true">↓</span>
      </button>

      <div className="physical-gates" aria-label="Состояние физических проверок">
        {(['paper', 'expert', 'toile'] as const).map((item) => {
          const gateStatus = summary?.gates.find((entry) => entry.gate === item);
          const state = gateStatus?.status ?? 'pending';
          return (
            <button
              key={item}
              type="button"
              className={`physical-gate physical-gate--${state}`}
              aria-pressed={gate === item}
              onClick={() => setGate(item)}
            >
              <span>{state === 'passed' ? '✓' : state === 'failed' ? '!' : '○'}</span>
              <strong>{GATE_LABELS[item]}</strong>
              <small>{STATUS_LABELS[state]}{gateStatus && gateStatus.required_observations > 1
                ? ` · ${gateStatus.passed_observations}/${gateStatus.required_observations}`
                : ''}</small>
            </button>
          );
        })}
      </div>

      {loading ? <p className="physical-loading">Загружаем журнал…</p> : (
        <form className="physical-form" onSubmit={(event) => void save(event)}>
          <h4>Добавить запись: {GATE_LABELS[gate]}</h4>
          {gate === 'paper' && (
            <>
              <label className="physical-wide">Принтер
                <input required minLength={2} maxLength={120} value={printer} onChange={(event) => setPrinter(event.target.value)} placeholder="Например, HP LaserJet M404" />
              </label>
              <label>Ширина квадрата
                <span><input required inputMode="decimal" value={squareWidth} onChange={(event) => setSquareWidth(event.target.value)} /><em>мм</em></span>
              </label>
              <label>Высота квадрата
                <span><input required inputMode="decimal" value={squareHeight} onChange={(event) => setSquareHeight(event.target.value)} /><em>мм</em></span>
              </label>
              <label>Линия 200 мм
                <span><input required inputMode="decimal" value={controlLine} onChange={(event) => setControlLine(event.target.value)} /><em>мм</em></span>
              </label>
              <p className="physical-hint">Результат рассчитывается автоматически: 50 ±1 мм по обеим сторонам и 200 ±1 мм по длинной линии.</p>
            </>
          )}
          {gate !== 'paper' && (
            <fieldset className="physical-outcome">
              <legend>Результат</legend>
              <label><input type="radio" name="physical-outcome" checked={outcome === 'passed'} onChange={() => setOutcome('passed')} /> Пройдено</label>
              <label><input type="radio" name="physical-outcome" checked={outcome === 'failed'} onChange={() => setOutcome('failed')} /> Есть замечания</label>
            </fieldset>
          )}
          {gate === 'toile' && (
            <label className="physical-wide">Фигура или профиль мерок
              <input required minLength={2} maxLength={120} value={figureLabel} onChange={(event) => setFigureLabel(event.target.value)} placeholder="Например, профиль Анна · макет 1" />
            </label>
          )}
          <label className="physical-wide">Кто проверил
            <input required minLength={2} maxLength={120} value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Имя проверяющего" />
          </label>
          <label className="physical-wide">Замечания
            <textarea required={outcome === 'failed' && gate !== 'paper'} maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Что проверили и что нужно поправить" />
          </label>
          <label className="physical-wide physical-evidence">Фото бумажной сборки или макета · до 4 файлов
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length > 4) {
                  setError('Можно приложить не больше четырёх фотографий к одной записи.');
                  event.target.value = '';
                  return;
                }
                setError(null);
                setEvidenceFiles(files);
              }}
            />
            <small>Хранятся только локально и не отправляются Qwen или Gemini.</small>
          </label>
          {evidenceFiles.length > 0 && (
            <ul className="physical-evidence-list physical-wide">
              {evidenceFiles.map((file) => <li key={`${file.name}-${file.lastModified}`}>{file.name}</li>)}
            </ul>
          )}
          {error && <div className="inline-error physical-wide" role="alert">{error}</div>}
          <button className="primary-button physical-wide" type="submit" disabled={saving}>
            {saving ? 'Сохраняем…' : 'Записать проверку'} <span aria-hidden="true">→</span>
          </button>
        </form>
      )}

      {(summary?.records.length ?? 0) > 0 && (
        <details className="physical-history">
          <summary>История проверок <span>{summary?.records.length}</span></summary>
          <ol>{summary?.records.map((record) => (
            <li key={record.record_id}>
              <span><strong>{GATE_LABELS[record.gate]} · {STATUS_LABELS[record.outcome]}</strong><small>{record.reviewer_name} · {new Date(record.created_at).toLocaleString('ru-RU')}</small></span>
              {record.notes && <p>{record.notes}</p>}
              {record.evidence_image_refs.length > 0 && (
                <div className="physical-history__images" aria-label={`Фото-доказательства: ${record.evidence_image_refs.length}`}>
                  {record.evidence_image_refs.map((imageRef, index) => (
                    <a key={imageRef} href={api.imageUrl(imageRef)} target="_blank" rel="noreferrer">
                      <img src={api.imageUrl(imageRef)} alt={`Фото проверки ${index + 1}`} />
                    </a>
                  ))}
                </div>
              )}
            </li>
          ))}</ol>
        </details>
      )}
    </section>
  );
}

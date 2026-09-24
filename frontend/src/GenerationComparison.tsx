import {useEffect, useMemo, useState} from 'react';
import {api, ApiError} from './api';
import type {
  GenerationComparisonResult,
  GenerationSummary,
  MeasurementChange,
  PieceGeometryChange,
  StyleChange,
} from './types';

const VALUE_LABELS: Record<string, string> = {
  true: 'да',
  false: 'нет',
  dress: 'платье',
  sundress: 'сарафан',
  skirt: 'юбка',
  top: 'топ',
  blouse: 'блузка',
  shirt: 'рубашка',
  vest: 'жилет',
  jacket: 'жакет',
  trousers: 'брюки',
  shorts: 'шорты',
  sleeveless: 'без рукава',
  short: 'короткий',
  long: 'длинный',
  straight: 'прямой',
  a_line: 'А-силуэт',
  fitted: 'прилегающий',
  semi_fitted: 'полуприлегающий',
  woven: 'тканая',
  toile: 'макет',
  final: 'основная ткань',
  by_edge: 'по типу края',
};

function versionLabel(item: GenerationSummary): string {
  const date = new Date(item.created_at).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  return `${date} · ${item.piece_count} дет. · ${item.issue_count} замеч.`;
}

function formatValue(value: unknown, unit?: string | null): string {
  if (value === null || value === undefined) return '—';
  const raw = String(value);
  const translated = VALUE_LABELS[raw] ?? raw;
  const displayUnit = unit === 'mm' ? 'мм' : unit === 'deg' ? '°' : unit;
  return displayUnit && typeof value === 'number' ? `${translated} ${displayUnit}` : translated;
}

function signed(value: number | null, unit: string): string {
  if (value === null) return 'изменено';
  const prefix = value > 0 ? '+' : '';
  const displayUnit = unit === 'mm' ? 'мм' : unit === 'deg' ? '°' : unit;
  return `${prefix}${value}${displayUnit ? ` ${displayUnit}` : ''}`;
}

function MeasurementRow({change}: {change: MeasurementChange}) {
  return (
    <li>
      <span><strong>{change.label_ru}</strong><small>{formatValue(change.before, change.unit)} → {formatValue(change.after, change.unit)}</small></span>
      <em>{signed(change.delta, change.unit)}</em>
    </li>
  );
}

function StyleRow({change}: {change: StyleChange}) {
  return (
    <li>
      <span><strong>{change.label_ru}</strong><small>{change.section} · {formatValue(change.before, change.unit)} → {formatValue(change.after, change.unit)}</small></span>
      {change.delta !== null && <em>{signed(change.delta, change.unit ?? '')}</em>}
    </li>
  );
}

function GeometryRow({change}: {change: PieceGeometryChange}) {
  const metrics = [
    change.width_delta_mm ? `ширина ${signed(change.width_delta_mm, 'мм')}` : null,
    change.height_delta_mm ? `высота ${signed(change.height_delta_mm, 'мм')}` : null,
    change.area_delta_mm2 ? `площадь ${signed(change.area_delta_mm2, 'мм²')}` : null,
    change.perimeter_delta_mm ? `периметр ${signed(change.perimeter_delta_mm, 'мм')}` : null,
    change.segment_count_delta ? `сегменты ${signed(change.segment_count_delta, '')}` : null,
  ].filter(Boolean);
  return (
    <li>
      <span><strong>{change.name_ru}</strong><small>{metrics.join(' · ') || 'Изменилась форма контура'}</small></span>
    </li>
  );
}

export function GenerationComparison({
  projectId,
  currentGenerationId,
}: {
  projectId: string;
  currentGenerationId: string;
}) {
  const [generations, setGenerations] = useState<GenerationSummary[]>([]);
  const [baseId, setBaseId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [comparison, setComparison] = useState<GenerationComparisonResult | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    setError('');
    api.listGenerations(projectId).then(({items}) => {
      if (!active) return;
      setGenerations(items);
      const comparable = items.filter((item) => item.comparable);
      const target = comparable.find((item) => item.generation_id === currentGenerationId)
        ?? comparable[0];
      const base = comparable.find((item) => item.generation_id !== target?.generation_id);
      setTargetId(target?.generation_id ?? '');
      setBaseId(base?.generation_id ?? '');
    }).catch((caught) => {
      if (active) setError(caught instanceof ApiError ? caught.message : 'Не удалось загрузить версии.');
    }).finally(() => {
      if (active) setLoadingList(false);
    });
    return () => { active = false; };
  }, [projectId, currentGenerationId]);

  useEffect(() => {
    if (!baseId || !targetId || baseId === targetId) {
      setComparison(null);
      return;
    }
    let active = true;
    setLoadingComparison(true);
    setError('');
    api.compareGenerations(projectId, baseId, targetId).then((result) => {
      if (active) setComparison(result);
    }).catch((caught) => {
      if (!active) return;
      setComparison(null);
      setError(caught instanceof ApiError ? caught.message : 'Не удалось сравнить версии.');
    }).finally(() => {
      if (active) setLoadingComparison(false);
    });
    return () => { active = false; };
  }, [projectId, baseId, targetId]);

  const comparableCount = useMemo(
    () => generations.filter((item) => item.comparable).length,
    [generations],
  );

  function swap() {
    setBaseId(targetId);
    setTargetId(baseId);
  }

  return (
    <section className="generation-comparison" aria-labelledby="generation-comparison-title">
      <header>
        <div>
          <p className="eyebrow">Этап 26 · сравнение версий</p>
          <h3 id="generation-comparison-title">Что изменилось в выкройке</h3>
          <p>Сравнение использует сохранённые входы и реальные контуры двух генераций одного проекта.</p>
        </div>
        {generations.length > 0 && <span>{generations.length} версий</span>}
      </header>

      {loadingList && <p className="comparison-empty">Загружаем версии…</p>}
      {!loadingList && generations.length < 2 && (
        <p className="comparison-empty">Сравнение появится после построения второй версии выкройки.</p>
      )}
      {!loadingList && generations.length >= 2 && comparableCount < 2 && (
        <p className="comparison-empty">Для старых версий не сохранились два точных снимка входов. Постройте следующую версию — новые сравнения будут доступны автоматически.</p>
      )}

      {comparableCount >= 2 && (
        <div className="comparison-selectors">
          <label>Базовая версия
            <select value={baseId} onChange={(event) => setBaseId(event.target.value)}>
              {generations.map((item) => (
                <option key={item.generation_id} value={item.generation_id} disabled={!item.comparable || item.generation_id === targetId}>
                  {versionLabel(item)}{item.is_current ? ' · текущая' : ''}{!item.comparable ? ' · без снимка' : ''}
                </option>
              ))}
            </select>
          </label>
          <button className="comparison-swap" type="button" onClick={swap} aria-label="Поменять версии местами">⇄</button>
          <label>Новая версия
            <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
              {generations.map((item) => (
                <option key={item.generation_id} value={item.generation_id} disabled={!item.comparable || item.generation_id === baseId}>
                  {versionLabel(item)}{item.is_current ? ' · текущая' : ''}{!item.comparable ? ' · без снимка' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {error && <div className="inline-error" role="alert">{error}</div>}
      {loadingComparison && <p className="comparison-empty">Считаем изменения контуров…</p>}

      {comparison && !loadingComparison && (
        <>
          {comparison.no_changes ? (
            <div className="notice notice--success"><strong>Версии геометрически одинаковы</strong><span>Мерки, фасон, детали и предупреждения не изменились.</span></div>
          ) : (
            <dl className="comparison-totals">
              <div><dt>Мерки</dt><dd>{comparison.totals.measurement_changes}</dd></div>
              <div><dt>Фасон</dt><dd>{comparison.totals.style_changes}</dd></div>
              <div><dt>Новые детали</dt><dd>{comparison.totals.added_pieces}</dd></div>
              <div><dt>Удалено</dt><dd>{comparison.totals.removed_pieces}</dd></div>
              <div><dt>Контуры</dt><dd>{comparison.totals.changed_pieces}</dd></div>
              <div><dt>Проверки</dt><dd>{comparison.totals.validation_changes}</dd></div>
            </dl>
          )}

          <div className="comparison-previews" aria-label="Предпросмотр сравниваемых версий">
            <figure>
              {comparison.base.status === 'succeeded' ? <img src={api.patternPreviewUrl(comparison.base.generation_id, ['cutting', 'seam', 'labels'])} alt="Базовая версия выкройки" /> : <div>Построение отклонено</div>}
              <figcaption>Было · {versionLabel(comparison.base)}</figcaption>
            </figure>
            <figure>
              {comparison.target.status === 'succeeded' ? <img src={api.patternPreviewUrl(comparison.target.generation_id, ['cutting', 'seam', 'labels'])} alt="Новая версия выкройки" /> : <div>Построение отклонено</div>}
              <figcaption>Стало · {versionLabel(comparison.target)}</figcaption>
            </figure>
          </div>

          <div className="comparison-sections">
            <details open={comparison.measurements.length > 0}>
              <summary>Мерки <span>{comparison.measurements.length}</span></summary>
              {comparison.measurements.length > 0
                ? <ul>{comparison.measurements.map((change) => <MeasurementRow key={change.field_id} change={change} />)}</ul>
                : <p>Мерки не менялись.</p>}
            </details>
            <details open={comparison.style.length > 0}>
              <summary>Фасон, прибавки и ткань <span>{comparison.style.length}</span></summary>
              {comparison.style.length > 0
                ? <ul>{comparison.style.map((change) => <StyleRow key={change.path} change={change} />)}</ul>
                : <p>Параметры фасона не менялись.</p>}
            </details>
            <details open={comparison.pattern.changed_pieces.length + comparison.pattern.added_pieces.length + comparison.pattern.removed_pieces.length > 0}>
              <summary>Детали и геометрия <span>{comparison.pattern.piece_count_before} → {comparison.pattern.piece_count_after}</span></summary>
              <p>Листы A4: {comparison.pattern.sheet_count_before ?? '—'} → {comparison.pattern.sheet_count_after ?? '—'}</p>
              {(comparison.pattern.added_pieces.length > 0 || comparison.pattern.removed_pieces.length > 0) && (
                <ul>
                  {comparison.pattern.added_pieces.map((piece) => <li key={`add-${piece.piece_id}`}><span><strong>Добавлена: {piece.name_ru}</strong><small>Кроить: {piece.cut_quantity}{piece.cut_on_fold ? ' · со сгибом' : ''}</small></span></li>)}
                  {comparison.pattern.removed_pieces.map((piece) => <li key={`remove-${piece.piece_id}`}><span><strong>Удалена: {piece.name_ru}</strong><small>Раньше кроить: {piece.cut_quantity}</small></span></li>)}
                </ul>
              )}
              {comparison.pattern.changed_pieces.length > 0
                ? <ul>{comparison.pattern.changed_pieces.map((change) => <GeometryRow key={change.piece_id} change={change} />)}</ul>
                : <p>Контуры общих деталей не менялись.</p>}
            </details>
            <details open={comparison.validation.added_issues.length + comparison.validation.removed_issues.length > 0}>
              <summary>Предупреждения <span>{comparison.validation.status_before} → {comparison.validation.status_after}</span></summary>
              <ul>
                {comparison.validation.added_issues.map((issue) => <li key={`add-${issue.code}-${issue.piece_id}`}><span><strong>Появилось: {issue.code}</strong><small>{issue.message_ru}</small></span></li>)}
                {comparison.validation.removed_issues.map((issue) => <li key={`remove-${issue.code}-${issue.piece_id}`}><span><strong>Устранено: {issue.code}</strong><small>{issue.message_ru}</small></span></li>)}
              </ul>
              {comparison.validation.added_issues.length + comparison.validation.removed_issues.length === 0 && <p>Набор предупреждений не изменился.</p>}
            </details>
          </div>
        </>
      )}
    </section>
  );
}

import {PointerEvent as ReactPointerEvent, useMemo, useRef, useState} from 'react';
import {api, ApiError} from './api';
import type {
  ManualEditHandle,
  ManualPointEditRequest,
  PatternEngineResult,
  PatternPath,
  PatternPiece,
  PatternPoint,
  PatternSegment,
} from './types';

interface PointKey {
  segmentId: string;
  handle: ManualEditHandle;
}

type EditablePatternPiece = PatternPiece & {
  seam_contour: PatternPath;
  cutting_contour: PatternPath | null;
};

function isEditablePiece(piece: PatternPiece): piece is EditablePatternPiece {
  return Boolean(piece.seam_contour?.segments.length);
}

const HANDLE_NAMES: Record<ManualEditHandle, string> = {
  end: 'Узел',
  control_1: 'Направляющая 1',
  control_2: 'Направляющая 2',
};

function clonePieces(pieces: EditablePatternPiece[]): EditablePatternPiece[] {
  return structuredClone(pieces) as EditablePatternPiece[];
}

function point(segment: PatternSegment, handle: ManualEditHandle): PatternPoint | null {
  if (handle === 'end') return segment.end;
  if (segment.type !== 'cubic_bezier') return null;
  return segment[handle];
}

function points(piece: EditablePatternPiece): PointKey[] {
  return piece.seam_contour.segments.flatMap((segment) => [
    {segmentId: segment.id, handle: 'end' as const},
    ...(segment.type === 'cubic_bezier' ? [
      {segmentId: segment.id, handle: 'control_1' as const},
      {segmentId: segment.id, handle: 'control_2' as const},
    ] : []),
  ]);
}

function pathData(path: PatternPath): string {
  const first = path.segments[0]?.start;
  if (!first) return '';
  const commands = [`M ${first[0]} ${first[1]}`];
  path.segments.forEach((segment) => {
    if (segment.type === 'line') commands.push(`L ${segment.end[0]} ${segment.end[1]}`);
    else if (segment.type === 'cubic_bezier') commands.push(
      `C ${segment.control_1[0]} ${segment.control_1[1]} ${segment.control_2[0]} ${segment.control_2[1]} ${segment.end[0]} ${segment.end[1]}`,
    );
    else commands.push(
      `A ${segment.radius_x_mm} ${segment.radius_y_mm} ${segment.rotation_deg} ${segment.large_arc ? 1 : 0} ${segment.sweep ? 1 : 0} ${segment.end[0]} ${segment.end[1]}`,
    );
  });
  if (path.closed) commands.push('Z');
  return commands.join(' ');
}

function updatePoint(
  pieces: EditablePatternPiece[],
  pieceId: string,
  key: PointKey,
  nextPoint: PatternPoint,
): EditablePatternPiece[] {
  const updated = clonePieces(pieces);
  const piece = updated.find((item) => item.id === pieceId);
  if (!piece) return pieces;
  const segments = piece.seam_contour.segments;
  const index = segments.findIndex((segment) => segment.id === key.segmentId);
  if (index < 0) return pieces;
  const segment = segments[index];
  if (key.handle === 'end') {
    segment.end = [...nextPoint];
    segments[(index + 1) % segments.length].start = [...nextPoint];
  } else if (segment.type === 'cubic_bezier') {
    segment[key.handle] = [...nextPoint];
  }
  return updated;
}

function bounds(piece: EditablePatternPiece) {
  const values = piece.seam_contour.segments.flatMap((segment) => [
    segment.start,
    segment.end,
    ...(segment.type === 'cubic_bezier' ? [segment.control_1, segment.control_2] : []),
  ]);
  const xs = values.map((value) => value[0]);
  const ys = values.map((value) => value[1]);
  const margin = 20;
  const minX = Math.min(...xs) - margin;
  const minY = Math.min(...ys) - margin;
  return {
    minX,
    minY,
    width: Math.max(...xs) - minX + margin,
    height: Math.max(...ys) - minY + margin,
  };
}

function editsFrom(
  original: EditablePatternPiece[],
  current: EditablePatternPiece[],
): ManualPointEditRequest[] {
  const edits: ManualPointEditRequest[] = [];
  current.forEach((piece) => {
    const source = original.find((item) => item.id === piece.id);
    if (!source) return;
    piece.seam_contour.segments.forEach((segment) => {
      const old = source.seam_contour.segments.find((item) => item.id === segment.id);
      if (!old) return;
      (['end', 'control_1', 'control_2'] as ManualEditHandle[]).forEach((handle) => {
        const before = point(old, handle);
        const after = point(segment, handle);
        if (!before || !after || (before[0] === after[0] && before[1] === after[1])) return;
        edits.push({
          piece_id: piece.id,
          segment_id: segment.id,
          handle,
          x_mm: after[0],
          y_mm: after[1],
        });
      });
    });
  });
  return edits;
}

export function PatternGeometryEditor({
  result,
  projectRevision,
  onSaved,
}: {
  result: PatternEngineResult;
  projectRevision: number;
  onSaved: (result: PatternEngineResult) => Promise<void> | void;
}) {
  const pattern = result.pattern;
  const editablePieces = useMemo(
    () => (pattern?.pieces ?? []).filter(isEditablePiece),
    [result.generation_id],
  );
  const original = useMemo(() => clonePieces(editablePieces), [editablePieces]);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => clonePieces(editablePieces));
  const [pieceId, setPieceId] = useState(editablePieces[0]?.id ?? '');
  const [selected, setSelected] = useState<PointKey | null>(null);
  const [past, setPast] = useState<EditablePatternPiece[][]>([]);
  const [future, setFuture] = useState<EditablePatternPiece[][]>([]);
  const [snap, setSnap] = useState(1);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dragStart = useRef<EditablePatternPiece[] | null>(null);
  const dragKey = useRef<{pieceId: string; key: PointKey} | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  if (!pattern) return null;
  const piece = draft.find((item) => item.id === pieceId) ?? draft[0];
  if (!piece) return null;
  const originalPiece = original.find((item) => item.id === piece.id) ?? original[0];
  const availablePoints = points(piece);
  const selectedSegment = selected
    ? piece.seam_contour.segments.find((item) => item.id === selected.segmentId)
    : null;
  const selectedPoint = selectedSegment && selected ? point(selectedSegment, selected.handle) : null;
  const view = bounds(piece);
  const edits = editsFrom(original, draft);

  function selectPiece(nextId: string) {
    setPieceId(nextId);
    setSelected(null);
  }

  function commitPoint(nextPoint: PatternPoint) {
    if (!selected) return;
    setPast((items) => [...items, clonePieces(draft)]);
    setFuture([]);
    setDraft(updatePoint(draft, piece.id, selected, nextPoint));
  }

  function undo() {
    const previous = past.at(-1);
    if (!previous) return;
    setFuture((items) => [clonePieces(draft), ...items]);
    setDraft(clonePieces(previous));
    setPast((items) => items.slice(0, -1));
  }

  function redo() {
    const next = future[0];
    if (!next) return;
    setPast((items) => [...items, clonePieces(draft)]);
    setDraft(clonePieces(next));
    setFuture((items) => items.slice(1));
  }

  function reset() {
    setPast((items) => [...items, clonePieces(draft)]);
    setFuture([]);
    setDraft(clonePieces(original));
    setSelected(null);
  }

  function svgPoint(event: ReactPointerEvent<SVGSVGElement>): PatternPoint {
    const rectangle = svgRef.current?.getBoundingClientRect();
    if (!rectangle) return [0, 0];
    const rawX = view.minX + (event.clientX - rectangle.left) / rectangle.width * view.width;
    const rawY = view.minY + (event.clientY - rectangle.top) / rectangle.height * view.height;
    return [Math.round(rawX / snap) * snap, Math.round(rawY / snap) * snap];
  }

  function startDrag(event: ReactPointerEvent<SVGCircleElement>, key: PointKey) {
    event.preventDefault();
    setSelected(key);
    dragStart.current = clonePieces(draft);
    dragKey.current = {pieceId: piece.id, key};
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveDrag(event: ReactPointerEvent<SVGSVGElement>) {
    if (!dragStart.current || !dragKey.current) return;
    setDraft(updatePoint(
      draft,
      dragKey.current.pieceId,
      dragKey.current.key,
      svgPoint(event),
    ));
  }

  function endDrag() {
    if (!dragStart.current) return;
    setPast((items) => [...items, dragStart.current as EditablePatternPiece[]]);
    setFuture([]);
    dragStart.current = null;
    dragKey.current = null;
  }

  async function save() {
    if (edits.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.editPatternGeometry(
        result.generation_id, projectRevision, edits, note,
      );
      await onSaved(saved);
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught.message
        : 'Не удалось сохранить ручную правку.');
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <section className="geometry-editor-launch" aria-labelledby="geometry-editor-title">
        <div>
          <p className="eyebrow">Этап 27 · точная корректировка</p>
          <h3 id="geometry-editor-title">Ручной редактор выкройки</h3>
          <p>Подвиньте узлы или направляющие кривых. Исходная версия сохранится отдельно.</p>
        </div>
        <button className="secondary-button" type="button" onClick={() => setOpen(true)}>
          Открыть редактор <span aria-hidden="true">✎</span>
        </button>
      </section>
    );
  }

  return (
    <section className="geometry-editor" aria-labelledby="geometry-editor-heading">
      <header>
        <div>
          <p className="eyebrow">Безопасная ручная правка</p>
          <h3 id="geometry-editor-heading">Редактор линии шва</h3>
          <p>Сервер заново проверит контур, парные швы и построит линию среза.</p>
        </div>
        <button className="text-button" type="button" onClick={() => setOpen(false)}>Закрыть</button>
      </header>
      <div className="geometry-editor__toolbar">
        <label>Деталь
          <select value={piece.id} onChange={(event) => selectPiece(event.target.value)}>
            {draft.map((item) => <option key={item.id} value={item.id}>{item.name_ru}</option>)}
          </select>
        </label>
        <label>Точка
          <select
            value={selected ? `${selected.segmentId}:${selected.handle}` : ''}
            onChange={(event) => {
              const [segmentId, handle] = event.target.value.split(':');
              setSelected(event.target.value ? {segmentId, handle: handle as ManualEditHandle} : null);
            }}
          >
            <option value="">Выберите на чертеже</option>
            {availablePoints.map((item) => (
              <option key={`${item.segmentId}:${item.handle}`} value={`${item.segmentId}:${item.handle}`}>
                {HANDLE_NAMES[item.handle]} · {item.segmentId}
              </option>
            ))}
          </select>
        </label>
        <label>Шаг сетки
          <select value={snap} onChange={(event) => setSnap(Number(event.target.value))}>
            <option value={1}>1 мм</option><option value={5}>5 мм</option>
          </select>
        </label>
        <div className="geometry-editor__history" aria-label="История правок">
          <button type="button" onClick={undo} disabled={past.length === 0}>↶ Отменить</button>
          <button type="button" onClick={redo} disabled={future.length === 0}>↷ Повторить</button>
          <button type="button" onClick={reset} disabled={edits.length === 0}>Сбросить</button>
        </div>
      </div>
      <div className="geometry-editor__canvas">
        <svg
          ref={svgRef}
          role="img"
          aria-label={`Редактор детали ${piece.name_ru}`}
          viewBox={`${view.minX} ${view.minY} ${view.width} ${view.height}`}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <path className="geometry-editor__original" d={pathData(originalPiece.seam_contour)} />
          {piece.cutting_contour && <path className="geometry-editor__cutting" d={pathData(piece.cutting_contour)} />}
          <path className="geometry-editor__seam" d={pathData(piece.seam_contour)} />
          {piece.seam_contour.segments.map((segment) => segment.type === 'cubic_bezier' && (
            <g key={`${segment.id}-guides`} className="geometry-editor__guides">
              <line x1={segment.start[0]} y1={segment.start[1]} x2={segment.control_1[0]} y2={segment.control_1[1]} />
              <line x1={segment.end[0]} y1={segment.end[1]} x2={segment.control_2[0]} y2={segment.control_2[1]} />
            </g>
          ))}
          {availablePoints.map((key) => {
            const segment = piece.seam_contour.segments.find((item) => item.id === key.segmentId);
            const value = segment ? point(segment, key.handle) : null;
            if (!value) return null;
            const active = selected?.segmentId === key.segmentId && selected.handle === key.handle;
            return <circle
              key={`${key.segmentId}:${key.handle}`}
              className={`geometry-editor__point geometry-editor__point--${key.handle}${active ? ' is-selected' : ''}`}
              cx={value[0]} cy={value[1]} r={active ? 3.2 : 2.4}
              onPointerDown={(event) => startDrag(event, key)}
            />;
          })}
        </svg>
      </div>
      <ul className="geometry-editor__legend" aria-label="Линии редактора">
        <li><span className="is-current" />Красная — текущая линия шва</li>
        <li><span className="is-original" />Серый пунктир — исходная линия шва</li>
        <li><span className="is-cutting" />Серая область — прежняя линия среза; новая появится после проверки</li>
      </ul>
      {selectedPoint && selected && (
        <div className="geometry-editor__coordinates">
          <strong>{HANDLE_NAMES[selected.handle]} · {selected.segmentId}</strong>
          <label>X, мм<input type="number" step={snap} value={selectedPoint[0]} onChange={(event) => commitPoint([Number(event.target.value), selectedPoint[1]])} /></label>
          <label>Y, мм<input type="number" step={snap} value={selectedPoint[1]} onChange={(event) => commitPoint([selectedPoint[0], Number(event.target.value)])} /></label>
          <div className="geometry-editor__nudges">
            <button type="button" aria-label="Сдвинуть влево" onClick={() => commitPoint([selectedPoint[0] - snap, selectedPoint[1]])}>←</button>
            <button type="button" aria-label="Сдвинуть вверх" onClick={() => commitPoint([selectedPoint[0], selectedPoint[1] - snap])}>↑</button>
            <button type="button" aria-label="Сдвинуть вниз" onClick={() => commitPoint([selectedPoint[0], selectedPoint[1] + snap])}>↓</button>
            <button type="button" aria-label="Сдвинуть вправо" onClick={() => commitPoint([selectedPoint[0] + snap, selectedPoint[1]])}>→</button>
          </div>
        </div>
      )}
      <label className="geometry-editor__note">Комментарий к версии
        <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} placeholder="Например: уточнила линию бока после макета" />
      </label>
      <div className="geometry-editor__warning">
        <strong>Это новая экспериментальная версия</strong>
        <span>После сохранения бумажную, экспертную и макетную проверку нужно пройти заново.</span>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <div className="geometry-editor__save">
        <span>{edits.length === 0 ? 'Правок пока нет' : `Изменено точек: ${edits.length}`}</span>
        <button className="primary-button" type="button" disabled={edits.length === 0 || saving} onClick={() => void save()}>
          {saving ? 'Проверяем геометрию…' : 'Проверить и сохранить новую версию'}
        </button>
      </div>
    </section>
  );
}

import {useId, useRef, useState} from 'react';
import type {MeasurementDefinition} from './types';
import {ATLAS_BY_ID, ATLAS_LINES} from './measurementAtlasData';

export function MeasurementAtlas({definitions, activeId, onSelect}: {
  definitions: MeasurementDefinition[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const [showAll, setShowAll] = useState(true);
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const active = definitions.find((item) => item.id === activeId);
  const available = new Map(definitions.map((item) => [item.id, item]));
  const seated = activeId === 'sitting_height';

  function illustration(interactive: boolean, seatedView = seated) {
    const seated = seatedView;
    return <svg viewBox={seated ? '0 0 1024 1024' : '0 0 1536 1024'} role="img" aria-label={seated ? 'Высота сидения: измерение сидя на твёрдой поверхности' : 'Общая иллюстрация мерок: вид спереди, сзади и сбоку'}>
      <image href={seated ? '/images/measurements-seated.png' : '/images/measurements-body.png'} width={seated ? 1024 : 1536} height="1024" />
      {ATLAS_LINES.filter((line) => available.has(line.id) && Boolean(line.seated) === seated
        && (showAll || line.id === activeId)).map((line) => <g key={line.id} data-measurement={line.id}
          opacity={!activeId || line.id === activeId ? 1 : 0.4}>
        <path d={line.path} fill="none" stroke="white" strokeWidth="8" strokeLinejoin="round" />
        <path d={line.path} fill="none" stroke={line.color} strokeWidth={line.id === activeId ? 5 : 3} strokeLinejoin="round" />
        <g transform={`translate(${line.badge[0]},${line.badge[1]})`} onClick={() => interactive && onSelect(line.id)}>
          <circle r="19" fill={line.color} stroke="white" strokeWidth="3" />
          <text textAnchor="middle" dominantBaseline="central" fill="white" fontSize="20" fontWeight="700">{line.number}</text>
          <title>{available.get(line.id)?.label_ru}</title>
        </g>
      </g>)}
    </svg>;
  }

  return <aside className="measurement-atlas" aria-labelledby={titleId}>
    <div className="atlas-heading"><h3 id={titleId}>Мерки на фигуре</h3>
      <button type="button" className="secondary-button" onClick={() => dialog.current?.showModal()}>Увеличить рисунок</button>
    </div>
    <figure>{illustration(true)}<figcaption>{seated ? 'Высоту сидения снимают сидя, от талии до поверхности стула.' : 'Спереди · сзади · сбоку. Номера и цвета совпадают с полями. Обхваты показаны кольцом, ширины и длины — линиями.'}</figcaption></figure>
    {available.has('sitting_height') && !seated && <figure className="atlas-seated">{illustration(true, true)}<figcaption>28. Высота сидения — отдельная мерка в положении сидя.</figcaption></figure>}
    <label className="atlas-all"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Показывать все линии</label>
    {active && <div className="atlas-instruction" aria-live="polite"><strong>{ATLAS_BY_ID.get(active.id)?.number}. {active.label_ru}</strong><p>{active.instruction_ru}</p>
      {active.id === 'sleeve_length' || active.id === 'elbow_circumference' ? <small>Для этой мерки слегка согните руку.</small> : null}
      {active.id === 'hip_inclination' && <small>Укажите удвоенный угол отмеченной боковой линии к вертикали.</small>}
    </div>}
    <div className="atlas-legend" aria-label="Мерки на рисунке">
      {definitions.map((item) => {
        const line = ATLAS_BY_ID.get(item.id);
        return <button key={item.id} type="button" aria-pressed={activeId === item.id} onClick={() => onSelect(item.id)}>
          <span style={{background: line?.color}}>{line?.number}</span>{item.label_ru}
        </button>;
      })}
    </div>
    <dialog ref={dialog} className="atlas-dialog"><div className="atlas-heading"><strong>Общий рисунок мерок</strong>
      <button type="button" className="secondary-button" onClick={() => dialog.current?.close()}>Закрыть рисунок</button></div>{illustration(false)}</dialog>
  </aside>;
}

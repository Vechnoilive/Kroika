import {useId} from 'react';
import {DESIGN_LOCATION_NAMES} from './designModules';
import type {GarmentDesignIntent} from './types';

type Element = GarmentDesignIntent['elements'][number];
const RECIPES = new Set(['placed_patch_pocket_v1', 'rectangular_applied_panel_v1', 'rounded_patch_pocket_v3', 'welt_pocket_v3']);
const cm = (value: number | null | undefined) => value == null ? 'укажите размер' : `${Number((value / 10).toFixed(2)).toLocaleString('ru-RU')} см`;

/** A dimension-reference illustration, not a computed or scaled pattern preview. */
export function PlacementGuide({item, moduleId, elements}: {item: Element; moduleId?: string; elements: Element[]}) {
  const uid = useId().replace(/:/g, '');
  if (!moduleId || !RECIPES.has(moduleId)) return null;
  const legacy = moduleId.endsWith('_v1');
  const welt = moduleId === 'welt_pocket_v3';
  const panel = moduleId === 'rectangular_applied_panel_v1';
  const body = item.location.startsWith('bodice');
  const dimensions = item.dimensions_mm;
  const width = dimensions?.[welt ? 'length' : 'width'];
  const height = dimensions?.[panel ? 'length' : 'depth'];
  const spacing = dimensions?.spacing;
  const offset = item.placement?.offset_mm ?? 20;
  const w = width ?? 80, h = height ?? 100, distance = spacing ?? 60;
  const fw = Math.max(300, w + distance + 80), fh = Math.max(500, h + (legacy ? distance : offset) + 150);
  const pw = w / fw * 220, ph = h / fh * 230;
  const x = legacy ? 190 - pw / 2 : 80 + distance / fw * 220;
  const y = legacy ? 280 - distance / fh * 230 - ph : 50 + offset / fh * 230;
  const name = panel ? 'панель' : 'карман';
  const labels = [
    {color: '#2563eb', label: welt ? 'Длина входа' : panel ? 'Ширина панели' : 'Ширина кармана', value: width},
    {color: '#15803d', label: panel ? 'Высота панели' : welt ? 'Глубина мешковины' : 'Высота кармана', value: height},
    {color: '#be185d', label: legacy ? 'От нижней точки основы вверх' : 'От левой границы области к боку', value: spacing},
    ...(!legacy ? [{color: '#c2410c', label: 'От верхней точки основы вниз', value: offset}] : []),
    ...(welt ? [{color: '#475569', label: 'Ширина одной обтачки', value: dimensions?.width}] : []),
  ];
  const active = elements.filter(e => e.included !== false && e.source_element_id !== item.source_element_id);
  const seams: string[] = [];
  for (const e of active) {
    const id = e.selected_module_id ?? e.module_id;
    if (!body && id === 'paired_equal_skirt_panels_v1') {
      for (let n = 1; n < Math.min(e.count ?? 3, 6); n++) {
        const f = n / Math.min(e.count ?? 3, 6);
        seams.push(`M${80 + 205 * f} 50L${80 + 250 * f} 280`);
      }
    } else if (!body && id === 'offset_skirt_panel_v3' && e.location === item.location) seams.push('M160 50L220 280');
    else if ((!body && id === 'paired_straight_skirt_yoke_v1') || (body && e.location === item.location && ['front_bodice_yoke_v3', 'back_bodice_yoke_v3'].includes(id ?? ''))) seams.push('M80 125L310 125');
    else if (body && e.location === item.location && id === 'shoulder_princess_seam_v3') seams.push('M190 55Q170 160 195 280');
  }
  const outline = body ? 'M80 105Q110 105 145 50L230 65Q230 135 280 135L300 280L80 280Z' : 'M80 50L285 50L330 280L80 280Z';
  const arrow = (key: string, color: string, x1: number, y1: number, x2: number, y2: number) => <line key={key} x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth="2" markerStart={`url(#${uid}-${color.slice(1)})`} markerEnd={`url(#${uid}-${color.slice(1)})`} />;
  return <figure className="placement-guide">
    <figcaption><strong>Как расположится {name}</strong><span>{DESIGN_LOCATION_NAMES[item.location]}{item.placement?.side && ` · ${item.placement.side === 'both' ? 'с обеих сторон' : item.placement.side === 'left' ? 'слева' : 'справа'}`}</span></figcaption>
    <div className="placement-guide__layout">
      <svg viewBox="0 0 390 330" role="img" aria-labelledby={`${uid}-title`} aria-describedby={`${uid}-desc`}>
        <title id={`${uid}-title`}>Направления размеров: {name}</title>
        <desc id={`${uid}-desc`}>{labels.map(l => `${l.label}: ${cm(l.value)}`).join('; ')}. Оранжевым пунктиром показаны условные швы членения.</desc>
        <defs>
          <clipPath id={`${uid}-clip`}><path d={outline} /></clipPath>
          {labels.map(l => <marker key={l.color} id={`${uid}-${l.color.slice(1)}`} viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L6 3L0 6Z" fill={l.color} /></marker>)}
        </defs>
        <path d={outline} fill="#fff8ed" stroke="#64748b" strokeWidth="2" />
        <g clipPath={`url(#${uid}-clip)`}>{seams.map((d, i) => <path key={i} d={d} fill="none" stroke="#c2410c" strokeWidth="2" strokeDasharray="6 4" />)}</g>
        <rect x={x} y={y} width={pw} height={ph} rx={moduleId === 'rounded_patch_pocket_v3' ? 10 : 0} fill="#dbeafe" fillOpacity="0.7" stroke="#2563eb" strokeWidth="2" strokeDasharray={welt ? '5 3' : undefined} />
        {welt && <><rect x={x} y={y - 4} width={pw} height="8" fill="#bbf7d0" stroke="#15803d" /><line x1={x} x2={x + pw} y1={y} y2={y} stroke="#0f172a" strokeWidth="2" /></>}
        {arrow('width', '#2563eb', x, y - 15, x + pw, y - 15)}
        {arrow('height', '#15803d', x + pw + 16, y, x + pw + 16, y + ph)}
        {legacy ? arrow('spacing', '#be185d', x - 18, y + ph, x - 18, 280) : <>
          {arrow('spacing', '#be185d', 80, y + ph + 18, x, y + ph + 18)}
          {arrow('offset', '#c2410c', 55, 50, 55, y)}
        </>}
        <text x="80" y="25" fill="#475569" fontSize="12">Верхняя точка области</text>
        <text x="80" y="310" fill="#475569" fontSize="12">Нижняя точка области</text>
      </svg>
      <dl>{labels.map(l => <div key={l.label}><dt><i style={{background: l.color}} />{l.label}</dt><dd>{cm(l.value)}</dd></div>)}</dl>
    </div>
    <p className="placement-guide__caption">Направления размеров показаны без масштаба. Форма основы и швы условные; положение относительно контура и вытачек проверяется по вашим меркам при построении. На половине лекала левая граница обычно проходит по центру изделия.</p>
    {seams.length > 0 && <p className="placement-guide__order">Сначала стачайте швы членения и разутюжьте припуски. Затем {welt ? 'выполните вход кармана на собранной основе' : 'совместите линии нанесения и пришейте целую накладную деталь'}.</p>}
  </figure>;
}

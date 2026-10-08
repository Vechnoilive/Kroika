import {useId} from 'react';
import {DESIGN_LOCATION_NAMES, type DesignModule} from './designModules';
import type {GarmentDesignIntent} from './types';

type Element = GarmentDesignIntent['elements'][number];
const COLORS: Record<string, string> = {width: '#2563eb', length: '#15803d', depth: '#c2410c', spacing: '#be185d'};
const NAMES: Record<string, string> = {width: 'Ширина', length: 'Длина', depth: 'Глубина', spacing: 'Расстояние'};
const POCKETS = new Set(['placed_patch_pocket_v1', 'rectangular_applied_panel_v1', 'rounded_patch_pocket_v3', 'welt_pocket_v3']);

export function RecipeGuide({item, module}: {item: Element; module?: DesignModule}) {
  const uid = useId().replace(/:/g, '');
  if (!module || POCKETS.has(module.id)) return null;
  const fields = [...new Set([...Object.keys(module.dimensions?.required ?? {}), ...Object.keys(module.dimensions?.optional ?? {})])];
  const yoke = item.type === 'yoke';
  const panel = module.id === 'offset_skirt_panel_v3';
  const princess = module.id === 'shoulder_princess_seam_v3';
  const opening = ['slit', 'vent', 'closure'].includes(item.type);
  const fullness = (module.group === 'fullness' && ['pleat', 'tuck', 'gather', 'drape'].includes(item.type) && module.id.startsWith('integrated_')) || ['placed_skirt_pleats_v2', 'placed_skirt_tucks_v2', 'placed_skirt_gathers_v2'].includes(module.id);
  const collar = item.type === 'collar' && module.id !== 'stand_collar_v1';
  const hood = item.type === 'hood';
  const band = ['belt', 'sash', 'waistband', 'cuff'].includes(item.type) || module.id === 'stand_collar_v1';
  const trim = ['flounce', 'ruffle', 'peplum'].includes(item.type);
  const edge = item.placement?.edge ?? (['neckline', 'waist', 'hem'].includes(item.location) ? item.location : trim ? 'hem' : item.location);
  const edgeNames: Record<string, string> = {neckline: 'Горловина', waist: 'Линия талии', hem: 'Низ', shoulder: 'Плечевой срез'};
  const attachment = yoke ? 'M60 105L195 120' : panel ? 'M120 35L165 205' : princess ? 'M140 45L125 135L115 205' : opening ? (module.id === 'side_skirt_slit_v3' ? 'M195 135L195 205' : 'M55 135L55 205') : collar || hood || module.id === 'stand_collar_v1' ? 'M75 35Q125 80 175 35' : edge === 'neckline' ? 'M75 35Q125 80 175 35' : edge === 'waist' ? 'M55 105L195 105' : edge === 'shoulder' ? 'M75 35L125 50' : item.location === 'sleeve' ? 'M80 180L180 180' : 'M55 205L195 205';
  const arrows: Array<[string, number, number, number, number]> = [];
  if (yoke) {arrows.push(['depth', 35, 35, 35, 105]); if (fields.includes('width')) arrows.push(['width', 215, 105, 215, 120]);}
  else if (panel) arrows.push(['width', 55, 22, 120, 22], ['depth', 120, 220, 165, 220]);
  else if (princess) arrows.push(['spacing', 100, 32, 140, 45]);
  else if (fullness) arrows.push(['width', 55, 60, 95, 60], ['spacing', 95, 85, 140, 85], ['depth', 90, 175, 115, 175], ['length', 215, 105, 215, 205]);
  else if (collar) arrows.push(['width', 235, 95, 235, 145], ['depth', 335, 95, 335, 120]);
  else if (hood) arrows.push(['width', 235, 195, 320, 195], ['length', 335, 45, 335, 180], ['depth', 290, 65, 310, 65]);
  else if (band) {arrows.push(['width', 235, 100, 235, 140], ['length', 245, 155, 325, 155]); if (module.id === 'shaped_cuff_v3') arrows.push(['depth', 340, 100, 340, 140]); else if (['shaped_belt_v3', 'tapered_sash_v3'].includes(module.id)) arrows.push(['depth', 295, 85, 325, 85]);}
  else if (trim) {arrows.push(['depth', 335, 105, 335, 170]); if (module.id.startsWith('placed_edge_') || module.id === 'explicit_polygon_detail_v3') arrows.push(['length', 260, 85, 320, 85], ['spacing', 230, 195, 260, 195]);}
  return <figure className="placement-guide" aria-label={`Схема: ${module.title_ru}`}>
    <figcaption><strong>Место и размеры конструкции</strong><span>{DESIGN_LOCATION_NAMES[item.location]} · {edgeNames[edge] ?? DESIGN_LOCATION_NAMES[item.location]}</span></figcaption>
    <div className="placement-guide__layout">
      <svg viewBox="0 0 365 250" role="img" aria-labelledby={`${uid}-title`} aria-describedby={`${uid}-desc`}>
        <title id={`${uid}-title`}>Схема: {module.title_ru}</title>
        <desc id={`${uid}-desc`}>Голубая линия — место крепления или размещения. Цветные стрелки поясняют направления размеров; схема без масштаба.</desc>
        <defs>{Object.entries(COLORS).map(([key, color]) => <marker key={key} id={`${uid}-${key}`} viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L6 3L0 6Z" fill={color} /></marker>)}</defs>
        <path d="M55 205L65 70L75 35Q125 80 175 35L195 70L195 205Z" fill="#fff8ed" stroke="#64748b" strokeWidth="2" />
        <path d={attachment} fill="none" stroke="#0891b2" strokeWidth="4" />
        {yoke && <path d="M60 105L195 120" stroke="#c2410c" strokeWidth="3" fill="none" />}
        {panel && <path d="M120 35L165 205" stroke="#2563eb" strokeWidth="3" fill="none" />}
        {princess && <path d="M140 45L125 135L115 205" stroke="#be185d" strokeWidth="3" fill="none" />}
        {fullness && <>{[95, 140, 175].map(x => <path key={x} d={`M${x} 105L${x} 205`} stroke="#be185d" strokeDasharray="5 3" />)}<path d="M90 180L102 160L115 180" fill="none" stroke="#c2410c" /></>}
        {opening && <path d="M55 205L55 135" stroke="#be185d" strokeWidth="4" />}
        {collar && <path d="M250 95Q285 145 320 95L320 120Q285 175 250 145Z" fill="#dbeafe" stroke="#2563eb" strokeWidth="2" />}
        {hood && <path d="M245 180L320 180L320 70Q290 15 250 45Z" fill="#dbeafe" stroke="#2563eb" strokeWidth="2" />}
        {band && <path d="M245 100L325 100L325 140L245 140Z" fill="#dbeafe" stroke="#2563eb" strokeWidth="2" />}
        {trim && <path d="M230 105L320 105L320 170Q275 145 230 170Z" fill="#dbeafe" stroke="#2563eb" strokeWidth="2" />}
        {arrows.filter(([key]) => fields.includes(key)).map(([key, x1, y1, x2, y2]) => <line key={key} x1={x1} y1={y1} x2={x2} y2={y2} stroke={COLORS[key]} strokeWidth="2" markerStart={`url(#${uid}-${key})`} markerEnd={`url(#${uid}-${key})`} />)}
        <text x="55" y="238" fill="#475569" fontSize="12">Основа · условный вид</text>
      </svg>
      <dl>{fields.map(key => {
        const value = item.dimensions_mm?.[key as keyof NonNullable<Element['dimensions_mm']>];
        return <div key={key}><dt><i style={{background: COLORS[key]}} />{module.parameter_labels_ru?.[key] ?? NAMES[key]}</dt><dd>{value == null ? (key in (module.dimensions?.optional ?? {}) ? 'по желанию' : 'укажите размер') : `${Number((value / 10).toFixed(2)).toLocaleString('ru-RU')} см`}</dd></div>;
      })}</dl>
    </div>
    <p className="placement-guide__caption">Условная схема без масштаба. Точное положение, контуры и соединения можно проверить ниже по вашим меркам.</p>
  </figure>;
}

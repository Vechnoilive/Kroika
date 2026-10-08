import {useEffect, useRef, useState} from 'react';
import {api, ApiError} from './api';
import {finalizeDesignIntent} from './designIntent';
import type {ProjectDocument, StyleAnalysis} from './types';

export function ConstructionPreview({project, analysis}: {project: ProjectDocument; analysis: StyleAnalysis}) {
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.previewPattern>> | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(100);
  const pending = useRef<AbortController | null>(null);
  const inputs = JSON.stringify([project.garment_spec, project.body_measurements, project.fit_settings, project.fabric_properties, project.pattern_method]);
  useEffect(() => {
    pending.current?.abort();
    pending.current = null;
    setResult(null); setError(''); setBusy(false); setZoom(100);
    return () => pending.current?.abort();
  }, [inputs]);
  async function preview() {
    const controller = new AbortController();
    pending.current?.abort(); pending.current = controller;
    setBusy(true); setResult(null); setError('');
    try {
      const candidate = structuredClone(project);
      const intent = candidate.garment_spec.design_intent;
      if (intent) candidate.garment_spec.design_intent = finalizeDesignIntent(intent, candidate.garment_spec, analysis);
      candidate.garment_spec.selection_status = 'confirmed';
      candidate.garment_spec.confirmed_at = new Date().toISOString();
      const response = await api.previewPattern(candidate, controller.signal);
      if (pending.current === controller && !controller.signal.aborted) setResult(response);
    } catch (caught) {
      if (pending.current === controller && !controller.signal.aborted) setError(caught instanceof ApiError && (caught.issues ?? []).length ? (caught.issues ?? []).map(i => i.message_ru).join(' ') : caught instanceof Error ? caught.message : 'Не удалось рассчитать предварительный вид.');
    } finally {
      if (pending.current === controller) {setBusy(false); pending.current = null;}
    }
  }
  return <section className="construction-preview" aria-label="Предварительный вид по меркам">
    <h3>Проверка размещения по меркам</h3>
    <p>Подтвердите детали и заполните мерки, затем проверьте рассчитанные линии крепления и швы. Предпросмотр не сохраняет новую выкройку и не меняет проект.</p>
    <button type="button" disabled={busy} onClick={() => void preview()}>{busy ? 'Рассчитываем размещение…' : 'Проверить размещение по меркам'}</button>
    {error && <p role="alert">{error}</p>}
    {result?.issues.filter(i => i.severity === 'blocking_error').map(i => <p role="alert" key={i.code + i.json_pointer}>{i.message_ru}</p>)}
    {result?.svg && <><p>Рассчитанный вид: {result.piece_count} деталей. Линии нанесения показаны на фактических частях основы.</p><label>Масштаб просмотра <input aria-label="Масштаб предварительного вида" type="range" min="50" max="300" step="25" value={zoom} onChange={e => setZoom(Number(e.target.value))} /> {zoom}%</label><div className="construction-preview__viewport"><img style={{width: `${zoom}%`}} className="construction-preview__image" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(result.svg)}`} alt="Рассчитанные контуры, членения и линии крепления по вашим меркам" /></div></>}
  </section>;
}

import {api} from './api';
import {desktopApi, nativeValue, type ExportKind} from './desktop';

export async function saveExport(generationId: string, kind: ExportKind): Promise<void> {
  const native = desktopApi();
  if (native) {
    nativeValue(await native.save_export(generationId, kind));
    return;
  }
  const file = kind === 'a4-pdf' ? await api.downloadA4Pdf(generationId)
    : kind === 'scale-check-pdf' ? await api.downloadScaleCheckPdf(generationId)
      : kind === 'acceptance-report' ? await api.downloadAcceptanceReport(generationId) : null;
  if (!file) return;
  const url = URL.createObjectURL(file.blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = file.filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser time to start consuming the blob before releasing it.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {PatternResultCard} from './App';
import {api} from './api';
import {PhysicalValidationJournal} from './PhysicalValidationJournal';
import type {PatternEngineResult, PhysicalValidationSummary} from './types';

const generationId = '11111111-1111-4111-8111-111111111111';
const evidenceRef = 'img_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

const result: PatternEngineResult = {
  generation_id: generationId,
  engine_version: '0.12.0',
  status: 'succeeded',
  pattern: {
    unit: 'mm',
    pieces: [{id: 'front', name_ru: 'Перед', cut_quantity: 1, cut_on_fold: true}],
    seam_pairs: [{id: 'side'}],
    print_layout: {page_format: 'A4', overlap_mm: 10, scale: 1, control_square_mm: 50},
  },
  validation_report: {
    status: 'warnings',
    issues: [],
    diagnostic_export_allowed: true,
    production_export_allowed: false,
  },
};

function summary(withEvidence = false): PhysicalValidationSummary {
  return {
    project_id: '22222222-2222-4222-8222-222222222222',
    generation_id: generationId,
    gates: [
      {gate: 'paper', status: 'pending', latest_record_id: null, checked_at: null, passed_observations: withEvidence ? 1 : 0, required_observations: 2},
      {gate: 'expert', status: 'pending', latest_record_id: null, checked_at: null, passed_observations: 0, required_observations: 1},
      {gate: 'toile', status: 'pending', latest_record_id: null, checked_at: null, passed_observations: 0, required_observations: 3},
    ],
    production_allowed: false,
    policy: 'Допуск относится только к этой версии.',
    records: withEvidence ? [{
      record_id: '33333333-3333-4333-8333-333333333333',
      project_id: '22222222-2222-4222-8222-222222222222',
      generation_id: generationId,
      gate: 'paper',
      outcome: 'passed',
      reviewer_name: 'Анна',
      notes: 'Листы совпали.',
      printer_name: 'HP LaserJet M404',
      square_width_mm: 50,
      square_height_mm: 50,
      control_line_mm: 200,
      figure_label: null,
      evidence_image_refs: [evidenceRef],
      created_at: '2026-09-23T20:00:00Z',
    }] : [],
  };
}

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:kroika-test'),
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});

afterEach(() => vi.restoreAllMocks());

describe('stage 25 print and acceptance workflow', () => {
  it('shows the exact sheet count and downloads a one-page scale check first', async () => {
    vi.spyOn(api, 'physicalValidation').mockResolvedValue(summary());
    vi.spyOn(api, 'printPlan').mockResolvedValue({
      generation_id: generationId,
      page_format: 'A4',
      scale: 1,
      pattern_sheet_count: 18,
      total_pdf_pages: 19,
      columns: 3,
      rows: 6,
      overlap_mm: 10,
      control_square_mm: 50,
      production_allowed: false,
    });
    vi.spyOn(api, 'downloadScaleCheckPdf').mockResolvedValue({
      blob: new Blob(['pdf'], {type: 'application/pdf'}),
      filename: 'scale-check.pdf',
    });

    render(<PatternResultCard result={result} />);
    expect(await screen.findByText('18')).toBeVisible();
    expect(screen.getByText('19 стр.')).toBeVisible();
    expect(screen.getByText(/18 листов выкройки \+ 1 карта/i)).toBeVisible();
    await userEvent.click(screen.getByRole('button', {name: /pdf проверки масштаба/i}));
    await waitFor(() => expect(api.downloadScaleCheckPdf).toHaveBeenCalledWith(generationId));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
  });

  it('uploads evidence before the journal record and exports the local report', async () => {
    vi.spyOn(api, 'physicalValidation').mockResolvedValue(summary());
    vi.spyOn(api, 'uploadImage').mockResolvedValue({
      image_ref: evidenceRef,
      media_type: 'image/png',
      size_bytes: 123,
    });
    vi.spyOn(api, 'recordPhysicalValidation').mockResolvedValue(summary(true));
    vi.spyOn(api, 'downloadAcceptanceReport').mockResolvedValue({
      blob: new Blob(['report'], {type: 'application/pdf'}),
      filename: 'acceptance-report.pdf',
    });

    render(<PhysicalValidationJournal generationId={generationId} garmentName="Платье" />);
    expect(await screen.findByText(/кроить ткань пока нельзя/i)).toBeVisible();
    const photo = new File(['photo'], 'paper-proof.png', {type: 'image/png'});
    await userEvent.upload(screen.getByLabelText(/фото бумажной сборки/i), photo);
    expect(screen.getByText('paper-proof.png')).toBeVisible();
    await userEvent.type(screen.getByLabelText(/^Принтер$/i), 'HP LaserJet M404');
    await userEvent.type(screen.getByLabelText(/ширина квадрата/i), '50');
    await userEvent.type(screen.getByLabelText(/высота квадрата/i), '50');
    await userEvent.type(screen.getByLabelText(/линия 200 мм/i), '200');
    await userEvent.type(screen.getByLabelText(/кто проверил/i), 'Анна');
    await userEvent.click(screen.getByRole('button', {name: /записать проверку/i}));

    await waitFor(() => expect(api.uploadImage).toHaveBeenCalledWith(photo));
    expect(api.recordPhysicalValidation).toHaveBeenCalledWith(
      generationId,
      expect.objectContaining({evidence_image_refs: [evidenceRef]}),
    );
    const history = await screen.findByText(/история проверок/i);
    await userEvent.click(history);
    expect(screen.getByAltText('Фото проверки 1')).toHaveAttribute(
      'src',
      `/api/v1/images/${evidenceRef}`,
    );

    await userEvent.click(screen.getByRole('button', {name: /скачать pdf-отчёт/i}));
    await waitFor(() => expect(api.downloadAcceptanceReport).toHaveBeenCalledWith(generationId));
  });
});

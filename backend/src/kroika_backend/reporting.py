"""Printable local acceptance report with optional sanitized evidence photos."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import textwrap
from typing import Any, Mapping

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


_FONT_NAME = "KroikaReportDejaVu"
_FONT_BOLD_NAME = "KroikaReportDejaVuBold"
_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/local/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)
_BOLD_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/local/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
)
_GATE_LABELS = {"paper": "Печать 1:1", "expert": "Конструктор", "toile": "Макет"}
_STATUS_LABELS = {"pending": "не проверено", "passed": "пройдено", "failed": "замечания"}


def _fonts() -> tuple[str, str]:
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        regular = next((path for path in _FONT_CANDIDATES if path.is_file()), None)
        if regular is None:
            raise RuntimeError("Не найден Unicode-шрифт для отчёта приёмки.")
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(regular)))
    if _FONT_BOLD_NAME not in pdfmetrics.getRegisteredFontNames():
        bold = next((path for path in _BOLD_FONT_CANDIDATES if path.is_file()), None)
        if bold is None:
            return _FONT_NAME, _FONT_NAME
        pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, str(bold)))
    return _FONT_NAME, _FONT_BOLD_NAME


def render_acceptance_report_pdf(
    project: Mapping[str, Any],
    generation: Mapping[str, Any],
    summary: Mapping[str, Any],
    print_plan: Mapping[str, Any],
    evidence_images: Mapping[str, bytes],
) -> bytes:
    """Render a human-readable report for one immutable generation."""

    regular_font, bold_font = _fonts()
    output = BytesIO()
    document = canvas.Canvas(
        output, pagesize=A4, pageCompression=1, invariant=1, pdfVersion=(1, 7)
    )
    document.setTitle("Kroika — отчёт физической приёмки")
    document.setAuthor("Kroika")
    page_number = 0
    y_mm = 0.0

    def finish_page() -> None:
        document.setFont(regular_font, 7)
        document.setFillColor(HexColor("#756b78"))
        document.drawString(15 * mm, 8 * mm, "Kroika · локальный отчёт · фото не отправлялись в AI")
        document.drawRightString(195 * mm, 8 * mm, f"Страница {page_number}")
        document.showPage()

    def start_page(*, continuation: bool = False) -> None:
        nonlocal page_number, y_mm
        page_number += 1
        document.setFillColor(HexColor("#fffdf9"))
        document.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        document.setFillColor(HexColor("#2f2833"))
        document.setFont(bold_font, 16)
        title = "Отчёт физической приёмки" + (" · продолжение" if continuation else "")
        document.drawString(15 * mm, 280 * mm, title)
        y_mm = 268.0

    def ensure_space(required_mm: float) -> None:
        nonlocal y_mm
        if y_mm - required_mm >= 18:
            return
        finish_page()
        start_page(continuation=True)

    def line(
        value: str,
        *,
        bold: bool = False,
        size: float = 9,
        color: str = "#2f2833",
        gap_mm: float = 5,
        indent_mm: float = 0,
    ) -> None:
        nonlocal y_mm
        ensure_space(gap_mm + 2)
        document.setFillColor(HexColor(color))
        document.setFont(bold_font if bold else regular_font, size)
        document.drawString((15 + indent_mm) * mm, y_mm * mm, value)
        y_mm -= gap_mm

    def paragraph(value: str, *, indent_mm: float = 0) -> None:
        for row in textwrap.wrap(value, width=96) or [""]:
            line(row, size=8, color="#5f5662", gap_mm=4.2, indent_mm=indent_mm)

    start_page()
    line(f"Проект: {project.get('name', 'Без названия')}", bold=True, size=11, gap_mm=7)
    line(f"Версия выкройки: {generation['generation_id']}", size=7.5, color="#756b78")
    line(
        f"Изделие: {project.get('garment_spec', {}).get('garment_type', '—')} · "
        f"листов выкройки: {print_plan['pattern_sheet_count']} · "
        f"всего страниц PDF: {print_plan['total_pdf_pages']}",
        gap_mm=6,
    )
    release = "ДОПУСК ОТКРЫТ" if summary["production_allowed"] else "ТОЛЬКО ПРОВЕРКА"
    line(
        release,
        bold=True,
        size=11,
        color="#27624f" if summary["production_allowed"] else "#a33e34",
        gap_mm=9,
    )

    line("Состояние обязательных проверок", bold=True, size=11, gap_mm=7)
    for gate in summary["gates"]:
        label = _GATE_LABELS[gate["gate"]]
        state = _STATUS_LABELS[gate["status"]]
        line(
            f"• {label}: {state} · {gate['passed_observations']}/{gate['required_observations']}",
            indent_mm=2,
        )
    y_mm -= 3
    paragraph(str(summary["policy"]))
    y_mm -= 4

    line(f"История наблюдений: {len(summary['records'])}", bold=True, size=11, gap_mm=8)
    for index, record in enumerate(summary["records"], start=1):
        refs = record.get("evidence_image_refs", [])
        estimated = 31 if refs else 18
        ensure_space(estimated)
        label = _GATE_LABELS[record["gate"]]
        outcome = _STATUS_LABELS[record["outcome"]]
        line(
            f"{index}. {label} · {outcome}",
            bold=True,
            size=9.5,
            gap_mm=5,
        )
        line(
            f"Проверил: {record['reviewer_name']} · {record['created_at']}",
            size=7.5,
            color="#756b78",
            gap_mm=4.2,
            indent_mm=3,
        )
        if record["gate"] == "paper":
            line(
                f"Принтер: {record.get('printer_name') or '—'} · квадрат "
                f"{record.get('square_width_mm')} × {record.get('square_height_mm')} мм · "
                f"линия {record.get('control_line_mm')} мм",
                size=7.5,
                gap_mm=4.2,
                indent_mm=3,
            )
        if record.get("figure_label"):
            line(
                f"Фигура: {record['figure_label']}", size=7.5, gap_mm=4.2, indent_mm=3
            )
        if record.get("notes"):
            paragraph(str(record["notes"]), indent_mm=3)
        if refs:
            line(f"Фото-доказательства: {len(refs)}", size=7.5, gap_mm=5, indent_mm=3)
            ensure_space(31)
            x_mm = 18.0
            for image_ref in refs:
                data = evidence_images.get(image_ref)
                if data is None:
                    continue
                reader = ImageReader(BytesIO(data))
                width, height = reader.getSize()
                box_width, box_height = 40.0, 27.0
                scale = min(box_width / width, box_height / height)
                drawn_width = width * scale
                drawn_height = height * scale
                document.drawImage(
                    reader,
                    x_mm * mm,
                    (y_mm - box_height) * mm,
                    width=drawn_width * mm,
                    height=drawn_height * mm,
                    preserveAspectRatio=True,
                    mask="auto",
                )
                x_mm += 44
            y_mm -= 31
        y_mm -= 3

    if not summary["records"]:
        paragraph("Записей пока нет. Этот отчёт не подтверждает физическую проверку выкройки.")
    y_mm -= 2
    line("Важно", bold=True, color="#a33e34", gap_mm=6)
    paragraph(
        "Цифровая генерация и этот отчёт не заменяют измерение контрольного квадрата, "
        "заключение конструктора и проверку макетов перед раскроем основной ткани."
    )
    finish_page()
    document.save()
    return output.getvalue()

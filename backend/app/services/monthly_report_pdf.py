"""Monats-Report als A4-PDF, im Stil des Angebots-/Rechnungs-PDFs (services/quote_pdf.py).

Zahlenwerk von ``services/monthly_report.py``; Briefkopf wie dort aus den
Firmendaten. Bewusst derselbe minimalistische canvas-Stil: Label links,
Betrag rechts, Trennlinien — keine Tabellen-Engine, kein externer Font.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

MARGIN = 20 * mm

LABELS: dict[str, dict[str, str]] = {
    "de": {
        "title": "MONATSREPORT",
        "period": "Zeitraum",
        "invoices": "Rechnungen",
        "issued": "Ausgestellt",
        "paid": "Bezahlt",
        "open": "Offen",
        "cancelled": "Storniert",
        "overdue": "Überfällig",
        "quotes": "Angebote",
        "production": "Fertigung",
        "prints": "Drucke",
        "failed": "Gescheitert",
        "minutes": "Druckstunden",
        "grams": "Filament",
        "material": "Materialkosten",
        "energy": "Energiekosten",
        "by_type": "Nach Materialtyp",
        "by_printer": "Nach Drucker",
        "profit": "Nachkalkulation verknüpfter Angebote",
        "revenue": "Angebotssumme",
        "actual_cost": "Ist-Kosten",
        "profit_total": "Gewinn",
        "estimated_note": "Einige Ist-Kosten sind geschätzt (fehlende Archivkosten).",
        "no_data": "Für diesen Monat liegen keine Zahlen vor.",
    },
    "en": {
        "title": "MONTHLY REPORT",
        "period": "Period",
        "invoices": "Invoices",
        "issued": "Issued",
        "paid": "Paid",
        "open": "Open",
        "cancelled": "Cancelled",
        "overdue": "Overdue",
        "quotes": "Quotes",
        "production": "Production",
        "prints": "Prints",
        "failed": "Failed",
        "minutes": "Print hours",
        "grams": "Filament",
        "material": "Material cost",
        "energy": "Energy cost",
        "by_type": "By filament type",
        "by_printer": "By printer",
        "profit": "Cost check of linked quotes",
        "revenue": "Quote revenue",
        "actual_cost": "Actual cost",
        "profit_total": "Profit",
        "estimated_note": "Some actual costs are estimated (missing archive costs).",
        "no_data": "No numbers for this month.",
    },
}


def money(value: float, currency: str, lang: str = "de") -> str:
    text = f"{value:,.2f}"
    if lang == "de":
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {currency}"


def _period_text(report: dict[str, Any], lang: str) -> str:
    months_de = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    months_en = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    month = int(report.get("month") or 1)
    year = int(report.get("year") or datetime.now().year)
    names = months_de if lang == "de" else months_en
    return f"{names[month - 1]} {year}"


def render(report: dict[str, Any], company: dict[str, Any], lang: str = "de") -> bytes:
    lang = lang if lang in LABELS else "de"
    t = LABELS[lang]
    buffer = io.BytesIO()
    # pageCompression=0: die Datei ist klein, und Prüftests können den Inhalt lesen.
    pdf = rl_canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    width, height = A4
    right = width - MARGIN
    y = height - MARGIN

    # Briefkopf (wie im Angebots-PDF): Logo optional, Firmenname, Kontaktpuffer
    name_y = y - 4 * mm
    logo = company.get("_logo_path")
    if logo:
        try:
            from reportlab.lib.utils import ImageReader

            image = ImageReader(str(logo))
            width_px, height_px = image.getSize()
            scale = min(45 * mm / width_px, 18 * mm / height_px)
            pdf.drawImage(image, MARGIN, y - 18 * mm, width=width_px * scale, height=height_px * scale, mask="auto")
            name_y = y - 22 * mm
        except Exception:  # ein unlesbares Logo darf den Report nie verhindern
            name_y = y - 4 * mm
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(MARGIN, name_y, company.get("name") or "")
    pdf.setFont("Helvetica", 9)
    line_y = name_y - 6 * mm
    for line in [
        *str(company.get("address") or "").splitlines(),
        company.get("email") or "",
        company.get("phone") or "",
    ]:
        if str(line).strip():
            pdf.drawString(MARGIN, line_y, str(line).strip())
            line_y -= 4.2 * mm

    # Kopf rechts: Titel und Zeitraum
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawRightString(right, y - 4 * mm, t["title"])
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(right, y - 12 * mm, _period_text(report, lang))

    y = min(line_y, y - 30 * mm)

    def section(title: str) -> None:
        nonlocal y
        if y < MARGIN + 60 * mm:
            pdf.showPage()
            y = height - MARGIN
        y -= 2 * mm
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(MARGIN, y, title)
        pdf.setLineWidth(0.8)
        pdf.line(MARGIN, y - 1.5 * mm, right, y - 1.5 * mm)
        y -= 7 * mm

    def row(label: str, value: str, bold: bool = False, indent: float = 0.0) -> None:
        nonlocal y
        if y < MARGIN + 15 * mm:
            pdf.showPage()
            y = height - MARGIN
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        pdf.drawString(MARGIN + indent, y, label)
        pdf.drawRightString(right, y, value)
        y -= 5.2 * mm

    production = report.get("production") or {}
    invoices_by_currency = report.get("invoices") or {}
    quotes_by_currency = report.get("quotes") or {}
    profit = report.get("profit") or {}

    has_numbers = bool(invoices_by_currency or quotes_by_currency or production.get("prints"))
    if not has_numbers:
        section(_period_text(report, lang))
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(MARGIN, y, t["no_data"])
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    section(t["invoices"])
    for currency, bucket in sorted(invoices_by_currency.items()):
        if bucket.get("count"):
            row(t["issued"], f"{bucket['count']} · {money(bucket['total'], currency, lang)}", bold=False)
            if bucket.get("paid"):
                row(f"   {t['paid']}", money(bucket["paid"], currency, lang))
            if bucket.get("open"):
                row(f"   {t['open']}", money(bucket["open"], currency, lang))
            if bucket.get("cancelled"):
                row(f"   {t['cancelled']}", money(bucket["cancelled"], currency, lang))
            if bucket.get("overdue"):
                row(f"   {t['overdue']} ({bucket['overdue_count']})", money(bucket["overdue"], currency, lang))

    section(t["quotes"])
    for currency, total in sorted(quotes_by_currency.items()):
        if total:
            row(t["quotes"], money(total, currency, lang))

    section(t["production"])
    row(t["prints"], str(production.get("prints", 0)))
    row(t["failed"], str(production.get("failed", 0)))
    row(t["minutes"], f"{(production.get('minutes') or 0) / 60:.1f} h")
    row(t["grams"], f"{production.get('grams') or 0} g")
    if production.get("material_cost") is not None:
        row(t["material"], money(float(production["material_cost"]), "EUR", lang))
    if production.get("energy_cost") is not None:
        row(t["energy"], money(float(production["energy_cost"]), "EUR", lang))
    by_type = production.get("by_filament_type") or []
    if by_type:
        row(f"{t['by_type']}:", "")
        for line in by_type:
            row(f"   {line.get('type')}", f"{line.get('grams', 0)} g", indent=4 * mm)
    by_printer = production.get("by_printer") or []
    if by_printer:
        row(f"{t['by_printer']}:", "")
        for line in by_printer:
            row(
                f"   {line.get('name')}",
                f"{line.get('prints', 0)} · {((line.get('minutes') or 0) / 60):.1f} h",
                indent=4 * mm,
            )

    if profit.get("quotes"):
        section(t["profit"])
        for currency, bucket in sorted((profit.get("per_currency") or {}).items()):
            row(t["revenue"], money(bucket["revenue"], currency, lang))
            row(t["actual_cost"], money(bucket["actual_cost"], currency, lang))
            row(t["profit_total"], money(bucket["profit"], currency, lang), bold=True)
        if profit.get("estimated_quotes"):
            pdf.setFont("Helvetica-Oblique", 8.5)
            pdf.drawString(MARGIN, y - 1 * mm, t["estimated_note"])
            y -= 5 * mm

    # Fußzeile wie im Angebots-PDF
    footer_parts = [str(company.get(key) or "").strip() for key in ("tax_id", "iban", "bic")]
    footer = "  ·  ".join(part for part in footer_parts if part)
    if footer:
        if y < MARGIN + 15 * mm:
            pdf.showPage()
            y = height - MARGIN
        pdf.setStrokeColorRGB(0.75, 0.75, 0.75)
        pdf.setLineWidth(0.5)
        pdf.line(MARGIN, y - 2 * mm, right, y - 2 * mm)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(MARGIN, y - 6 * mm, footer)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()

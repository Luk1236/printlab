"""Angebot als PDF: Briefkopf aus den Firmendaten, Positionen aus dem gespeicherten Angebot.

Nutzt reportlab (schon für die Etiketten im Einsatz). Die Standardschrift Helvetica deckt deutsche Umlaute und das
Euro-Zeichen ab.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas

LABELS = {
    "de": {
        "invoice_title": "RECHNUNG",
        "invoice_number": "Rechnungsnummer",
        "due": "Zahlbar bis",
        "service": "Leistungsdatum",
        "reference": "Zu Angebot {number}",
        "pay_hint": "Bitte überweisen Sie den Betrag bis {due} unter Angabe der Rechnungsnummer.",
        "title": "ANGEBOT",
        "number": "Nummer",
        "date": "Datum",
        "valid": "Gültig bis",
        "to": "Angebot für",
        "description": "Leistung",
        "material": "Material",
        "energy": "Energie",
        "labor": "Arbeitszeit",
        "subtotal": "Zwischensumme",
        "markup": "Aufschlag",
        "total": "Gesamtpreis",
        "net": "Gesamtpreis (netto)",
        "vat": "Umsatzsteuer {pct} %",
        "gross": "Gesamtpreis (brutto)",
        "tax_id": "Steuernummer / USt-IdNr.",
        "page": "Seite",
    },
    "en": {
        "invoice_title": "INVOICE",
        "invoice_number": "Invoice number",
        "due": "Due date",
        "service": "Service date",
        "reference": "Re: quote {number}",
        "pay_hint": "Please transfer the amount by {due} quoting the invoice number.",
        "title": "QUOTE",
        "number": "Number",
        "date": "Date",
        "valid": "Valid until",
        "to": "Quote for",
        "description": "Description",
        "material": "Material",
        "energy": "Energy",
        "labor": "Labor",
        "subtotal": "Subtotal",
        "markup": "Markup",
        "total": "Total",
        "net": "Total (net)",
        "vat": "VAT {pct} %",
        "gross": "Total (gross)",
        "tax_id": "Tax ID / VAT ID",
        "page": "Page",
    },
}
MARGIN = 20 * mm


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value: float, currency: str, lang: str = "de") -> str:
    text = f"{value:,.2f}"
    if lang == "de":
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {currency}"


def _date(value: str, lang: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _fmt_date(moment: datetime, lang: str) -> str:
    return moment.strftime("%d.%m.%Y") if lang == "de" else moment.strftime("%Y-%m-%d")


def render(entry: dict[str, Any], company: dict[str, Any], lang: str = "de", kind: str = "quote") -> bytes:
    """``kind``: ``quote`` (Angebot) oder ``invoice`` (Rechnung; Eintrag aus ``services/invoices.py``)."""
    invoice = kind == "invoice"
    lang = lang if lang in LABELS else "de"
    t = LABELS[lang]
    currency = str(entry.get("currency") or "EUR")
    buffer = io.BytesIO()
    pdf = rl_canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    right = width - MARGIN
    y = height - MARGIN

    # Briefkopf links
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
        except Exception:  # ein unlesbares Logo darf das Angebot nie verhindern
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
        if line.strip():
            pdf.drawString(MARGIN, line_y, line.strip())
            line_y -= 4.2 * mm

    # Kopf rechts: Titel, Nummer, Datum, Gültigkeit
    created = _date(str(entry.get("issued") if invoice else entry.get("ts", "")) or str(entry.get("ts", "")), lang)
    number = str(entry.get("number") or entry.get("id", ""))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawRightString(right, y - 4 * mm, t["invoice_title"] if invoice else t["title"])
    pdf.setFont("Helvetica", 9)
    info = [(t["invoice_number"] if invoice else t["number"], number), (t["date"], _fmt_date(created, lang))]
    if invoice:
        if entry.get("service_date"):
            info.append((t["service"], _fmt_date(_date(str(entry["service_date"]), lang), lang)))
        if entry.get("due"):
            info.append((t["due"], _fmt_date(_date(str(entry["due"]), lang), lang)))
    else:
        days = int(company.get("valid_days") or 0)
        if days:
            info.append((t["valid"], _fmt_date(created + timedelta(days=days), lang)))
    info_y = y - 11 * mm
    for label, value in info:
        pdf.drawRightString(right - 28 * mm, info_y, f"{label}:")
        pdf.drawRightString(right, info_y, value)
        info_y -= 4.2 * mm

    # Empfänger
    y = min(line_y, info_y) - 12 * mm
    pdf.setFont("Helvetica", 8)
    pdf.drawString(MARGIN, y, t["to"])
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(MARGIN, y - 5.5 * mm, str(entry.get("customer", "")))
    pdf.setFont("Helvetica", 10)
    address_y = y - 10.5 * mm
    for line in str(entry.get("customer_address") or "").splitlines()[:6]:
        if line.strip():
            pdf.drawString(MARGIN, address_y, line.strip())
            address_y -= 4.6 * mm
    y = min(y - 18 * mm, address_y - 6 * mm)

    # Leistung
    description = str(entry.get("description") or "").strip()
    if description:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(MARGIN, y, t["description"])
        pdf.setFont("Helvetica", 10)
        y -= 5.5 * mm
        for wrapped in simpleSplit(description, "Helvetica", 10, right - MARGIN):
            pdf.drawString(MARGIN, y, wrapped)
            y -= 4.8 * mm
        y -= 6 * mm

    # Positionen
    def row(label: str, value: float, bold: bool = False, line_above: bool = False) -> None:
        nonlocal y
        if line_above:
            pdf.setLineWidth(0.5)
            pdf.line(MARGIN, y + 3.5 * mm, right, y + 3.5 * mm)
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 10.5 if bold else 10)
        pdf.drawString(MARGIN, y, label)
        pdf.drawRightString(right, y, money(value, currency, lang))
        y -= 6.2 * mm

    for key in ("material", "energy", "labor"):
        row(t[key], float(entry.get(key, 0) or 0))
    row(t["subtotal"], float(entry.get("subtotal", 0) or 0), line_above=True)
    row(t["markup"], float(entry.get("markup", 0) or 0))
    for item in entry.get("items") or []:
        if not isinstance(item, dict):
            continue
        quantity = _as_float(item.get("quantity"), 1.0)
        unit = _as_float(item.get("unit_price"), 0.0)
        label = f"{str(item.get('description', ''))[:55]} ({quantity:g} × {money(unit, currency, lang)})"
        row(label, _as_float(item.get("amount"), quantity * unit))
    total = float(entry.get("total", 0) or 0)
    vat_percent = float(company.get("vat_percent") or 0)
    if vat_percent > 0:
        vat = round(total * vat_percent / 100, 2)
        row(t["net"], total, bold=True, line_above=True)
        row(t["vat"].format(pct=f"{vat_percent:g}"), vat)
        row(t["gross"], round(total + vat, 2), bold=True, line_above=True)
    else:
        row(t["total"], total, bold=True, line_above=True)
        note = str(company.get("vat_note") or "").strip()
        if note:
            y -= 2 * mm
            pdf.setFont("Helvetica-Oblique", 8.5)
            for wrapped in simpleSplit(note, "Helvetica-Oblique", 8.5, right - MARGIN):
                pdf.drawString(MARGIN, y, wrapped)
                y -= 4 * mm

    if invoice:
        y -= 4 * mm
        pdf.setFont("Helvetica", 9)
        if entry.get("quote_number"):
            pdf.drawString(MARGIN, y, t["reference"].format(number=entry["quote_number"]))
            y -= 5 * mm
        if entry.get("due"):
            due_text = _fmt_date(_date(str(entry["due"]), lang), lang)
            for wrapped in simpleSplit(t["pay_hint"].format(due=due_text), "Helvetica", 9, right - MARGIN):
                pdf.drawString(MARGIN, y, wrapped)
                y -= 4.5 * mm

    # Fußzeile: Freitext, Bank, Steuernummer
    foot_y = MARGIN + 14 * mm
    pdf.setLineWidth(0.4)
    pdf.line(MARGIN, foot_y + 5 * mm, right, foot_y + 5 * mm)
    pdf.setFont("Helvetica", 8)
    footer = str(company.get("footer") or "").strip()
    for wrapped in simpleSplit(footer, "Helvetica", 8, right - MARGIN) if footer else []:
        pdf.drawString(MARGIN, foot_y, wrapped)
        foot_y -= 3.6 * mm
    bank = " | ".join(
        p
        for p in (
            f"IBAN {company['iban']}" if company.get("iban") else "",
            f"BIC {company['bic']}" if company.get("bic") else "",
        )
        if p
    )
    if bank:
        pdf.drawString(MARGIN, foot_y, bank)
        foot_y -= 3.6 * mm
    if company.get("tax_id"):
        pdf.drawString(MARGIN, foot_y, f"{t['tax_id']}: {company['tax_id']}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()

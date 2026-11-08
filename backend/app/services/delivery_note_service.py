"""Lieferschein- und Versandetiketten-Generator für PrintLab.

Erzeugt:
1. Normierte Lieferschein-PDFs (DIN A4) mit Positionstabelle,
   Materialangaben, Gewichten und Kunden-Unterschriftsfeld.
2. Thermo-Versand- und Paket-Etiketten (100×150 mm & 62×29 mm)
   mit QR-Code zur Auftragsverfolgung im Kundenportal.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import qrcode
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas

DEFAULT_COMPANY = {
    "name": "PrintLab 3D-Fertigung",
    "owner": "Lukas Bootz",
    "street": "Industriestraße 1",
    "zip_city": "10115 Berlin",
    "email": "kontakt@printlab.local",
    "phone": "+49 30 12345678",
    "website": "www.printlab.local",
    "tax_id": "DE123456789",
}


def _draw_qr(
    pdf: rl_canvas.Canvas,
    data: str,
    x: float,
    y: float,
    size: float,
) -> None:
    """Zeichnet einen QR-Code direkt auf das Canvas."""
    qr = qrcode.QRCode(
        box_size=1,
        border=0,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    dim = len(matrix)
    cell = size / float(dim)

    pdf.setFillColor(black)
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                # y in reportlab wächst von unten nach oben
                pdf.rect(x + (c * cell), y + ((dim - 1 - r) * cell), cell, cell, fill=1, stroke=0)


def generate_delivery_note_pdf(
    order_data: dict[str, Any],
    company: dict[str, Any] | None = None,
    lang: str = "de",
) -> bytes:
    """Generiert einen A4-Lieferschein als druckfähiges PDF."""
    buf = io.BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    co = dict(DEFAULT_COMPANY)
    if company:
        co.update({k: v for k, v in company.items() if v})

    margin = 20 * mm
    right = width - margin
    y = height - margin

    # 1. Absenderzeile (klein, einzeilig nach DIN 5008)
    pdf.setFont("Helvetica", 7.5)
    pdf.setFillColor(HexColor("#666666"))
    sender_line = f"{co['name']} · {co.get('street', '')} · {co.get('zip_city', '')}"
    pdf.drawString(margin, y, sender_line)
    y -= 8 * mm

    # 2. Empfängeradresse
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.setFillColor(black)
    customer_name = order_data.get("customer") or order_data.get("customer_name") or "Sehr geehrte Damen und Herren"
    pdf.drawString(margin, y, str(customer_name))
    y -= 4.5 * mm

    pdf.setFont("Helvetica", 9.5)
    address = order_data.get("customer_address") or order_data.get("address") or ""
    if address:
        for line in address.splitlines():
            line_str = line.strip()
            if line_str:
                pdf.drawString(margin, y, line_str)
                y -= 4.2 * mm
    else:
        pdf.drawString(margin, y, "Lieferung frei Haus")
        y -= 4.2 * mm

    # 3. Firmen-Briefkopf oben rechts
    head_y = height - margin
    pdf.setFont("Helvetica-Bold", 14)
    pdf.setFillColor(HexColor("#00AE42"))  # Bambu Green
    pdf.drawRightString(right, head_y, str(co["name"]))
    head_y -= 5 * mm

    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(HexColor("#333333"))
    if co.get("owner"):
        pdf.drawRightString(right, head_y, f"Inh. {co['owner']}")
        head_y -= 4 * mm
    if co.get("email"):
        pdf.drawRightString(right, head_y, f"E-Mail: {co['email']}")
        head_y -= 4 * mm
    if co.get("phone"):
        pdf.drawRightString(right, head_y, f"Tel: {co['phone']}")
        head_y -= 4 * mm
    if co.get("website"):
        pdf.drawRightString(right, head_y, str(co["website"]))
        head_y -= 4 * mm

    y = min(y - 12 * mm, height - 60 * mm)

    # 4. Titel & Metadaten-Block
    pdf.setFont("Helvetica-Bold", 16)
    pdf.setFillColor(black)
    pdf.drawString(margin, y, "LIEFERSCHEIN" if lang == "de" else "DELIVERY NOTE")
    y -= 7 * mm

    quote_id = order_data.get("quote_id") or order_data.get("order_id") or "SQ-1001"
    now_str = datetime.now().strftime("%d.%m.%Y")

    pdf.setFont("Helvetica", 9)
    meta_info = [
        f"Lieferschein-Nr.: LS-{quote_id}",
        f"Datum: {now_str}",
        f"Auftrags-Nr.: {quote_id}",
    ]
    meta_str = "   |   ".join(meta_info)
    pdf.drawString(margin, y, meta_str)
    y -= 5 * mm

    pdf.setStrokeColor(HexColor("#E0E0E0"))
    pdf.setLineWidth(0.6)
    pdf.line(margin, y, right, y)
    y -= 8 * mm

    # 5. Positionstabelle
    # Tabellenkopf
    pdf.setFillColor(HexColor("#F5F5F7"))
    pdf.rect(margin, y - 2 * mm, right - margin, 7 * mm, fill=1, stroke=0)

    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.setFillColor(black)
    pdf.drawString(margin + 2 * mm, y + 1 * mm, "Pos.")
    pdf.drawString(margin + 16 * mm, y + 1 * mm, "Artikel / 3D-Druckteil")
    pdf.drawString(margin + 80 * mm, y + 1 * mm, "Material & Spezifikation")
    pdf.drawRightString(margin + 130 * mm, y + 1 * mm, "Gewicht")
    pdf.drawRightString(right - 2 * mm, y + 1 * mm, "Menge")
    y -= 8 * mm

    # Positionen aus Daten
    qty = int(order_data.get("quantity", 1))
    mat_name = order_data.get("material_name") or order_data.get("filament_type") or "Bambu PLA"
    infill = order_data.get("infill_percent", 15)
    layer_h = order_data.get("layer_height_mm", 0.20)
    single_weight = float(order_data.get("single_weight_grams", 0.0))
    total_weight = float(order_data.get("total_weight_grams", single_weight * qty))
    filename = order_data.get("filename") or order_data.get("description") or "3D-Druckmodell"

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(black)
    pdf.drawString(margin + 2 * mm, y, "1")

    # Artikelname
    model_label = f"{filename[:40]}"
    pdf.drawString(margin + 16 * mm, y, model_label)

    # Spezifikation
    spec_label = f"{mat_name} · {infill}% Infill · {layer_h:.2f}mm"
    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(HexColor("#444444"))
    pdf.drawString(margin + 80 * mm, y, spec_label)

    # Gewichte & Menge
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(black)
    weight_str = f"{total_weight:.1f} g" if total_weight > 0 else "—"
    pdf.drawRightString(margin + 130 * mm, y, weight_str)
    pdf.drawRightString(right - 2 * mm, y, f"{qty} Stk.")
    y -= 8 * mm

    pdf.setStrokeColor(HexColor("#EEEEEE"))
    pdf.setLineWidth(0.4)
    pdf.line(margin, y + 2 * mm, right, y + 2 * mm)
    y -= 6 * mm

    # Zusatzpositionen (z. B. Verpackung, Express)
    for idx, item in enumerate(order_data.get("items") or [], start=2):
        if not isinstance(item, dict):
            continue
        pdf.drawString(margin + 2 * mm, y, str(idx))
        desc = str(item.get("description") or "Zusatzleistung")[:40]
        pdf.drawString(margin + 16 * mm, y, desc)
        pdf.drawRightString(right - 2 * mm, y, f"{int(item.get('quantity', 1))} Stk.")
        y -= 7 * mm

    y -= 10 * mm

    # 6. Gesamtangaben & Hinweise
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(margin, y, f"Gesamtgewicht der Sendung: ca. {total_weight / 1000.0:.2f} kg ({total_weight:.0f} g)")
    y -= 5 * mm

    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(HexColor("#555555"))
    pdf.drawString(margin, y, "Versandart: Paketversand / Direktzustellung")
    y -= 4.5 * mm
    pdf.drawString(margin, y, "Qualitätskontrolle: Sichtprüfung und Maßhaltigkeit vor Warenausgang bestanden.")
    y -= 25 * mm

    # 7. Empfangsbestätigung & Unterschriftsfeld
    pdf.setStrokeColor(HexColor("#999999"))
    pdf.setLineWidth(0.5)

    sig_width = 75 * mm
    # Datum / Ort
    pdf.line(margin, y, margin + sig_width, y)
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(HexColor("#666666"))
    pdf.drawString(margin, y - 4 * mm, "Datum, Ort")

    # Unterschrift
    sig_right = right
    pdf.line(sig_right - sig_width, y, sig_right, y)
    pdf.drawString(sig_right - sig_width, y - 4 * mm, "Ware vollständig und unbeschädigt erhalten (Unterschrift)")

    # 8. Fußzeile
    foot_y = margin + 8 * mm
    pdf.setStrokeColor(HexColor("#D0D0D0"))
    pdf.setLineWidth(0.4)
    pdf.line(margin, foot_y + 4 * mm, right, foot_y + 4 * mm)

    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(margin, foot_y, f"{co['name']} · {co.get('website', '')}")
    if co.get("tax_id"):
        pdf.drawRightString(right, foot_y, f"USt-IdNr.: {co['tax_id']}")

    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def generate_thermal_label_pdf(
    order_data: dict[str, Any],
    company: dict[str, Any] | None = None,
    format_size: str = "100x150",
) -> bytes:
    """Generiert ein hochauflösendes Thermo-Versand- oder Paket-Etikett."""
    co = dict(DEFAULT_COMPANY)
    if company:
        co.update({k: v for k, v in company.items() if v})

    buf = io.BytesIO()

    # Formate in Points (1 pt = 1/72 inch, 1 mm = 72/25.4 pt)
    if format_size == "62x29":
        page_w = 62 * mm
        page_h = 29 * mm
        margin = 2 * mm
    else:  # Standard: 100x150 mm Paketaufkleber
        page_w = 100 * mm
        page_h = 150 * mm
        margin = 5 * mm

    pdf = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
    right = page_w - margin
    y = page_h - margin

    quote_id = str(order_data.get("quote_id") or order_data.get("order_id") or "SQ-1001")
    customer_name = str(order_data.get("customer") or order_data.get("customer_name") or "Kunde / Empfänger")
    mat_name = str(order_data.get("material_name") or order_data.get("filament_type") or "Bambu PLA")
    qty = int(order_data.get("quantity", 1))
    weight = float(order_data.get("total_weight_grams", 0.0))

    if format_size == "62x29":
        # Kompaktes Brother QL Etikett
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(margin, y - 2 * mm, f"PrintLab: {quote_id}")
        pdf.setFont("Helvetica", 7)
        pdf.drawString(margin, y - 6 * mm, f"{customer_name[:25]}")
        pdf.drawString(margin, y - 10 * mm, f"{qty}x {mat_name[:20]}")
        pdf.drawString(margin, y - 14 * mm, f"Gewicht: {weight:.0f} g")

        # Kleiner QR rechts
        tracking_url = f"https://printlab.local/portal?quote={quote_id}"
        _draw_qr(pdf, tracking_url, right - 18 * mm, margin + 1 * mm, 16 * mm)

    else:
        # 100x150 mm Großformatiges Paket-Etikett
        # 1. Absender Kopf
        pdf.setFillColor(HexColor("#222222"))
        pdf.rect(margin, y - 12 * mm, right - margin, 12 * mm, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margin + 3 * mm, y - 5 * mm, str(co["name"]).upper())
        pdf.setFont("Helvetica", 7.5)
        pdf.drawString(margin + 3 * mm, y - 9.5 * mm, f"{co.get('street', '')} · {co.get('zip_city', '')}")
        y -= 16 * mm

        # 2. Empfänger Block (groß & prominent)
        pdf.setFillColor(black)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(margin, y, "EMPFÄNGER / DELIVER TO:")
        y -= 5 * mm

        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(margin, y, customer_name)
        y -= 5.5 * mm

        address = order_data.get("customer_address") or order_data.get("address") or ""
        pdf.setFont("Helvetica", 10)
        if address:
            for l in address.splitlines():
                if l.strip():
                    pdf.drawString(margin, y, l.strip())
                    y -= 4.5 * mm
        else:
            pdf.drawString(margin, y, "Selbstabholung / Standard-Lieferung")
            y -= 4.5 * mm

        y -= 4 * mm
        pdf.setLineWidth(1)
        pdf.line(margin, y, right, y)
        y -= 6 * mm

        # 3. Auftrags- & QR-Code Sektion
        qr_size = 28 * mm
        qr_x = right - qr_size - 2 * mm
        tracking_url = f"https://printlab.local/portal?quote={quote_id}"
        _draw_qr(pdf, tracking_url, qr_x, y - qr_size, qr_size)

        # Linke Spalte: Auftragsdaten
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin, y - 2 * mm, f"AUFTRAG: {quote_id}")

        pdf.setFont("Helvetica", 9)
        pdf.drawString(margin, y - 8 * mm, f"Druckteile: {qty} Stück")
        pdf.drawString(margin, y - 13 * mm, f"Material: {mat_name}")
        pdf.drawString(margin, y - 18 * mm, f"Gewicht: {weight:.1f} g")
        pdf.drawString(margin, y - 23 * mm, f"Datum: {datetime.now().strftime('%d.%m.%Y')}")

        y -= qr_size + 8 * mm

        # 4. Qualitäts-Banner
        pdf.setFillColor(HexColor("#F2F2F2"))
        pdf.rect(margin, y - 10 * mm, right - margin, 10 * mm, fill=1, stroke=0)
        pdf.setFillColor(black)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(margin + 4 * mm, y - 6.5 * mm, "[✓] QUALITÄT GEPRÜFT & VERSANDFERTIG")
        y -= 16 * mm

        # 5. Barcode / Token Visualisierung
        pdf.setFont("Helvetica", 7.5)
        pdf.drawCentredString(page_w / 2.0, margin + 4 * mm, f"* {quote_id} *")

    pdf.showPage()
    pdf.save()
    return buf.getvalue()

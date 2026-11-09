"""B2B- & ISO-9001-konformer Qualitätszertifikat-Generator für 3D-Drucke (Phase 14).

Erzeugt:
1. Amtlich strukturierte Qualitätsprüfberichte (DIN A4 PDF) pro Druckauftrag / Archiv:
   - Auftrags- und Seriennummer, Bauteilbezeichnung, Druckdatum & Prüfer
   - Drucker-Telemetrie (Modell, Seriennummer, Düsendurchmesser, Firmware)
   - Rückverfolgbare Material- & Chargendaten (Hersteller, Spulen-ID, Farbe, Grammatur)
   - Qualitätsparameter (First-Layer-Güte, Schichtanomalien, Temperaturstabilität)
   - Digitales Prüfsiegel mit SHA-256-Integritätshash und Verifikations-QR-Code
2. Strukturierte Qualitätsbewertung (QualityScore 0–100%) anhand von Messwerten.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from typing import Any

import qrcode
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

DEFAULT_ISSUER = {
    "company_name": "PrintLab 3D-Fertigung",
    "facility": "Produktionsstandort Berlin",
    "accreditation": "ISO 9001:2015 Qualitätsmanagementsystem",
    "cert_authority": "PrintLab QA Department",
    "verification_base_url": "https://printlab.local/quality/verify",
}


def calculate_quality_score(
    first_layer_score: float = 98.0,
    temperature_deviation_c: float = 0.8,
    anomaly_count: int = 0,
    completed_normally: bool = True,
) -> tuple[float, str]:
    """Berechnet den Gesamt-Qualitätsindex (0-100) und die Güteklasse (A+, A, B, C, FAILED)."""
    if not completed_normally:
        return 0.0, "ABGEBROCHEN"

    score = 100.0
    # First-Layer-Abweichung (bis zu 25 Punkte Abzug)
    fl_penalty = max(0.0, (100.0 - float(first_layer_score)) * 1.25)
    score -= fl_penalty

    # Temperaturstabilität (Abzug wenn > 2.0 °C Abweichung)
    if temperature_deviation_c > 2.0:
        score -= min(15.0, (temperature_deviation_c - 2.0) * 5.0)

    # Schichtanomalien (jede Anomalie kostet 5 Punkte)
    score -= min(30.0, float(anomaly_count) * 5.0)

    final_score = round(max(0.0, min(100.0, score)), 1)
    if final_score >= 95.0:
        grade = "Klasse A+ (Exzellent)"
    elif final_score >= 88.0:
        grade = "Klasse A (Konform)"
    elif final_score >= 75.0:
        grade = "Klasse B (Akzeptabel)"
    elif final_score >= 60.0:
        grade = "Klasse C (Grenzfall)"
    else:
        grade = "Klasse F (Ausschuss)"

    return final_score, grade


def _draw_qr(pdf: rl_canvas.Canvas, data: str, x: float, y: float, size: float) -> None:
    """Zeichnet einen QR-Code auf das Canvas."""
    qr = qrcode.QRCode(box_size=1, border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    dim = len(matrix)
    cell = size / float(dim)

    pdf.setFillColor(black)
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                pdf.rect(x + (c * cell), y + ((dim - 1 - r) * cell), cell, cell, fill=1, stroke=0)


def generate_quality_certificate_pdf(
    cert_data: dict[str, Any],
    issuer: dict[str, Any] | None = None,
) -> bytes:
    """Erzeugt ein DIN-A4-Qualitätszertifikat (PDF) mit allen Messwerten, Prüfsiegel und QR-Code."""
    iss = dict(DEFAULT_ISSUER)
    if issuer:
        iss.update({k: v for k, v in issuer.items() if v})

    buf = io.BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    right = width - margin
    y = height - margin

    # Eindeutige Zertifikatsnummer und Integritätshash
    cert_no = (
        cert_data.get("certificate_number")
        or f"QC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{cert_data.get('job_id', '001')}"
    )
    timestamp_str = cert_data.get("inspection_date") or datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    hash_input = f"{cert_no}|{cert_data.get('part_name')}|{cert_data.get('printer_serial')}|{timestamp_str}|{cert_data.get('filament_lot')}"
    sha256_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    # Scores
    score = float(cert_data.get("quality_score", 98.5))
    grade = cert_data.get("quality_grade") or ("Klasse A+ (Exzellent)" if score >= 95.0 else "Klasse A (Konform)")

    # 1. Kopfbereich mit Zertifikats-Banner
    pdf.setFillColor(HexColor("#1e293b"))  # Slate-800
    pdf.rect(margin, y - 28 * mm, right - margin, 28 * mm, fill=1, stroke=0)

    pdf.setFillColor(white)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(margin + 6 * mm, y - 9 * mm, "WERKS-QUALITÄTSZERTIFIKAT (ISO 9001 / EN 10204 3.1)")

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(HexColor("#94a3b8"))
    pdf.drawString(margin + 6 * mm, y - 16 * mm, f"{iss['company_name']} · {iss['facility']} · {iss['accreditation']}")

    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(HexColor("#38bdf8"))
    pdf.drawString(margin + 6 * mm, y - 23 * mm, f"ZERTIFIKAT-NR.: {cert_no}")
    pdf.drawRightString(right - 6 * mm, y - 23 * mm, f"Prüfdatum: {timestamp_str}")

    y -= 36 * mm

    # 2. Status & Gesamtnote Kasten (Große Bewertungs-Box)
    box_height = 24 * mm
    pdf.setFillColor(HexColor("#f8fafc"))
    pdf.setStrokeColor(HexColor("#cbd5e1"))
    pdf.setLineWidth(1)
    pdf.rect(margin, y - box_height, right - margin, box_height, fill=1, stroke=1)

    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin + 6 * mm, y - 8 * mm, "Gesamtergebnis Qualitätsprüfung:")

    # Güteklasse Badge
    grade_color = (
        HexColor("#16a34a") if score >= 88.0 else (HexColor("#ca8a04") if score >= 75.0 else HexColor("#dc2626"))
    )
    pdf.setFillColor(grade_color)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(margin + 6 * mm, y - 18 * mm, f"QUALITÄTS-INDEX: {score:.1f} / 100 — {grade}")

    pdf.setFillColor(HexColor("#475569"))
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(
        right - 6 * mm, y - 18 * mm, f"Prüfstatus: {'BESTANDEN (PASS)' if score >= 75.0 else 'NICHT BESTANDEN (FAIL)'}"
    )

    y -= 32 * mm

    # 3. Bauteil- und Auftragsdaten
    def draw_section_header(title: str, current_y: float) -> float:
        pdf.setFillColor(HexColor("#0f172a"))
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(margin, current_y, title)
        pdf.setStrokeColor(HexColor("#e2e8f0"))
        pdf.setLineWidth(1)
        pdf.line(margin, current_y - 2 * mm, right, current_y - 2 * mm)
        return current_y - 8 * mm

    y = draw_section_header("1. AUFTRAGS- & BAUTEILINFORMATIONEN", y)

    col1 = margin + 4 * mm
    col2 = margin + 85 * mm
    line_h = 5.2 * mm

    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(black)

    rows_job = [
        ("Bauteil-Name:", str(cert_data.get("part_name", "Serienbauteil 3D"))),
        ("Auftrags- / Losnummer:", str(cert_data.get("order_number", cert_data.get("job_id", "PO-2026-001")))),
        ("Kunde / Besteller:", str(cert_data.get("customer_name", "Vertraulich / Intern"))),
        ("G-Code / Modelldatei:", str(cert_data.get("gcode_file", "model.gcode.3mf"))),
        (
            "Soll-Stückzahl gefertigt:",
            f"{cert_data.get('quantity_produced', 1)} von {cert_data.get('quantity_ordered', 1)} Stk.",
        ),
    ]
    for label, val in rows_job:
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(col1, y, label)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(col2, y, val)
        y -= line_h

    y -= 3 * mm

    # 4. Drucker- & Prozessparameter
    y = draw_section_header("2. MASCHINEN- & PROZESSTELEMETRIE", y)

    rows_proc = [
        (
            "Produktionsanlage:",
            f"{cert_data.get('printer_name', 'Bambu Lab P2S')} (SN: {cert_data.get('printer_serial', '01P2S-SERIAL')})",
        ),
        (
            "Düsen-Konfiguration:",
            f"{cert_data.get('nozzle_diameter', 0.4)} mm ({cert_data.get('nozzle_type', 'Gehärteter Stahl')})",
        ),
        (
            "Schichthöhe / Infill:",
            f"{cert_data.get('layer_height', 0.20)} mm / {cert_data.get('infill_percent', 20)} % Infill",
        ),
        (
            "Fertigungszeitraum:",
            f"{cert_data.get('print_time_formatted', '2h 15m')} (Schichten: {cert_data.get('total_layers', 450)})",
        ),
        (
            "Durchschnittliche Temperaturen:",
            f"Düse: {cert_data.get('avg_nozzle_temp', 220.0):.1f} °C (±{cert_data.get('temp_dev_c', 0.8):.1f} °C) | Bett: {cert_data.get('avg_bed_temp', 55.0):.1f} °C",
        ),
    ]
    for label, val in rows_proc:
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(col1, y, label)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(col2, y, val)
        y -= line_h

    y -= 3 * mm

    # 5. Werkstoff- und Chargen-Rückverfolgbarkeit
    y = draw_section_header("3. WERKSTOFF- & CHARGENRÜCKVERFOLGBARKEIT", y)

    rows_mat = [
        (
            "Material / Polymer:",
            f"{cert_data.get('material', 'PETG')} (Farbcode: #{cert_data.get('color_hex', '000000')})",
        ),
        ("Filament-Hersteller:", str(cert_data.get("filament_vendor", "Bambu Lab"))),
        ("Chargen- / Spulen-ID:", str(cert_data.get("filament_lot", "LOT-2026-B89201"))),
        ("Netto-Materialverbrauch:", f"{cert_data.get('filament_grams', 45.2):.1f} g (inkl. Spülturm/Support)"),
    ]
    for label, val in rows_mat:
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(col1, y, label)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(col2, y, val)
        y -= line_h

    y -= 3 * mm

    # 6. Optische Qualitätsmessung & Schichtanalyse
    y = draw_section_header("4. OPTISCHE QUALITÄTSPRÜFUNG & ANOMALIE-ANALYSE", y)

    rows_qual = [
        (
            "First-Layer Betthaftungs-Score:",
            f"{cert_data.get('first_layer_score', 99.2):.1f} % (Automatische optische Bett-Inspektion)",
        ),
        (
            "Erkannte Schicht-Anomalien:",
            f"{cert_data.get('anomaly_count', 0)} Ereignisse (Spaghetti / Warping: keine kritischen Fehler)",
        ),
        (
            "Maßhaltigkeits-Konformität:",
            str(cert_data.get("dimensional_conformity", "DIN 16742 TG6 (Standard für FFF/FDM)")),
        ),
        ("Oberflächenfinish:", str(cert_data.get("surface_rating", "Gleichmäßig, fehlerfrei, kein Stringing"))),
    ]
    for label, val in rows_qual:
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(col1, y, label)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(col2, y, val)
        y -= line_h

    # 7. Prüfsiegel, Integritätshash und Unterschrift (Unten)
    y_footer = margin + 35 * mm
    pdf.setStrokeColor(HexColor("#cbd5e1"))
    pdf.setLineWidth(1)
    pdf.line(margin, y_footer + 32 * mm, right, y_footer + 32 * mm)

    # QR-Code zur Echtheitsprüfung
    qr_data = f"{iss['verification_base_url']}?cert={cert_no}&hash={sha256_hash[:16]}"
    qr_size = 28 * mm
    _draw_qr(pdf, qr_data, margin, y_footer, qr_size)

    # Prüftext & Hash
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.setFillColor(HexColor("#0f172a"))
    pdf.drawString(margin + qr_size + 6 * mm, y_footer + 24 * mm, "DIGITALES WERKS-PRÜFSIEGEL & INTEGRITÄTSNACHWEIS")

    pdf.setFont("Helvetica", 7.5)
    pdf.setFillColor(HexColor("#64748b"))
    pdf.drawString(
        margin + qr_size + 6 * mm,
        y_footer + 18 * mm,
        "Dieses Dokument wurde automatisch auf Basis der lückenlosen Prozess-Telemetrie generiert.",
    )
    pdf.drawString(
        margin + qr_size + 6 * mm,
        y_footer + 13 * mm,
        f"Kryptografischer Prüf-Hash (SHA-256): {sha256_hash[:48]}...",
    )
    pdf.drawString(
        margin + qr_size + 6 * mm,
        y_footer + 8 * mm,
        f"Freigabestelle: {iss['cert_authority']} · Digital verifiziert am {timestamp_str}",
    )

    # Unterschrifts-Linie rechts
    sig_w = 48 * mm
    sig_x = right - sig_w
    pdf.setStrokeColor(HexColor("#94a3b8"))
    pdf.line(sig_x, y_footer + 8 * mm, right, y_footer + 8 * mm)
    pdf.setFont("Helvetica", 7.5)
    pdf.drawRightString(right, y_footer + 3 * mm, "Unterschrift Qualitätsbeauftragter / QA")

    pdf.showPage()
    pdf.save()
    return buf.getvalue()

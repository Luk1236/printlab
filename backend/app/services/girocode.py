"""EPC-QR-Code (GiroCode) für SEPA-Überweisungen nach dem Standard des European Payments Council (EPC069-12).

Ermöglicht das sekundenschnelle Bezahlen von PrintLab-Rechnungen und -Angeboten
in jeder Banking-App durch Scannen des generierten QR-Codes.
"""

from __future__ import annotations

import base64
import io
import re
from decimal import Decimal
from typing import Any

try:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    QRCODE_AVAILABLE = True
except ImportError:
    qrcode = None
    SvgPathImage = None
    QRCODE_AVAILABLE = False


IBAN_CLEAN_RX = re.compile(r"[\s\-_.]")


def sanitize_iban(iban: str) -> str:
    """Bereinigt eine IBAN von Leerzeichen und Bindestrichen und wandelt sie in Großbuchstaben um."""
    return IBAN_CLEAN_RX.sub("", iban or "").upper()


def build_epc_qr_payload(
    name: str,
    iban: str,
    amount: float | Decimal | None = None,
    bic: str = "",
    purpose: str = "",
    reference: str = "",
) -> str:
    """Erzeugt den normierten Text-Payload für einen EPC-QR-Code (GiroCode).

    Spezifikation EPC069-12 / Version 002:
    Zeile 1: Service Tag ('BCD')
    Zeile 2: Version ('002')
    Zeile 3: Zeichenkodierung ('1' = UTF-8)
    Zeile 4: Funktion ('SCT' = SEPA Credit Transfer)
    Zeile 5: BIC des Empfängers (optional, max 11 Zeichen)
    Zeile 6: Name des Zahlungsempfängers (max 70 Zeichen)
    Zeile 7: IBAN des Empfängers (max 34 Zeichen)
    Zeile 8: Betrag mit Währung ('EUR12.34', max 12 Zeichen)
    Zeile 9: Zweck-Code (optional, 4 Zeichen)
    Zeile 10: Strukturierte Referenz (z.B. ISO 11649 RF-Kreditorreferenz, max 35 Zeichen)
    Zeile 11: Unstrukturierter Verwendungszweck (z.B. 'Rechnung R-2026-0003', max 140 Zeichen)
    Zeile 12: Hinweis an den Empfänger (optional, max 70 Zeichen)
    """
    clean_iban = sanitize_iban(iban)
    if not clean_iban:
        raise ValueError("IBAN darf für den GiroCode nicht leer sein.")

    clean_name = str(name or "").strip()[:70]
    if not clean_name:
        raise ValueError("Name des Empfängers darf nicht leer sein.")

    amount_str = ""
    if amount is not None and float(amount) > 0:
        val = Decimal(str(amount))
        amount_str = f"EUR{val:.2f}"

    clean_bic = str(bic or "").strip().upper()[:11]
    clean_ref = str(reference or "").strip()[:35]
    clean_purpose = str(purpose or "").strip()[:140] if not clean_ref else ""

    lines = [
        "BCD",
        "002",
        "1",
        "SCT",
        clean_bic,
        clean_name,
        clean_iban,
        amount_str,
        "",  # Purpose code
        clean_ref,
        clean_purpose,
        "",  # Beneficiary to originator information
    ]
    return "\n".join(lines)


def generate_girocode_svg(
    name: str,
    iban: str,
    amount: float | Decimal | None = None,
    bic: str = "",
    purpose: str = "",
    reference: str = "",
) -> str:
    """Erzeugt den GiroCode direkt als SVG-String."""
    if not QRCODE_AVAILABLE:
        raise RuntimeError("Das Modul 'qrcode' ist nicht installiert.")

    payload = build_epc_qr_payload(
        name=name,
        iban=iban,
        amount=amount,
        bic=bic,
        purpose=purpose,
        reference=reference,
    )
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
        image_factory=SvgPathImage,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image()
    stream = io.BytesIO()
    img.save(stream)
    return stream.getvalue().decode("utf-8")


def generate_girocode_data_uri(
    name: str,
    iban: str,
    amount: float | Decimal | None = None,
    bic: str = "",
    purpose: str = "",
    reference: str = "",
) -> str:
    """Erzeugt den GiroCode als PNG-Base64 Data-URI ('data:image/png;base64,...')."""
    if not QRCODE_AVAILABLE:
        raise RuntimeError("Das Modul 'qrcode' ist nicht installiert.")

    payload = build_epc_qr_payload(
        name=name,
        iban=iban,
        amount=amount,
        bic=bic,
        purpose=purpose,
        reference=reference,
    )
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def girocode_for_invoice(invoice: dict[str, Any], company: dict[str, Any]) -> str:
    """Gibt die PNG-Data-URI für eine gegebene Rechnung und Firmendaten zurück."""
    iban = company.get("iban") or ""
    bic = company.get("bic") or ""
    name = company.get("name") or "PrintLab"
    amount = invoice.get("total") or invoice.get("gross")
    number = invoice.get("number") or invoice.get("id") or ""
    purpose = f"Rechnung {number}".strip()
    return generate_girocode_data_uri(
        name=name,
        iban=iban,
        amount=amount,
        bic=bic,
        purpose=purpose,
    )

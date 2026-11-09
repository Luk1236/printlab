"""DATEV-Export & ZUGFeRD 2.2 / Factur-X Hybrid PDF Service (Phase 16).

Bietet DATEV EXTF Buchungsstapel (CSV) Export nach amtlicher Schnittstellendefinition
für Steuerberater (SKR03 / SKR04) sowie ZUGFeRD 2.2 / Factur-X Hybrid-PDF Generierung
(PDF/A-3 konform mit eingebettetem factur-x.xml).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from backend.app.services import company_profile, einvoice, quote_pdf

# Kontenrahmen-Definitionen
KONTENRAHMEN: dict[str, dict[str, Any]] = {
    "SKR03": {
        "name": "Standardkontenrahmen 03 (Prozessgliederungsprinzip)",
        "erloese_19": "8400",  # Erlöse 19% USt
        "erloese_7": "8300",  # Erlöse 7% USt
        "erloese_0": "8100",  # Steuerfreie Erlöse
        "forderungen": "10000",  # Sammelkonto Forderungen aus L+L
        "bu_schluessel_auto": "3",  # Automatik 19%
    },
    "SKR04": {
        "name": "Standardkontenrahmen 04 (Abschlussgliederungsprinzip)",
        "erloese_19": "4400",  # Erlöse 19% USt
        "erloese_7": "4300",  # Erlöse 7% USt
        "erloese_0": "4100",  # Steuerfreie Erlöse
        "forderungen": "10000",  # Sammelkonto Debitoren
        "bu_schluessel_auto": "3",
    },
}


def _clean_text(val: Any, max_len: int = 60) -> str:
    """Bereinigt Strings für DATEV-Felder (keine Semikolons, begrenzte Länge)."""
    s = str(val or "").strip().replace(";", " ")
    return s[:max_len]


def generate_datev_csv(
    invoices_list: list[dict[str, Any]],
    skr: str = "SKR03",
    consultant_number: int = 1001,
    client_number: int = 10001,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """Erzeugt den amtlichen DATEV EXTF Buchungsstapel als CSV-String."""
    skr_key = skr.upper() if skr.upper() in KONTENRAHMEN else "SKR03"
    accounts = KONTENRAHMEN[skr_key]

    # Rechnungen filtern
    filtered: list[dict[str, Any]] = []
    for inv in invoices_list:
        if inv.get("status") == "cancelled":
            continue
        issued = inv.get("issued", "")
        if from_date and issued < from_date:
            continue
        if to_date and issued > to_date:
            continue
        filtered.append(inv)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d%H%M%S")
    year = now.year

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quotechar='"', quoting=csv.QUOTE_NONNUMERIC, lineterminator="\r\n")

    # DATEV Header Zeile 1: Datei-Kopf (EXTF-Spezifikation 700)
    # Format: "EXTF";Version;Datenkategorie;Formatname;Formatversion;ErzeugtAm;Importiert;Herkunft;ExportiertVon;...
    writer.writerow(
        [
            "EXTF",
            700,
            21,
            "Buchungsstapel",
            12,
            date_str,
            "",
            "PrintLab 3D Farm",
            "PrintLab",
            "",
            consultant_number,
            client_number,
            int(f"{year}0101"),
            4,
            int(f"{year}0101"),
            int(f"{year}1231"),
            "PrintLab Ausgangsrechnungen",
            "",
            1,
            0,
            0,
            "EUR",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )

    # DATEV Header Zeile 2: Spaltenbezeichnungen
    headers = [
        "Umsatz (ohne Soll/Haben-Kz)",
        "Soll/Haben-Kennzeichen",
        "WKZ",
        "Kurs",
        "Basis-Umsatz",
        "WKZ Basis-Umsatz",
        "Konto",
        "Gegenkonto (ohne BU-Schlüssel)",
        "BU-Schlüssel",
        "Belegdatum",
        "Belegfeld 1",
        "Belegfeld 2",
        "Skonto",
        "Buchungstext",
        "Postensperre",
        "Diverse Adressnummer",
        "Geschäftspartnerbank",
        "Sachverhalt",
        "Zinssperre",
        "Beleglink",
    ]
    writer.writerow(headers)

    # Buchungszeilen
    for inv in filtered:
        # Betrag formatieren (z. B. 119,00)
        gross_cents = inv.get("gross_amount_cents")
        if gross_cents is not None:
            gross_val = Decimal(gross_cents) / Decimal(100)
        else:
            gross_val = Decimal(str(inv.get("total_gross") or inv.get("gross") or 0.0))

        gross_str = f"{gross_val:.2f}".replace(".", ",")

        # Belegdatum: Format TTMM
        issued_raw = inv.get("issued", "")
        if issued_raw and len(issued_raw) >= 10:
            parts = issued_raw.split("-")
            belegdatum = f"{parts[2]}{parts[1]}"
        else:
            belegdatum = now.strftime("%d%m")

        # Konto & Gegenkonto
        tax_pct = float(inv.get("vat_percent") or 19.0)
        if tax_pct >= 18.0:
            erloeskonto = accounts["erloese_19"]
        elif tax_pct > 0.0:
            erloeskonto = accounts["erloese_7"]
        else:
            erloeskonto = accounts["erloese_0"]

        gegenkonto = accounts["forderungen"]
        sh_kz = "S"  # Forderung an Debitor im Soll
        bu_schluessel = ""

        belegfeld_1 = _clean_text(inv.get("number") or f"R-{inv.get('id', '')}", 36)
        customer = inv.get("customer") or inv.get("customer_name") or "Barverkauf / Kunde"
        buchungstext = _clean_text(f"{customer} {inv.get('description', '')}", 60)

        row = [
            gross_str,
            sh_kz,
            "EUR",
            "",
            "",
            "",
            gegenkonto,
            erloeskonto,
            bu_schluessel,
            belegdatum,
            belegfeld_1,
            "",
            "",
            buchungstext,
            "",
            "",
            "",
            "",
            "",
            "",
        ]
        writer.writerow(row)

    return output.getvalue()


def get_accounting_summary(invoices_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Liefert statistische Zusammenfassung aller exportierbaren Rechnungen."""
    total_net = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_gross = Decimal("0.00")
    count = 0

    for inv in invoices_list:
        if inv.get("status") == "cancelled":
            continue
        count += 1
        gross_cents = inv.get("gross_amount_cents")
        net_cents = inv.get("net_amount_cents")
        vat_cents = inv.get("vat_amount_cents")

        if gross_cents is not None and net_cents is not None:
            g = Decimal(gross_cents) / Decimal(100)
            n = Decimal(net_cents) / Decimal(100)
            v = Decimal(vat_cents or (gross_cents - net_cents)) / Decimal(100)
        else:
            g = Decimal(str(inv.get("total_gross") or inv.get("gross") or 0.0))
            n = Decimal(str(inv.get("total_net") or inv.get("net") or 0.0))
            v = Decimal(str(inv.get("total_vat") or inv.get("vat") or (g - n)))

        total_gross += g
        total_net += n
        total_vat += v

    return {
        "invoice_count": count,
        "total_net_eur": float(total_net),
        "total_vat_eur": float(total_vat),
        "total_gross_eur": float(total_gross),
        "currency": "EUR",
    }


def generate_zugferd_facturx_pdf(
    invoice: dict[str, Any],
    company: dict[str, Any] | None = None,
    lang: str = "de",
) -> bytes:
    """Erzeugt ein vollständiges ZUGFeRD 2.2 / Factur-X PDF/A-3 Dokument mit integriertem XML."""
    comp = company or company_profile.read()
    xml_content = einvoice.build_xml(invoice, comp)
    pdf_bytes = quote_pdf.render(
        invoice,
        {**comp, "_logo_path": company_profile.logo_path()},
        lang=lang,
        kind="invoice",
    )
    hybrid_pdf = einvoice.embed_zugferd_xml(pdf_bytes, xml_content, attachment_name="factur-x.xml")
    return hybrid_pdf

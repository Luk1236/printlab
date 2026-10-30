"""E-Rechnung als XRechnung (UBL): Pflichtangaben prüfen und XML erzeugen.

Was dieses Modul leistet: aus einer gespeicherten Rechnung und den Firmendaten
entsteht ein XRechnung-3.0-XML (UBL 2.1) mit den Pflichtfeldern, die die
Rechnung selbst kennt — Verkäufer, Käufer, Steuernummer/USt-IdNr., Nummern,
Daten, Positionen, Steueraufteilung und Summen. Fehlt eine Pflichtangabe,
liefert ``validate`` sie als lesbare Liste, und es wird **kein** XML erzeugt.

Was es **nicht** leistet:

* Keine Zertifizierung und keine Prüfung gegen einen KoSIT-Validator. Ob und ab
  wann XRechnung für den eigenen Betrieb verlangt wird und welche Angaben im
  Einzelfall nötig sind (§ 14 UStG), klärt die Steuerberatung.
* Kein ZUGFeRD (PDF/A-3 mit eingebettetem XML). Dafür bräuchte es einen
  PDF/A-3-Schreiber; das PDF hier bleibt ein normales PDF.
* Keine Sonderfälle: Reverse-Charge, innergemeinschaftliche Lieferung,
  Gutschriften, mehrere Steuersätze, Fremdwährung mit Umrechnung. Eine Rechnung
  mit 0 % Steuer wird als steuerbefreit (Kategorie E) ausgegeben und braucht
  den Hinweis zur Steuerbefreiung in den Firmendaten.

Die Anschrift wird aus dem Freitext der Firmendaten gelesen (Straße in der
ersten Zeile, danach Postleitzahl + Ort); ein Land wird nur erkannt, wenn die
letzte Zeile ein zweibuchstabiger Ländercode ist, sonst gilt ``DE``.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from xml.sax.saxutils import escape

CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_3.0"
PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
DEFAULT_COUNTRY = "DE"
DEFAULT_UNIT = "C62"  # Stück
COUNTRY_RX = re.compile(r"^[A-Z]{2}$")
POSTAL_RX = re.compile(r"^(\d{4,6})\s+(.+)$")


class EInvoiceError(ValueError):
    """Die Rechnung lässt sich nicht als XRechnung ausgeben (Liste in ``issues``)."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _text(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _address(raw: str) -> dict[str, str]:
    """Freitext-Anschrift in Straße, Postleitzahl, Ort und Land zerlegen."""
    lines = [line.strip() for line in str(raw or "").splitlines() if line.strip()]
    if len(lines) == 1 and "," in lines[0]:
        lines = [part.strip() for part in lines[0].split(",") if part.strip()]
    country = DEFAULT_COUNTRY
    if lines and COUNTRY_RX.match(lines[-1]) and len(lines) > 1:
        country = lines.pop()
    street = lines[0] if lines else ""
    postal = city = ""
    if len(lines) > 1:
        match = POSTAL_RX.match(lines[1])
        if match:
            postal, city = match.group(1), match.group(2)
        else:
            city = lines[1]
    if len(lines) > 2 and not city:
        city = lines[2]
    return {"street": street, "postal": postal, "city": city, "country": country}


def validate(invoice: dict[str, Any], company: dict[str, Any]) -> list[str]:
    """Fehlende Pflichtangaben als lesbare Liste; leer heißt „XML kann erzeugt werden“."""
    issues: list[str] = []
    if not _text(company.get("name")):
        issues.append("Firmenname fehlt in den Firmendaten.")
    if not _text(company.get("address")):
        issues.append("Anschrift der Firma fehlt in den Firmendaten.")
    if not _text(company.get("tax_id")):
        issues.append("Steuernummer oder USt-IdNr. fehlt in den Firmendaten.")
    if not _text(company.get("email")):
        issues.append("E-Mail der Firma fehlt — für XRechnung ist eine elektronische Adresse Pflicht.")
    if not _text(invoice.get("customer")):
        issues.append("Kundenname fehlt.")
    if not _text(invoice.get("customer_address")):
        issues.append("Kundenanschrift fehlt.")
    if not _text(invoice.get("number")):
        issues.append("Rechnungsnummer fehlt.")
    for key, label in (("issued", "Rechnungsdatum"), ("due", "Fälligkeitsdatum"), ("service_date", "Leistungsdatum")):
        if not _text(invoice.get(key)):
            issues.append(f"{label} fehlt.")
    if not _text(invoice.get("currency")):
        issues.append("Währung fehlt.")
    try:
        percent = float(company.get("vat_percent") or 0)
    except (TypeError, ValueError):
        percent = 0.0
    if percent <= 0 and not _text(company.get("vat_note")):
        issues.append(
            "Bei 0 % Umsatzsteuer fehlt der Hinweis zur Steuerbefreiung in den Firmendaten "
            "(z. B. „Kleinunternehmer gemäß § 19 UStG“)."
        )
    if _money(invoice.get("total")) < 0:
        issues.append("Der Rechnungsbetrag ist negativ — Gutschriften sind hier nicht vorgesehen.")
    return issues


def _tax_category(percent: float) -> str:
    if percent <= 0:
        return "E"  # steuerbefreit; Begründung steht als Note in der Rechnung
    return "S"  # Regelsteuersatz


def _party(name: str, address: dict[str, str], tax_id: str, email: str, scheme: str | None = None) -> str:
    endpoint = f'<cbc:EndpointID schemeID="{escape(scheme or "EM")}">{escape(email)}</cbc:EndpointID>' if email else ""
    tax = (
        "<cac:PartyTaxScheme>"
        f"<cbc:CompanyID>{escape(tax_id)}</cbc:CompanyID>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        "</cac:PartyTaxScheme>"
        if tax_id
        else ""
    )
    postal = f"<cbc:PostalZone>{escape(address['postal'])}</cbc:PostalZone>" if address["postal"] else ""
    return (
        "<cac:Party>"
        f"{endpoint}"
        f"<cac:PartyName><cbc:Name>{escape(name)}</cbc:Name></cac:PartyName>"
        "<cac:PostalAddress>"
        f"<cbc:StreetName>{escape(address['street'])}</cbc:StreetName>"
        f"{postal}"
        f"<cbc:CityName>{escape(address['city'])}</cbc:CityName>"
        f"<cac:Country><cbc:IdentificationCode>{escape(address['country'])}</cbc:IdentificationCode></cac:Country>"
        "</cac:PostalAddress>"
        f"{tax}"
        f"<cac:PartyLegalEntity><cbc:RegistrationName>{escape(name)}</cbc:RegistrationName></cac:PartyLegalEntity>"
        "</cac:Party>"
    )


def _lines(invoice: dict[str, Any], tax_category: str, percent: float) -> list[dict[str, Any]]:
    """Positionen: Druckleistung (Gesamt minus Zusatzpositionen) und die Zusatzpositionen selbst."""
    total = _money(invoice.get("total"))
    items = [item for item in invoice.get("items") or [] if isinstance(item, dict)]
    extras = Decimal("0.00")
    lines: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=2):
        quantity = _money(item.get("quantity") or 0)
        amount = _money(item.get("amount"))
        if amount <= 0:
            amount = (quantity * _money(item.get("unit_price"))).quantize(Decimal("0.01"))
        if amount <= 0:
            continue
        extras += amount
        lines.append(
            {
                "id": str(index),
                "name": _text(item.get("description"), 80) or "Zusatzposition",
                "quantity": quantity if quantity > 0 else Decimal("1"),
                "amount": amount,
            }
        )
    base = total - extras
    if base < 0:
        base = total
        lines = []
    if base > 0 or not lines:
        description = _text(invoice.get("description"), 120) or "Druckleistung"
        lines.insert(
            0,
            {"id": "1", "name": description, "quantity": Decimal("1"), "amount": base if base > 0 else total},
        )
    for line in lines:
        line["tax_category"] = tax_category
        line["percent"] = percent
    return lines


def build_xml(invoice: dict[str, Any], company: dict[str, Any]) -> str:
    """XRechnung-XML (UBL) erzeugen. ``EInvoiceError``, wenn Pflichtangaben fehlen."""
    issues = validate(invoice, company)
    if issues:
        raise EInvoiceError(issues)

    try:
        percent = float(company.get("vat_percent") or 0)
    except (TypeError, ValueError):
        percent = 0.0
    percent = round(max(0.0, min(percent, 100.0)), 2)
    currency = _text(invoice.get("currency")) or "EUR"
    net = _money(invoice.get("total"))
    vat = (net * Decimal(str(percent)) / 100).quantize(Decimal("0.01"))
    gross = net + vat
    tax_category = _tax_category(percent)
    lines = _lines(invoice, tax_category, percent)
    seller_address = _address(str(company.get("address") or ""))
    buyer_address = _address(str(invoice.get("customer_address") or ""))
    seller = _party(
        _text(company.get("name")),
        seller_address,
        _text(company.get("tax_id"), 40),
        _text(company.get("email"), 80),
    )
    buyer = _party(_text(invoice.get("customer")), buyer_address, "", "", scheme=None)
    reference = _text(invoice.get("quote_number") or invoice.get("number"))
    note = _text(company.get("vat_note") or invoice.get("description"), 400)
    payment = ""
    iban = "".join(ch for ch in _text(company.get("iban"), 40) if ch.isalnum())
    if iban:
        payment = (
            "<cac:PaymentMeans>"
            "<cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>"
            f"<cac:PayeeFinancialAccount><cbc:ID>{escape(iban)}</cbc:ID></cac:PayeeFinancialAccount>"
            "</cac:PaymentMeans>"
        )
    tax_subtotal = (
        "<cac:TaxSubtotal>"
        f'<cbc:TaxableAmount currencyID="{escape(currency)}">{net}</cbc:TaxableAmount>'
        f'<cbc:TaxAmount currencyID="{escape(currency)}">{vat}</cbc:TaxAmount>'
        "<cac:TaxCategory>"
        f"<cbc:ID>{tax_category}</cbc:ID>"
        + (f"<cbc:Percent>{percent:g}</cbc:Percent>" if tax_category != "E" else "")
        + (
            f"<cbc:TaxExemptionReason>{escape(_text(company.get('vat_note'), 200))}</cbc:TaxExemptionReason>"
            if tax_category == "E"
            else ""
        )
        + "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>"
    )
    line_xml = ""
    for line in lines:
        line_xml += (
            "<cac:InvoiceLine>"
            f"<cbc:ID>{escape(line['id'])}</cbc:ID>"
            f'<cbc:InvoicedQuantity unitCode="{DEFAULT_UNIT}">{line["quantity"]}</cbc:InvoicedQuantity>'
            f'<cbc:LineExtensionAmount currencyID="{escape(currency)}">{line["amount"]}</cbc:LineExtensionAmount>'
            "<cac:Item>"
            f"<cbc:Name>{escape(line['name'])}</cbc:Name>"
            "<cac:ClassifiedTaxCategory>"
            f"<cbc:ID>{line['tax_category']}</cbc:ID>"
            + (f"<cbc:Percent>{line['percent']:g}</cbc:Percent>" if line["tax_category"] != "E" else "")
            + "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory>"
            "</cac:Item>"
            f'<cac:Price><cbc:PriceAmount currencyID="{escape(currency)}">{line["amount"]}</cbc:PriceAmount></cac:Price>'
            "</cac:InvoiceLine>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"'
        ' xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
        ' xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        f"<cbc:CustomizationID>{CUSTOMIZATION_ID}</cbc:CustomizationID>"
        f"<cbc:ProfileID>{PROFILE_ID}</cbc:ProfileID>"
        f"<cbc:ID>{escape(_text(invoice.get('number')))}</cbc:ID>"
        f"<cbc:IssueDate>{escape(_text(invoice.get('issued')))}</cbc:IssueDate>"
        f"<cbc:DueDate>{escape(_text(invoice.get('due')))}</cbc:DueDate>"
        "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>"
        + (f"<cbc:Note>{escape(note)}</cbc:Note>" if note else "")
        + f"<cbc:DocumentCurrencyCode>{escape(currency)}</cbc:DocumentCurrencyCode>"
        f"<cbc:BuyerReference>{escape(reference)}</cbc:BuyerReference>"
        f"<cac:AccountingSupplierParty>{seller}</cac:AccountingSupplierParty>"
        f"<cac:AccountingCustomerParty>{buyer}</cac:AccountingCustomerParty>"
        + payment
        + "<cac:PaymentTerms><cbc:Note>"
        + escape(
            f"Zahlbar bis {_text(invoice.get('due'))} unter Angabe der Rechnungsnummer {_text(invoice.get('number'))}."
        )
        + "</cbc:Note></cac:PaymentTerms>"
        f'<cac:TaxTotal><cbc:TaxAmount currencyID="{escape(currency)}">{vat}</cbc:TaxAmount>{tax_subtotal}</cac:TaxTotal>'
        "<cac:LegalMonetaryTotal>"
        f'<cbc:LineExtensionAmount currencyID="{escape(currency)}">{net}</cbc:LineExtensionAmount>'
        f'<cbc:TaxExclusiveAmount currencyID="{escape(currency)}">{net}</cbc:TaxExclusiveAmount>'
        f'<cbc:TaxInclusiveAmount currencyID="{escape(currency)}">{gross}</cbc:TaxInclusiveAmount>'
        f'<cbc:PayableAmount currencyID="{escape(currency)}">{gross}</cbc:PayableAmount>'
        "</cac:LegalMonetaryTotal>"
        f"{line_xml}"
        "</Invoice>"
    )


def filename(invoice: dict[str, Any]) -> str:
    number = re.sub(r"[^A-Za-z0-9._-]", "_", _text(invoice.get("number")) or "Rechnung")
    return f"XRechnung-{number}.xml"

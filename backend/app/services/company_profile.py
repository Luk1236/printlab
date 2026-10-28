"""Firmendaten für Angebote: Briefkopf, Bankverbindung, Umsatzsteuer-Hinweis, Nummernkreis.

Liegt in ``company.json`` im Datenordner. Die Angebots-PDFs lesen den Briefkopf von hier.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.app.core.config import settings

COMPANY_PATH = settings.base_dir / "company.json"

TEXT_LIMITS = {
    "name": 80,
    "address": 240,
    "tax_id": 40,
    "email": 80,
    "phone": 40,
    "iban": 40,
    "bic": 20,
    "footer": 400,
    "vat_note": 240,
    "number_prefix": 8,
}
DEFAULTS: dict[str, Any] = {
    **dict.fromkeys(TEXT_LIMITS, ""),
    "number_prefix": "A",
    "vat_percent": 0.0,
    "valid_days": 14,
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # Zeilenumbruch (\n) bleibt erlaubt


def read() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(COMPANY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if isinstance(raw, dict):
        try:
            data.update(_clean(raw, strict=False))
        except ValueError:
            pass
    return data


def _clean(raw: dict[str, Any], strict: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, limit in TEXT_LIMITS.items():
        if key in raw:
            value = _CONTROL.sub("", str(raw[key] if raw[key] is not None else "")).strip()
            if len(value) > limit and strict:
                raise ValueError(f"„{key}“ ist zu lang (höchstens {limit} Zeichen).")
            out[key] = value[:limit]
    if "number_prefix" in out:
        prefix = re.sub(r"[^A-Za-z0-9]", "", out["number_prefix"])
        out["number_prefix"] = prefix or "A"
    if "vat_percent" in raw:
        try:
            vat = float(raw["vat_percent"])
        except (TypeError, ValueError):
            raise ValueError("Umsatzsteuer muss eine Zahl sein.") from None
        if not 0 <= vat <= 30 or vat != vat:
            raise ValueError("Umsatzsteuer muss zwischen 0 und 30 Prozent liegen.")
        out["vat_percent"] = round(vat, 2)
    if "valid_days" in raw:
        try:
            days = int(raw["valid_days"])
        except (TypeError, ValueError):
            raise ValueError("Gültigkeit muss eine ganze Zahl sein.") from None
        if not 0 <= days <= 365:
            raise ValueError("Gültigkeit muss zwischen 0 und 365 Tagen liegen.")
        out["valid_days"] = days
    return out


def write(raw: dict[str, Any]) -> dict[str, Any]:
    """Firmendaten speichern (nur bekannte Felder, hart geprüft). Wirft ValueError bei ungültigen Werten."""
    if not isinstance(raw, dict):
        raise ValueError("Firmendaten müssen ein Objekt sein.")
    data = {**read(), **_clean(raw, strict=True)}
    COMPANY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = COMPANY_PATH.with_name(COMPANY_PATH.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(COMPANY_PATH)
    return data

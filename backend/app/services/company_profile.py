"""Firmendaten für Angebote: Briefkopf, Bankverbindung, Umsatzsteuer-Hinweis, Nummernkreis.

Liegt in ``company.json`` im Datenordner. Die Angebots-PDFs lesen den Briefkopf von hier.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

COMPANY_PATH = settings.base_dir / "company.json"
LOGO_NAME = "company_logo.png"
MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_LOGO_PIXELS = 4000 * 4000
LOGO_MAX_EDGE = 1200

DEFAULT_NUMBER_FORMAT = "{prefix}-{year}-{seq4}"
NUMBER_TOKENS = ("{prefix}", "{year}", "{yy}", "{seq}", "{seq4}", "{seq5}")
NUMBER_FORMAT_RX = re.compile(r"[A-Za-z0-9{}/_.-]+")

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
    "number_format": 40,
}
DEFAULTS: dict[str, Any] = {
    **dict.fromkeys(TEXT_LIMITS, ""),
    "number_prefix": "A",
    "number_format": DEFAULT_NUMBER_FORMAT,
    "vat_percent": 0.0,
    "valid_days": 14,
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # Zeilenumbruch (\n) bleibt erlaubt


def logo_path() -> Path | None:
    path = COMPANY_PATH.with_name(LOGO_NAME)
    return path if path.is_file() else None


def save_logo(data: bytes) -> None:
    """Logo prüfen (echtes PNG/JPEG, nicht zu groß) und als sauberes PNG ohne Metadaten ablegen."""
    if not data or len(data) > MAX_LOGO_BYTES:
        raise ValueError("Das Logo ist leer oder größer als 2 MB.")
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = MAX_LOGO_PIXELS
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG"):
                raise ValueError("Nur PNG oder JPEG sind als Logo erlaubt.")
            image = image.convert("RGBA")
            image.thumbnail((LOGO_MAX_EDGE, LOGO_MAX_EDGE))
            clean = Image.new("RGBA", image.size)
            clean.putdata(list(image.getdata()))  # nur die Bildpunkte, keine Zusatzdaten
            target = COMPANY_PATH.with_name(LOGO_NAME)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            clean.save(tmp, format="PNG")
            tmp.replace(target)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Das Logo konnte nicht gelesen werden (kein gültiges PNG oder JPEG).") from exc


def delete_logo() -> bool:
    path = COMPANY_PATH.with_name(LOGO_NAME)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def read() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(COMPANY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    if isinstance(raw, dict):
        try:
            data.update(_clean(raw, strict=False))
        except ValueError:
            pass
    data["has_logo"] = logo_path() is not None
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
    if "number_format" in out:
        fmt = out["number_format"] or DEFAULT_NUMBER_FORMAT
        rest = fmt
        for token in NUMBER_TOKENS:
            rest = rest.replace(token, "")
        if (
            not NUMBER_FORMAT_RX.fullmatch(fmt)
            or "{" in rest
            or "}" in rest
            or "{seq" not in fmt
            or ".." in fmt
            or fmt.startswith(("/", "."))
        ):
            if strict:
                raise ValueError(
                    "Das Nummernformat braucht {seq}, {seq4} oder {seq5} und darf nur {prefix}, {year}, {yy} enthalten."
                )
            fmt = DEFAULT_NUMBER_FORMAT
        out["number_format"] = fmt
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

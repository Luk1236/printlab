"""Öffentlicher Angebots-Link mit Zusage oder Ablehnung.

Ein Angebot lässt sich als Link verschicken, den der Kunde **ohne Anmeldung**
öffnet. Der Link ist die Berechtigung: ein zufälliges Merkmal in der Adresse,
zeitlich begrenzt, jederzeit zurückziehbar, und je Angebot höchstens einer
gültig (ein neuer Link macht den alten ungültig).

Was der Kunde sieht: Firma, Angebotsnummer, Datum, Gültigkeit, Kunde,
Leistung, Positionen und Gesamtpreis — **nicht** die interne Kalkulation
(Material, Energie, Arbeitszeit, Aufschlag). Zusagen und Ablehnen ändern nur
diesen Vorgang; das Angebot selbst bleibt, wie es gespeichert wurde.

Ablage: ``data/quote_shares.json``.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.config import settings

SHARES_PATH = settings.base_dir / "quote_shares.json"
MAX_ENTRIES = 2000
DEFAULT_DAYS = 14
MAX_DAYS = 180
MAX_NOTE = 500
DECISIONS = ("accepted", "declined")
_lock = threading.Lock()


class ShareError(ValueError):
    """Meldung, die der Aufrufer dem Benutzer zeigen darf."""


def _read() -> list[dict[str, Any]]:
    try:
        data = json.loads(SHARES_PATH.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(entries: list[dict[str, Any]]) -> None:
    SHARES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SHARES_PATH.with_name(SHARES_PATH.name + ".tmp")
    tmp.write_text(json.dumps(entries[:MAX_ENTRIES], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SHARES_PATH)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_expired(entry: dict[str, Any], now: datetime | None = None) -> bool:
    expires = _parse(entry.get("expires_at"))
    return expires is None or expires <= (now or _now())


def create(quote_id: str, days: int = DEFAULT_DAYS, quote: dict[str, Any] | None = None) -> dict[str, Any]:
    """Neuen Link erzeugen; ein noch offener Link desselben Angebots wird ungültig.

    ``quote`` ist der gespeicherte Angebotseintrag — er wird hier nur geprüft,
    damit kein Link auf ein gelöschtes Angebot entsteht.
    """
    if quote is None:
        raise ShareError("Angebot nicht gefunden.")
    days = max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))
    now = _now()
    entry = {
        "token": secrets.token_urlsafe(32),
        "quote_id": str(quote_id),
        "number": str(quote.get("number") or ""),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=days)).isoformat(),
        "status": "open",
        "responded_at": None,
        "note": "",
    }
    with _lock:
        stored = _read()
        for other in stored:
            if other.get("quote_id") == entry["quote_id"] and other.get("status") == "open":
                other["status"] = "revoked"
                other["revoked_at"] = now.isoformat()
        _write([entry, *stored])
    return entry


def get(token: str) -> dict[str, Any] | None:
    token = str(token or "").strip()
    if not token:
        return None
    return next((e for e in _read() if e.get("token") == token), None)


def list_for_quote(quote_id: str) -> list[dict[str, Any]]:
    """Links eines Angebots, neueste zuerst — ohne das Merkmal selbst preiszugeben."""
    result = []
    for entry in _read():
        if entry.get("quote_id") != str(quote_id):
            continue
        result.append(
            {
                "created_at": entry.get("created_at"),
                "expires_at": entry.get("expires_at"),
                "status": entry.get("status"),
                "responded_at": entry.get("responded_at"),
                "note": entry.get("note") or "",
                "expired": _is_expired(entry),
                "token_tail": str(entry.get("token", ""))[-6:],
            }
        )
    return result


def revoke(token: str) -> bool:
    """Link zurückziehen. Gibt ``False`` zurück, wenn es ihn nicht (mehr) gibt."""
    with _lock:
        stored = _read()
        for entry in stored:
            if entry.get("token") == token:
                if entry.get("status") == "open":
                    entry["status"] = "revoked"
                    entry["revoked_at"] = _now().isoformat()
                    _write(stored)
                return True
    return False


def revoke_open(quote_id: str) -> bool:
    """Den offenen Link eines Angebots zurückziehen (ohne das Merkmal zu kennen)."""
    changed = False
    with _lock:
        stored = _read()
        for entry in stored:
            if entry.get("quote_id") == str(quote_id) and entry.get("status") == "open":
                entry["status"] = "revoked"
                entry["revoked_at"] = _now().isoformat()
                changed = True
        if changed:
            _write(stored)
    return changed


def open_entry(token: str) -> tuple[dict[str, Any], bool]:
    """Gültigen, offenen Link laden. Rückgabe: (Eintrag, bereits beantwortet).

    ``ShareError`` mit lesbarer Begründung, wenn der Link unbekannt, abgelaufen
    oder zurückgezogen ist. Ein bereits beantworteter Link ist kein Fehler —
    die Seite zeigt dann das Ergebnis.
    """
    entry = get(token)
    if entry is None:
        raise ShareError("Dieser Link ist unbekannt. Bitte den Absender um einen neuen bitten.")
    if entry.get("status") == "revoked":
        raise ShareError("Dieser Link wurde zurückgezogen. Bitte den Absender um einen neuen bitten.")
    # Eine bereits gegebene Antwort bleibt sichtbar, auch nach Ablauf der Frist:
    # der Kunde soll nachlesen können, was er zugesagt oder abgelehnt hat.
    if entry.get("status") in DECISIONS:
        return entry, True
    if _is_expired(entry):
        raise ShareError("Dieser Link ist abgelaufen. Bitte den Absender um einen neuen bitten.")
    return entry, False


def respond(token: str, decision: str, note: str = "") -> dict[str, Any]:
    """Zusage oder Ablehnung festhalten — genau einmal.

    Ein zweiter Aufruf ändert nichts und meldet den bereits gespeicherten
    Stand; so kann ein doppelt abgeschicktes Formular die Entscheidung nicht
    umdrehen.
    """
    if decision not in DECISIONS:
        raise ShareError("Unbekannte Antwort.")
    entry, answered = open_entry(token)
    if answered:
        return entry
    with _lock:
        stored = _read()
        for current in stored:
            if current.get("token") != token:
                continue
            if current.get("status") != "open":
                return current  # inzwischen beantwortet oder zurückgezogen
            current["status"] = decision
            current["responded_at"] = _now().isoformat()
            current["note"] = str(note or "").strip()[:MAX_NOTE]
            _write(stored)
            return current
    raise ShareError("Dieser Link wurde inzwischen zurückgezogen.")


def public_view(quote: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    """Die Angaben, die der Kunde sehen darf — ohne interne Kalkulation."""
    created = _parse(quote.get("ts")) or _now()
    valid_days = 0
    try:
        valid_days = max(0, min(int(company.get("valid_days") or 0), MAX_DAYS))
    except (TypeError, ValueError):
        valid_days = 0
    items = []
    for item in quote.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "description": str(item.get("description") or "")[:80],
                "quantity": item.get("quantity"),
                "unit_price": item.get("unit_price"),
                "amount": item.get("amount"),
            }
        )
    return {
        "number": str(quote.get("number") or ""),
        "date": created.date().isoformat(),
        "valid_until": (created + timedelta(days=valid_days)).date().isoformat() if valid_days else None,
        "customer": str(quote.get("customer") or ""),
        "customer_address": str(quote.get("customer_address") or ""),
        "description": str(quote.get("description") or ""),
        "currency": str(quote.get("currency") or "EUR"),
        "items": items,
        "extras": quote.get("extras") or 0,
        "total": quote.get("total") or 0,
        "company": {
            "name": str(company.get("name") or ""),
            "address": str(company.get("address") or ""),
            "email": str(company.get("email") or ""),
            "phone": str(company.get("phone") or ""),
            "tax_id": str(company.get("tax_id") or ""),
            "vat_note": str(company.get("vat_note") or ""),
        },
    }

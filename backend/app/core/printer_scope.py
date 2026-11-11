"""Drucker-Beschränkung von API-Schlüsseln für alle Routen durchsetzen (T6-01 der Code-Analyse).

Ein API-Schlüssel kann auf einzelne Drucker beschränkt sein (``APIKey.printer_ids``, ``None`` = alle). Geprüft wurde
das bisher nur in den Dateirouten; Stopp, Pause, Bewegung, Kamera und der Rest ließen jeden Drucker zu. Statt die
Prüfung an 160 Routen einzeln nachzutragen, hängt sie einmal an der App und greift überall dort, wo eine Anfrage einen
Drucker benennt:

* ``printer_id`` im Pfad oder als Query-Parameter,
* ``printer_id``, ``target_printer_id`` oder ``printer_ids`` auf der obersten Ebene eines JSON-Körpers.

Das ist keine Anmeldung. Ob der Schlüssel gültig ist und das nötige Recht hat, entscheidet weiterhin die Route; hier
wird nur abgelehnt, was ein beschränkter Schlüssel nicht darf. Deshalb genügt die Suche über den (nicht geheimen)
Schlüssel-Präfix ohne die teure Hash-Prüfung: Passt genau ein Schlüssel, ist es entweder dieser oder die Route lehnt
die Anfrage ohnehin ab. Nur wenn mehrere Schlüssel denselben Präfix haben, wird vollständig geprüft.

Nicht abgedeckt: Listen ohne Druckerangabe (zeigen weiter alle Drucker) und Drucker, die tiefer im Körper stehen.
"""

from __future__ import annotations

import json
import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from starlette.requests import HTTPConnection, Request

from backend.app.core import auth
from backend.app.models.api_key import APIKey

logger = logging.getLogger(__name__)

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BODY_SINGLE_KEYS = ("printer_id", "target_printer_id")
_UNRESTRICTED = object()


def _presented_key(conn: HTTPConnection) -> str | None:
    """Der mitgeschickte API-Schlüssel; gleiche zwei Wege wie ``validated_api_key_from_request``."""
    key = conn.headers.get("x-api-key")
    if key:
        return key
    scheme, _, token = conn.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() == "bearer" and token.startswith("bb_"):
        return token
    return None


def _as_printer_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


async def _allowed_printer_ids(candidate: str) -> object:
    """Erlaubte Drucker des Schlüssels, oder ``_UNRESTRICTED`` (auch für unbekannte Schlüssel: die Route lehnt sie ab)."""
    prefix = candidate[:8]
    pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    async with auth.async_session() as db:
        result = await db.execute(
            select(APIKey.printer_ids).where(APIKey.enabled.is_(True), APIKey.key_prefix.like(pattern, escape="\\"))
        )
        rows = [row[0] for row in result.all()]
    if not rows:
        return _UNRESTRICTED
    if len(rows) > 1:
        try:
            api_key = await auth.validated_api_key_from_request(None, candidate)
        except HTTPException:
            return _UNRESTRICTED
        if api_key is None:
            return _UNRESTRICTED
        rows = [api_key.printer_ids]
    return _UNRESTRICTED if rows[0] is None else rows[0]


async def _body_printer_ids(request: Request) -> set[int]:
    try:
        payload = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return set()  # kein lesbares JSON: die Route antwortet selbst mit 422
    if not isinstance(payload, dict):
        return set()
    found = {_as_printer_id(payload.get(key)) for key in _BODY_SINGLE_KEYS}
    many = payload.get("printer_ids")
    if isinstance(many, list):
        found.update(_as_printer_id(item) for item in many)
    found.discard(None)
    return found  # type: ignore[return-value]


async def enforce_api_key_printer_scope(conn: HTTPConnection) -> None:
    """App-weite Abhängigkeit, siehe Modul-Docstring. Ohne API-Schlüssel oder ohne Druckerangabe ein No-op."""
    candidate = _presented_key(conn)
    if candidate is None:
        return
    targets = {
        _as_printer_id(conn.path_params.get("printer_id")),
        _as_printer_id(conn.query_params.get("printer_id")),
    }
    targets.discard(None)
    reads_body = (
        isinstance(conn, Request)
        and conn.method in _BODY_METHODS
        and "json" in conn.headers.get("content-type", "").lower()
    )
    if not targets and not reads_body:
        return

    allowed = await _allowed_printer_ids(candidate)
    if allowed is _UNRESTRICTED:
        return
    if reads_body:
        targets |= await _body_printer_ids(conn)  # type: ignore[arg-type]
    for printer_id in sorted(targets):  # type: ignore[type-var]
        if printer_id not in allowed:  # type: ignore[operator]
            logger.warning("API key refused for printer %s: outside its printer_ids", printer_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key does not have access to printer {printer_id}",
            )

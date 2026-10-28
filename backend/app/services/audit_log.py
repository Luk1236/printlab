"""Audit-Log für Hardware- und Wartungsaktionen (Roadmap P2).

Jede relevante Aktion (Tür, Plattenwechsel, Magazin, Not-Halt,
Konfigurationsänderung, Wartungsprogramme) landet als Zeile in
``data/audit_log.jsonl``: Zeitstempel, Drucker, Aktion, Ergebnis, optional
Benutzer. Die Datei liegt chronologisch vor (älteste Zeile zuerst) und wird
auf ``MAX_LINES`` gekappt; das Lesen liefert die neuesten Einträge zuerst.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Wie der Einmessungs-Layer: ``data/`` unter dem Projekt (lokal) bzw. DATA_DIR
# (Docker) — dort, wo die übrigen PrintLab-Konfigurationen liegen.
_LOG_DIR = settings.plate_calibration_dir.parent
LOG_PATH = _LOG_DIR / "audit_log.jsonl"
_LEGACY_PATH = settings.base_dir / "audit_log.jsonl"  # Stand vor v1.3.0 im Projekt-Root
MAX_LINES = 2000
_TRIM_EVERY = 250  # Zeilen bis zum nächsten Kappen (Anfügen statt stetigem Neuschreiben)
_lock = threading.Lock()
_lines_since_trim = 0
_migrated = False


def _ensure_path() -> Any:
    """Ablage sicherstellen und die Alt-Schnittstelle aus dem Projekt-Root mitnehmen.

    Die alte Datei stand „neueste zuerst“; für das chronologische Anfügen wird
    sie beim Übernehmen gedreht.
    """
    global _migrated
    if not _migrated:
        _migrated = True
        try:
            legacy_lines: list[str] = []
            if _LEGACY_PATH.exists():
                legacy_lines = _LEGACY_PATH.read_text(encoding="utf-8").splitlines()
            if legacy_lines and not LOG_PATH.exists():
                LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                LOG_PATH.write_text("\n".join(reversed(legacy_lines)) + "\n", encoding="utf-8")
                _LEGACY_PATH.unlink()
        except OSError as exc:
            logger.warning("[AuditLog] Alte Datei nicht übernommen: %s", exc)
    return LOG_PATH


def _trim() -> None:
    """Datei auf ``MAX_LINES`` kappen (chronologisch: die neuesten Zeilen bleiben)."""
    try:
        existing = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return
    if len(existing) <= MAX_LINES:
        return
    tmp = LOG_PATH.with_name(LOG_PATH.name + ".tmp")
    try:
        tmp.write_text("\n".join(existing[-MAX_LINES:]) + "\n", encoding="utf-8")
        tmp.replace(LOG_PATH)
    except OSError as exc:
        logger.warning("[AuditLog] Kappen fehlgeschlagen: %s", exc)


def record(action: str, ok: bool, message: str = "", printer_id: int | None = None,
           user: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aktion protokollieren (Fehler beim Schreiben dürfen nie aufsteigen)."""
    global _lines_since_trim
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "ok": ok,
        "message": message,
        "printer_id": printer_id,
        "user": user,
    }
    if details:
        entry["details"] = details
    try:
        with _lock:
            path = _ensure_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:  # anfügen; Kappen nur alle _TRIM_EVERY Zeilen
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _lines_since_trim += 1
            if _lines_since_trim >= min(MAX_LINES, _TRIM_EVERY):
                _lines_since_trim = 0
                _trim()
    except OSError as exc:
        logger.warning("[AuditLog] Schreiben fehlgeschlagen: %s", exc)
    return entry


def entries(limit: int = 50, printer_id: int | None = None) -> list[dict[str, Any]]:
    """Neueste Einträge; optional auf einen Drucker gefiltert."""
    out: list[dict[str, Any]] = []
    try:
        with _lock:
            lines = _ensure_path().read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return out
    # Neueste zuerst: beim Anfügen stehen die ältesten am Dateianfang.
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if printer_id is not None and entry.get("printer_id") not in (printer_id, None):
            continue
        out.append(entry)
        if len(out) >= max(1, min(limit, MAX_LINES)):
            break
    return out

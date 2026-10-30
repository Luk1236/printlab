"""Dauerhafte Ablage für Fehlerbilder (KI-Material zum Anschauen und späteren Lernen).

Bei jeder Fehlprüfungs-Warnung mit Kamerabild (Platte nicht frei, Erste-Schicht-
Inspektor, Spaghetti-Verdacht, Bauteil-Wächter, KI-Fehlererkennung) kommt das
Bild statt nur in die Meldung auch hierher. Anders als die Benachrichtigungs-
Fotos (`notification_photos`) bleiben sie bewusst liegen: sie sind das Rohmaterial
für eine spätere Fehlererkennung, die echte Fehlerbilder braucht. Deshalb:

- Aufbewahrung nach Alter **und** Anzahl (älteste zuerst weg), beide Konstanten
  bewusst knapp, damit die SD-Karte nicht volläuft — die Pi-Gesundheitskarte
  meldet es sonst als ``disk_low``.
- Der Dateiname ist wie bei den Benachrichtigungs-Fotos die Zugangskarte:
  unguessbares Token, die Route dient nur Namen dieses exakten Musters.
- Speichern läuft ohne Netz — es darf niemals eine Meldung blockieren; jeder
  Fehler landet nur im Debug-Protokoll.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

from backend.app.core.config import settings
from backend.app.utils.safe_path import PathTraversalError, safe_join_under

logger = logging.getLogger(__name__)

# 90 Tage und höchstens 500 Bilder in Summe — für die Sammlung reicht das
# reichlich, ein späteres Trainingsset lebt ohnehin woanders (exportiert).
_MAX_AGE_SECONDS = 90 * 24 * 60 * 60
_MAX_FILES = 500

# fail_{event}_{YYYYmmdd}_{HHMMSS}_{token_urlsafe(24)}.jpg
_TOKEN_BYTES = 24
_FILENAME_RE = re.compile(
    r"fail_(?P<event>[a-z0-9_]+?)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<token>[A-Za-z0-9_-]{32})\.jpg"
)


def failure_images_dir() -> Path:
    return settings.base_dir / "failure_images"  # SEC-PATH-OK: konstanter Unterordner


def _prune(directory: Path) -> None:
    """Best-effort: zu alte und zu viele Bilder löschen (älteste zuerst).

    Die Übergrenze gilt für die Bilder, die den Altersschnitt **überlebt** haben. Früher wurde sie auf
    die alte Gesamtzahl gerechnet und danach noch einmal so viele frische Bilder gelöscht (600 Bilder,
    300 zu alt → nur 300 statt 500 übrig).
    """
    try:
        entries = [entry for entry in directory.iterdir() if entry.is_file() and _FILENAME_RE.fullmatch(entry.name)]
        cutoff = time.time() - _MAX_AGE_SECONDS
        survivors: list[tuple[float, Path]] = []
        for entry in entries:
            try:
                mtime = entry.stat().st_mtime
                if mtime < cutoff:
                    entry.unlink()
                    continue
                survivors.append((mtime, entry))
            except OSError:
                continue
        over = len(survivors) - _MAX_FILES
        if over > 0:
            for _mtime, entry in sorted(survivors, key=lambda item: item[0])[:over]:
                try:
                    entry.unlink()
                except OSError:
                    continue
    except OSError as exc:
        logger.debug("Fehlerbilder nicht aufgeräumt: %s", exc)


def save_failure_image(image_data: bytes, event_type: str) -> str | None:
    """Bild ablegen und Dateinamen liefern; None, wenn nichts zu tun ging.

    Läuft synchron — Aufrufer auf dem Async-Pfad wickeln das in
    ``asyncio.to_thread``.
    """
    if not image_data:
        return None
    directory = failure_images_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune(directory)
        safe_event = re.sub(r"[^a-z0-9_]", "", event_type.lower()) or "event"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fail_{safe_event}_{timestamp}_{secrets.token_urlsafe(_TOKEN_BYTES)}.jpg"
        (directory / filename).write_bytes(image_data)  # SEC-PATH-OK: Name oben erzeugt, nicht Nutzereingabe
        return filename
    except OSError as exc:
        logger.debug("Fehlerbild nicht gespeichert: %s", exc)
        return None


def find_failure_image(filename: str) -> Path | None:
    """Dateipfad zum Namen (None bei fremdem Muster, Traversal, Alter)."""
    if not _FILENAME_RE.fullmatch(filename):
        return None
    try:
        candidate = safe_join_under(failure_images_dir(), filename, http=False)
    except PathTraversalError:
        return None
    try:
        if not candidate.is_file() or candidate.stat().st_mtime < time.time() - _MAX_AGE_SECONDS:
            return None
    except OSError:
        return None
    return candidate


def list_failure_images() -> list[dict]:
    """Alle noch gültigen Bilder, neueste zuerst (name, event, timestamp, size, mtime)."""
    directory = failure_images_dir()
    out: list[dict] = []
    try:
        cutoff = time.time() - _MAX_AGE_SECONDS
        for entry in directory.iterdir():
            match = _FILENAME_RE.fullmatch(entry.name) if entry.is_file() else None
            if match is None:
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue
            out.append(
                {
                    "name": entry.name,
                    "event": match.group("event"),
                    "timestamp": datetime.strptime(
                        f"{match.group('date')}{match.group('time')}", "%Y%m%d%H%M%S"
                    ).strftime("%Y-%m-%dT%H:%M:%S"),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    except OSError:
        return []
    return sorted(out, key=lambda item: item["mtime"], reverse=True)


def delete_failure_image(filename: str) -> bool:
    """Datei löschen; True nur bei echtem Löschvorgang (fremdes Muster: False)."""
    path = find_failure_image(filename)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True

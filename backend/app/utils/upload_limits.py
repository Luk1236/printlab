"""Grenzen für Uploads (T5-02 und T5-03 der Code-Analyse).

``await file.read()`` ohne Größenangabe lädt den ganzen Upload in den Speicher und prüft nichts; auf einem
Raspberry Pi reicht eine große Datei, um den Prozess zu beenden. Die Hilfen hier lesen in Stücken und
brechen bei Überschreitung mit 413 ab, ohne weiterzulesen.

* :func:`read_upload_limited` für Uploads, die ohnehin im Speicher verarbeitet werden (Bilder, kleine Modelle).
* :func:`save_upload_limited` für große Dateien (3MF, ZIP): schreibt in Stücken auf die Platte, der
  Speicherbedarf ist ein Stück und nicht die Datei.

Die Obergrenzen kommen aus den Einstellungen ``max_upload_mb`` (Standard 1024) und ``max_portal_upload_mb``
(Standard 25, für das öffentliche Kundenportal); gesetzt über die Umgebung ``MAX_UPLOAD_MB`` und
``MAX_PORTAL_UPLOAD_MB``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fastapi import HTTPException

from backend.app.core.config import settings

MB = 1024 * 1024
UPLOAD_CHUNK_BYTES = 1 * MB

# Feste Grenzen für Uploads, die nie groß sein sollen.
MAX_IMAGE_UPLOAD_BYTES = 25 * MB
MAX_AUDIO_UPLOAD_BYTES = 100 * MB
MAX_DESIGN_UPLOAD_BYTES = 256 * MB
MAX_SMALL_FILE_UPLOAD_BYTES = 50 * MB


class _AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


def max_upload_bytes() -> int:
    """Obergrenze für große Uploads (Bibliothek, Archiv, ZIP)."""
    return settings.max_upload_mb * MB


def max_portal_upload_bytes() -> int:
    """Obergrenze für Uploads ohne Anmeldung (Kundenportal)."""
    return settings.max_portal_upload_mb * MB


def _too_large(max_bytes: int) -> HTTPException:
    return HTTPException(status_code=413, detail=f"Upload too large (max {max(1, max_bytes // MB)} MB)")


async def read_upload_limited(upload: _AsyncReadable, max_bytes: int) -> bytes:
    """Upload in Stücken in den Speicher lesen; bei Überschreitung 413, ohne weiterzulesen."""
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            return b"".join(parts)
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(max_bytes)
        parts.append(chunk)


async def save_upload_limited(upload: _AsyncReadable, dest: Path, max_bytes: int) -> tuple[int, bytes]:
    """Upload in Stücken nach *dest* schreiben. Gibt (Größe, erste 8 Byte) zurück.

    Die ersten Bytes reichen für die Magic-Byte-Prüfung (``PK\\x03\\x04`` bei 3MF). Bei Überschreitung
    und bei jedem anderen Abbruch wird die angefangene Datei gelöscht.
    """
    total = 0
    head = b""
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    return total, head
                if not head:
                    head = chunk[:8]
                total += len(chunk)
                if total > max_bytes:
                    raise _too_large(max_bytes)
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

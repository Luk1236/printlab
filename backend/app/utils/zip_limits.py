"""Grenzen für das Entpacken von Zip-Dateien (T5-01 der Code-Analyse).

Eine 3MF ist ein Zip. Ein Zip kann mit gut komprimierbarem Inhalt tausendfach größer entpackt werden
als es auf der Platte liegt (gemessen: 199 KB zu 200 MB). ``ZipFile.read`` lädt das ganze Teil in den
Speicher und fragt nicht nach; ein hochgeladenes Zip konnte so den Prozess beenden.

``ZipInfo.file_size`` ist als Obergrenze verlässlich: ``zipfile`` liest nie mehr als diese Zahl, ein
zu klein angegebener Eintrag endet in einem CRC-Fehler und nicht in mehr Daten. Die Prüfung läuft
deshalb **vor** dem Entpacken und kostet nichts.

Jede Stelle, die ein Teil einer fremden Zip-Datei in den Speicher liest, geht durch :func:`read_member`.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

MB = 1024 * 1024

# Metadaten, Konfiguration, Vorschaubilder: nie groß. Ein größeres Teil dieser Art ist kein 3MF-Teil.
MAX_SMALL_MEMBER_BYTES = 32 * MB
# Netze und G-code sind es mitunter: ein 163-MB-Netz ist in Bambu-Dateien gesehen worden
# (siehe ``plate_thumbnail._parse_model_file``), G-code einer langen Platte liegt ähnlich.
MAX_LARGE_MEMBER_BYTES = 768 * MB
_LARGE_SUFFIXES = (".model", ".gcode", ".stl", ".obj", ".3mf", ".step", ".stp")

# Obergrenzen für ganze Archive, wo viele Dateien entpackt werden (ZIP-Upload in die Bibliothek).
MAX_ZIP_MEMBERS = 20_000
MAX_ZIP_TOTAL_BYTES = 4096 * MB


class ZipLimitError(ValueError):
    """Ein Zip-Teil oder das ganze Archiv ist größer, als dieser Pfad lesen darf."""


def member_limit(name: str) -> int:
    """Obergrenze für ein Teil nach seiner Endung: große für Netze und G-code, kleine für alles andere."""
    return MAX_LARGE_MEMBER_BYTES if name.lower().endswith(_LARGE_SUFFIXES) else MAX_SMALL_MEMBER_BYTES


def check_zip(
    zf: zipfile.ZipFile,
    *,
    max_members: int = MAX_ZIP_MEMBERS,
    max_total_bytes: int = MAX_ZIP_TOTAL_BYTES,
) -> None:
    """Teilzahl und entpackte Gesamtgröße aus dem Inhaltsverzeichnis prüfen, ohne etwas zu entpacken."""
    infos = zf.infolist()
    if len(infos) > max_members:
        raise ZipLimitError(f"zip has {len(infos)} entries, limit is {max_members}")
    total = sum(info.file_size for info in infos)
    if total > max_total_bytes:
        raise ZipLimitError(f"zip unpacks to {total} bytes, limit is {max_total_bytes}")


def read_member(zf: zipfile.ZipFile, name: str | zipfile.ZipInfo, *, max_bytes: int | None = None) -> bytes:
    """``zf.read(name)`` mit Obergrenze. Wirft :class:`ZipLimitError`, bevor etwas entpackt wird.

    Ohne *max_bytes* gilt die Grenze nach der Endung (:func:`member_limit`). Ein fehlendes Teil wirft wie
    ``ZipFile.read`` ``KeyError``.
    """
    info = name if isinstance(name, zipfile.ZipInfo) else zf.getinfo(name)
    limit = member_limit(info.filename) if max_bytes is None else max_bytes
    if info.file_size > limit:
        raise ZipLimitError(f"{info.filename!r} unpacks to {info.file_size} bytes, limit is {limit}")
    return zf.read(info)


def read_member_large(zf: zipfile.ZipFile, name: str | zipfile.ZipInfo) -> bytes:
    """Wie :func:`read_member`, aber mit der großen Grenze für jedes Teil.

    Für Schleifen, die *alle* Teile einer 3MF in eine neue kopieren: dort kann jede Endung vorkommen
    (Anhänge, Bilder), und die Grenze soll nur Bomben abwehren, nicht Dateien umbenennen.
    """
    return read_member(zf, name, max_bytes=MAX_LARGE_MEMBER_BYTES)


def extract_member_limited(zf: zipfile.ZipFile, name: str, dest: Path, *, max_bytes: int) -> int:
    """Ein Zip-Teil in Stücken nach *dest* schreiben, ohne es im Speicher zu halten. Gibt die Größe zurück.

    Prüft die angegebene Größe vor dem Entpacken und zählt beim Schreiben noch einmal mit. Bei Überschreitung
    wird die angefangene Datei gelöscht und :class:`ZipLimitError` geworfen.
    """
    info = zf.getinfo(name)
    if info.file_size > max_bytes:
        raise ZipLimitError(f"{info.filename!r} unpacks to {info.file_size} bytes, limit is {max_bytes}")
    total = 0
    try:
        with zf.open(info) as src, dest.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ZipLimitError(f"{info.filename!r} unpacks to more than {max_bytes} bytes")
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return total

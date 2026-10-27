"""Wartungsdruck: reine Bewegung ohne Filament und ohne Heizung.

Baut aus einer vorhandenen, gültigen P2S-3MF eine neue Datei, deren G-code nur
das Schmierprogramm ausführt. Am Bambu-Monitor am P2S getestet; hier als
Dienst im PrintLab-Fork, damit die erzeugte Datei über den Dateimanager oder
die Warteschlange gestartet werden kann.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

Z_LOW = 30
Z_HIGH = 150
FEED_Z = 600
FEED_XY = 3000
PAUSE = 30
CYCLES = 5
MAX_XY = 236
MIN_XY = 20

HEADER = """; HEADER_BLOCK_START
; BambuStudio 02.08.02.61
; Wartungsdruck: {title} (nur Bewegung, kein Filament)
; model printing time: {minutes}m; total estimated time: {minutes}m
; total layer number: 0
; total filament length [mm] : 0
; total filament volume [cm^3] : 0
; total filament weight [g] : 0
; HEADER_BLOCK_END

; EXECUTABLE_BLOCK_START
M73 P0 R7
M17
M400
G28
G90
M400
"""

FOOTER = """M400
M73 P100 R0
; EXECUTABLE_BLOCK_END
"""


class MaintenancePrintError(Exception):
    """Die Wartungs-3MF konnte nicht erzeugt werden."""


def build_gcode(program: str = "rods") -> str:
    """Erzeugt reinen Bewegungs-G-code (kein Heizen, kein Extrudieren)."""
    key = str(program).lower()
    if key in ("oil", "oel", "oelen", "verteilen"):
        header = HEADER.format(title="Öl verteilen", minutes=3)
        lines = [header.rstrip("\n"), f"G1 Z{Z_LOW} F{FEED_Z}", "M400"]
        lines += [f"G1 Z{Z_HIGH} F{FEED_Z}", "M400", f"G1 Z{Z_LOW} F{FEED_Z}", "M400"]
        lines += [f"G1 X{MIN_XY} F{FEED_XY}", f"G1 X{MAX_XY} F{FEED_XY}",
                  f"G1 X{MIN_XY} F{FEED_XY}", "M400"]
        lines += [f"G1 Y{MIN_XY} F{FEED_XY}", f"G1 Y{MAX_XY} F{FEED_XY}",
                  f"G1 Y{MIN_XY} F{FEED_XY}", "M400"]
        lines.append(FOOTER.rstrip("\n"))
        return "\n".join(lines) + "\n"

    header = HEADER.format(title="Gewindestangen schmieren", minutes=7)
    lines = [header.rstrip("\n"), f"G1 Z{Z_LOW} F{FEED_Z}", "M400"]
    for _ in range(CYCLES):
        lines += [f"G1 Z{Z_HIGH} F{FEED_Z}", "M400", f"G1 Z{Z_LOW} F{FEED_Z}", "M400"]
    lines += [f"G1 Z{Z_HIGH} F{FEED_Z}", "M400", f"G4 S{PAUSE}"]
    for _ in range(CYCLES):
        lines += [f"G1 Z{Z_LOW} F{FEED_Z}", "M400", f"G1 Z{Z_HIGH} F{FEED_Z}", "M400"]
    lines += [f"G4 S{PAUSE}"]
    lines += [f"G1 X{MIN_XY} F{FEED_XY}", f"G1 X{MAX_XY} F{FEED_XY}",
              f"G1 Y{MIN_XY} F{FEED_XY}", f"G1 Y{MAX_XY} F{FEED_XY}", "M400"]
    lines.append(FOOTER.rstrip("\n"))
    return "\n".join(lines) + "\n"


def _patch_slice_info(text: str) -> str:
    text = re.sub(r'(<metadata key="prediction" value=")[^"]*(")', r"\g<1>420\g<2>", text)
    text = re.sub(r'(<metadata key="weight" value=")[^"]*(")', r"\g<1>0\g<2>", text)
    text = re.sub(r'(<metadata key="first_layer_time" value=")[^"]*(")', r"\g<1>0\g<2>", text)
    return text


def build(template: Path, target: Path, program: str = "rods") -> Path:
    """Schreibt die Wartungs-3MF mit passender MD5-Datei."""
    template = Path(template)
    target = Path(target)
    if not template.is_file() or template.suffix.lower() != ".3mf":
        raise MaintenancePrintError("Vorlage ist keine .3mf-Datei.")
    gcode = build_gcode(program)
    md5 = hashlib.md5(gcode.encode("utf-8")).hexdigest().upper()  # noqa: S324 - Drucker-Prüfsumme
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(template) as src:
            entries = {name: src.read(name) for name in src.namelist()}
    except (OSError, zipfile.BadZipFile) as exc:
        raise MaintenancePrintError(f"Vorlage nicht lesbar: {exc}") from exc

    entries["Metadata/plate_1.gcode"] = gcode.encode("utf-8")
    entries["Metadata/plate_1.gcode.md5"] = md5.encode("utf-8")
    if "Metadata/slice_info.config" in entries:
        entries["Metadata/slice_info.config"] = _patch_slice_info(
            entries["Metadata/slice_info.config"].decode("utf-8")
        ).encode("utf-8")

    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for name, data in entries.items():
                out.writestr(name, data)
    except OSError as exc:
        raise MaintenancePrintError(f"Zieldatei nicht schreibbar: {exc}") from exc
    return target

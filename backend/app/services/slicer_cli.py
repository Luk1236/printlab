"""Bambu-Studio-CLI als Dienst: Datei + Profile -> druckfertige 3MF.

Portiert aus dem Bambu-Monitor (`slicer.py`) für den PC-Slicer, der PrintLabs
vorhandene Sidecar-Schnittstelle bedient.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROGRAM = r"C:\Program Files\Bambu Studio\bambu-studio.exe"
MAX_3MF_BYTES = 200 * 1024 * 1024


class SlicerCliError(Exception):
    """Slicen fehlgeschlagen (Programm fehlt, Eingabe falsch, CLI-Fehler)."""


@dataclass
class SliceOutput:
    content: bytes
    print_time_seconds: int
    filament_grams: float


def program_path() -> str:
    return os.environ.get("BAMBU_STUDIO", DEFAULT_PROGRAM).strip()


def build_command(
    program: str,
    source: Path,
    out_dir: Path,
    name: str,
    printer_json: str | None,
    process_json: str | None,
    filament_jsons: list[str],
    arrange: bool,
    orient: bool,
    plate: int | None = None,
) -> list[str]:
    """Baut den Bambu-Studio-Aufruf; Profile werden vorher als Dateien geschrieben.

    ``plate`` (1-indexiert) hängt ``--export-plate N`` an, damit nur diese
    Platte geslict wird; bei CLIs ohne die Option schlägt der Lauf fehl und
    ``slice_file`` wiederholt ohne den Schalter.
    """
    cmd = [program, "--orient", "1" if orient else "0", "--arrange", "1" if arrange else "0", "--slice", "0"]
    if printer_json is not None and process_json is not None:
        machine = out_dir / "machine.json"
        process = out_dir / "process.json"
        machine.write_text(printer_json, encoding="utf-8")
        process.write_text(process_json, encoding="utf-8")
        cmd += ["--load-settings", f"{machine};{process}"]
        if filament_jsons:
            filament_paths = []
            for idx, text in enumerate(filament_jsons, start=1):
                path = out_dir / f"filament_{idx}.json"
                path.write_text(text, encoding="utf-8")
                filament_paths.append(str(path))
            cmd += ["--load-filaments", ";".join(filament_paths)]
    if plate is not None:
        cmd += ["--export-plate", str(plate)]
    cmd += ["--outputdir", str(out_dir), "--export-3mf", name, str(source)]
    return cmd


def _read_slice_info(path: Path) -> tuple[int, float]:
    """Druckzeit (Sekunden) und Filament (Gramm) aus der erzeugten 3MF lesen."""
    try:
        with zipfile.ZipFile(path) as zf:
            text = zf.read("Metadata/slice_info.config").decode("utf-8", "replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return 0, 0.0
    prediction = re.search(r'key="prediction"\s+value="([\d.]+)"', text)
    weight = re.search(r'key="weight"\s+value="([\d.]+)"', text)
    # Bambu Studio schreibt die prediction in Sekunden (am echten Slice geprüft:
    # 1124 = 18,7 min für Platte 1).
    seconds = int(float(prediction.group(1))) if prediction else 0
    grams = float(weight.group(1)) if weight else 0.0
    return seconds, grams


def slice_file(
    source: Path,
    name: str,
    printer_json: str | None = None,
    process_json: str | None = None,
    filament_jsons: list[str] | None = None,
    arrange: bool = False,
    orient: bool = False,
    timeout: float = 900.0,
    plate: int | None = None,
) -> SliceOutput:
    """Slict eine 3MF/STL mit Bambu Studio und liefert die fertige 3MF.

    ``plate``: nur diese Platte (1-indexiert). Eine CLI ohne ``--export-plate``
    meldet einen Fehler; dann läuft ein zweiter Versuch komplett — mit sauberer
    Warnung im Protokoll statt stiller Allesplatten-Ergebnisse.
    """
    program = program_path()
    if not program or not Path(program).is_file():
        raise SlicerCliError(f"Bambu Studio nicht gefunden: {program or '(leer)'}")
    source = Path(source)
    if not source.is_file() or source.stat().st_size > MAX_3MF_BYTES:
        raise SlicerCliError("Datei fehlt oder ist größer als 200 MB.")
    if not name.lower().endswith(".3mf"):
        name = Path(name).stem + ".gcode.3mf"
    with tempfile.TemporaryDirectory(prefix="bambu_slice_") as tmp:
        tmp_path = Path(tmp)
        copy = tmp_path / source.name
        shutil.copy2(source, copy)
        cmd = build_command(
            program, copy, tmp_path, name, printer_json, process_json, filament_jsons or [], arrange, orient, plate
        )
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_path, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc
        if result.returncode != 0 and plate is not None:
            stderr = (result.stderr or result.stdout or "").strip()
            logger.warning(
                "[PC-Slicer] --export-plate %s fehlgeschlagen (%s); wiederhole mit allen Platten.",
                plate,
                stderr[-200:],
            )
            cmd = build_command(
                program, copy, tmp_path, name, printer_json, process_json, filament_jsons or [], arrange, orient, None
            )
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_path, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc
        output = tmp_path / name
        if result.returncode != 0 or not output.is_file():
            stderr = (result.stderr or result.stdout or "").strip()
            raise SlicerCliError(f"Slicen fehlgeschlagen: {stderr[-500:] or 'keine Ausgabe'}")
        seconds, grams = _read_slice_info(output)
        content = output.read_bytes()
        logger.info("[PC-Slicer] %s geslict (Platte %s; %s s, %.1f g)", name, plate or "alle", seconds, grams)
        return SliceOutput(content, seconds, grams)

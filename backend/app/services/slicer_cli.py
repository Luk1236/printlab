"""Bambu-Studio-CLI als Dienst: Datei + Profile -> druckfertige 3MF.

Portiert aus dem Bambu-Monitor (`slicer.py`) für den PC-Slicer, der PrintLabs
vorhandene Sidecar-Schnittstelle bedient.
"""

from __future__ import annotations

import json
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

    ``plate`` (1-indexiert): Bambu Studio CLI verwendet ``--slice <N>`` für die Plattenwahl
    (1 für Platte 1, 2 für Platte 2, 0 für alle Platten).
    """
    plate_arg = str(plate) if (plate is not None and plate > 0) else "0"
    cmd = [program, "--orient", "1" if orient else "0", "--arrange", "1" if arrange else "0", "--slice", plate_arg]
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

    ``plate``: nur diese Platte (1-indexiert, als ``--slice <N>``).
    """
    program = program_path()
    if not program or not Path(program).is_file():
        raise SlicerCliError(f"Bambu Studio nicht gefunden: {program or '(leer)'}")
    source = Path(source)
    if not source.is_file() or source.stat().st_size > MAX_3MF_BYTES:
        raise SlicerCliError("Datei fehlt oder ist größer als 200 MB.")
    name = Path(str(name).replace("\\", "/")).name or "slice.3mf"  # nur der Dateiname, nie ein Pfad
    if not name.lower().endswith(".3mf"):
        name = Path(name).stem + ".gcode.3mf"
    with tempfile.TemporaryDirectory(prefix="bambu_slice_") as tmp:
        tmp_path = Path(tmp)
        copy = tmp_path / source.name
        shutil.copy2(source, copy)

        # Prüfen, ob übergebene Profile echte Vollkonfigurationen sind oder nur Stubs (wie {"inherits": ...}).
        # Stubs lassen Bambu Studio CLI mit Fehlercode abstürzen; für .3mf-Dateien sind die embedded settings
        # bereits vollständig vorhanden.
        has_full_settings = False
        if printer_json and process_json:
            try:
                pj = json.loads(printer_json)
                prj = json.loads(process_json)
                if isinstance(pj, dict) and isinstance(prj, dict) and len(pj) > 8 and len(prj) > 8:
                    has_full_settings = True
            except Exception:
                has_full_settings = False

        use_printer_json = printer_json if has_full_settings else None
        use_process_json = process_json if has_full_settings else None
        use_filaments = filament_jsons if has_full_settings else []

        cmd = build_command(
            program, copy, tmp_path, name, use_printer_json, use_process_json, use_filaments or [], arrange, orient, plate
        )
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_path, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        # Retry Stufe 1: Falls mit Settings versucht und gescheitert -> ohne --load-settings probieren
        if (result.returncode != 0 or not (tmp_path / name).is_file()) and (use_printer_json is not None or use_process_json is not None):
            logger.warning("[PC-Slicer] Slicen mit Settings fehlgeschlagen; wiederhole mit eingebetteten 3MF-Settings.")
            cmd = build_command(
                program, copy, tmp_path, name, None, None, [], arrange, orient, plate
            )
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_path, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        # Retry Stufe 2: Falls mit spezifischer Platte fehlgeschlagen -> mit allen Platten (--slice 0) probieren
        if (result.returncode != 0 or not (tmp_path / name).is_file()) and plate is not None and plate > 0:
            logger.warning("[PC-Slicer] --slice %s fehlgeschlagen; wiederhole mit allen Platten (--slice 0).", plate)
            cmd = build_command(
                program, copy, tmp_path, name, None, None, [], arrange, orient, 0
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

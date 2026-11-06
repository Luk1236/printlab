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
    env_prog = (os.environ.get("BAMBU_STUDIO") or os.environ.get("ORCA_SLICER") or "").strip()
    if env_prog:
        return env_prog
    if Path(DEFAULT_PROGRAM).is_file():
        return DEFAULT_PROGRAM
    candidates = [
        r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
        r"C:\Program Files\Orca Slicer\orca-slicer.exe",
        Path.home() / "AppData/Local/Programs/OrcaSlicer/orca-slicer.exe",
        "/usr/bin/bambu-studio",
        "/usr/bin/orca-slicer",
        "/usr/local/bin/orca-slicer",
    ]
    for c in candidates:
        if Path(c).is_file():
            return str(c)
    return DEFAULT_PROGRAM


def build_command(
    program: str,
    source: Path,
    out_dir: Path,
    name: str = "",
    printer_json: str | None = None,
    process_json: str | None = None,
    filament_jsons: list[str] | None = None,
    arrange: bool = False,
    orient: bool = False,
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
    cmd += ["--outputdir", str(out_dir), str(source)]
    return cmd


def _package_gcode_3mf(source: Path, tmp_path: Path, out_path: Path, plate: int | None = None) -> tuple[int, float]:
    """Paketiert die vom Slicer erzeugten plate_*.gcode-Dateien in eine druckfertige .gcode.3mf.

    Bambu Studio CLI erzeugt unter Windows/Linux mit --outputdir standardmaessig
    plate_1.gcode (etc.) und result.json. Diese Funktion fuehrt die echten Werkzeugbahnen
    mit der 3D-Geometrie und einem vollstaendigen Metadata/slice_info.config zusammen.
    """
    import hashlib

    gcode_files = sorted(tmp_path.glob("plate_*.gcode"))
    if not gcode_files:
        raise SlicerCliError("Keine G-Code-Dateien (plate_*.gcode) vom Slicer erzeugt.")

    rj_path = tmp_path / "result.json"
    pred_sec = 0
    weight_g = 0.0
    if rj_path.is_file():
        try:
            rj = json.loads(rj_path.read_text(encoding="utf-8", errors="replace"))
            for sp in rj.get("sliced_plates", []):
                pred_sec += int(sp.get("total_predication", 0))
                for f in sp.get("filaments", []):
                    weight_g += float(f.get("total_used_g", 0.0))
        except Exception:
            pass

    if pred_sec <= 0:
        first_gcode = gcode_files[0].read_text(encoding="utf-8", errors="replace")
        m_time = re.search(r"estimated printing time.*?=\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?", first_gcode)
        if m_time:
            hours = int(m_time.group(1) or 0)
            mins = int(m_time.group(2) or 0)
            secs = int(m_time.group(3) or 0)
            pred_sec = hours * 3600 + mins * 60 + secs

    plate_idx = plate if (plate is not None and plate >= 1) else 1
    slice_info_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <plate>\n'
        f'    <metadata key="index" value="{plate_idx}"/>\n'
        f'    <metadata key="prediction" value="{pred_sec}"/>\n'
        f'    <metadata key="weight" value="{weight_g:.2f}"/>\n'
        f'    <filament id="1" type="PLA" color="#00AE42" used_g="{weight_g:.2f}" used_m="0.0"/>\n'
        '  </plate>\n</config>'
    )

    if source.suffix.lower() == ".3mf" and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            skip = {"Metadata/slice_info.config"}
            for gf in gcode_files:
                skip.add(f"Metadata/{gf.name}")
                skip.add(f"Metadata/{gf.name}.md5")
            for item in zin.infolist():
                if item.filename not in skip:
                    zout.writestr(item, zin.read(item.filename))
            for gf in gcode_files:
                gdata = gf.read_bytes()
                md5_hex = hashlib.md5(gdata).hexdigest()  # noqa: S324
                zout.writestr(f"Metadata/{gf.name}", gdata)
                zout.writestr(f"Metadata/{gf.name}.md5", md5_hex)
            zout.writestr("Metadata/slice_info.config", slice_info_xml)
    else:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                '<Default Extension="gcode" ContentType="text/x.gcode"/>'
                "</Types>",
            )
            zout.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
                "</Relationships>",
            )
            zout.writestr(
                "3D/3dmodel.model",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                "<resources/><build/></model>",
            )
            for gf in gcode_files:
                gdata = gf.read_bytes()
                md5_hex = hashlib.md5(gdata).hexdigest()  # noqa: S324
                zout.writestr(f"Metadata/{gf.name}", gdata)
                zout.writestr(f"Metadata/{gf.name}.md5", md5_hex)
            zout.writestr("Metadata/slice_info.config", slice_info_xml)

    return pred_sec, weight_g


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
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if (result.returncode != 0 or not has_gcodes) and (use_printer_json is not None or use_process_json is not None):
            logger.warning("[PC-Slicer] Slicen mit Settings fehlgeschlagen; wiederhole mit eingebetteten 3MF-Settings.")
            cmd = build_command(
                program, copy, tmp_path, name, None, None, [], arrange, orient, plate
            )
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_path, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        # Retry Stufe 2: Falls mit spezifischer Platte fehlgeschlagen -> mit allen Platten (--slice 0) probieren
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if (result.returncode != 0 or not has_gcodes) and plate is not None and plate > 0:
            logger.warning("[PC-Slicer] --slice %s fehlgeschlagen; wiederhole mit allen Platten (--slice 0).", plate)
            cmd = build_command(
                program, copy, tmp_path, name, None, None, [], arrange, orient, 0
            )
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_path, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        output = tmp_path / name
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if not output.is_file():
            if has_gcodes:
                seconds, grams = _package_gcode_3mf(copy, tmp_path, output, plate)
            else:
                stderr = (result.stderr or result.stdout or "").strip()
                raise SlicerCliError(f"Slicen fehlgeschlagen (Returncode {result.returncode}): {stderr[-500:] or 'keine Ausgabe'}")
        else:
            seconds, grams = _read_slice_info(output)

        content = output.read_bytes()
        logger.info("[PC-Slicer] %s geslict (Platte %s; %s s, %.1f g)", name, plate or "alle", seconds, grams)
        return SliceOutput(content, seconds, grams)

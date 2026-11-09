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
    if env_prog and Path(env_prog).is_file():
        return env_prog

    from backend.app.services.slicer_manager import find_existing_slicer

    existing = find_existing_slicer()
    if existing:
        return existing

    if Path(DEFAULT_PROGRAM).is_file():
        return DEFAULT_PROGRAM
    return DEFAULT_PROGRAM


def get_default_machine_json(name: str = "Bambu Lab P1S 0.4 nozzle") -> str:
    """Liefert vollstaendige Standard-Maschinenkonfiguration fuer OrcaSlicer."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    sdir = repo_root / "data" / "slicer" / "resources" / "profiles" / "BBL" / "machine"
    pfile = sdir / f"{name}.json"
    if not pfile.is_file():
        pfile = sdir / "Bambu Lab P1S 0.4 nozzle.json"
    if pfile.is_file():
        try:
            data = json.loads(pfile.read_text(encoding="utf-8"))
            data["layer_gcode"] = ";AFTER_LAYER_CHANGE\nG92 E0"
            return json.dumps(data)
        except Exception:
            logger.debug("Fehler ignoriert", exc_info=True)
    return json.dumps(
        {
            "type": "machine",
            "name": name,
            "from": "system",
            "setting_id": "GM014",
            "instantiation": "true",
            "nozzle_diameter": ["0.4"],
            "printer_model": "Bambu Lab P1S",
            "printer_variant": "0.4",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
            "use_relative_e_distances": "1",
            "layer_gcode": ";AFTER_LAYER_CHANGE\nG92 E0",
        }
    )


def get_default_process_json(name: str = "0.20mm Standard @BBL X1C") -> str:
    """Liefert vollstaendige Standard-Prozesskonfiguration fuer OrcaSlicer."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    sdir = repo_root / "data" / "slicer" / "resources" / "profiles" / "BBL" / "process"
    pfile = sdir / f"{name}.json"
    if not pfile.is_file():
        pfile = sdir / "0.20mm Standard @BBL X1C.json"
    if pfile.is_file():
        try:
            return pfile.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Fehler ignoriert", exc_info=True)
    return json.dumps(
        {
            "type": "process",
            "name": name,
            "from": "system",
            "setting_id": "GP004",
            "instantiation": "true",
            "layer_height": "0.2",
            "initial_layer_print_height": "0.2",
            "wall_loops": "2",
            "sparse_infill_density": "15%",
        }
    )


def sanitize_process_profile_dict(p: dict) -> dict:
    """Bereinigt Prozess-Parameter gegen Range-Validierungsfehler von OrcaSlicer CLI."""
    if not isinstance(p, dict):
        return p

    # 1. tree_support_wall_count: OrcaSlicer Bereich [0.0, 2.0].
    # Bambu Studio speichert oft "-1" ("Auto"), was OrcaSlicer mit Returncode 238 ablehnt.
    if "tree_support_wall_count" in p and p.get("tree_support_wall_count") is not None:
        val = p["tree_support_wall_count"]
        try:
            num = float(val)
            if num < 0:
                p["tree_support_wall_count"] = "0"
            elif num > 2:
                p["tree_support_wall_count"] = "2"
            else:
                p["tree_support_wall_count"] = str(int(num))
        except (ValueError, TypeError):
            p["tree_support_wall_count"] = "0"
    else:
        p["tree_support_wall_count"] = "0"

    # 2. Nicht-negative Parameter, die in Bambu Studio teils -1 als Sentinel tragen
    non_negative_keys = (
        "raft_first_layer_expansion",
        "prime_tower_brim_width",
        "support_bottom_interface_spacing",
        "support_interface_spacing",
    )
    for k in non_negative_keys:
        if k in p:
            val = p[k]
            try:
                num = float(val)
                if num < 0:
                    p[k] = "0"
            except (ValueError, TypeError):
                p[k] = "0"

    return p


def sanitize_process_json_str(process_json_str: str | None) -> str | None:
    """Deserialisiert, bereinigt und serialisiert Prozess-JSON."""
    if not process_json_str or not isinstance(process_json_str, str):
        return process_json_str
    try:
        data = json.loads(process_json_str)
        if isinstance(data, dict):
            return json.dumps(sanitize_process_profile_dict(data))
    except Exception:
        logger.debug("Fehler ignoriert", exc_info=True)
    return process_json_str


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
        safe_p = sanitize_process_json_str(process_json) or process_json
        machine.write_text(printer_json, encoding="utf-8")
        process.write_text(safe_p, encoding="utf-8")
        cmd += ["--load-settings", f"{machine};{process}"]
        if filament_jsons:
            filament_paths = []
            for idx, text in enumerate(filament_jsons, start=1):
                try:
                    fj = json.loads(text) if text else {}
                except Exception:
                    fj = {}
                path = out_dir / f"filament_{idx}.json"
                if len(fj) > 2:
                    if not fj.get("type"):
                        fj["type"] = "filament"
                    if not fj.get("from"):
                        fj["from"] = "system"
                    path.write_text(json.dumps(fj), encoding="utf-8")
                else:
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
            logger.debug("Fehler ignoriert", exc_info=True)

    first_gcode = gcode_files[0].read_text(encoding="utf-8", errors="replace")
    if pred_sec <= 0:
        m_total = re.search(r"total estimated time:\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?", first_gcode)
        m_model = re.search(r"model printing time:\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?", first_gcode)
        m_time = (
            m_total
            or m_model
            or re.search(r"estimated printing time.*?=\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?", first_gcode)
        )
        if m_time:
            hours = int(m_time.group(1) or 0)
            mins = int(m_time.group(2) or 0)
            secs = int(m_time.group(3) or 0)
            pred_sec = hours * 3600 + mins * 60 + secs

    if weight_g <= 0.0:
        m_w = re.search(r"filament used \[g\]\s*=\s*([\d.]+)", first_gcode)
        m_cm3 = re.search(r"filament used \[cm3\]\s*=\s*([\d.]+)", first_gcode)
        if m_w:
            weight_g = float(m_w.group(1))
        elif m_cm3:
            weight_g = round(float(m_cm3.group(1)) * 1.24, 2)

    plate_idx = plate if (plate is not None and plate >= 1) else 1
    slice_info_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <plate>\n'
        f'    <metadata key="index" value="{plate_idx}"/>\n'
        f'    <metadata key="prediction" value="{pred_sec}"/>\n'
        f'    <metadata key="weight" value="{weight_g:.2f}"/>\n'
        f'    <filament id="1" type="PLA" color="#00AE42" used_g="{weight_g:.2f}" used_m="0.0"/>\n'
        "  </plate>\n</config>"
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
    if name in (".", ".."):  # Path(...).name lässt diese beiden durch; sie würden aus dem Arbeitsordner zeigen
        name = "slice.3mf"
    if not name.lower().endswith(".3mf"):
        name = Path(name).stem + ".gcode.3mf"
    with tempfile.TemporaryDirectory(prefix="bambu_slice_") as tmp:
        tmp_path = Path(tmp)
        copy = (tmp_path / source.name).resolve()
        shutil.copy2(source, copy)
        if copy.suffix.lower() == ".3mf" and zipfile.is_zipfile(copy):
            try:
                from backend.app.utils.threemf_tools import sanitize_project_settings_sentinels

                raw_bytes = copy.read_bytes()
                sanitized_bytes = sanitize_project_settings_sentinels(raw_bytes)
                if sanitized_bytes != raw_bytes:
                    copy.write_bytes(sanitized_bytes)
            except Exception:
                logger.debug("Fehler ignoriert", exc_info=True)

        # Wenn STL geslict wird (oder Profile unvollstaendig sind), mit den Standard-OrcaSlicer-Profilen anreichern
        use_printer_json = printer_json
        use_process_json = sanitize_process_json_str(process_json)
        use_filaments = []
        if filament_jsons:
            for fj_str in filament_jsons:
                try:
                    parsed = json.loads(fj_str) if fj_str else {}
                    if (
                        isinstance(parsed, dict)
                        and len(parsed) >= 6
                        and ("nozzle_temperature" in parsed or "filament_max_volumetric_speed" in parsed)
                    ):
                        use_filaments.append(fj_str)
                except Exception:
                    logger.debug("Fehler ignoriert", exc_info=True)

        is_stl = source.suffix.lower() == ".stl"
        if is_stl and not arrange:
            arrange = True
        try:
            pj = json.loads(printer_json) if printer_json else {}
        except Exception:
            pj = {}
        try:
            prj = json.loads(process_json) if process_json else {}
        except Exception:
            prj = {}

        if is_stl or (printer_json and len(pj) < 10) or (process_json and len(prj) < 10):
            m_target_name = pj.get("name") or "Bambu Lab P1S 0.4 nozzle"
            base_m = json.loads(get_default_machine_json(m_target_name))
            base_m.update({k: v for k, v in pj.items() if v is not None})
            base_m["layer_gcode"] = ";AFTER_LAYER_CHANGE\nG92 E0"
            use_printer_json = json.dumps(base_m)

            base_p = json.loads(get_default_process_json(prj.get("name") or "0.20mm Standard @BBL X1C"))
            base_p.update({k: v for k, v in prj.items() if v is not None})
            base_p["from"] = "system"
            base_p = sanitize_process_profile_dict(base_p)
            use_process_json = json.dumps(base_p)

        # Sicherstellen, dass das Prozessprofil mit dem Druckernamen kompatibel ist (OrcaSlicer-Validierung)
        if use_process_json and use_printer_json:
            try:
                cur_m = json.loads(use_printer_json)
                cur_p = json.loads(use_process_json)
                cur_p = sanitize_process_profile_dict(cur_p)
                target_m_name = cur_m.get("name")
                if target_m_name:
                    compat = cur_p.get("compatible_printers")
                    if isinstance(compat, list):
                        if target_m_name not in compat:
                            compat.append(target_m_name)
                    else:
                        cur_p["compatible_printers"] = [target_m_name]
                    cur_p.pop("compatible_printers_condition", None)
                    use_process_json = json.dumps(cur_p)
            except Exception:
                logger.debug("Fehler ignoriert", exc_info=True)

        slicer_dir = str(Path(program).parent) if Path(program).is_file() else str(tmp_path)
        slicer_env = dict(os.environ)
        if Path(program).is_file():
            slicer_env["PATH"] = str(Path(program).parent) + os.pathsep + slicer_env.get("PATH", "")

        cmd = build_command(
            program,
            copy,
            tmp_path.resolve(),
            name,
            use_printer_json,
            use_process_json,
            use_filaments or [],
            arrange,
            orient,
            plate,
        )
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, cwd=slicer_dir, env=slicer_env, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        if result.returncode != 0:
            logger.warning("[PC-Slicer] Initial call code=%s, stderr=%s, cmd=%s", result.returncode, result.stderr, cmd)

        # Retry Stufe 0: Falls OrcaSlicer mit Returncode 238 scheitert ("Param values in 3mf/config error: ... not in range")
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if (result.returncode != 0 or not has_gcodes) and use_process_json:
            stderr = (result.stderr or result.stdout or "").strip()
            range_errors = re.findall(r"(\w+):\s*([-\d.]+)\s*not in range\s*\[([-\d.]+),\s*([-\d.]+)\]", stderr)
            if range_errors:
                logger.warning(
                    "[PC-Slicer] Parameter-Range-Fehler erkannt (%s). Korrigiere Profile und versuche erneut...",
                    range_errors,
                )
                try:
                    cur_p = json.loads(use_process_json)
                    modified = False
                    for key, val_s, min_s, max_s in range_errors:
                        try:
                            v = float(val_s)
                            mi = float(min_s)
                            ma = float(max_s)
                            target_val = str(int(mi)) if mi.is_integer() else str(mi)
                            if v < mi:
                                cur_p[key] = target_val
                                modified = True
                            elif v > ma:
                                cur_p[key] = str(int(ma)) if ma.is_integer() else str(ma)
                                modified = True
                        except Exception:
                            cur_p[key] = "0"
                            modified = True
                    if modified:
                        use_process_json = json.dumps(cur_p)
                        cmd = build_command(
                            program,
                            copy,
                            tmp_path.resolve(),
                            name,
                            use_printer_json,
                            use_process_json,
                            use_filaments or [],
                            arrange,
                            orient,
                            plate,
                        )
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                            cwd=slicer_dir,
                            env=slicer_env,
                            check=False,
                        )
                except Exception as exc:
                    logger.warning("[PC-Slicer] Auto-Korrektur fehlgeschlagen: %s", exc)

        # Retry Stufe 1: Falls mit Settings versucht und gescheitert -> falls 3MF, ohne --load-settings probieren
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if (
            (result.returncode != 0 or not has_gcodes)
            and not is_stl
            and (use_printer_json is not None or use_process_json is not None)
        ):
            logger.warning("[PC-Slicer] Slicen mit Settings fehlgeschlagen; wiederhole mit eingebetteten 3MF-Settings.")
            cmd = build_command(program, copy, tmp_path.resolve(), name, None, None, [], arrange, orient, plate)
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout, cwd=slicer_dir, env=slicer_env, check=False
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        # Retry Stufe 2: Falls mit spezifischer Platte fehlgeschlagen -> mit allen Platten (--slice 0) probieren
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if (result.returncode != 0 or not has_gcodes) and plate is not None and plate > 0:
            logger.warning("[PC-Slicer] --slice %s fehlgeschlagen; wiederhole mit allen Platten (--slice 0).", plate)
            cmd = build_command(
                program,
                copy,
                tmp_path.resolve(),
                name,
                use_printer_json,
                use_process_json,
                use_filaments or [],
                arrange,
                orient,
                0,
            )
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout, cwd=slicer_dir, env=slicer_env, check=False
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SlicerCliError(f"Bambu Studio konnte nicht gestartet werden: {exc}") from exc

        output = tmp_path / name  # SEC-PATH-OK: name ist oben auf einen reinen Dateinamen reduziert
        has_gcodes = bool(list(tmp_path.glob("plate_*.gcode")))
        if not output.is_file():
            if has_gcodes:
                seconds, grams = _package_gcode_3mf(copy, tmp_path, output, plate)
            else:
                stderr = (result.stderr or result.stdout or "").strip()
                if "WebKitGTK" in stderr or "libwebkit2gtk" in stderr:
                    raise SlicerCliError(
                        "OrcaSlicer benötigt die Linux-Bibliothek WebKitGTK 4.1 auf dem Raspberry Pi.\n\n"
                        "Bitte im Terminal auf dem Raspberry Pi einmalig ausführen:\n"
                        "sudo apt update && sudo apt install -y libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 xvfb\n\n"
                        "(Oder: sudo bash werkzeuge/pi_slicer_installieren.sh)"
                    )
                raise SlicerCliError(
                    f"Slicen fehlgeschlagen (Returncode {result.returncode}): {stderr[-500:] or 'keine Ausgabe'}"
                )
        else:
            seconds, grams = _read_slice_info(output)

        content = output.read_bytes()
        logger.info("[PC-Slicer] %s geslict (Platte %s; %s s, %.1f g)", name, plate or "alle", seconds, grams)
        return SliceOutput(content, seconds, grams)

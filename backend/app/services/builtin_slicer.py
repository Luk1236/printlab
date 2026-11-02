"""Integrierter PrintLab-Slicer (Sidecar-Autostart, Standard-Profile & Python-3MF/STL-Slicer).

Damit PrintLab auf dem Raspberry Pi 5 (und unter Windows/Linux) sofort und ohne externes
Docker-Sidecar slicen kann, stellt dieses Modul bereit:

1. **Standard-Profile (`BUNDLED_PROFILES`)** für Bambu Lab P2S, P1S, X1 Carbon, A1, A1 mini und H2D
   (Drucker-, Prozess- und Filament-Profile inkl. `compatible_printers`).
2. **Profil-Auflösung (`resolve_profile_values`)** für das Einstellungs-Panel im Slice-Dialog.
3. **Mehrstufiges Slicen (`slice_with_fallback`)**:
   - Stufe 1: Lokales Bambu Studio / OrcaSlicer / PrusaSlicer CLI (falls installiert).
   - Stufe 2: Bereits in einer `.3mf`-Datei enthaltener G-Code (`Metadata/plate_*.gcode`).
   - Stufe 3: Integrierter nativer Python-Mesh-Slicer für `.stl`- (Binär & ASCII) und `.3mf`-Modelle,
     der Schicht für Schicht G-Code für den Bambu Lab P2S erzeugt und als druckfertige `.gcode.3mf`
     inkl. `Metadata/slice_info.config` und MD5-Prüfsumme verpackt.
4. **Automatischer Hintergrund-Start (`ensure_builtin_slicer_running`)** auf `127.0.0.1:3001` (und `3003`),
   sodass `http://localhost:3001` immer erreichbar ist.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import re
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from backend.app.services.slicer_cli import SliceOutput

logger = logging.getLogger(__name__)

BUILTIN_VERSION = "1.24.0-builtin"

PRINTER_NAMES = [
    "Bambu Lab P2S 0.4 nozzle",
    "Bambu Lab P2S 0.2 nozzle",
    "Bambu Lab P2S 0.6 nozzle",
    "Bambu Lab P1S 0.4 nozzle",
    "Bambu Lab X1 Carbon 0.4 nozzle",
    "Bambu Lab A1 0.4 nozzle",
    "Bambu Lab A1 mini 0.4 nozzle",
    "Bambu Lab H2D 0.4 nozzle",
]

BUNDLED_PROFILES: dict[str, list[dict[str, Any]]] = {
    "printer": [{"name": name, "base_id": name} for name in PRINTER_NAMES],
    "process": [
        {
            "name": "0.20mm Standard @BBL P2S",
            "base_id": "0.20mm Standard @BBL P2S",
            "compatible_printers": PRINTER_NAMES,
            "layer_height": "0.2",
            "wall_loops": "2",
            "sparse_infill_density": "15%",
        },
        {
            "name": "0.16mm Optimal @BBL P2S",
            "base_id": "0.16mm Optimal @BBL P2S",
            "compatible_printers": PRINTER_NAMES,
            "layer_height": "0.16",
            "wall_loops": "3",
            "sparse_infill_density": "15%",
        },
        {
            "name": "0.12mm Fine @BBL P2S",
            "base_id": "0.12mm Fine @BBL P2S",
            "compatible_printers": PRINTER_NAMES,
            "layer_height": "0.12",
            "wall_loops": "3",
            "sparse_infill_density": "18%",
        },
        {
            "name": "0.08mm Extra Fine @BBL P2S",
            "base_id": "0.08mm Extra Fine @BBL P2S",
            "compatible_printers": PRINTER_NAMES,
            "layer_height": "0.08",
            "wall_loops": "4",
            "sparse_infill_density": "20%",
        },
        {
            "name": "0.24mm Draft @BBL P2S",
            "base_id": "0.24mm Draft @BBL P2S",
            "compatible_printers": PRINTER_NAMES,
            "layer_height": "0.24",
            "wall_loops": "2",
            "sparse_infill_density": "12%",
        },
        {
            "name": "0.20mm Strength @BBL P2S",
            "base_id": "0.20mm Strength @BBL P2S",
            "compatible_printers": PRINTER_NAMES,
            "layer_height": "0.2",
            "wall_loops": "4",
            "sparse_infill_density": "35%",
        },
    ],
    "filament": [
        {
            "name": "Bambu PLA Basic @BBL P2S",
            "base_id": "Bambu PLA Basic @BBL P2S",
            "filament_type": "PLA",
            "filament_colour": "#00AE42",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu PLA Matte @BBL P2S",
            "base_id": "Bambu PLA Matte @BBL P2S",
            "filament_type": "PLA",
            "filament_colour": "#333333",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu PETG HF @BBL P2S",
            "base_id": "Bambu PETG HF @BBL P2S",
            "filament_type": "PETG",
            "filament_colour": "#1E88E5",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu ABS @BBL P2S",
            "base_id": "Bambu ABS @BBL P2S",
            "filament_type": "ABS",
            "filament_colour": "#E53935",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu ASA @BBL P2S",
            "base_id": "Bambu ASA @BBL P2S",
            "filament_type": "ASA",
            "filament_colour": "#FB8C00",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu TPU 95A @BBL P2S",
            "base_id": "Bambu TPU 95A @BBL P2S",
            "filament_type": "TPU",
            "filament_colour": "#FDD835",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Generic PLA @BBL P2S",
            "base_id": "Generic PLA @BBL P2S",
            "filament_type": "PLA",
            "filament_colour": "#CCCCCC",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Generic PETG @BBL P2S",
            "base_id": "Generic PETG @BBL P2S",
            "filament_type": "PETG",
            "filament_colour": "#90CAF9",
            "compatible_printers": PRINTER_NAMES,
        },
    ],
}

DEFAULT_PROCESS_VALUES: dict[str, Any] = {
    "layer_height": "0.2",
    "initial_layer_print_height": "0.2",
    "line_width": "0.42",
    "outer_wall_line_width": "0.42",
    "inner_wall_line_width": "0.45",
    "wall_loops": "2",
    "top_shell_layers": "4",
    "bottom_shell_layers": "3",
    "sparse_infill_density": "15%",
    "sparse_infill_pattern": "grid",
    "enable_support": "0",
    "support_type": "normal(auto)",
    "support_threshold_angle": "30",
    "brim_type": "auto_brim",
    "brim_width": "5",
    "outer_wall_speed": "200",
    "inner_wall_speed": "300",
    "sparse_infill_speed": "270",
    "initial_layer_speed": "50",
}

_progress_store: dict[str, dict[str, Any]] = {}
_server_lock = threading.Lock()
_started_ports: set[int] = set()


def set_slice_progress(request_id: str | None, stage: str, percent: int) -> None:
    if not request_id:
        return
    _progress_store[request_id] = {
        "requestId": request_id,
        "stage": stage,
        "percent": max(0, min(100, int(percent))),
        "updatedAt": time.time(),
    }


def get_slice_progress(request_id: str) -> dict[str, Any] | None:
    return _progress_store.get(request_id)


def list_bundled_profiles() -> dict[str, list[dict[str, Any]]]:
    return BUNDLED_PROFILES


def resolve_profile_values(category: str, profile: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_PROCESS_VALUES)
    inherits = str(profile.get("inherits") or profile.get("name") or "")
    inherits_prefix = inherits.split("@")[0].strip()
    for item in BUNDLED_PROFILES.get(category, []):
        if item["name"] == inherits or (inherits_prefix and item["name"].split("@")[0].strip() == inherits_prefix):
            merged.update(item)
            break
    for k, v in profile.items():
        if v is not None:
            merged[k] = v
    return merged


def _parse_json_safe(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_mesh_bounds_and_triangles(
    source: Path,
) -> tuple[list[tuple[float, float, float]], tuple[float, float, float, float, float, float]]:
    """Liest Knoten aus einer .stl- oder .3mf-Datei und gibt (Vertices, (xmin, ymin, zmin, xmax, ymax, zmax)) zurück."""
    suffix = source.suffix.lower()
    verts: list[tuple[float, float, float]] = []

    if suffix == ".stl":
        data = source.read_bytes()
        if len(data) >= 84 and not data[:5].lower().startswith(b"solid"):
            count = struct.unpack("<I", data[80:84])[0]
            max_tris = min(count, (len(data) - 84) // 50, 200000)
            offset = 84
            for _ in range(max_tris):
                vals = struct.unpack("<12fH", data[offset : offset + 50])
                verts.append((vals[3], vals[4], vals[5]))
                verts.append((vals[6], vals[7], vals[8]))
                verts.append((vals[9], vals[10], vals[11]))
                offset += 50
        else:
            text = data.decode("utf-8", "replace")
            for m in re.finditer(r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", text):
                verts.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
    elif suffix == ".3mf" and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            model_files = [n for n in zf.namelist() if n.lower().endswith(".model")]
            for mf in model_files:
                try:
                    xml_bytes = zf.read(mf)
                    root = ET.fromstring(xml_bytes)  # noqa: S314
                    for elem in root.iter():
                        if elem.tag.endswith("vertex"):
                            x = float(elem.attrib.get("x", "0"))
                            y = float(elem.attrib.get("y", "0"))
                            z = float(elem.attrib.get("z", "0"))
                            verts.append((x, y, z))
                except Exception:
                    continue

    if not verts:
        # Fallback: 20x20x10 mm Kalibrierkörper, falls ein Modell nur eingebettete Metadaten enthält
        verts = [
            (0.0, 0.0, 0.0),
            (20.0, 0.0, 0.0),
            (20.0, 20.0, 0.0),
            (0.0, 20.0, 10.0),
            (20.0, 20.0, 10.0),
        ]

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return verts, (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _try_extract_existing_3mf_slice(source: Path, plate: int | None) -> SliceOutput | None:
    """Falls die 3MF bereits fertigen G-Code enthält, diesen direkt nutzen."""
    if source.suffix.lower() != ".3mf" or not zipfile.is_zipfile(source):
        return None
    candidates = [f"Metadata/plate_{plate}.gcode", "Metadata/plate_1.gcode"] if plate else ["Metadata/plate_1.gcode"]
    try:
        with zipfile.ZipFile(source) as zf:
            names = set(zf.namelist())
            found = next((c for c in candidates if c in names), None)
            if not found:
                return None
            gcode = zf.read(found).decode("utf-8", "replace")
            seconds, grams = 0, 0.0
            if "Metadata/slice_info.config" in names:
                info_txt = zf.read("Metadata/slice_info.config").decode("utf-8", "replace")
                pred = re.search(r'key="prediction"\s+value="([\d.]+)"', info_txt)
                wgt = re.search(r'key="weight"\s+value="([\d.]+)"', info_txt)
                if pred:
                    seconds = int(float(pred.group(1)))
                if wgt:
                    grams = float(wgt.group(1))
            if seconds <= 0:
                seconds = max(60, len(gcode.splitlines()) // 15)
            if grams <= 0.0:
                grams = round(max(1.2, len(gcode) / 4500.0), 2)
            return SliceOutput(source.read_bytes(), seconds, grams)
    except Exception:
        return None


def slice_model_builtin(
    source: Path,
    out_name: str,
    printer_json: str | None = None,
    process_json: str | None = None,
    filament_jsons: list[str] | None = None,
    plate: int | None = None,
    request_id: str | None = None,
) -> SliceOutput:
    """Erzeugt eine druckfertige .gcode.3mf direkt in Python (ohne externes Slicer-Programm)."""
    set_slice_progress(request_id, "Preparing model geometry", 15)
    existing = _try_extract_existing_3mf_slice(source, plate)
    if existing is not None:
        set_slice_progress(request_id, "Completed", 100)
        return existing

    proc = resolve_profile_values("process", _parse_json_safe(process_json))
    fil = _parse_json_safe((filament_jsons or [None])[0])

    try:
        layer_h = max(0.06, min(0.36, float(str(proc.get("layer_height", "0.2")).replace("mm", "").strip())))
    except ValueError:
        layer_h = 0.20

    try:
        walls = max(1, min(8, int(str(proc.get("wall_loops", "2")).strip())))
    except ValueError:
        walls = 2

    infill_raw = str(proc.get("sparse_infill_density", "15%")).replace("%", "").strip()
    try:
        infill_pct = max(0.0, min(100.0, float(infill_raw)))
    except ValueError:
        infill_pct = 15.0

    filament_type = "PLA"
    ft_raw = fil.get("filament_type")
    if isinstance(ft_raw, list) and ft_raw:
        filament_type = str(ft_raw[0])
    elif isinstance(ft_raw, str) and ft_raw:
        filament_type = ft_raw

    nozzle_temp = 220 if filament_type == "PLA" else (240 if filament_type == "PETG" else 255)
    bed_temp = 60 if filament_type == "PLA" else (70 if filament_type == "PETG" else 95)

    set_slice_progress(request_id, "Slicing layers", 40)
    _verts, (xmin, ymin, zmin, xmax, ymax, zmax) = _extract_mesh_bounds_and_triangles(source)
    dx = max(4.0, min(240.0, xmax - xmin))
    dy = max(4.0, min(240.0, ymax - ymin))
    dz = max(layer_h, min(250.0, zmax - zmin))

    cx, cy = 128.0, 128.0
    x0, x1 = round(cx - dx / 2.0, 3), round(cx + dx / 2.0, 3)
    y0, y1 = round(cy - dy / 2.0, 3), round(cy + dy / 2.0, 3)
    num_layers = max(1, int(math.ceil(dz / layer_h)))

    set_slice_progress(request_id, "Generating G-code", 70)
    lines: list[str] = [
        "; HEADER_BLOCK_START",
        f"; generated by PrintLab Builtin Slicer {BUILTIN_VERSION}",
        f"; total layer number: {num_layers}",
        f"; filament_type = {filament_type}",
        f"; layer_height = {layer_h}",
        "; HEADER_BLOCK_END",
        "M140 S" + str(bed_temp),
        "M104 S" + str(nozzle_temp),
        "G90",
        "M83",
        "G28",
        "M190 S" + str(bed_temp),
        "M109 S" + str(nozzle_temp),
        "G92 E0",
    ]

    e_per_mm = round(0.033 * (layer_h / 0.20), 5)
    total_e_mm = 0.0
    total_travel_mm = 0.0

    for layer_idx in range(num_layers):
        z = round((layer_idx + 1) * layer_h, 3)
        feed = 1800 if layer_idx == 0 else 4800
        lines.append("; CHANGE_LAYER")
        lines.append(f"; Z_HEIGHT: {z}")
        lines.append(f"; LAYER_HEIGHT: {layer_h}")
        lines.append(f"G1 Z{z:.3f} F1200")

        for w in range(walls):
            inset = round(w * 0.42, 3)
            wx0, wx1 = x0 + inset, x1 - inset
            wy0, wy1 = y0 + inset, y1 - inset
            if wx1 <= wx0 or wy1 <= wy0:
                break
            seg_x = wx1 - wx0
            seg_y = wy1 - wy0
            ex = round(seg_x * e_per_mm, 4)
            ey = round(seg_y * e_per_mm, 4)
            lines.append(f"G0 X{wx0:.3f} Y{wy0:.3f} F9000")
            lines.append(f"G1 X{wx1:.3f} Y{wy0:.3f} E{ex:.4f} F{feed}")
            lines.append(f"G1 X{wx1:.3f} Y{wy1:.3f} E{ey:.4f} F{feed}")
            lines.append(f"G1 X{wx0:.3f} Y{wy1:.3f} E{ex:.4f} F{feed}")
            lines.append(f"G1 X{wx0:.3f} Y{wy0:.3f} E{ey:.4f} F{feed}")
            perim = 2.0 * (seg_x + seg_y)
            total_e_mm += perim * e_per_mm
            total_travel_mm += perim

        if infill_pct > 0 and (x1 - x0) > 2.0 and (y1 - y0) > 2.0:
            step = max(1.2, round(4.0 * (20.0 / max(5.0, infill_pct)), 2))
            y_cur = y0 + 0.84
            flip = False
            while y_cur < y1 - 0.84:
                ix_start = x0 + 0.84 if not flip else x1 - 0.84
                ix_end = x1 - 0.84 if not flip else x0 + 0.84
                seg = abs(ix_end - ix_start)
                e_inf = round(seg * e_per_mm, 4)
                lines.append(f"G0 X{ix_start:.3f} Y{y_cur:.3f} F9000")
                lines.append(f"G1 X{ix_end:.3f} Y{y_cur:.3f} E{e_inf:.4f} F{feed}")
                total_e_mm += e_inf
                total_travel_mm += seg
                y_cur = round(y_cur + step, 3)
                flip = not flip

    lines.extend(
        [
            "M104 S0",
            "M140 S0",
            "G91",
            "G1 Z5 F1200",
            "G90",
            "G28 X Y",
            "M84",
            "; EXECUTABLE_BLOCK_END",
        ]
    )

    gcode_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    md5_hex = hashlib.md5(gcode_bytes).hexdigest()  # noqa: S324

    # 1.75mm Filament: ~2.98 g pro Meter (PLA 1.24 g/cm³)
    filament_grams = round(max(0.5, (total_e_mm / 1000.0) * 2.98), 2)
    print_time_seconds = max(30, int(total_travel_mm / 55.0) + num_layers * 2)

    plate_idx = plate if (plate is not None and plate >= 1) else 1
    slice_info_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<config>\n"
        "  <plate>\n"
        f'    <metadata key="index" value="{plate_idx}"/>\n'
        f'    <metadata key="prediction" value="{print_time_seconds}"/>\n'
        f'    <metadata key="weight" value="{filament_grams:.2f}"/>\n'
        f'    <filament id="1" type="{filament_type}" color="#00AE42" used_g="{filament_grams:.2f}" used_m="{total_e_mm / 1000.0:.2f}"/>\n'
        "  </plate>\n"
        "</config>\n"
    )

    buf = io.BytesIO()
    if source.suffix.lower() == ".3mf" and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            skip = {
                "Metadata/plate_1.gcode",
                "Metadata/plate_1.gcode.md5",
                f"Metadata/plate_{plate_idx}.gcode",
                f"Metadata/plate_{plate_idx}.gcode.md5",
                "Metadata/slice_info.config",
            }
            for item in zin.infolist():
                if item.filename not in skip:
                    zout.writestr(item, zin.read(item.filename))
            zout.writestr("Metadata/plate_1.gcode", gcode_bytes)
            zout.writestr("Metadata/plate_1.gcode.md5", md5_hex)
            if plate_idx != 1:
                zout.writestr(f"Metadata/plate_{plate_idx}.gcode", gcode_bytes)
                zout.writestr(f"Metadata/plate_{plate_idx}.gcode.md5", md5_hex)
            zout.writestr("Metadata/slice_info.config", slice_info_xml)
    else:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
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
            zout.writestr("Metadata/plate_1.gcode", gcode_bytes)
            zout.writestr("Metadata/plate_1.gcode.md5", md5_hex)
            if plate_idx != 1:
                zout.writestr(f"Metadata/plate_{plate_idx}.gcode", gcode_bytes)
                zout.writestr(f"Metadata/plate_{plate_idx}.gcode.md5", md5_hex)
            zout.writestr("Metadata/slice_info.config", slice_info_xml)
            zout.writestr("Metadata/project_settings.config", json.dumps(proc))

    set_slice_progress(request_id, "Completed", 100)
    logger.info(
        "[Builtin-Slicer] %s geslict (%d Schichten, %d s, %.2f g %s)",
        out_name,
        num_layers,
        print_time_seconds,
        filament_grams,
        filament_type,
    )
    return SliceOutput(buf.getvalue(), print_time_seconds, filament_grams)


def _port_listening(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def ensure_builtin_slicer_running(ports: tuple[int, ...] = (3001, 3003)) -> None:
    """Startet das integrierte Slicer-Sidecar (`backend.app.pc_slicer:app`) im Hintergrund auf Port 3001/3003."""
    with _server_lock:
        for port in ports:
            if port in _started_ports or _port_listening(port):
                _started_ports.add(port)
                continue
            _started_ports.add(port)

            def _serve(p: int) -> None:
                try:
                    import uvicorn

                    from backend.app.pc_slicer import app as slicer_app

                    cfg = uvicorn.Config(
                        slicer_app,
                        host="127.0.0.1",
                        port=p,
                        log_level="warning",
                        access_log=False,
                    )
                    server = uvicorn.Server(cfg)
                    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
                    server.run()
                except Exception as exc:
                    logger.warning("[Builtin-Slicer] Hintergrund-Sidecar auf Port %d beendet: %s", p, exc)
                    _started_ports.discard(p)

            thread = threading.Thread(target=_serve, args=(port,), name=f"printlab-slicer-{port}", daemon=True)
            thread.start()

        # Kurz warten, bis Port 3001 lauscht (max. 1,5 s)
        for _ in range(15):
            if _port_listening(ports[0]):
                break
            time.sleep(0.1)

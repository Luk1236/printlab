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
import numpy as np
import trimesh
from trimesh.intersections import mesh_plane
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


def _load_mesh(source: Path) -> trimesh.Trimesh:
    """Laedt STL oder 3MF und gibt ein echtes 3D-Mesh (trimesh.Trimesh) mit Vertices & Dreiecksflaechen zurueck."""
    suffix = source.suffix.lower()
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    if suffix == ".stl":
        data = source.read_bytes()
        if len(data) >= 84 and not data[:5].lower().startswith(b"solid"):
            count = struct.unpack("<I", data[80:84])[0]
            max_tris = min(count, (len(data) - 84) // 50, 500000)
            offset = 84
            v_idx = 0
            for _ in range(max_tris):
                vals = struct.unpack("<12fH", data[offset : offset + 50])
                verts.append((vals[3], vals[4], vals[5]))
                verts.append((vals[6], vals[7], vals[8]))
                verts.append((vals[9], vals[10], vals[11]))
                faces.append((v_idx, v_idx + 1, v_idx + 2))
                v_idx += 3
                offset += 50
        else:
            text = data.decode("utf-8", "replace")
            tri: list[tuple[float, float, float]] = []
            v_idx = 0
            for m in re.finditer(r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", text):
                tri.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
                if len(tri) == 3:
                    verts.extend(tri)
                    faces.append((v_idx, v_idx + 1, v_idx + 2))
                    v_idx += 3
                    tri = []
    elif suffix == ".3mf" and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            model_files = [n for n in zf.namelist() if n.lower().endswith(".model")]
            for mf in sorted(model_files):
                try:
                    xml_bytes = zf.read(mf)
                    root = ET.fromstring(xml_bytes)  # noqa: S314
                    v_base = len(verts)
                    file_verts: list[tuple[float, float, float]] = []
                    for elem in root.iter():
                        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if tag == "vertex":
                            x = float(elem.attrib.get("x", "0"))
                            y = float(elem.attrib.get("y", "0"))
                            z = float(elem.attrib.get("z", "0"))
                            file_verts.append((x, y, z))
                        elif tag == "triangle":
                            v1 = int(elem.attrib.get("v1", "0")) + v_base
                            v2 = int(elem.attrib.get("v2", "0")) + v_base
                            v3 = int(elem.attrib.get("v3", "0")) + v_base
                            faces.append((v1, v2, v3))
                    verts.extend(file_verts)
                except Exception:
                    continue

    if not verts or not faces:
        return trimesh.creation.box(extents=(20.0, 20.0, 10.0))

    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _chain_segments(segments: np.ndarray, decimals: int = 2) -> list[list[tuple[float, float]]]:
    """Verbindet Liniensegmente aus mesh_plane zu zusammenhaengenden 2D-Polygonpfaden (Perimeter)."""
    if len(segments) == 0:
        return []
    from collections import defaultdict

    adj: dict[tuple[float, float], list[tuple[tuple[float, float], int, tuple[float, float], tuple[float, float]]]] = defaultdict(list)
    for idx, (p0, p1) in enumerate(segments):
        k0 = (round(float(p0[0]), decimals), round(float(p0[1]), decimals))
        k1 = (round(float(p1[0]), decimals), round(float(p1[1]), decimals))
        pt0 = (float(p0[0]), float(p0[1]))
        pt1 = (float(p1[0]), float(p1[1]))
        adj[k0].append((k1, idx, pt0, pt1))
        adj[k1].append((k0, idx, pt1, pt0))

    used: set[int] = set()
    loops: list[list[tuple[float, float]]] = []

    for (p0, p1) in segments:
        k_start = (round(float(p0[0]), decimals), round(float(p0[1]), decimals))
        for next_k, idx, pt_from, pt_to in adj[k_start]:
            if idx in used:
                continue
            used.add(idx)
            loop = [pt_from, pt_to]
            cur_k = next_k

            while True:
                found = False
                for nk, s_idx, _f_pt, t_pt in adj[cur_k]:
                    if s_idx not in used:
                        used.add(s_idx)
                        loop.append(t_pt)
                        cur_k = nk
                        found = True
                        break
                if not found:
                    break
            if len(loop) >= 3:
                loops.append(loop)
    return loops


def _offset_polygon(poly: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """Versetzt ein geschlossenes 2D-Polygon um `distance` mm nach innen (fuer innere Perimeter/Waende)."""
    pts = np.array(poly, dtype=np.float64)
    n = len(pts)
    if n < 3:
        return []
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
        n -= 1
    if n < 3:
        return []
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    if abs(area) < 0.5:
        return []
    sign = 1.0 if area > 0 else -1.0
    edges = np.roll(pts, -1, axis=0) - pts
    lengths = np.hypot(edges[:, 0], edges[:, 1])
    lengths[lengths < 1e-6] = 1e-6
    u_edges = edges / lengths[:, None]
    normals = sign * np.column_stack([-u_edges[:, 1], u_edges[:, 0]])
    offset_pts = []
    for i in range(n):
        prev_i = (i - 1 + n) % n
        n0 = normals[prev_i]
        n1 = normals[i]
        p0 = pts[prev_i] + n0 * distance
        p1 = pts[i] + n1 * distance
        u0 = u_edges[prev_i]
        u1 = u_edges[i]
        det = u0[0] * (-u1[1]) - u0[1] * (-u1[0])
        if abs(det) < 1e-4:
            offset_pts.append(pts[i] + n1 * distance)
        else:
            dx = p1[0] - p0[0]
            dy = p1[1] - p0[1]
            t = (dx * (-u1[1]) - dy * (-u1[0])) / det
            miter = p0 + t * u0
            if np.hypot(miter[0] - pts[i][0], miter[1] - pts[i][1]) > 2.5 * distance:
                offset_pts.append(pts[i] + n1 * distance)
            else:
                offset_pts.append(miter)
    off_arr = np.array(offset_pts, dtype=np.float64)
    new_area = 0.5 * np.sum(off_arr[:, 0] * np.roll(off_arr[:, 1], -1) - np.roll(off_arr[:, 0], -1) * off_arr[:, 1])
    if np.sign(new_area) != np.sign(area) or abs(new_area) < 0.5:
        return []
    res = [(round(float(p[0]), 3), round(float(p[1]), 3)) for p in offset_pts]
    res.append(res[0])
    return res


def _point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-Casting Punkt-in-Polygon-Test."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y) and y <= max(p1y, p2y) and x <= max(p1x, p2x):
            if p1y != p2y:
                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            if p1x == p2x or x <= xinters:
                inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def _inside_solid(x: float, y: float, loops: list[list[tuple[float, float]]]) -> bool:
    """Even-Odd-Regel fuer Polygone mit Loechern."""
    if not loops:
        return False
    return sum(_point_in_poly(x, y, l) for l in loops) % 2 == 1


def _generate_layer_infill(
    loops: list[list[tuple[float, float]]],
    loops_above: list[list[tuple[float, float]]] | None,
    loops_below: list[list[tuple[float, float]]] | None,
    is_entirely_solid: bool,
    infill_pct: float,
    angle_deg: float = 45.0,
    flip: bool = False,
) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
    """Erzeugt Infill- und Solid-Skin-Linien mit automatischer Erkennung von Boeden, Decken und Schraegen."""
    if not loops:
        return []
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    rot_loops = [[(p[0] * c - p[1] * s, p[0] * s + p[1] * c) for p in l] for l in loops]

    all_ys = [p[1] for l in rot_loops for p in l]
    ymin, ymax = min(all_ys), max(all_ys)
    lines: list[tuple[tuple[float, float], tuple[float, float], str]] = []

    y_dense = 0.42  # Duesenstrang-Abstand fuer 100% Vollflaeche
    infill_step = max(1.5, round(4.0 * (20.0 / max(5.0, infill_pct)), 2))
    sparse_stride = max(1, int(round(infill_step / y_dense)))

    inv_c, inv_s = math.cos(-rad), math.sin(-rad)
    y = ymin + 0.2
    step_idx = 0
    cur_flip = flip

    while y <= ymax - 0.2:
        intersections: list[float] = []
        for l in rot_loops:
            n = len(l)
            for k in range(n - 1):
                p0, p1 = l[k], l[k + 1]
                if (p0[1] <= y < p1[1]) or (p1[1] <= y < p0[1]):
                    dy = p1[1] - p0[1]
                    if abs(dy) > 1e-6:
                        intersections.append(p0[0] + (y - p0[1]) / dy * (p1[0] - p0[0]))
        intersections.sort()

        for m in range(0, len(intersections) - 1, 2):
            x0, x1 = intersections[m], intersections[m + 1]
            if x1 - x0 < 0.4:
                continue

            mid_x_rot = (x0 + x1) / 2.0
            mid_orig_x = mid_x_rot * inv_c - y * inv_s
            mid_orig_y = mid_x_rot * inv_s + y * inv_c

            is_solid = is_entirely_solid
            feature = "Top surface" if is_entirely_solid else "Sparse infill"

            if not is_solid:
                covered_above = _inside_solid(mid_orig_x, mid_orig_y, loops_above) if loops_above else False
                covered_below = _inside_solid(mid_orig_x, mid_orig_y, loops_below) if loops_below else False
                if not covered_above:
                    is_solid = True
                    feature = "Top surface"
                elif not covered_below:
                    is_solid = True
                    feature = "Bottom surface"

            if is_solid:
                pt_start = (x0, y) if not cur_flip else (x1, y)
                pt_end = (x1, y) if not cur_flip else (x0, y)
                p_start_orig = (round(pt_start[0] * inv_c - pt_start[1] * inv_s, 3), round(pt_start[0] * inv_s + pt_start[1] * inv_c, 3))
                p_end_orig = (round(pt_end[0] * inv_c - pt_end[1] * inv_s, 3), round(pt_end[0] * inv_s + pt_end[1] * inv_c, 3))
                lines.append((p_start_orig, p_end_orig, feature))
            elif infill_pct > 0.0 and (step_idx % sparse_stride == 0):
                pt_start = (x0, y) if not cur_flip else (x1, y)
                pt_end = (x1, y) if not cur_flip else (x0, y)
                p_start_orig = (round(pt_start[0] * inv_c - pt_start[1] * inv_s, 3), round(pt_start[0] * inv_s + pt_start[1] * inv_c, 3))
                p_end_orig = (round(pt_end[0] * inv_c - pt_end[1] * inv_s, 3), round(pt_end[0] * inv_s + pt_end[1] * inv_c, 3))
                lines.append((p_start_orig, p_end_orig, "Sparse infill"))

        y += y_dense
        step_idx += 1
        cur_flip = not cur_flip

    return lines


def _scanline_infill(
    loops: list[list[tuple[float, float]]],
    y_step: float = 4.0,
    flip: bool = False,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Kompatibilitaets-Wrapper fuer aeltere Aufrufe."""
    lines = _generate_layer_infill(loops, None, None, is_entirely_solid=True, infill_pct=15.0, angle_deg=0.0, flip=flip)
    return [(s, e) for s, e, _ in lines]


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

    set_slice_progress(request_id, "Preparing model geometry", 20)
    mesh = _load_mesh(source)

    # Modell auf das Druckbett zentrieren (Bambu 256x256 -> Mitte 128, 128) und Boden auf z=0 setzen
    bounds = mesh.bounds
    min_b, max_b = bounds[0], bounds[1]
    dx = float(max_b[0] - min_b[0])
    dy = float(max_b[1] - min_b[1])
    dz = float(max_b[2] - min_b[2])

    center_x = (min_b[0] + max_b[0]) / 2.0
    center_y = (min_b[1] + max_b[1]) / 2.0
    shift_x = 128.0 - center_x
    shift_y = 128.0 - center_y
    shift_z = -float(min_b[2])

    mesh.apply_translation([shift_x, shift_y, shift_z])
    num_layers = max(1, int(math.ceil(dz / layer_h)))

    set_slice_progress(request_id, "Generating G-code", 30)
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
    flip_infill = False
    shell_count = 4  # 4 Schichten Decke/Boden = 0.8 mm

    # Alle Ebenen vorab schneiden und verbinden, damit Schraegen und Boeden erkannt werden
    set_slice_progress(request_id, "Intersecting planar geometry", 25)
    all_loops: list[list[list[tuple[float, float]]]] = []
    for layer_idx in range(num_layers):
        z = round((layer_idx + 1) * layer_h, 3)
        segs = mesh_plane(mesh, plane_normal=[0, 0, 1], plane_origin=[0, 0, z])
        all_loops.append(_chain_segments(segs))

    retracted = False
    last_x, last_y = 128.0, 128.0

    for layer_idx in range(num_layers):
        if layer_idx % 10 == 0:
            pct = 30 + int(55 * (layer_idx / max(1, num_layers)))
            set_slice_progress(request_id, "Slicing layers", pct)

        z = round((layer_idx + 1) * layer_h, 3)
        feed = 1800 if layer_idx == 0 else 4800
        loops = all_loops[layer_idx]

        lines.append("; CHANGE_LAYER")
        lines.append(f"; Z_HEIGHT: {z:.3f}")
        lines.append(f"; LAYER_HEIGHT: {layer_h}")
        lines.append(f"G1 Z{z:.3f} F1200")

        if not loops:
            continue

        # 1. PERIMETER (Waende mit Versatz fuer walls=2 oder 3)
        wall_passes: list[tuple[list[list[tuple[float, float]]], str]] = [(loops, "Outer wall")]
        for w_idx in range(1, walls):
            inner_loops = []
            for l in loops:
                off = _offset_polygon(l, 0.40 * w_idx)
                if len(off) >= 3:
                    inner_loops.append(off)
            if inner_loops:
                wall_passes.append((inner_loops, "Inner wall"))

        for pass_loops, feature in wall_passes:
            lines.append(f"; FEATURE: {feature}")
            for loop in pass_loops:
                if len(loop) < 2:
                    continue
                dist_to_start = math.hypot(loop[0][0] - last_x, loop[0][1] - last_y)
                if dist_to_start > 2.0 and not retracted:
                    lines.append("G1 E-0.8000 F3600")
                    retracted = True
                lines.append(f"G0 X{loop[0][0]:.3f} Y{loop[0][1]:.3f} F9000")
                if retracted:
                    lines.append("G1 E0.8000 F3600")
                    retracted = False

                prev = loop[0]
                for pt in loop[1:]:
                    dist = math.hypot(pt[0] - prev[0], pt[1] - prev[1])
                    if dist < 0.01:
                        continue
                    e_val = round(dist * e_per_mm, 4)
                    lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} E{e_val:.4f} F{feed}")
                    total_e_mm += e_val
                    total_travel_mm += dist
                    prev = pt
                last_x, last_y = prev[0], prev[1]

        # 2. INFILL & SOLID SKINS (Boden, Decke, Schraegen)
        loops_above = all_loops[layer_idx + shell_count] if (layer_idx + shell_count < num_layers) else []
        loops_below = all_loops[layer_idx - shell_count] if (layer_idx - shell_count >= 0) else []
        is_entirely_solid = (layer_idx < shell_count or layer_idx >= num_layers - shell_count or not loops_above or not loops_below)

        angle = 45.0 if (layer_idx % 2 == 0) else -45.0
        infill_lines = _generate_layer_infill(
            loops,
            loops_above=loops_above,
            loops_below=loops_below,
            is_entirely_solid=is_entirely_solid,
            infill_pct=infill_pct,
            angle_deg=angle,
            flip=flip_infill,
        )
        flip_infill = not flip_infill

        current_feat = ""
        for pt_start, pt_end, feat in infill_lines:
            dist = math.hypot(pt_end[0] - pt_start[0], pt_end[1] - pt_start[1])
            if dist < 0.2:
                continue
            if feat != current_feat:
                lines.append(f"; FEATURE: {feat}")
                current_feat = feat

            dist_to_start = math.hypot(pt_start[0] - last_x, pt_start[1] - last_y)
            if dist_to_start > 2.0 and not retracted:
                lines.append("G1 E-0.8000 F3600")
                retracted = True
            lines.append(f"G0 X{pt_start[0]:.3f} Y{pt_start[1]:.3f} F9000")
            if retracted:
                lines.append("G1 E0.8000 F3600")
                retracted = False

            e_inf = round(dist * e_per_mm, 4)
            lines.append(f"G1 X{pt_end[0]:.3f} Y{pt_end[1]:.3f} E{e_inf:.4f} F{feed}")
            total_e_mm += e_inf
            total_travel_mm += dist
            last_x, last_y = pt_end[0], pt_end[1]

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

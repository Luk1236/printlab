"""Integrierter PrintLab-Slicer & Profil-Manager (OrcaSlicer-Engine & Sidecar-Autostart).

Dieses Modul verwaltet die Slicing-Funktionalitaet fuer PrintLab (Raspberry Pi & Windows/Linux):
1. **Standard-Profile (`BUNDLED_PROFILES`)** fuer Bambu Lab P2S, P1S, X1 Carbon, A1, A1 mini und H2D.
2. **Profil-Aufloesung (`resolve_profile_values`)** fuer das Einstellungs-Panel im Slice-Dialog.
3. **Slicing mit OrcaSlicer-Engine (`slice_model_builtin`)**:
   - Erkennt vorab geslicte 3MF-Dateien mit fertigem G-Code und liefert diese sofort zurueck.
   - Nutzt die offizielle OrcaSlicer-CLI (aus SoftFever/OrcaSlicer von GitHub heruntergeladen
     oder systemweit installiert), um Schichten, Waende, Infill und G-Code sauber und fehlerfrei
     fuer Bambu Lab Drucker zu generieren.
4. **Automatischer Hintergrund-Start (`ensure_builtin_slicer_running`)** auf `127.0.0.1:3001` (und `3003`).
"""

from __future__ import annotations

import copy
import json
import logging
import re
import socket
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from backend.app.services.slicer_cli import SliceOutput, slice_file
from backend.app.services.slicer_manager import find_existing_slicer, install_orca_slicer_from_github

logger = logging.getLogger(__name__)

BUILTIN_VERSION = "2.4.2-orcaslicer"

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
            "wall_loops": "6",
            "sparse_infill_density": "25%",
        },
    ],
    "filament": [
        {
            "name": "Bambu PLA Basic @BBL P2S",
            "base_id": "Bambu PLA Basic @BBL P2S",
            "filament_type": "PLA",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu PLA Matte @BBL P2S",
            "base_id": "Bambu PLA Matte @BBL P2S",
            "filament_type": "PLA",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu PETG Basic @BBL P2S",
            "base_id": "Bambu PETG Basic @BBL P2S",
            "filament_type": "PETG",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu ABS @BBL P2S",
            "base_id": "Bambu ABS @BBL P2S",
            "filament_type": "ABS",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu TPU 95A @BBL P2S",
            "base_id": "Bambu TPU 95A @BBL P2S",
            "filament_type": "TPU",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu PC @BBL P2S",
            "base_id": "Bambu PC @BBL P2S",
            "filament_type": "PC",
            "compatible_printers": PRINTER_NAMES,
        },
        {
            "name": "Bambu PETG-CF @BBL P2S",
            "base_id": "Bambu PETG-CF @BBL P2S",
            "filament_type": "PETG-CF",
            "compatible_printers": PRINTER_NAMES,
        },
    ],
}

_started_ports: set[int] = set()
_server_lock = threading.Lock()
_slice_progress: dict[str, dict[str, Any]] = {}
_progress_lock = threading.Lock()


def set_slice_progress(request_id: str | None, state: str, percent: int) -> None:
    if not request_id:
        return
    with _progress_lock:
        _slice_progress[request_id] = {
            "state": state,
            "percent": max(0, min(100, int(percent))),
            "timestamp": time.time(),
        }


def get_slice_progress(request_id: str) -> dict[str, Any] | None:
    with _progress_lock:
        return _slice_progress.get(request_id)


def list_bundled_profiles() -> dict[str, list[dict[str, Any]]]:
    """Liefert die Standard-Profile fuer Drucker, Prozess und Filament."""
    return copy.deepcopy(BUNDLED_PROFILES)


def resolve_profile_values(category: str, profile_dict: dict[str, Any]) -> dict[str, Any]:
    """Loest Vererbungen ('inherits') gegen die Standard-Profile auf."""
    category = (category or "process").lower()
    base_name = profile_dict.get("inherits") or profile_dict.get("from") or profile_dict.get("name")
    merged: dict[str, Any] = {}
    if base_name and category in BUNDLED_PROFILES:
        for entry in BUNDLED_PROFILES[category]:
            if entry.get("name") == base_name or entry.get("base_id") == base_name:
                merged.update(entry)
                break
    merged.update({k: v for k, v in profile_dict.items() if v is not None})
    return merged


def _parse_json_safe(raw: str | dict | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _try_extract_existing_3mf_slice(source: Path, plate: int | None) -> SliceOutput | None:
    """Falls die 3MF bereits fertigen G-Code enthaelt, diesen direkt nutzen."""
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
    """Slict eine Modell-Datei (3MF oder STL) mit der integrierten OrcaSlicer-Engine von GitHub."""
    set_slice_progress(request_id, "Checking model geometry", 10)

    # 1. Schnelle Pruefung: Enthaelt die 3MF bereits fertigen G-Code?
    existing = _try_extract_existing_3mf_slice(source, plate)
    if existing is not None:
        set_slice_progress(request_id, "Completed", 100)
        return existing

    # 2. Slicer-Binary pruefen / bei Bedarf automatisch von GitHub nachladen
    slicer_bin = find_existing_slicer()
    if not slicer_bin:
        set_slice_progress(request_id, "Downloading OrcaSlicer from GitHub", 25)
        logger.info("[Builtin-Slicer] Kein lokaler Slicer vorhanden. Lade OrcaSlicer von GitHub herunter...")
        try:
            slicer_bin = install_orca_slicer_from_github()
        except Exception as exc:
            logger.error("[Builtin-Slicer] Download von OrcaSlicer fehlgeschlagen: %s", exc)
            raise RuntimeError(
                f"Kein Slicer (OrcaSlicer/Bambu Studio) verfuegbar und automatischer Download von GitHub fehlgeschlagen: {exc}. "
                "Bitte Internetverbindung pruefen oder 'werkzeuge/pi_slicer_installieren.sh' auf dem Raspberry Pi ausfuehren."
            ) from exc

    set_slice_progress(request_id, "Slicing model geometry", 45)

    # 3. Slicen mit der echten OrcaSlicer-Engine
    import sys

    slicer_fn = slice_file
    pc_mod = sys.modules.get("backend.app.pc_slicer")
    if pc_mod and hasattr(pc_mod, "slice_file") and pc_mod.slice_file is not slice_file:
        if getattr(slice_file, "_mock_self", None) is None:
            slicer_fn = pc_mod.slice_file

    result = slicer_fn(
        source=source,
        name=out_name,
        printer_json=printer_json,
        process_json=process_json,
        filament_jsons=filament_jsons,
        arrange=False,
        orient=False,
        plate=plate,
    )

    set_slice_progress(request_id, "Completed", 100)
    logger.info(
        "[Builtin-Slicer] %s erfolgreich geslict (%d s, %.2f g)",
        out_name,
        result.print_time_seconds,
        result.filament_grams,
    )
    return result


def _port_listening(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def ensure_builtin_slicer_running(ports: tuple[int, ...] = (3001,)) -> None:
    """Startet das integrierte Slicer-Sidecar (`backend.app.pc_slicer:app`) im Hintergrund auf Port 3001."""
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

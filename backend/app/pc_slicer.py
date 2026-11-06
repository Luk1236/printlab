"""Integrierter Slicer & PC-Slicer-Sidecar für PrintLab (Port 3001 / 3003).

Wird beim Start von PrintLab automatisch im Hintergrund auf ``127.0.0.1:3001`` (und ``3003``)
gestartet, sodass ``http://localhost:3001`` ohne Zusatz-Container sofort antwortet.
Nutzt ein installiertes Bambu Studio / OrcaSlicer CLI (falls vorhanden) und fällt auf dem
Raspberry Pi 5 automatisch auf den integrierten Python-3MF/STL-Slicer (``builtin_slicer.py``) zurück.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.app.services.builtin_slicer import (
    BUILTIN_VERSION,
    get_slice_progress,
    list_bundled_profiles,
    resolve_profile_values,
    slice_model_builtin,
)
from backend.app.services.slicer_cli import SlicerCliError, program_path, slice_file

logger = logging.getLogger(__name__)
app = FastAPI(title="PrintLab Integrated Slicer Sidecar", version=BUILTIN_VERSION)

MAX_BYTES = 200 * 1024 * 1024


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_ip(value: str | None):
    if value == "testclient":
        return ipaddress.ip_address("127.0.0.1")
    try:
        return ipaddress.ip_address((value or "").strip().split("%")[0])
    except ValueError:
        return None


def _allowed_networks() -> list:
    networks = []
    for part in os.environ.get("PC_SLICER_ALLOWED_IPS", "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("[PC-Slicer] Ungültiger Eintrag in PC_SLICER_ALLOWED_IPS ignoriert: %r", part)
    return networks


def _client_allowed(client_host: str | None, headers) -> bool:
    """Loopback immer; sonst müssen konfigurierte IP-Liste und/oder Token passen (Standard: verweigern)."""
    ip = _parse_ip(client_host)
    if ip is not None and ip.is_loopback:
        return True
    networks = _allowed_networks()
    token = os.environ.get("PC_SLICER_TOKEN", "")
    if not networks and not token:
        return False
    if networks and (ip is None or not any(ip in net for net in networks)):
        return False
    if token:
        auth = headers.get("authorization", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else headers.get("x-slicer-token", "")
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return False
    return True


@app.middleware("http")
async def access_guard(request: Request, call_next):
    client_host = request.client.host if request.client else None
    if not _client_allowed(client_host, request.headers):
        logger.warning("[PC-Slicer] Zugriff von %s abgelehnt", client_host)
        return JSONResponse(status_code=403, content={"detail": "Zugriff nicht erlaubt."})
    return await call_next(request)


@app.get("/health")
async def health():
    program = program_path()
    cli_available = bool(program) and Path(program).is_file()
    engine = "bambu-studio" if cli_available else "printlab-builtin"
    return {
        "status": "ok",
        "slicer": engine,
        "program": program,
        "available": True,
        "cli_available": cli_available,
        "checks": {
            "slicer": {
                "status": "ok",
                "version": BUILTIN_VERSION if not cli_available else f"{BUILTIN_VERSION}+cli",
            }
        },
    }


@app.get("/")
async def root():
    return {
        "service": "printlab-integrated-slicer",
        "version": BUILTIN_VERSION,
        "slice": "POST /slice",
        "health": "/health",
        "bundled_profiles": "/profiles/bundled",
    }


@app.get("/profiles/bundled")
async def bundled_profiles():
    """Liefert die integrierten Standard-Profile (Drucker, Prozess, Filament) für den Slice-Dialog."""
    return list_bundled_profiles()


@app.post("/profiles/resolve")
async def resolve_profile(payload: dict[str, Any]):
    """Flacht ein Prozess-/Filament-Profil gegen die integrierten Standardwerte ab."""
    category = str(payload.get("category") or "process")
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    resolved = resolve_profile_values(category, profile)
    return {"profile": resolved, "values": resolved}


@app.get("/slice/progress/{request_id}")
async def progress(request_id: str):
    """Liefert den Live-Fortschritt eines laufenden Slice-Auftrags."""
    snap = get_slice_progress(request_id)
    if snap is None:
        return JSONResponse(status_code=404, content={"detail": "progress not supported"})
    return snap


async def _read_form_text(item: Any) -> str | None:
    if item is None:
        return None
    if isinstance(item, (UploadFile, StarletteUploadFile)) or hasattr(item, "read"):
        raw = await item.read()
        return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    return str(item)


@app.post("/slice")
async def slice_route(request: Request):
    form = await request.form()
    upload = form.get("file") or form.get("model")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "Keine Modelldatei ('file') übergeben.")

    filename = Path(getattr(upload, "filename", None) or "modell.3mf").name
    suffix = Path(filename).suffix.lower()
    if suffix not in (".3mf", ".stl"):
        raise HTTPException(400, "Nur .3mf oder .stl werden unterstützt.")

    plate = await _read_form_text(form.get("plate"))
    exportType = await _read_form_text(form.get("exportType"))
    arrange = await _read_form_text(form.get("arrange"))
    orient = await _read_form_text(form.get("orient"))
    requestId = await _read_form_text(form.get("requestId")) or request.headers.get("x-slice-request-id")
    printerProfile = await _read_form_text(form.get("printerProfile"))
    presetProfile = await _read_form_text(form.get("presetProfile"))

    filament_items = form.getlist("filamentProfile")
    filamentProfile: list[str] = []
    for f_item in filament_items:
        txt = await _read_form_text(f_item)
        if txt:
            filamentProfile.append(txt)

    plate_num: int | None = None
    if plate is not None and str(plate).strip():
        try:
            plate_num = int(str(plate).strip())
            if plate_num < 1:
                raise ValueError
        except ValueError:
            raise HTTPException(400, f"Ungültige Platte: {plate!r} (Zahl >= 1 oder leer).") from None

    data = await upload.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "Die Datei ist leer.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Die Datei ist größer als 200 MB.")

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_name = tmp.name
        out_name = Path(filename).stem + ".gcode.3mf"
        try:
            result = await asyncio.to_thread(
                slice_model_builtin,
                Path(tmp_name),
                out_name,
                printerProfile,
                presetProfile,
                list(filamentProfile),
                plate_num,
                requestId,
            )
        except Exception as exc:
            logger.warning("[PC-Slicer] Slicing fehlgeschlagen: %s", exc)
            raise HTTPException(500, str(exc)) from exc
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)

    headers = {
        "X-Print-Time-Seconds": str(result.print_time_seconds),
        "X-Filament-Used-G": f"{result.filament_grams:.2f}",
        "X-Filament-Used-Mm": f"{result.filament_grams * 335.0:.1f}",
    }
    if str(exportType or "").strip().lower() == "3mf":
        return Response(content=result.content, media_type="application/octet-stream", headers=headers)

    candidates = (
        [f"Metadata/plate_{plate_num}.gcode", "Metadata/plate_1.gcode"]
        if plate_num is not None
        else ["Metadata/plate_1.gcode"]
    )
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gcode.3mf") as tmp:
            tmp.write(result.content)
            tmp_name = tmp.name
        with zipfile.ZipFile(tmp_name) as zf:
            names = set(zf.namelist())
            wanted = next((c for c in candidates if c in names), None)
            if wanted is None:
                found = [n for n in names if n.endswith(".gcode")][:3]
                raise KeyError(f"plate_N.gcode nicht in der 3MF (gefunden: {found})")
            gcode = zf.read(wanted)
        return Response(content=gcode, media_type="text/plain", headers=headers)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise HTTPException(500, f"Erzeugte 3MF ohne G-code: {exc}") from exc
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("PC_SLICER_HOST", "127.0.0.1"),
        port=int(os.environ.get("PC_SLICER_PORT", "3001")),
        loop="asyncio",
    )

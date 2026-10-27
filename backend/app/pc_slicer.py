"""PC-Slicer für Bambuddy: Bambu Studio CLI über die Sidecar-Schnittstelle.

Start (PC, im Bambuddy-Ordner):

    .venv\\Scripts\\python.exe -m uvicorn backend.app.pc_slicer:app --host 127.0.0.1 --port 3001

In Bambuddy unter Einstellungen → Workflow → Slicer die „Bambu Studio sidecar URL“
auf http://127.0.0.1:3001 setzen (oder die IP des PCs, wenn Bambuddy auf dem Pi läuft)
und „Slicer-API verwenden“ einschalten.

Zugriffsschutz (Standard: nur Anfragen von diesem PC, also Loopback):

- ``PC_SLICER_ALLOWED_IPS`` – kommagetrennte IPs/Netze (z. B. ``192.168.178.133,10.0.0.0/24``),
  die zusätzlich zugreifen dürfen. Das ist der Weg für Bambuddy auf dem Pi, weil Bambuddys
  Slicer-Client keinen Token mitschickt.
- ``PC_SLICER_TOKEN`` – wenn gesetzt, müssen Nicht-Loopback-Clients ``Authorization: Bearer <Token>``
  oder ``X-Slicer-Token`` senden.

Ohne eine der beiden Variablen werden Anfragen von anderen Rechnern mit 403 abgelehnt, auch
wenn der Dienst auf ``0.0.0.0`` lauscht (Firewall-Regel für Port 3001 bleibt trotzdem sinnvoll).
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

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from backend.app.services.slicer_cli import SlicerCliError, program_path, slice_file

logger = logging.getLogger(__name__)
app = FastAPI(title="Bambu Studio PC Slicer", version="1.0")

MAX_BYTES = 200 * 1024 * 1024


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_ip(value: str | None):
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
    return {
        "status": "ok",
        "slicer": "bambu-studio",
        "program": program,
        "available": bool(program) and Path(program).is_file(),
    }


@app.get("/")
async def root():
    return {"service": "bambu-studio-pc-slicer", "slice": "POST /slice", "health": "/health"}


@app.get("/slice/progress/{request_id}")
async def progress(request_id: str):
    """Fortschritt wird nicht gemeldet; Bambuddy fällt auf seine Zeitüberwachung zurück."""
    return JSONResponse(status_code=404, content={"detail": "progress not supported"})


@app.post("/slice")
async def slice_route(
    file: UploadFile = File(...),
    printerProfile: str | None = Form(None),
    presetProfile: str | None = Form(None),
    filamentProfile: list[str] = Form(default=[]),
    plate: str | None = Form(None),
    exportType: str | None = Form(None),
    arrange: str | None = Form(None),
    orient: str | None = Form(None),
    requestId: str | None = Form(None),
):
    filename = Path(file.filename or "modell.3mf").name
    suffix = Path(filename).suffix.lower()
    if suffix not in (".3mf", ".stl"):
        raise HTTPException(400, "Nur .3mf oder .stl werden unterstützt.")
    plate_num: int | None = None
    if plate is not None and str(plate).strip():
        try:
            plate_num = int(str(plate).strip())
            if plate_num < 1:
                raise ValueError
        except ValueError:
            raise HTTPException(400, f"Ungültige Platte: {plate!r} (Zahl >= 1 oder leer).") from None
    data = await file.read(MAX_BYTES + 1)
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
        result = await asyncio.to_thread(
            slice_file,
            Path(tmp_name),
            out_name,
            printerProfile,
            presetProfile,
            list(filamentProfile or []),
            _truthy(arrange),
            _truthy(orient),
            900.0,
            plate_num,
        )
    except SlicerCliError as exc:
        logger.warning("[PC-Slicer] %s", exc)
        raise HTTPException(500, str(exc)) from exc
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)

    headers = {
        "X-Print-Time-Seconds": str(result.print_time_seconds),
        "X-Filament-Used-G": f"{result.filament_grams:.2f}",
        "X-Filament-Used-Mm": "0",
    }
    if str(exportType or "").strip().lower() == "3mf":
        return Response(content=result.content, media_type="application/octet-stream", headers=headers)

    # Ohne 3MF-Wunsch den G-code aus der erzeugten Datei liefern (Bambuddy erwartet dann Text).
    # Mit Plattenwahl: zuerst Metadata/plate_N.gcode, sonst plate_1.gcode.
    candidates = ([f"Metadata/plate_{plate_num}.gcode", "Metadata/plate_1.gcode"]
                  if plate_num is not None else ["Metadata/plate_1.gcode"])
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

    uvicorn.run(app, host=os.environ.get("PC_SLICER_HOST", "127.0.0.1"),
                port=int(os.environ.get("PC_SLICER_PORT", "3001")), loop="asyncio")

"""PC-Slicer für Bambuddy: Bambu Studio CLI über die Sidecar-Schnittstelle.

Start (PC, im Bambuddy-Ordner):

    .venv\\Scripts\\python.exe -m uvicorn backend.app.pc_slicer:app --host 127.0.0.1 --port 3001

In Bambuddy unter Einstellungen → Workflow → Slicer die „Bambu Studio sidecar URL“
auf http://127.0.0.1:3001 setzen (oder die IP des PCs, wenn Bambuddy auf dem Pi läuft)
und „Slicer-API verwenden“ einschalten.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from backend.app.services.slicer_cli import SlicerCliError, program_path, slice_file

logger = logging.getLogger(__name__)
app = FastAPI(title="Bambu Studio PC Slicer", version="1.0")

MAX_BYTES = 200 * 1024 * 1024


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


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
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".3mf") as tmp:
            tmp.write(result.content)
            tmp_name = tmp.name
        with zipfile.ZipFile(tmp_name) as zf:
            gcode = zf.read("Metadata/plate_1.gcode")
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

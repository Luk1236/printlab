"""Leerbett-Prüfung einmessen (Oberfläche): aus Beispielbildern mit leerem und belegtem Bett einen Schwellwert ableiten.

Gegenstück zu ``werkzeuge/kamera_kalibrieren.py``. Die Bilder werden nur im Arbeitsspeicher ausgewertet und nicht
gespeichert; gespeichert wird allein der Schwellwert (``plate_detection_tuning.json`` im Datenordner), den
``PlateDetector`` danach benutzt. Der Schwellwert gilt für alle Drucker (die Referenzbilder dagegen je Drucker).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.camera import get_printer_or_404
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.user import User
from backend.app.services import audit_log, camera_calibration

router = APIRouter(prefix="/printers", tags=["plate-detection"])
logger = logging.getLogger(__name__)

MAX_IMAGES = 20
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}


def _load_detector():
    """Der Detektor, oder 503, wenn OpenCV fehlt (eine Stelle, die Tests ersetzen können)."""
    from backend.app.services.plate_detection import PlateDetector, is_plate_detection_available

    if not is_plate_detection_available():
        raise HTTPException(503, "Plate detection not available")
    return PlateDetector(difference_threshold=1.0)  # nur zum Messen der Abweichung


async def _read_images(files: list[UploadFile], label: str) -> list[tuple[str, bytes]]:
    if not files:
        raise HTTPException(400, f"Bilder fehlen: {label}.")
    if len(files) > MAX_IMAGES:
        raise HTTPException(400, f"Höchstens {MAX_IMAGES} Bilder je Gruppe.")
    out: list[tuple[str, bytes]] = []
    for file in files:
        if (file.content_type or "").lower() not in IMAGE_TYPES:
            raise HTTPException(400, f"Nur Bilder (JPEG oder PNG) sind erlaubt: {file.filename}.")
        data = await file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(400, f"Bild zu groß (höchstens 8 MB): {file.filename}.")
        if not data:
            raise HTTPException(400, f"Leeres Bild: {file.filename}.")
        out.append(((file.filename or "bild")[:80], data))
    return out


def _score(detector, printer_id: int, images: list[tuple[str, bytes]]) -> list[dict]:
    scores = []
    for name, data in images:
        result = detector.analyze_frame(data, printer_id)
        if result.needs_calibration:
            raise HTTPException(400, "Keine Referenz für diesen Drucker: erst eine Referenz aufnehmen.")
        scores.append({"name": name, "score": round(float(result.difference_percent), 3)})
    return scores


@router.get("/{printer_id}/camera/plate-detection/tuning")
async def get_tuning(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.CAMERA_VIEW),
):
    """Gespeicherter Schwellwert, Standardwert und der, der gerade gilt."""
    await get_printer_or_404(printer_id, db)
    from backend.app.services.plate_detection import PlateDetector

    saved = camera_calibration.load_difference_threshold()
    default = PlateDetector.DEFAULT_DIFFERENCE_THRESHOLD
    return {"saved": saved, "default": default, "effective": saved or default}


@router.post("/{printer_id}/camera/plate-detection/tuning/analyze")
async def analyze_tuning(
    printer_id: int,
    empty: list[UploadFile] = File(...),
    occupied: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.CAMERA_VIEW),
):
    """Messwerte der Beispielbilder und einen Vorschlag für Schwellwert und Mindest-Sicherheit (speichert nichts)."""
    await get_printer_or_404(printer_id, db)
    empty_images = await _read_images(empty, "leeres Bett")
    occupied_images = await _read_images(occupied, "belegtes Bett")
    detector = _load_detector()
    empty_scores = await asyncio.to_thread(_score, detector, printer_id, empty_images)
    occupied_scores = await asyncio.to_thread(_score, detector, printer_id, occupied_images)
    try:
        suggestion = camera_calibration.suggest(
            [s["score"] for s in empty_scores], [s["score"] for s in occupied_scores]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"empty": empty_scores, "occupied": occupied_scores, "suggestion": suggestion}


@router.put("/{printer_id}/camera/plate-detection/tuning")
async def save_tuning(
    printer_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Schwellwert (Prozent) speichern; gilt sofort für neue Prüfungen."""
    await get_printer_or_404(printer_id, db)
    try:
        value = float(payload.get("threshold"))
        camera_calibration.save_difference_threshold(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "Schwellwert muss eine Zahl zwischen 0,05 und 50 Prozent sein.") from None
    audit_log.record("plate_tuning_saved", True, f"{value:g} %", printer_id, getattr(user, "username", None))
    return {"saved": value}


@router.delete("/{printer_id}/camera/plate-detection/tuning")
async def reset_tuning(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Zurück zum Standardwert."""
    await get_printer_or_404(printer_id, db)
    existed = camera_calibration.clear_difference_threshold()
    audit_log.record("plate_tuning_reset", True, "", printer_id, getattr(user, "username", None))
    return {"reset": existed}

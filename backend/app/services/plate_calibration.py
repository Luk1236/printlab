"""Kamera-Einmessung über vier Plattenecken (Roadmap P1).

Die Frontkamera der P2S sieht das Druckbett perspektivisch. Für den
Leerbett-/Bauteilvergleich (Bauteil-Wächter, Erste-Schicht-Inspektor) ist
jedoch eine ebene Aufsicht nötig: der Dienst rechnet mit der Homographie
aus vier Punktepaaren um — die vier Plattenecken im Kamerabild auf die vier
Ecken einer normalisierten Platte.

Punkte werden normalisiert (0..1) gespeichert, Reihenfolge
oben-links, oben-rechts, unten-rechts, unten-links. Ablage:
``data/plate_calibration/<printer_id>.json``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

STORE_DIR = settings.base_dir / "plate_calibration"
PLATE_TARGET_PX = 800  # Zielseite für die Aufsicht
TARGET: np.ndarray = np.array(
    [[0, 0], [PLATE_TARGET_PX, 0], [PLATE_TARGET_PX, PLATE_TARGET_PX], [0, PLATE_TARGET_PX]],
    dtype=np.float32,
)


def _path_for(printer_id: int) -> Path:
    return STORE_DIR / f"{int(printer_id)}.json"


def _load_points(printer_id: int) -> list[list[float]] | None:
    path = _path_for(printer_id)
    if not path.exists():
        return None
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        points = data.get("points")
        if (
            isinstance(points, list)
            and len(points) == 4
            and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in points)
        ):
            return [[float(p[0]), float(p[1])] for p in points]
    except (OSError, ValueError):
        pass
    return None


def status(printer_id: int) -> dict[str, Any]:
    points = _load_points(printer_id)
    return {
        "calibrated": points is not None,
        "points": points,
        "plate_size": PLATE_TARGET_PX,
    }


def set_points(printer_id: int, points: list[list[float]]) -> dict[str, Any]:
    """Einmessung speichern (normalisierte Punkte 0..1, TL/TR/BR/BL)."""
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError("Genau vier Punkte erwartet (TL, TR, BR, BL).")
    normalized: list[list[float]] = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("Punktformat [x, y] erwartet.")
        x, y = float(p[0]), float(p[1])
        if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
            raise ValueError("Punkte müssen normalisiert sein (0..1).")
        normalized.append([x, y])
    path = _path_for(printer_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(
        json.dumps({"points": normalized, "plate_size": PLATE_TARGET_PX}, ensure_ascii=False),
        encoding="utf-8",
    )
    return status(printer_id)


def clear(printer_id: int) -> dict[str, Any]:
    _path_for(printer_id).unlink(missing_ok=True)
    return status(printer_id)


def has_calibration(printer_id: int) -> bool:
    """True, wenn für diesen Drucker eine Einmessung gespeichert ist."""
    return _load_points(printer_id) is not None


def warp_points_for(printer_id: int, size: tuple[int, int]) -> np.ndarray | None:
    """Quellpunkte in Pixeln für ein Bild der angegebenen Größe (oder None)."""
    points = _load_points(printer_id)
    if points is None:
        return None
    w, h = size
    return np.array([[p[0] * w, p[1] * h] for p in points], dtype=np.float32)


def warp_bytes(printer_id: int, image_bytes: bytes) -> bytes | None:
    """Bild in die Plattenaufsicht verzerren (None ohne Einmessung, Original bei Fehler)."""
    points = _load_points(printer_id)
    if points is None:
        return None
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        logger.warning("[PlateCalibration] Snapshot nicht lesbar (Drucker %s)", printer_id)
        return None
    h, w = frame.shape[:2]
    src = np.array([[p[0] * w, p[1] * h] for p in points], dtype=np.float32)
    try:
        matrix, _ = cv2.findHomography(src.reshape(-1, 1, 2), TARGET.reshape(-1, 1, 2))
        if matrix is None:
            return None
        warped = cv2.warpPerspective(frame, matrix, (PLATE_TARGET_PX, PLATE_TARGET_PX))
        success, encoded = cv2.imencode(".jpg", warped)
        if not success:
            return None
        return encoded.tobytes()
    except cv2.error as exc:
        logger.warning("[PlateCalibration] Warp fehlgeschlagen (Drucker %s): %s", printer_id, exc)
        return None


async def warp_snapshot(printer_id: int, image_bytes: bytes) -> bytes | None:
    """Asynchrone Variante von ``warp_bytes`` (CV-Arbeit im Thread)."""
    import asyncio

    return await asyncio.to_thread(warp_bytes, printer_id, image_bytes)

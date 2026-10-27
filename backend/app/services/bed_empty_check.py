"""Leerbett-Prüfung per Kamera (Roadmap P1): Warnt, falls beim Druckstart
etwas auf der Platte liegt.

Referenz: ein mit „Leerbett aufnehmen“ aufgenommenes, eingemessenes Aufsicht-
bild pro Drucker (``data/plate_calibration``, gleiche Homographie wie der
Bauteil-Wächter). Beim Start eines Drucks wird ein Snapshot gegriffen,
eingemessen und mit dem Leerbett verglichen; Differenz über Schwelle = Warnung
(an Bambuddys KI-Fehlerte-Kanal, ohne Eingriff).

Konfiguration: ``data/bed_empty_check.json``:
``{"enabled": false, "threshold": 8.0}``
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "bed_empty_check.json"
DEFAULT = {"enabled": False, "threshold": 8.0}
_lock = threading.Lock()


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_config() -> dict[str, Any]:
    cfg = dict(DEFAULT)
    cfg.update({k: _read(CONFIG_PATH).get(k, DEFAULT[k]) for k in DEFAULT})
    try:
        cfg["threshold"] = float(cfg["threshold"])
    except (TypeError, ValueError):
        cfg["threshold"] = DEFAULT["threshold"]
    return cfg


def write_config(update: dict[str, Any]) -> dict[str, Any]:
    cfg = read_config()
    if "enabled" in update:
        cfg["enabled"] = bool(update["enabled"])
    if "threshold" in update:
        cfg["threshold"] = float(update["threshold"])
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    return cfg


def save_reference(printer_id: int, image_bytes: bytes) -> dict[str, Any]:
    """Leerbett-Referenz speichern (durch die Einmessung in Aufsicht verzogen)."""
    from backend.app.services.plate_calibration import warp_bytes

    warped = warp_bytes(printer_id, image_bytes)
    if warped is None:
        raise ValueError("Keine Einmessung für diesen Drucker — erst die 4 Ecken einmessen.")
    path = settings.base_dir / "plate_calibration" / f"{int(printer_id)}.blank.jpg"
    path.write_bytes(warped)
    return {"saved": True, "reference": str(path.name)}


def has_reference(printer_id: int) -> bool:
    path = settings.base_dir / "plate_calibration" / f"{int(printer_id)}.blank.jpg"
    return path.is_file()


def check(printer_id: int, image_bytes: bytes) -> dict[str, Any] | None:
    """Vergleich Start-Snapshot ↔ Leerbett; dict mit Warnung oder None.

    Ohne Referenz, ohne Einmessung oder bei ausgeschalteter Prüfung immer None.
    """
    cfg = read_config()
    if not cfg["enabled"] or not has_reference(printer_id):
        return None
    from backend.app.services.plate_calibration import warp_bytes

    warped = warp_bytes(printer_id, image_bytes)
    if warped is None:
        return None
    reference_path = settings.base_dir / "plate_calibration" / f"{int(printer_id)}.blank.jpg"
    blank = cv2.imdecode(np.frombuffer(reference_path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    current = cv2.imdecode(np.frombuffer(warped, np.uint8), cv2.IMREAD_GRAYSCALE)
    if blank is None or current is None:
        return None
    if blank.shape != current.shape:
        current = cv2.resize(current, (blank.shape[1], blank.shape[0]))
    diff = float(cv2.absdiff(blank, current).mean())
    if diff <= float(cfg["threshold"]):
        logger.info("[Leerbett] Drucker %s: Platte frei (Diff %.2f)", printer_id, diff)
        return {"warning": None, "diff": round(diff, 2), "threshold": cfg["threshold"]}
    message = (
        f"Kamera meldet Material auf der Platte ({diff:.1f} > {cfg['threshold']:.1f}). "
        f"Platte freigeben oder Druck verwerfen, falls das Objekt falsch erkannt ist."
    )
    logger.warning("[Leerbett] Drucker %s: %s", printer_id, message)
    return {"warning": message, "diff": round(diff, 2), "threshold": cfg["threshold"]}
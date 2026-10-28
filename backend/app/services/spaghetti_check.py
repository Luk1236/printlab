"""Spaghetti-/Abbruch-Erkennung (Roadmap P1): nach Druckmitte einmalig das
entzerrte Kamerabild darauf prüfen, ob Filament auf der leeren Platte
verstreut liegt statt am Bauteil zu kleben.

Metrik (nur Warnung, nie Eingriff):
- Vergleich gegen die Leerbett-Referenz (``bed_empty_check``), aber nicht
  „ist das Bett verändert", sondern „ist die Veränderung verstreut":
  Schwellwertmaske der Differenz -> Zusammenhänge zählen. Ein sauberer Druck
  erzeugt wenige, kompakte Flecken; Spaghetti viele kleine.

Konfiguration: ``data/spaghetti_check.json``:
``{"enabled": false, "max_components": 25, "min_changed_percent": 0.5}``
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import cv2
import numpy as np

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "spaghetti_check.json"
DEFAULT = {"enabled": False, "max_components": 25, "min_changed_percent": 0.5}
_lock = threading.Lock()


def read_config() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = dict(DEFAULT)
        if isinstance(data, dict):
            cfg.update({k: data[k] for k in DEFAULT if k in data})
    except (OSError, ValueError):
        cfg = dict(DEFAULT)
    try:
        cfg["max_components"] = max(1, int(cfg["max_components"]))
        cfg["min_changed_percent"] = max(0.0, float(cfg["min_changed_percent"]))
    except (TypeError, ValueError):
        cfg = dict(DEFAULT)
    return cfg


def write_config(update: dict[str, Any]) -> dict[str, Any]:
    cfg = read_config()
    if "enabled" in update:
        cfg["enabled"] = bool(update["enabled"])
    if "max_components" in update:
        cfg["max_components"] = max(1, int(update["max_components"]))
    if "min_changed_percent" in update:
        cfg["min_changed_percent"] = max(0.0, float(update["min_changed_percent"]))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    return cfg


def spread_score(warped: bytes, blank: bytes) -> tuple[int, float]:
    """(Anzahl zusammenhängender Differenzflecken, veränderter Flächenanteil)."""
    ref = cv2.imdecode(np.frombuffer(blank, np.uint8), cv2.IMREAD_GRAYSCALE)
    cur = cv2.imdecode(np.frombuffer(warped, np.uint8), cv2.IMREAD_GRAYSCALE)
    if ref is None or cur is None:
        return 0, 0.0
    if ref.shape != cur.shape:
        cur = cv2.resize(cur, (ref.shape[1], ref.shape[0]))
    mask = cv2.absdiff(ref, cur) > 40
    percent = float(mask.mean()) * 100.0
    mask_u8 = mask.astype(np.uint8)
    components = int(cv2.connectedComponents(mask_u8, connectivity=8)[0] - 1)
    return components, percent


def check(printer_id: int, image_bytes: bytes, blank: bytes) -> dict[str, Any] | None:
    """Warnung bei verstreutem Material, sonst None (alle Gründe)."""
    cfg = read_config()
    if not cfg["enabled"] or not image_bytes or not blank:
        return None
    from backend.app.services.plate_calibration import warp_bytes

    warped = warp_bytes(printer_id, image_bytes)
    if warped is None:
        return None
    components, percent = spread_score(warped, blank)
    if components <= int(cfg["max_components"]) or percent < float(cfg["min_changed_percent"]):
        logger.info(
            "[Spaghetti] Drucker %s: unauffällig (%d Flecken, %.2f%% verändert)",
            printer_id,
            components,
            percent,
        )
        return {"warning": None, "components": components, "changed_percent": round(percent, 2)}
    message = (
        f"Kamera sieht verstreutes Filament: {components} getrennte Flecken "
        f"({percent:.1f}% der Platte). Druck prüfen — vielleicht Spaghetti oder abgebrochen."
    )
    logger.warning("[Spaghetti] Drucker %s: %s", printer_id, message)
    return {"warning": message, "components": components, "changed_percent": round(percent, 2)}


class SpaghettiCheck:
    """Einmal pro Druck, ab etwa 75 % der Schichten, Bild gegen Leerbett."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._keys: dict[int, str] = {}
        self._checked: dict[int, bool] = {}
        self._last: dict[int, int] = {}

    def _reset_if_new_print(self, printer_id: int, key: str, layer_num: int) -> None:
        old = self._keys.get(printer_id, "")
        last = self._last.get(printer_id, 0)
        if (key and old and key != old) or layer_num < last:
            self._checked[printer_id] = False
        if key:
            self._keys[printer_id] = key
        self._last[printer_id] = layer_num

    def needs_frame(self, printer_id: int, layer_num: int, total_layers: int, key: str = "") -> bool:
        with self._lock:
            self._reset_if_new_print(printer_id, key, layer_num)
            if not read_config()["enabled"] or self._checked.get(printer_id):
                return False
            if total_layers <= 0 or not key:
                return False
            return layer_num >= max(3, (total_layers * 3) // 4)

    def observe(
        self, printer_id: int, printer_name: str, layer_num: int, image: bytes | None, key: str = ""
    ) -> dict[str, Any] | None:
        with self._lock:
            self._reset_if_new_print(printer_id, key, layer_num)
            if not read_config()["enabled"] or not image or self._checked.get(printer_id):
                return None
            self._checked[printer_id] = True

        blank_path = settings.base_dir / "plate_calibration" / f"{int(printer_id)}.blank.jpg"
        if not blank_path.is_file():
            logger.info("[Spaghetti] Drucker %s: keine Leerbett-Referenz, überspringen", printer_id)
            return None
        try:
            result = check(printer_id, image, blank_path.read_bytes())
        except (OSError, ValueError) as exc:
            logger.warning("[Spaghetti] Prüfung fehlgeschlagen: %s", exc)
            return None
        if result and result.get("warning"):
            return {"layer": layer_num, "printer": printer_name, **result}
        return None


spaghetti_check = SpaghettiCheck()

"""Erste-Schicht-Inspektor: prüft das Kamerabild der ersten Schicht.

Port aus dem Bambu-Monitor. Nach Schicht 1–2 wird ein Bild aufgenommen und
ohne Referenz beurteilt: zu dunkel, zu kontrastarm oder keine Kanten deuten
auf fehlenden Materialauftrag hin. Nur melden, nie eingreifen.

Konfiguration in ``data/first_layer_inspector.json``.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "first_layer_inspector.json"
ROI = (0.20, 0.25, 0.80, 0.90)
MIN_BRIGHTNESS = 25.0
MIN_CONTRAST = 8.0
MIN_EDGES = 1.5


def inspect_image(image: bytes) -> dict[str, Any]:
    """Liefert Messwerte und Urteil für ein Kamerabild."""
    gray = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("Bild nicht lesbar")
    h, w = gray.shape[:2]
    roi = gray[int(h * ROI[1]) : int(h * ROI[3]), int(w * ROI[0]) : int(w * ROI[2])]
    brightness = float(roi.mean())
    contrast = float(roi.std())
    edges = cv2.Canny(roi, 50, 150)
    edge_density = float((edges > 0).mean() * 100.0)
    reasons = []
    if brightness < MIN_BRIGHTNESS:
        reasons.append("zu dunkel")
    if contrast < MIN_CONTRAST:
        reasons.append("zu kontrastarm")
    if edge_density < MIN_EDGES:
        reasons.append("keine Struktur erkennbar")
    return {
        "ok": not reasons,
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "edge_density": round(edge_density, 2),
        "message": "Erste Schicht unauffällig." if not reasons else "Erste Schicht prüfen: " + ", ".join(reasons) + ".",
    }


class FirstLayerInspector:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._config = self._load()
        self._print_key: dict[int, str] = {}
        self._checked: dict[int, bool] = {}
        self._last_layer: dict[int, int] = {}
        self._result: dict[int, dict[str, Any] | None] = {}

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self._config, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            logger.warning("[Erste-Schicht] Konfiguration nicht speicherbar: %s", exc)

    def _entry(self, printer_id: int) -> dict[str, Any]:
        entry = self._config.get(str(printer_id))
        if not isinstance(entry, dict):
            entry = {"enabled": False}
            self._config[str(printer_id)] = entry
        entry.setdefault("enabled", False)
        return entry

    def status(self, printer_id: int) -> dict[str, Any]:
        with self._lock:
            return {
                **self._entry(printer_id),
                "result": self._result.get(printer_id),
                "checked": bool(self._checked.get(printer_id, False)),
                "last_layer": int(self._last_layer.get(printer_id, 0)),
            }

    def configure(self, printer_id: int, enabled: bool, pause_on_warning: bool | None = None) -> dict[str, Any]:
        with self._lock:
            entry = self._entry(printer_id)
            entry["enabled"] = bool(enabled)
            if pause_on_warning is not None:
                entry["pause_on_warning"] = bool(pause_on_warning)
            self._save()
            self._checked[printer_id] = False
            self._result[printer_id] = None
            return self.status(printer_id)

    def pause_on_warning(self, printer_id: int) -> bool:
        """True, wenn bei einer Warnung der Druck automatisch pausieren soll."""
        with self._lock:
            return bool(self._entry(printer_id).get("pause_on_warning", False))

    def _reset_if_new_print(self, printer_id: int, key: str, layer_num: int) -> None:
        old_key = self._print_key.get(printer_id, "")
        last = self._last_layer.get(printer_id, 0)
        if (key and old_key and key != old_key) or layer_num < last:
            self._checked[printer_id] = False
            self._result[printer_id] = None
        if key:
            self._print_key[printer_id] = key
        self._last_layer[printer_id] = layer_num

    def needs_frame(self, printer_id: int, layer_num: int, key: str = "") -> bool:
        with self._lock:
            if not self._entry(printer_id).get("enabled"):
                return False
            self._reset_if_new_print(printer_id, key, layer_num)
            return 1 <= layer_num <= 5 and not self._checked.get(printer_id)

    def observe(self, printer_id: int, layer_num: int, image: bytes | None, key: str = "") -> dict[str, Any] | None:
        with self._lock:
            if not self._entry(printer_id).get("enabled") or not image:
                return None
            self._reset_if_new_print(printer_id, key, layer_num)
            if self._checked.get(printer_id):
                return None
            self._checked[printer_id] = True
            try:
                result = inspect_image(image)
            except ValueError as exc:
                logger.warning("[Erste-Schicht] %s", exc)
                return None
            result["layer"] = layer_num
            result["time"] = datetime.now(timezone.utc).isoformat()
            self._result[printer_id] = result
            if not result["ok"]:
                logger.warning("[Erste-Schicht] Drucker %s: %s", printer_id, result["message"])
                return result
            return None


first_layer_inspector = FirstLayerInspector()

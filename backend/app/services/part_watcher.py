"""Bauteil-Wächter: erkennt, ob sich der Druck zwischen zwei Schichten verändert.

Port aus dem Bambu-Monitor, hier auf Bambuddys Kamera-Snapshots. Beim Schicht-
wechsel wird bei Schicht 2 ein Referenzbild gespeichert und etwa bei der Hälfte
des Drucks mit einem neuen Bild verglichen. Kaum Unterschied = Warnung
(möglicherweise kein Materialauftrag / Fehldruck).

Nur melden, nie eingreifen. Die Konfiguration liegt in ``data/part_watcher.json``.
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

CONFIG_PATH = settings.base_dir / "part_watcher.json"
DEFAULT = {"enabled": False, "threshold": 1.0}
ROI = (0.20, 0.25, 0.80, 0.90)  # x0, y0, x1, y1 im Bild


def compare_images(reference: bytes, current: bytes) -> float:
    """Mittlere Grauwert-Differenz im Bauraum-Ausschnitt (0 = identisch)."""
    first = cv2.imdecode(np.frombuffer(reference, np.uint8), cv2.IMREAD_GRAYSCALE)
    second = cv2.imdecode(np.frombuffer(current, np.uint8), cv2.IMREAD_GRAYSCALE)
    if first is None or second is None:
        raise ValueError("Bild nicht lesbar")
    h, w = first.shape[:2]
    box = (int(w * ROI[0]), int(h * ROI[1]), int(w * ROI[2]), int(h * ROI[3]))
    second = cv2.resize(second, (w, h))
    first_roi = first[box[1]:box[3], box[0]:box[2]]
    second_roi = second[box[1]:box[3], box[0]:box[2]]
    return float(cv2.absdiff(first_roi, second_roi).mean())


class PartWatcher:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._config = self._load()
        self._ref: dict[int, bytes] = {}
        self._print_key: dict[int, str] = {}
        self._checked: dict[int, bool] = {}
        self._last_layer: dict[int, int] = {}
        self._warning: dict[int, dict[str, Any] | None] = {}

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
            logger.warning("[Bauteil-Wächter] Konfiguration nicht speicherbar: %s", exc)

    def _entry(self, printer_id: int) -> dict[str, Any]:
        entry = self._config.get(str(printer_id))
        if not isinstance(entry, dict):
            entry = dict(DEFAULT)
            self._config[str(printer_id)] = entry
        entry.setdefault("enabled", False)
        try:
            entry["threshold"] = max(0.05, min(20.0, float(entry.get("threshold", 1.0))))
        except (TypeError, ValueError):
            entry["threshold"] = 1.0
        return entry

    def _resolve(self, printer_id: int, key: str) -> dict[str, Any]:
        """Standard-Eintrag, überlagert vom ersten passenden Auftrags-Override.

        Overrides sitzen in ``self._config["overrides"]``:
        ``[{"key_contains": "mein-modell",
            "threshold": 2.0, "enabled": true}, ...]`` — Treffer, wenn
        ``key_contains`` (Groß-/Kleinschreibung egal) im Druck-Schlüssel steckt.
        Der erste Treffer gewinnt; ohne Treffer gilt der Drucker-Standard.
        """
        entry = dict(self._entry(printer_id))
        overrides = self._config.get("overrides")
        if isinstance(overrides, list) and key:
            lowered = key.lower()
            for rule in overrides:
                if not isinstance(rule, dict):
                    continue
                fragment = str(rule.get("key_contains", "")).strip().lower()
                if fragment and fragment in lowered:
                    entry["threshold"] = max(0.05, min(20.0, float(rule.get("threshold", entry["threshold"]))))
                    entry["enabled"] = bool(rule.get("enabled", entry["enabled"]))
                    entry["override"] = fragment
                    break
        return entry

    def status(self, printer_id: int) -> dict[str, Any]:
        with self._lock:
            entry = dict(self._entry(printer_id))
            overrides = self._config.get("overrides")
            return {
                **entry,
                "overrides": overrides if isinstance(overrides, list) else [],
                "warning": self._warning.get(printer_id),
                "checked": bool(self._checked.get(printer_id, False)),
                "last_layer": int(self._last_layer.get(printer_id, 0)),
            }

    def configure(self, printer_id: int, enabled: bool, threshold: float | None = None,
                  overrides: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._lock:
            entry = self._entry(printer_id)
            entry["enabled"] = bool(enabled)
            if threshold is not None:
                entry["threshold"] = max(0.05, min(20.0, float(threshold)))
            if overrides is not None:
                rules: list[dict[str, Any]] = []
                for rule in overrides:
                    if not isinstance(rule, dict):
                        continue
                    fragment = str(rule.get("key_contains", "")).strip()
                    if not fragment:
                        continue
                    rules.append({
                        "key_contains": fragment[:120],
                        "threshold": max(0.05, min(20.0, float(rule.get("threshold", 1.0)))),
                        "enabled": bool(rule.get("enabled", True)),
                    })
                self._config["overrides"] = rules
            self._save()
            self._checked[printer_id] = False
            self._warning[printer_id] = None
            return self.status(printer_id)

    def _reset_if_new_print(self, printer_id: int, key: str, layer_num: int) -> None:
        old_key = self._print_key.get(printer_id, "")
        last = self._last_layer.get(printer_id, 0)
        if (key and old_key and key != old_key) or layer_num < last:
            self._ref.pop(printer_id, None)
            self._checked[printer_id] = False
            self._warning[printer_id] = None
        if key:
            self._print_key[printer_id] = key
        self._last_layer[printer_id] = layer_num

    def needs_frame(self, printer_id: int, layer_num: int, total_layers: int, key: str = "") -> bool:
        with self._lock:
            entry = self._resolve(printer_id, key)
            if not entry.get("enabled"):
                return False
            self._reset_if_new_print(printer_id, key, layer_num)
            if printer_id not in self._ref:
                return layer_num <= 5
            return (
                total_layers > 0
                and layer_num >= max(3, total_layers // 2)
                and not self._checked.get(printer_id)
            )

    def observe(self, printer_id: int, printer_name: str, layer_num: int, total_layers: int,
                image: bytes | None, key: str = "") -> dict[str, Any] | None:
        with self._lock:
            entry = self._resolve(printer_id, key)
            if not entry.get("enabled") or not image:
                return None
            self._reset_if_new_print(printer_id, key, layer_num)
            if printer_id not in self._ref:
                self._ref[printer_id] = image
                logger.info("[Bauteil-Wächter] Referenzbild für Drucker %s gespeichert", printer_id)
                return None
            if total_layers <= 0 or layer_num < max(3, total_layers // 2) or self._checked.get(printer_id):
                return None
            self._checked[printer_id] = True
            try:
                difference = compare_images(self._ref[printer_id], image)
            except ValueError as exc:
                logger.warning("[Bauteil-Wächter] Vergleich fehlgeschlagen: %s", exc)
                return None
            if difference < float(entry["threshold"]):
                warning = {
                    "layer": layer_num,
                    "total_layers": total_layers,
                    "difference": round(difference, 2),
                    "printer": printer_name,
                    "message": "Kaum Veränderung zwischen den Schichten – Bauteil prüfen.",
                }
                self._warning[printer_id] = warning
                logger.warning("[Bauteil-Wächter] %s", warning["message"])
                return warning
            self._warning[printer_id] = None
            return None


part_watcher = PartWatcher()

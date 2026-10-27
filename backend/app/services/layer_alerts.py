"""Schicht-Hinweise: bei einer Zielschicht pausieren (Port aus dem Bambu-Monitor).

Der Bambu-Monitor konnte pro Auftrag eine Schicht setzen, an der der Druck
anhält (z.B. zum Einlegen von Magneten). Hier als PrintLab-Erweiterung pro
Drucker, konfiguriert in ``data/layer_alerts.json``.

Der Dienst läuft im vorhandenen Layer-Callback mit und pausiert höchstens
einmal je Druck. Ein neuer Druck wird an einer fallenden Schichtnummer oder
einer anderen Auftragskennung erkannt; dann ist die Pause wieder scharf.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "layer_alerts.json"
DEFAULT = {"enabled": False, "layer": 0}


class LayerAlerts:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._config = self._load()
        self._last_layer: dict[int, int] = {}
        self._print_key: dict[int, str] = {}
        self._triggered: dict[int, bool] = {}

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
            logger.warning("[Schicht-Hinweis] Konfiguration nicht speicherbar: %s", exc)

    def _entry(self, printer_id: int) -> dict[str, Any]:
        entry = self._config.get(str(printer_id))
        if not isinstance(entry, dict):
            entry = dict(DEFAULT)
            self._config[str(printer_id)] = entry
        entry.setdefault("enabled", False)
        entry.setdefault("layer", 0)
        return entry

    def status(self, printer_id: int) -> dict[str, Any]:
        with self._lock:
            entry = dict(self._entry(printer_id))
            return {
                **entry,
                "triggered": bool(self._triggered.get(printer_id, False)),
                "last_layer": int(self._last_layer.get(printer_id, 0)),
            }

    def configure(self, printer_id: int, enabled: bool, layer: int) -> dict[str, Any]:
        with self._lock:
            entry = self._entry(printer_id)
            entry["enabled"] = bool(enabled)
            entry["layer"] = max(0, min(100000, int(layer)))
            self._save()
            self._triggered[printer_id] = False
            return self.status(printer_id)

    @staticmethod
    def _key(state: Any) -> str:
        return str(
            getattr(state, "subtask_id", "")
            or getattr(state, "gcode_file", "")
            or getattr(state, "subtask_name", "")
            or ""
        )

    async def observe(self, printer_id: int, layer_num: int, client: Any) -> bool:
        """Prüft die Zielschicht und pausiert einmal. True, wenn pausiert wurde."""
        if client is None:
            return False
        state = getattr(client, "state", None)
        key = self._key(state)
        with self._lock:
            entry = self._entry(printer_id)
            if not entry.get("enabled"):
                return False
            target = int(entry.get("layer") or 0)
            if target <= 0:
                return False
            last = self._last_layer.get(printer_id, 0)
            old_key = self._print_key.get(printer_id, "")
            if (key and old_key and key != old_key) or layer_num < last:
                self._triggered[printer_id] = False
            if key:
                self._print_key[printer_id] = key
            self._last_layer[printer_id] = layer_num
            if self._triggered.get(printer_id):
                return False
            if layer_num < target:
                return False
            if str(getattr(state, "state", "")) != "RUNNING":
                return False
            self._triggered[printer_id] = True
        try:
            ok = bool(client.pause_print())
        except Exception as exc:  # noqa: BLE001 - Callback darf nicht abbrechen
            logger.warning("[Schicht-Hinweis] Pause fehlgeschlagen: %s", exc)
            return False
        if ok:
            logger.info("[Schicht-Hinweis] Drucker %s bei Schicht %s pausiert", printer_id, layer_num)
        return ok


layer_alerts = LayerAlerts()

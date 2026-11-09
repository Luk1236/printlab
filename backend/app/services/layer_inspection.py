"""Dienst zur kontinuierlichen Schichtanalyse während des Drucks.

Prüft in konfigurierbaren Schichtabständen (z. B. alle 2–5 Schichten)
das Kamerabild auf Filament-Salat, abgelöste Bauteile und Druckfehler.
Bei wiederholtem Fehlerverdacht wird der Druck automatisch pausiert
und eine Push-Benachrichtigung mit annotiertem Foto versendet.

Konfiguration liegt in ``data/layer_inspection.json``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.services.notification_service import notification_service
from backend.app.services.spaghetti_detector import spaghetti_detector
from backend.app.utils import failure_images

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "layer_inspection.json"

DEFAULT_PRINTER_CONFIG: dict[str, Any] = {
    "enabled": False,
    "layer_interval": 2,  # alle N Schichten prüfen
    "sensitivity_threshold": 0.65,  # Schwellwert (0.4 bis 0.9)
    "consecutive_alerts": 2,  # Anzahl aufeinanderfolgender Fehler vor Not-Pause
    "auto_pause": True,  # Druck bei bestätigtem Fehler automatisch pausieren
    "save_debug_snapshots": True,  # In Fehlerbild-Sammlung ablegen
    "min_layer": 3,  # Schichten 1-2 auslassen (macht first_layer_inspector)
}

MAX_HISTORY_ENTRIES = 50


class LayerInspectionService:
    """Verwaltet kontinuierliche Schichtprüfungen und automatische Notpausen."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._config: dict[str, Any] = self._load()
        self._consecutive_counts: dict[int, int] = {}
        self._last_layer: dict[int, int] = {}
        self._print_keys: dict[int, str] = {}
        self._history: dict[int, list[dict[str, Any]]] = {}

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
            logger.warning("[Schichtanalyse] Konfiguration nicht speicherbar: %s", exc)

    def get_config(self, printer_id: int) -> dict[str, Any]:
        """Liefert die Konfiguration für einen bestimmten Drucker (mit Standard-Fallback)."""
        with self._lock:
            printers = self._config.setdefault("printers", {})
            entry = printers.get(str(printer_id))
            if not isinstance(entry, dict):
                entry = dict(DEFAULT_PRINTER_CONFIG)
                printers[str(printer_id)] = entry

            merged = dict(DEFAULT_PRINTER_CONFIG)
            merged.update(entry)
            return merged

    def configure(self, printer_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Aktualisiert die Einstellungen eines Druckers."""
        with self._lock:
            cfg = self.get_config(printer_id)
            if "enabled" in updates:
                cfg["enabled"] = bool(updates["enabled"])
            if "layer_interval" in updates:
                cfg["layer_interval"] = max(1, min(50, int(updates["layer_interval"])))
            if "sensitivity_threshold" in updates:
                cfg["sensitivity_threshold"] = max(0.30, min(0.95, float(updates["sensitivity_threshold"])))
            if "consecutive_alerts" in updates:
                cfg["consecutive_alerts"] = max(1, min(10, int(updates["consecutive_alerts"])))
            if "auto_pause" in updates:
                cfg["auto_pause"] = bool(updates["auto_pause"])
            if "save_debug_snapshots" in updates:
                cfg["save_debug_snapshots"] = bool(updates["save_debug_snapshots"])
            if "min_layer" in updates:
                cfg["min_layer"] = max(1, min(50, int(updates["min_layer"])))

            self._config.setdefault("printers", {})[str(printer_id)] = cfg
            self._save()
            return cfg

    def reset(self, printer_id: int) -> None:
        """Setzt den laufenden Fehlerzähler zurück (z. B. nach Druckstart)."""
        with self._lock:
            self._consecutive_counts[printer_id] = 0
            self._last_layer[printer_id] = 0

    def get_status(self, printer_id: int) -> dict[str, Any]:
        """Liefert Konfiguration, aktuellen Fehlerzähler und Historie."""
        with self._lock:
            cfg = self.get_config(printer_id)
            history = self._history.get(printer_id, [])
            return {
                "printer_id": printer_id,
                "config": cfg,
                "consecutive_alerts": self._consecutive_counts.get(printer_id, 0),
                "last_layer": self._last_layer.get(printer_id, 0),
                "history": history[-15:],  # Letzte 15 Einträge für UI
            }

    def should_inspect(self, printer_id: int, layer_num: int) -> bool:
        """Prüft, ob für diese Schicht eine Analyse fällig ist."""
        cfg = self.get_config(printer_id)
        if not cfg["enabled"]:
            return False
        if layer_num < cfg["min_layer"]:
            return False
        interval = max(1, cfg["layer_interval"])
        return (layer_num % interval) == 0

    async def observe(
        self,
        printer_id: int,
        printer_name: str,
        layer_num: int,
        image_data: bytes,
        client: Any = None,
        db: Any = None,
        task_name: str = "",
        is_warped: bool = False,
    ) -> dict[str, Any] | None:
        """Führt die Schichtanalyse durch, steuert Not-Pausen und Notifikationen."""
        if not self.should_inspect(printer_id, layer_num):
            return None

        cfg = self.get_config(printer_id)
        threshold = cfg["sensitivity_threshold"]

        # CPU-intensive Analyse im Thread-Pool ausführen
        result = await asyncio.to_thread(
            spaghetti_detector.analyze_image,
            image_bytes=image_data,
            threshold=threshold,
            is_warped=is_warped,
        )

        with self._lock:
            # Neuer Druckjob: Zähler automatisch auf Null setzen
            if task_name and self._print_keys.get(printer_id) != task_name:
                self._print_keys[printer_id] = task_name
                self._consecutive_counts[printer_id] = 0

            self._last_layer[printer_id] = layer_num
            consecutive = self._consecutive_counts.get(printer_id, 0)
            if result.is_failure:
                consecutive += 1
            else:
                consecutive = max(0, consecutive - 1)
            self._consecutive_counts[printer_id] = consecutive

        action_taken = "ok"
        saved_filename: str | None = None

        if result.is_failure:
            trigger_count = cfg["consecutive_alerts"]
            if consecutive >= trigger_count:
                # Kritischer Fehler bestätigt!
                action_taken = "alert"
                if cfg["auto_pause"] and client and hasattr(client, "state"):
                    state_val = getattr(client.state, "state", None)
                    if state_val == "RUNNING" and hasattr(client, "pause_print"):
                        try:
                            await client.pause_print()
                            action_taken = "paused"
                            logger.warning(
                                "[Schichtanalyse] Spaghetti-Fehldruck an Drucker %s bestätigt (%dx in Folge) — Druck automatisch pausiert!",
                                printer_id,
                                consecutive,
                            )
                        except Exception as p_exc:  # noqa: BLE001
                            logger.error("[Schichtanalyse] Automatisches Pausieren fehlgeschlagen: %s", p_exc)

                # Foto in Fehlerbild-Sammlung ablegen
                if cfg["save_debug_snapshots"] and result.debug_image:
                    try:
                        saved_filename = await asyncio.to_thread(
                            failure_images.save_failure_image,
                            result.debug_image,
                            "spaghetti_detector",
                        )
                    except Exception as s_exc:  # noqa: BLE001
                        logger.warning("[Schichtanalyse] Konnte Fehlerbild nicht ablegen: %s", s_exc)

                # Benachrichtigung versenden
                if db:
                    try:
                        await notification_service.on_ai_failure_detection(
                            printer_id=printer_id,
                            printer_name=printer_name,
                            task_name=task_name or f"Schicht {layer_num}",
                            confidence=result.confidence,
                            action=f"spaghetti_{action_taken}",
                            db=db,
                            image_data=result.debug_image or image_data,
                        )
                    except Exception as n_exc:  # noqa: BLE001
                        logger.warning("[Schichtanalyse] Benachrichtigung fehlgeschlagen: %s", n_exc)
            else:
                action_taken = f"warning ({consecutive}/{trigger_count})"

        # Verlaufseintrag festhalten
        history_item = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer_num": layer_num,
            "chaos_score": result.chaos_score,
            "orientation_entropy": result.orientation_entropy,
            "edge_density": result.edge_density,
            "is_failure": result.is_failure,
            "consecutive_count": consecutive,
            "action_taken": action_taken,
            "saved_filename": saved_filename,
        }

        with self._lock:
            hist = self._history.setdefault(printer_id, [])
            hist.append(history_item)
            if len(hist) > MAX_HISTORY_ENTRIES:
                hist.pop(0)

        return {
            "analysis": result.to_dict(),
            "history_item": history_item,
        }

    async def test_frame(
        self,
        printer_id: int,
        image_data: bytes,
        is_warped: bool = False,
    ) -> dict[str, Any]:
        """Führt sofortige Test-Analyse für die UI durch (inkl. Base64-Vorschau)."""
        cfg = self.get_config(printer_id)
        result = await asyncio.to_thread(
            spaghetti_detector.analyze_image,
            image_bytes=image_data,
            threshold=cfg["sensitivity_threshold"],
            is_warped=is_warped,
        )
        return {
            "printer_id": printer_id,
            "config": cfg,
            "result": result.to_dict(include_image_b64=True),
        }


# Globale Instanz
layer_inspection_service = LayerInspectionService()

"""Laufende Fehlerüberwachung mit dem lokalen Bildmodell (Ersatz für Obico, rein lokal).

Während ein Druck läuft, holt PrintLab im eingestellten Abstand ein Kamerabild,
lässt es vom lokalen Vision-Modell einem Fehlerbild zuordnen und handelt erst,
wenn dasselbe Fehlerbild mehrfach hintereinander erkannt wurde. Dann wird das
Bild in der Fehlerbild-Sammlung abgelegt, ein Treffer für die Fehlerhilfe
festgehalten und eine Meldung geschickt; optional pausiert PrintLab den Druck.

Standardmäßig aus. Die Analyse ist deutlich langsamer als Obicos ML-API
(Minuten pro Bild), deshalb ist der Abstand großzügig und die Bestätigung über
mehrere Bilder vorgeschaltet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.services import ai_error_scan, assistant_config, error_patterns
from backend.app.utils import failure_images

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "local_ai_watch.json"
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "interval_seconds": 600,
    "min_confidence": 60,
    "min_consecutive": 2,
    "action": "notify",  # notify | pause
    "cooldown_minutes": 30,
    "printers": [],  # leer = alle aktiven Drucker
    "frames": 2,  # Bilder je Prüfung (Mehrheitsentscheid)
    "frame_gap_seconds": 2,
    "thresholds": {},  # Sicherheit je Fehlerbild, überschreibt min_confidence
}
ACTIONS = ("notify", "pause")
MIN_INTERVAL = 120

STATE: dict[str, Any] = {"started": None, "last_run": None, "last_error": None}
_printer_state: dict[int, dict[str, Any]] = {}
_run_lock = asyncio.Lock()
_config_lock = threading.RLock()


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if key in DEFAULTS:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    with _config_lock:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        config = _merge(DEFAULTS, data if isinstance(data, dict) else {})
        config["printers"] = [int(p) for p in config.get("printers") or []]
        config["thresholds"] = {
            str(key): int(value)
            for key, value in (config.get("thresholds") or {}).items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        return config


def save_config(update: dict[str, Any]) -> dict[str, Any]:
    with _config_lock:
        config = load_config()
        for key, value in update.items():
            if key not in DEFAULTS:
                continue
            if key == "enabled":
                config[key] = bool(value)
            elif key == "action":
                if value not in ACTIONS:
                    raise ValueError("action muss 'notify' oder 'pause' sein")
                config[key] = value
            elif key == "printers":
                config[key] = sorted({int(p) for p in value or []})
            elif key == "thresholds":
                allowed = {pattern["id"] for pattern in error_patterns.PATTERNS}
                cleaned: dict[str, int] = {}
                for pattern_id, threshold in (value or {}).items():
                    if pattern_id not in allowed:
                        continue
                    value_int = int(threshold)
                    if 0 <= value_int <= 100:
                        cleaned[str(pattern_id)] = value_int
                config[key] = cleaned
            else:
                value = int(value)
                config[key] = value
        config["interval_seconds"] = max(MIN_INTERVAL, int(config["interval_seconds"]))
        config["min_confidence"] = max(0, min(100, int(config["min_confidence"])))
        config["min_consecutive"] = max(1, min(10, int(config["min_consecutive"])))
        config["cooldown_minutes"] = max(0, min(1440, int(config["cooldown_minutes"])))
        config["frames"] = max(1, min(3, int(config["frames"])))
        config["frame_gap_seconds"] = max(1, min(15, int(config["frame_gap_seconds"])))
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
        return config


def _reset(printer_id: int, key: str) -> dict[str, Any]:
    state = {
        "key": key,
        "pattern": None,
        "count": 0,
        "last_checked": None,
        "last_confidence": None,
        "last_error": None,
        "last_action": None,
    }
    _printer_state[printer_id] = state
    return state


def status() -> dict[str, Any]:
    try:
        from backend.app.services.printer_manager import printer_manager

        printers = [
            {
                "id": pid,
                "name": (printer_manager.get_printer(pid).name if printer_manager.get_printer(pid) else f"#{pid}"),
            }
            for pid in _printer_state
        ]
    except Exception:  # noqa: BLE001 - Statusanzeige darf nicht scheitern
        printers = []
    by_id = {entry["id"]: entry for entry in printers}
    for pid, state in _printer_state.items():
        by_id.setdefault(pid, {"id": pid, "name": f"#{pid}"}).update(
            {
                "pattern": state.get("pattern"),
                "count": state.get("count"),
                "last_checked": state.get("last_checked"),
                "last_confidence": state.get("last_confidence"),
                "last_error": state.get("last_error"),
                "last_action": state.get("last_action"),
            }
        )
    return {"config": load_config(), "state": dict(STATE), "printers": list(by_id.values())}


def _cooldown_over(state: dict[str, Any], cooldown_minutes: int, now: datetime) -> bool:
    last = state.get("last_action")
    if not last:
        return True
    try:
        moment = datetime.fromisoformat(last)
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now - moment).total_seconds() >= cooldown_minutes * 60


async def _pause(printer_id: int) -> bool:
    from backend.app.services.printer_manager import printer_manager

    client = printer_manager.get_client(printer_id)
    if not client:
        return False
    try:
        return bool(client.pause_print())
    except Exception:  # noqa: BLE001 - Pause ist eine Zugabe, kein Grund abzubrechen
        logger.warning("Local AI watch: pause failed for printer %s", printer_id, exc_info=True)
        return False


async def check_once(only_printer: int | None = None) -> list[dict[str, Any]]:
    """Eine Runde: alle laufenden Drucker prüfen; Ergebnisse für die Oberfläche."""
    from backend.app.services.printer_manager import printer_manager

    config = load_config()
    assistant_cfg = assistant_config.read(settings.base_dir)
    if not str(assistant_cfg.get("vision_model") or assistant_cfg.get("model") or "").strip():
        raise ai_error_scan.AiScanError("Für die laufende Überwachung ist kein Bildmodell eingestellt.")
    allowed = set(config["printers"]) or None
    results: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    async with _run_lock:
        for printer_id, printer_status in list(printer_manager.get_all_statuses().items()):
            if only_printer is not None and printer_id != only_printer:
                continue
            if allowed is not None and printer_id not in allowed:
                continue
            if getattr(printer_status, "state", None) != "RUNNING" or not printer_manager.is_connected(printer_id):
                _printer_state.pop(printer_id, None)
                continue
            key = getattr(printer_status, "gcode_file", None) or getattr(printer_status, "subtask_name", None) or "?"
            state = _printer_state.get(printer_id)
            if state is None or state.get("key") != key:
                state = _reset(printer_id, key)
            try:
                from backend.app.services.obico_detection import capture_frame_for_printer

                frames: list[bytes] = []
                for index in range(int(config["frames"])):
                    frame = await capture_frame_for_printer(printer_id)
                    if frame:
                        frames.append(frame)
                    if index + 1 < int(config["frames"]):
                        await asyncio.sleep(int(config["frame_gap_seconds"]))
            except Exception as exc:  # noqa: BLE001
                state["last_error"] = str(exc)[:200]
                results.append({"printer_id": printer_id, "error": state["last_error"]})
                continue
            if not frames:
                state["last_error"] = "Kein Kamerabild erhalten."
                results.append({"printer_id": printer_id, "error": state["last_error"]})
                continue
            state["last_checked"] = now.isoformat()
            state["last_error"] = None
            attempts: list[tuple[bytes, dict[str, Any]]] = []
            last_exc: Exception | None = None
            for frame in frames:
                try:
                    attempts.append((frame, await ai_error_scan.classify(frame, assistant_cfg)))
                except Exception as exc:  # noqa: BLE001 - ein Bild darf die Runde nicht beenden
                    last_exc = exc
            if not attempts:
                state["last_error"] = str(last_exc or "Die Bildanalyse ist fehlgeschlagen.")[:200]
                results.append({"printer_id": printer_id, "error": state["last_error"]})
                continue

            # Nur Treffer über der Schwelle des jeweiligen Fehlerbilds zählen;
            # danach entscheidet die Mehrheit der aufgenommenen Bilder.
            qualified = [
                (frame, result)
                for frame, result in attempts
                if result.get("pattern_id")
                and float(result.get("confidence", 0)) * 100
                >= int(config["thresholds"].get(result["pattern_id"], config["min_confidence"]))
            ]
            chosen: tuple[bytes, dict[str, Any]] | None = None
            if qualified:
                from collections import Counter

                counts = Counter(result["pattern_id"] for _frame, result in qualified)
                top_pattern, top_count = counts.most_common(1)[0]
                if top_count * 2 > len(attempts):
                    chosen = max(
                        (pair for pair in qualified if pair[1]["pattern_id"] == top_pattern),
                        key=lambda pair: float(pair[1].get("confidence", 0)),
                    )
            display = chosen or max(attempts, key=lambda pair: float(pair[1].get("confidence", 0)))
            display_result = display[1]
            pattern_id = display_result.get("pattern_id")
            confidence = float(display_result.get("confidence", 0))
            state["last_confidence"] = confidence
            state["last_pattern"] = pattern_id
            entry = {
                "printer_id": printer_id,
                "pattern_id": pattern_id,
                "confidence": confidence,
                "reason": display_result.get("reason", ""),
                "action": None,
                "confirmed": chosen is not None,
            }
            if chosen is None:
                state["pattern"] = None
                state["count"] = 0
                results.append(entry)
                continue
            frame, result = chosen
            state["count"] = state["count"] + 1 if state.get("pattern") == pattern_id else 1
            state["pattern"] = pattern_id

            if state["count"] >= config["min_consecutive"] and _cooldown_over(state, config["cooldown_minutes"], now):
                image_name = None
                try:
                    image_name = await asyncio.to_thread(
                        failure_images.save_failure_image, frame, f"ai_watch_{pattern_id}"
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("Local AI watch: saving the failure image failed", exc_info=True)
                ai_error_scan.record(result, source="watch", printer_id=printer_id, image_name=image_name)
                await ai_error_scan.announce_finding(result, image_name)
                entry["action"] = "notify"
                if config["action"] == "pause" and await _pause(printer_id):
                    entry["action"] = "pause"
                state["last_action"] = now.isoformat()
                state["count"] = 0
            results.append(entry)
    return results


async def run() -> None:
    """Dauerschleife; liest Einstellungen in jedem Zyklus neu."""
    STATE["started"] = datetime.now(timezone.utc)
    await asyncio.sleep(180)
    while True:
        try:
            config = load_config()
            if config["enabled"]:
                await check_once()
                STATE["last_run"] = datetime.now(timezone.utc)
            STATE["last_error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Schleife darf nicht sterben
            logger.exception("Local AI watch failed")
            STATE["last_error"] = str(exc)[:200]
        await asyncio.sleep(max(MIN_INTERVAL, int(load_config()["interval_seconds"])))

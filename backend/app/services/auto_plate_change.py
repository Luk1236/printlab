"""Automatischer Plattenwechsel nach Druckende (Roadmap P2).

Nach einem erfolgreich beendeten Druck wartet dieser Dienst auf das Abkühlen
der Druckplatte, prüft die Tür (Endschalter muss „geschlossen“ melden) und
stößt den Plattenwechsel aus ``hardware_extension`` an. Schlägt ein Schritt
fehl oder läuft die Wartezeit ab, endet der Versuch mit Fehlerzustand; der
Hardware-Status meldet das Ergebnis und die Weboberfläche bekommt eine
WebSocket-Meldung. Der nächste Druck startet erst, wenn Bambuddys
Platte-frei-Gatter ohnehin bestätigt ist — der Wechsel ist also nie eine
Voraussetzung, sondern nur eine Automatik.

Konfiguration in ``data/hardware.json`` (unter dem Schlüssel
``auto_plate_change``; wird beim ersten Lesen mit den Standardwerten ergänzt):

.. code-block:: json

    {
      "auto_plate_change": {
          "enabled": false,           # nie ohne bewusstes Einschalten
          "cooldown_bed_temp": 45.0,  # °C; unter diesem Wert wird gewechselt
          "max_wait_seconds": 1800,   # Wartezeit auf die Abkühlung
          "poll_seconds": 10,         # Temperatur-Abfrageabstand
          "skip_if_offline": true
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = None  # spät gesetzt, siehe _set_config_path()
_LAST: dict[int, dict[str, Any]] = {}
_TASKS: dict[int, asyncio.Task] = {}

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "cooldown_bed_temp": 45.0,
    "max_wait_seconds": 1800,
    "poll_seconds": 10,
    "skip_if_offline": True,
}


def _set_config_path() -> Path:
    """Liefert den Pfad zu ``data/hardware.json`` (lazily, nach Settings-Import)."""
    from backend.app.services.hardware_extension import CONFIG_PATH

    return CONFIG_PATH


def _config_path() -> Path:
    return _set_config_path()


def _read_config(section_path: Path) -> dict[str, Any]:
    cfg: dict[str, Any] = dict(DEFAULTS)
    try:
        data = json.loads(section_path.read_text(encoding="utf-8"))
        section = data.get("auto_plate_change") if isinstance(data, dict) else None
        if isinstance(section, dict):
            cfg.update({k: section[k] for k in DEFAULTS if k in section})
    except (OSError, ValueError):
        pass
    return cfg


def read_config() -> dict[str, Any]:
    """Aktuelle Automatik-Konfiguration (mit Standardwerten)."""
    cfg = _read_config(_config_path())
    try:
        cfg["cooldown_bed_temp"] = float(cfg["cooldown_bed_temp"])
        cfg["max_wait_seconds"] = max(0, int(cfg["max_wait_seconds"]))
        cfg["poll_seconds"] = max(1, int(cfg["poll_seconds"]))
    except (TypeError, ValueError):
        cfg = dict(DEFAULTS)
    return cfg


def write_config(update: dict[str, Any]) -> dict[str, Any]:
    """Konfiguration abspeichern (nur bekannte Schlüssel, Werte typisiert)."""
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    section = data.get("auto_plate_change") if isinstance(data.get("auto_plate_change"), dict) else {}
    if "enabled" in update:
        section["enabled"] = bool(update["enabled"])
    for key in ("cooldown_bed_temp", "max_wait_seconds", "poll_seconds", "skip_if_offline"):
        if key in update:
            section[key] = update[key]
    data["auto_plate_change"] = section
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return read_config()


def last_run(printer_id: int) -> dict[str, Any] | None:
    """Letzter Versuch pro Drucker (für Status und UI)."""
    return _LAST.get(printer_id)


def _broadcast(payload: dict[str, Any]) -> None:
    try:
        from backend.app.main import ws_manager

        asyncio.get_running_loop().create_task(ws_manager.broadcast(payload))
    except Exception as exc:  #pragma: no cover - Broadcast ist optional
        logger.debug("[AutoPlateChange] Broadcast fehlgeschlagen: %s", exc)


async def _run_change(printer_id: int, job_name: str, cfg: dict[str, Any]) -> None:
    from backend.app.services.hardware_extension import get_hardware
    from backend.app.services.printer_manager import printer_manager

    async def record(ok: bool, message: str) -> None:
        entry = {
            "printer_id": printer_id,
            "job": job_name,
            "ok": ok,
            "message": message,
        }
        _LAST[printer_id] = entry
        _broadcast({"type": "auto_plate_change", **entry})
        logger.info("[AutoPlateChange] Drucker %s: %s%s", printer_id, "OK" if ok else "FEHLER", f" — {message}")

    max_wait = max(0, int(cfg["max_wait_seconds"]))
    poll = max(1, int(cfg["poll_seconds"]))
    threshold = float(cfg["cooldown_bed_temp"])

    waited = 0
    while True:
        state = printer_manager.get_status(printer_id)
        if state is None or not getattr(state, "connected", False):
            if bool(cfg["skip_if_offline"]):
                await record(False, "Drucker getrennt — Automatik übersprungen.")
                return
            break
        bed = None
        temps = getattr(state, "temperatures", None)
        if isinstance(temps, dict):
            for key in ("bed_temp", "bedTemp", "bed"):
                if isinstance(temps.get(key), (int, float)):
                    bed = float(temps[key])
                    break
        if bed is None or bed <= threshold:
            break
        if waited >= max_wait:
            await record(
                False,
                f"Druckplatte bleibt über {max_wait}s über {threshold}°C (aktuell {bed}°C) — kein Wechsel.",
            )
            return
        await asyncio.sleep(poll)
        waited += poll

    hw = get_hardware()
    hw_status = hw.status()
    if hw_status.get("door") not in ("closed", "open") or hw_status.get("door") == "open":
        await record(False, "Tür ist offen bzw. unbestätigt — Plattenwechsel nicht angetreten.")
        return
    if hw_status.get("busy"):
        await record(False, "Hardware-Vorgang läuft bereits — kein automatischer Wechsel.")
        return

    ok, message = await asyncio.to_thread(hw.change_plate, job_name)
    await record(bool(ok), message)


def schedule(printer_id: int, job_name: str = "") -> bool:
    """Automatik nach Druckende antreten (nur wenn eingeschaltet)."""
    cfg = read_config()
    if not cfg.get("enabled"):
        return False
    old = _TASKS.get(printer_id)
    if old and not old.done():
        old.cancel()
    _TASKS[printer_id] = asyncio.create_task(_run_change(printer_id, job_name, cfg))
    return True
"""Automatischer Plattenwechsel nach Druckende (Roadmap P2).

Nach einem erfolgreich beendeten Druck wartet dieser Dienst auf das Abkühlen
der Druckplatte, prüft die Tür (Endschalter muss „geschlossen“ melden) und
stößt den Plattenwechsel aus ``hardware_extension`` an. Schlägt ein Schritt
fehl oder läuft die Wartezeit ab, endet der Versuch mit Fehlerzustand; der
Hardware-Status meldet das Ergebnis und die Weboberfläche bekommt eine
WebSocket-Meldung. Der nächste Druck startet erst, wenn PrintLabs
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
    "only_with_queue": False,
    "low_supply_warning": 1,  # Warnung, wenn nach dem Wechsel höchstens so viele frische Platten bleiben
    "notify": True,  # Fehler und Magazin-Warnungen über die Benachrichtigungskanäle melden
    # Nach erfolgreichem Wechsel „Platte frei“ selbst bestätigen, wenn die Kamera ein leeres Bett sieht.
    # Standard aus: PrintLab fragt sonst nach, bevor der nächste Auftrag startet.
    "auto_confirm_plate_clear": False,
    "plate_clear_min_confidence": 0.6,  # darunter (oder ohne Referenz/Kamerabild) wird NICHT bestätigt
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
        cfg["low_supply_warning"] = max(0, int(cfg["low_supply_warning"]))
        cfg["plate_clear_min_confidence"] = min(1.0, max(0.0, float(cfg["plate_clear_min_confidence"])))
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
    for key in ("skip_if_offline", "only_with_queue", "notify", "auto_confirm_plate_clear"):
        if key in update:
            section[key] = bool(update[key])
    for key, kind in (
        ("cooldown_bed_temp", float),
        ("max_wait_seconds", int),
        ("poll_seconds", int),
        ("low_supply_warning", int),
        ("plate_clear_min_confidence", float),
    ):
        if key in update:
            # Ungültige Werte nicht speichern: read_config() würde sonst auf ALLE Standardwerte
            # zurückfallen und damit auch die Automatik stillschweigend ausschalten.
            try:
                section[key] = kind(update[key])
            except (TypeError, ValueError):
                continue
    data["auto_plate_change"] = section
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return read_config()


def last_run(printer_id: int) -> dict[str, Any] | None:
    """Letzter Versuch pro Drucker (für Status und UI); nach einem Neustart aus dem Audit-Log."""
    if printer_id in _LAST:
        return _LAST[printer_id]
    try:
        from backend.app.services import audit_log

        for entry in audit_log.entries(limit=200, printer_id=printer_id):
            if entry.get("action") == "auto_plate_change":
                details = entry.get("details") or {}
                restored = {
                    "printer_id": printer_id,
                    "job": details.get("job", ""),
                    "ok": bool(entry.get("ok")),
                    "message": entry.get("message", ""),
                }
                if details.get("warning"):
                    restored["warning"] = details["warning"]
                return restored
    except Exception as exc:  # pragma: no cover - Audit-Log ist optional
        logger.debug("[AutoPlateChange] Audit-Log nicht lesbar: %s", exc)
    return None


def _audit(entry: dict[str, Any]) -> None:
    """Ergebnis ins Audit-Log schreiben, damit es einen Neustart übersteht."""
    try:
        from backend.app.services import audit_log

        details = {"job": entry.get("job", "")}
        if entry.get("warning"):
            details["warning"] = entry["warning"]
        audit_log.record("auto_plate_change", bool(entry["ok"]), entry["message"], entry["printer_id"], None, details)
    except Exception as exc:  # pragma: no cover - Protokoll darf den Ablauf nie stören
        logger.debug("[AutoPlateChange] Audit-Log fehlgeschlagen: %s", exc)


async def _notify(printer_id: int, entry: dict[str, Any]) -> None:
    """Fehler und Magazin-Warnungen an die Kanäle senden, die „Nachrichten verbundener Apps“ erlauben."""
    try:
        from backend.app.core.database import async_session
        from backend.app.services.notification_service import notification_service

        title = "Plattenwechsel: Fehler" if not entry["ok"] else "Plattenwechsel: Magazin"
        text = entry["message"] if not entry["ok"] else entry.get("warning", "")
        if entry["ok"] is False and entry.get("warning"):
            text = f"{text}\n{entry['warning']}"
        async with async_session() as db:
            await notification_service.on_app_message(db, sender="PrintLab", title=title, message=text)
    except Exception as exc:  # Benachrichtigung ist optional
        logger.debug("[AutoPlateChange] Benachrichtigung fehlgeschlagen für Drucker %s: %s", printer_id, exc)


def _broadcast(payload: dict[str, Any]) -> None:
    try:
        from backend.app.main import ws_manager

        asyncio.get_running_loop().create_task(ws_manager.broadcast(payload))
    except Exception as exc:  #pragma: no cover - Broadcast ist optional
        logger.debug("[AutoPlateChange] Broadcast fehlgeschlagen: %s", exc)


async def _run_change(printer_id: int, job_name: str, cfg: dict[str, Any]) -> None:
    from backend.app.services.hardware_extension import get_hardware
    from backend.app.services.printer_manager import printer_manager

    async def record(ok: bool, message: str, warning: str | None = None) -> None:
        entry = {
            "printer_id": printer_id,
            "job": job_name,
            "ok": ok,
            "message": message,
        }
        if warning:
            entry["warning"] = warning
        _LAST[printer_id] = entry
        _broadcast({"type": "auto_plate_change", **entry})
        logger.info("[AutoPlateChange] Drucker %s: %s%s", printer_id, "OK" if ok else "FEHLER", f" — {message}")
        _audit(entry)
        if cfg.get("notify", True) and (not ok or warning):
            await _notify(printer_id, entry)

    try:
        await _wait_and_change(printer_id, job_name, cfg, record, printer_manager, get_hardware)
    except asyncio.CancelledError:
        # Abbruch während der Abkühlwartezeit (Not-Halt, manueller Abbruch, neuer Auftrag).
        # Ein bereits laufender Hardware-Schritt (Thread) lässt sich nur per Not-Halt stoppen.
        await record(False, "Automatischer Plattenwechsel abgebrochen.")
        raise


async def _wait_and_change(printer_id, job_name, cfg, record, printer_manager, get_hardware) -> None:
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
        if getattr(state, "state", None) in ("RUNNING", "PREPARE", "PAUSE"):
            await record(False, "Neuer Druck hat begonnen — Plattenwechsel abgebrochen.")
            return
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

    hw = get_hardware(printer_id)
    hw_status = hw.status()
    if hw_status.get("door") not in ("closed", "open") or hw_status.get("door") == "open":
        await record(False, "Tür ist offen bzw. unbestätigt — Plattenwechsel nicht angetreten.")
        return
    if hw_status.get("busy"):
        await record(False, "Hardware-Vorgang läuft bereits — kein automatischer Wechsel.")
        return

    ok, message = await asyncio.to_thread(hw.change_plate, job_name)
    warning = _low_supply_warning(hw.status(), cfg) if ok else None
    if ok and cfg.get("auto_confirm_plate_clear"):
        confirmed, note = await _confirm_plate_clear(printer_id, float(cfg["plate_clear_min_confidence"]))
        if confirmed:
            message = f"{message} {note}"
        else:
            warning = f"{warning} {note}" if warning else note
    await record(bool(ok), message, warning)


async def _load_printer(printer_id: int):
    from sqlalchemy import select

    from backend.app.core.database import async_session
    from backend.app.models.printer import Printer

    async with async_session() as db:
        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        return result.scalar_one_or_none()


async def _confirm_plate_clear(printer_id: int, min_confidence: float) -> tuple[bool, str]:
    """„Platte frei“ nur bestätigen, wenn die Kamera sicher ein leeres Bett erkennt (sonst bleibt die Sperre).

    Fail-closed: kein Drucker, keine Referenz, kein Kamerabild, niedrige Sicherheit oder jeder Fehler
    führen dazu, dass die Bestätigung von Hand erfolgen muss.
    """
    manual = "Platte-frei bitte von Hand bestätigen."
    try:
        from backend.app.services.plate_detection import check_plate_empty
        from backend.app.services.printer_manager import printer_manager

        if not printer_manager.is_awaiting_plate_clear(printer_id):
            return True, "Platte-frei war nicht angefordert."
        printer = await _load_printer(printer_id)
        if printer is None:
            return False, f"Drucker nicht gefunden. {manual}"
        roi = None
        if all(getattr(printer, f"plate_detection_roi_{k}", None) is not None for k in ("x", "y", "w", "h")):
            roi = tuple(getattr(printer, f"plate_detection_roi_{k}") for k in ("x", "y", "w", "h"))
        result = await check_plate_empty(
            printer_id=printer_id,
            ip_address=printer.ip_address,
            access_code=printer.access_code,
            model=printer.model,
            include_debug_image=False,
            external_camera_url=printer.external_camera_url,
            external_camera_type=printer.external_camera_type,
            use_external=printer.external_camera_enabled,
            roi=roi,
            external_camera_snapshot_url=printer.external_camera_snapshot_url,
        )
        if result.needs_calibration:
            return False, f"Keine Referenz für die Leerbett-Prüfung. {manual}"
        if not result.is_empty:
            return False, f"Kamera sieht Objekte auf der Platte. {manual}"
        if result.confidence < min_confidence:
            return False, f"Leerbett-Prüfung unsicher ({result.confidence:.0%}). {manual}"
        printer_manager.set_awaiting_plate_clear(printer_id, False)
        return True, f"Platte frei automatisch bestätigt (Kamera, {result.confidence:.0%})."
    except Exception as exc:
        logger.warning("[AutoPlateChange] Platte-frei-Prüfung fehlgeschlagen für Drucker %s: %s", printer_id, exc)
        return False, f"Leerbett-Prüfung nicht möglich. {manual}"


def _low_supply_warning(hw_status: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    """Warntext, wenn nach dem Wechsel kaum noch frische Platten oder freie Ablagefächer bleiben."""
    limit = int(cfg.get("low_supply_warning", 0))
    supply = hw_status.get("supply_ready")
    storage = hw_status.get("storage_empty")
    parts: list[str] = []
    if isinstance(supply, int) and supply <= limit:
        parts.append("keine frische Platte mehr" if supply == 0 else f"nur noch {supply} frische Platte(n)")
    if isinstance(storage, int) and storage <= limit:
        parts.append("kein freies Ablagefach mehr" if storage == 0 else f"nur noch {storage} freies Ablagefach/-fächer")
    if not parts:
        return None
    return "Magazin: " + ", ".join(parts) + " — bitte auffüllen bzw. leeren."


def cancel(printer_id: int | None = None, reason: str = "") -> int:
    """Wartende Automatik abbrechen (``None`` = alle Drucker); gibt die Zahl abgebrochener Aufträge zurück.

    Greift während der Abkühlwartezeit. Ein schon laufender Hardware-Schritt
    läuft in einem Thread weiter und wird nur durch den Not-Halt gestoppt.
    """
    cancelled = 0
    for pid, task in list(_TASKS.items()):
        if printer_id is not None and pid != printer_id:
            continue
        if not task.done():
            task.cancel()
            cancelled += 1
            logger.info("[AutoPlateChange] Drucker %s abgebrochen%s", pid, f" ({reason})" if reason else "")
    return cancelled


def schedule(printer_id: int, job_name: str = "") -> bool:
    """Automatik nach Druckende antreten (nur wenn eingeschaltet)."""
    cfg = read_config()
    if not cfg.get("enabled"):
        return False
    if cfg.get("only_with_queue"):
        pending = _has_pending_queue_item(printer_id)
        if pending is False:
            _note_no_queue(printer_id)
            return False
    old = _TASKS.get(printer_id)
    if old and not old.done():
        old.cancel()
    _TASKS[printer_id] = asyncio.create_task(_run_change(printer_id, job_name, cfg))
    return True


def _has_pending_queue_item(printer_id: int) -> bool | None:
    """True/False, wenn die DB nicht erreichbar ist None (dann weiterlaufen)."""
    try:
        import sqlite3

        from backend.app.models.print_queue import PrintQueueItem
        from backend.app.services.hardware_extension import settings as app_settings

        if not app_settings.database_url.startswith("sqlite"):
            return None  # PostgreSQL & Co.: sqlite3.connect() würde sonst eine Fantasie-Datei anlegen
        db_path = app_settings.database_url.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
        db_file = db_path or str(app_settings.base_dir / "printlab.db")
        con = sqlite3.connect(db_file)
        try:
            row = con.execute(
                f"SELECT 1 FROM {PrintQueueItem.__tablename__} WHERE printer_id=? AND status='pending' LIMIT 1",
                (printer_id,),
            ).fetchone()
        finally:
            con.close()
        return row is not None
    except Exception as exc:
        logger.debug("[AutoPlateChange] Warteschlangen-Prüfung fehlgeschlagen: %s", exc)
        return None


def _note_no_queue(printer_id: int) -> None:
    _LAST[printer_id] = {
        "printer_id": printer_id,
        "job": "",
        "ok": True,
        "message": "Kein weiterer Auftrag wartet — Wechsel übersprungen (only_with_queue).",
    }
    _audit(_LAST[printer_id])

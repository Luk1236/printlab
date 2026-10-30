"""Automatische Gegenmaßnahmen am laufenden Druck (Fehlerhilfe).

Zwei Regeln, die sich aus den Daten sicher ableiten lassen — beide nur bei
Modellen mit echter Bauraumtemperatur und nur nach ausdrücklicher Freigabe je
Drucker:

- ``chamber_hot``: PLA/PETG/TPU bei Bauraum über der Schwelle → Kammer- und
  Zusatzlüfter aufdrehen, Bettziel leicht absenken (Heat-Creep-Vorsorge).
- ``chamber_cold``: ABS/ASA/PC/PA bei Bauraum unter der Schwelle → lüftende
  Lüfter aus (Warping-/Riss-Vorsorge).

Standardmäßig ist **alles aus** und der Trockenlauf **an**: PrintLab schreibt
nur ins Audit-Log, was es getan hätte. Eingriffe sind auf ``max_per_print`` je
Regel und einen Abstand von ``cooldown_seconds`` begrenzt. Jeder Eingriff landet
im Audit-Log; es wird nie ein Druck gestartet, pausiert oder abgebrochen.

Die Regelprüfung ist als reine Funktion (``evaluate``) gebaut, damit sie ohne
Drucker und ohne Wartezeit testbar bleibt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.services import audit_log, error_patterns

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "countermeasures.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "dry_run": True,
    "printers": {},  # {"<id>": {"enabled": true, "rules": {"chamber_hot": true, "chamber_cold": true}}}
    "thresholds": {"hot_c": 38.0, "cold_c": 45.0},
    "cooldown_seconds": 600,
    "max_per_print": 3,
}

RULES = {
    "chamber_hot": {
        "title": "Bauraum zu warm (PLA/PETG/TPU)",
        "title_en": "Chamber too warm (PLA/PETG/TPU)",
        "patterns": ["heat_creep", "stringing"],
    },
    "chamber_cold": {
        "title": "Bauraum zu kalt (ABS/ASA/PC/PA)",
        "title_en": "Chamber too cold (ABS/ASA/PC/PA)",
        "patterns": ["warping", "delamination"],
    },
}

MIN_LAYER = 5
_LOW_TEMP_GROUP = {"pla", "petg", "tpu"}
_HIGH_TEMP_GROUP = {"abs", "asa", "pc", "pa", "ppa"}

_lock = threading.RLock()
_memory: dict[tuple[int, str], dict[str, Any]] = {}


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    """Konfiguration lesen; fehlende Datei oder kaputtes JSON ergibt die Vorgaben."""
    with _lock:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return _merge(DEFAULT_CONFIG, data if isinstance(data, dict) else {})


def merged_config(update: dict[str, Any]) -> dict[str, Any]:
    """Was ``save_config`` schreiben würde, ohne zu schreiben."""
    with _lock:
        return _merge(load_config(), {k: v for k, v in update.items() if k in DEFAULT_CONFIG})


def threshold_error(config: dict[str, Any]) -> str | None:
    """Die beiden Schwellen dürfen sich nicht überlappen.

    Läge „zu warm“ auf oder über „zu kalt“, wären beide Regeln für denselben
    Bauraum zuständig — je nach Filamentgruppe mit widersprüchlichen Eingriffen.
    Geprüft wird die *zusammengeführte* Konfiguration, weil die Oberfläche immer
    nur ein Feld schickt.
    """
    thresholds = config.get("thresholds") or {}
    try:
        hot = float(thresholds.get("hot_c"))
        cold = float(thresholds.get("cold_c"))
    except (TypeError, ValueError):
        return "Die Schwellen müssen Zahlen in °C sein."
    if hot >= cold:
        return f"Die Schwelle „zu warm“ ({hot:g} °C) muss unter „zu kalt“ ({cold:g} °C) liegen."
    return None


def save_config(update: dict[str, Any]) -> dict[str, Any]:
    """Konfiguration zusammenführen und schreiben (nur bekannte Felder)."""
    with _lock:
        merged = merged_config(update)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
        return merged


def printer_config(config: dict[str, Any], printer_id: int) -> dict[str, Any]:
    entry = (config.get("printers") or {}).get(str(printer_id)) or {}
    return {
        "enabled": bool(entry.get("enabled", False)),
        "rules": {rule: bool((entry.get("rules") or {}).get(rule, False)) for rule in RULES},
    }


def material_group(state) -> str | None:
    """Filamentgruppe aus den geladenen AMS-Fächern, nur bei eindeutiger Lage.

    Gemischte Bestückung ergibt None: dann ist nicht sicher, welches Material
    gerade gedruckt wird, und eine temperaturbasierte Regel wäre geraten.
    """
    raw = getattr(state, "raw_data", None) or {}
    types: set[str] = set()
    for unit in raw.get("ams") or []:
        if not isinstance(unit, dict):
            continue
        for tray in unit.get("tray") or []:
            if isinstance(tray, dict):
                tray_type = str(tray.get("tray_type") or "").strip().upper()
                if tray_type:
                    types.add(tray_type)
    # MQTT schickt vt_tray je nach Firmware als Objekt oder Liste.
    vt_raw = raw.get("vt_tray")
    if isinstance(vt_raw, dict):
        vt_trays = [vt_raw]
    elif isinstance(vt_raw, list):
        vt_trays = vt_raw
    else:
        vt_trays = []
    for vt in vt_trays:
        if isinstance(vt, dict):
            tray_type = str(vt.get("tray_type") or "").strip().upper()
            if tray_type:
                types.add(tray_type)
    if len(types) != 1:
        return None
    name = next(iter(types))
    for prefix in ("PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PA", "PPA"):
        if name.startswith(prefix):
            return prefix.lower()
    return None


def _num(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _chamber_supported(model: str | None, state) -> bool:
    from backend.app.services.printer_manager import supports_chamber_temp

    if not supports_chamber_temp(model):
        return False
    return _num((getattr(state, "temperatures", None) or {}).get("chamber")) is not None


def _fan_known(state, attr: str) -> int | None:
    value = getattr(state, attr, None)
    return None if value is None else int(value)


def _commands_for_hot(state) -> list[str]:
    commands: list[str] = []
    chamber_fan = _fan_known(state, "big_fan2_speed")
    aux_fan = _fan_known(state, "big_fan1_speed")
    if chamber_fan is not None and chamber_fan < 100:
        commands.append("M106 P3 S255")
    if aux_fan is not None and aux_fan < 70:
        commands.append("M106 P2 S178")
    temps = getattr(state, "temperatures", None) or {}
    bed_target = _num(temps.get("bed_target"))
    if bed_target is not None and bed_target > 45:
        commands.append(f"M140 S{int(max(40, bed_target - 5))}")
    return commands


def _commands_for_cold(state) -> list[str]:
    commands: list[str] = []
    chamber_fan = _fan_known(state, "big_fan2_speed")
    aux_fan = _fan_known(state, "big_fan1_speed")
    if chamber_fan is not None and chamber_fan > 0:
        commands.append("M106 P3 S0")
    if aux_fan is not None and aux_fan > 0:
        commands.append("M106 P2 S0")
    return commands


def evaluate(
    printer_id: int,
    state,
    model: str | None,
    config: dict[str, Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Welche Regel würde jetzt eingreifen? Reine Entscheidung, ohne zu senden."""
    now = now or datetime.now(timezone.utc)
    if not config.get("enabled", True):
        return []
    if getattr(state, "state", None) != "RUNNING":
        _memory.pop((printer_id, "chamber_hot"), None)
        _memory.pop((printer_id, "chamber_cold"), None)
        return []
    if int(getattr(state, "layer_num", 0) or 0) < MIN_LAYER:
        return []
    if not _chamber_supported(model, state):
        return []

    per_printer = printer_config(config, printer_id)
    if not per_printer["enabled"]:
        return []
    chamber = _num((state.temperatures or {}).get("chamber"))
    if chamber is None:
        return []
    material = material_group(state)
    if material is None:
        return []

    thresholds = config.get("thresholds") or {}
    candidates: list[tuple[str, float, list[str], str]] = []
    if material in _LOW_TEMP_GROUP:
        limit = float(thresholds.get("hot_c", 38.0))
        if chamber >= limit and not getattr(state, "door_open", False):
            commands = _commands_for_hot(state)
            if commands:
                candidates.append(
                    (
                        "chamber_hot",
                        limit,
                        commands,
                        f"Bauraum {chamber:.1f} °C bei {material.upper()} (Schwelle {limit:.0f} °C)",
                    )
                )
    if material in _HIGH_TEMP_GROUP:
        limit = float(thresholds.get("cold_c", 45.0))
        if chamber < limit:
            commands = _commands_for_cold(state)
            if commands:
                candidates.append(
                    (
                        "chamber_cold",
                        limit,
                        commands,
                        f"Bauraum {chamber:.1f} °C bei {material.upper()} (Schwelle {limit:.0f} °C)",
                    )
                )

    cooldown = int(config.get("cooldown_seconds", 600))
    max_per_print = int(config.get("max_per_print", 3))
    print_key = getattr(state, "gcode_file", None) or getattr(state, "subtask_name", None) or "?"
    actions: list[dict[str, Any]] = []
    for rule, _limit, commands, reason in candidates:
        if not per_printer["rules"].get(rule):
            continue
        memory = _memory.setdefault((printer_id, rule), {"print": print_key, "count": 0, "last": None, "dry": None})
        if memory["print"] != print_key:
            memory.update({"print": print_key, "count": 0, "last": None})
        dry = bool(config.get("dry_run", True))
        if memory.get("dry") != dry:
            memory.update({"dry": dry, "count": 0, "last": None})
        if memory["count"] >= max_per_print:
            continue
        last = memory["last"]
        if last is not None and (now - last).total_seconds() < cooldown:
            continue
        memory["count"] += 1
        memory["last"] = now
        actions.append(
            {
                "rule": rule,
                "commands": commands,
                "reason": reason,
                "dry_run": dry,
            }
        )
    return actions


def reset_memory() -> None:
    """Nur für Tests und nach dem Umschalten der Einstellungen."""
    _memory.clear()


def _execute(printer_id: int, actions: list[dict[str, Any]], client) -> None:
    for action in actions:
        rule = action["rule"]
        commands: list[str] = action["commands"]
        if action["dry_run"]:
            audit_log.record(
                f"countermeasure:{rule}",
                True,
                f"Trockenlauf: {action['reason']} — hätte gesendet: {', '.join(commands)}",
                printer_id,
                None,
                {"dry_run": True, "commands": commands, "reason": action["reason"]},
            )
            continue
        sent: list[str] = []
        failed: list[str] = []
        for command in commands:
            ok = bool(client and client.send_gcode(command))
            (sent if ok else failed).append(command)
        audit_log.record(
            f"countermeasure:{rule}",
            not failed,
            f"{action['reason']} — gesendet: {', '.join(sent)}"
            + (f" (fehlgeschlagen: {', '.join(failed)})" if failed else ""),
            printer_id,
            None,
            {"dry_run": False, "sent": sent, "failed": failed, "reason": action["reason"]},
        )


def build_manual_command(action: dict[str, Any], state, model: str | None) -> tuple[str | None, str | None]:
    """Befehl für einen Sofort-Eingriff bauen; (Befehl, Fehlermeldung)."""
    if getattr(state, "state", None) not in ("RUNNING", "PAUSE"):
        return None, "Der Drucker druckt gerade nicht."
    if "fan" in action:
        fan = action["fan"]
        if fan["index"] == 3:
            from backend.app.services.printer_manager import supports_chamber_temp

            if not supports_chamber_temp(model) and getattr(state, "big_fan2_speed", None) is None:
                return None, "Dieser Drucker hat keinen meldenden Kammerlüfter."
        if fan["index"] == 2 and getattr(state, "big_fan1_speed", None) is None:
            return None, "Dieser Drucker hat keinen Zusatzlüfter."
        return action["command"], None
    temps = getattr(state, "temperatures", None) or {}
    if "bed_delta" in action:
        target = _num(temps.get("bed_target"))
        if target is None:
            return None, "Das Bettziel wird nicht gemeldet."
        new_target = int(max(0, round(target + action["bed_delta"])))
        return f"M140 S{new_target}", None
    if "nozzle_delta" in action:
        target = _num(temps.get("nozzle_target"))
        if target is None:
            return None, "Das Düsenziel wird nicht gemeldet."
        new_target = int(min(320, max(0, round(target + action["nozzle_delta"]))))
        return f"M104 S{new_target}", None
    return action["command"], None


def apply_manual(printer_id: int, action_id: str, client, state, model: str | None) -> dict[str, Any]:
    """Sofort-Eingriff ausführen und protokollieren (Aufrufer prüft Rechte)."""
    action = error_patterns.manual_action(action_id)
    if action is None:
        return {"success": False, "error": "Unbekannte Gegenmaßnahme."}
    command, error = build_manual_command(action, state, model)
    if error:
        audit_log.record(f"errorhelp:manual:{action_id}", False, error, printer_id, None, {"pattern_action": action_id})
        return {"success": False, "error": error}
    ok = bool(client and client.send_gcode(command))
    message = f"{action['title']}: {command}" if ok else f"{action['title']}: Befehl konnte nicht gesendet werden."
    audit_log.record(
        f"errorhelp:manual:{action_id}",
        ok,
        message,
        printer_id,
        None,
        {"pattern_action": action_id, "command": command},
    )
    return {"success": ok, "command": command, "message": message}


async def run(interval: float = 30.0) -> None:
    """Dauerschleife: Regeln im Takt der Statusmeldungen prüfen."""
    from backend.app.services.printer_manager import printer_manager

    await asyncio.sleep(90)  # erst verbinden und ein paar Schichten drucken lassen
    while True:
        try:
            config = load_config()
            statuses = printer_manager.get_all_statuses()
            for printer_id, state in statuses.items():
                try:
                    model = printer_manager.get_model(printer_id)
                    for action in evaluate(printer_id, state, model, config):
                        client = printer_manager.get_client(printer_id)
                        _execute(printer_id, [action], client)
                except Exception:
                    logger.exception("Countermeasure evaluation failed for printer %s", printer_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Countermeasure loop failed")
        await asyncio.sleep(interval)

"""Tür- und Plattenwechsler-Steuerung (Port aus dem Bambu-Monitor).

PrintLab steuert den Drucker, aber nicht die eigene Mechanik. Dieser Dienst
ergänzt Tür-Servo, Endschalter und Magazin/Plattenwechsler. Er läuft in zwei
Modi:

- ``simulated``: keine Hardware, Zustände werden nur geführt (für PC/Tests),
- ``command``: führt konfigurierte Befehle aus und wertet deren Ausgabe aus.

Die Befehle stehen in ``data/hardware.json`` (wird beim ersten Start angelegt).
Sicherheit: Tür und Wechsler sind nur bei verbundenem, nicht druckendem Drucker
erlaubt; jeder Schritt hat ein Zeitlimit, ein Fehler bricht den Ablauf ab.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "hardware.json"
MAGAZINE_PATH = settings.base_dir / "magazine.json"
TIMEOUT = 15.0

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "simulated",
    "door_open_command": "",
    "door_close_command": "",
    "door_status_command": "",
    "plate_change_command": "",
    "emergency_stop_command": "",
    "timeout_seconds": TIMEOUT,
}

DEFAULT_SLOTS: list[dict[str, Any]] = [
    {"id": 1, "type": "supply", "status": "ready", "label": "PEI A"},
    {"id": 2, "type": "supply", "status": "ready", "label": "PEI B"},
    {"id": 3, "type": "supply", "status": "ready", "label": "PEI C"},
    {"id": 4, "type": "storage", "status": "empty", "label": "Fach 1"},
    {"id": 5, "type": "storage", "status": "empty", "label": "Fach 2"},
    {"id": 6, "type": "storage", "status": "empty", "label": "Fach 3"},
]

COMMAND_KEYS = (
    "door_open_command",
    "door_close_command",
    "door_status_command",
    "plate_change_command",
    "emergency_stop_command",
)


def _valid_command(value: Any) -> bool:
    """Ein Befehl ist ein String oder eine Liste von Strings (Programm + Argumente)."""
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(part, str) for part in value)


VALID_SLOT_STATUSES = frozenset({"ready", "used", "empty", "occupied"})


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _run(command: str | list[str], timeout: float, on_start: Callable[[subprocess.Popen], None] | None = None
         ) -> tuple[bool, str]:
    """Führt einen lokalen Hardware-Befehl aus (Konfiguration ist vertrauenswürdig).

    Eine **Liste** (``["programm", "arg1", ...]``) läuft ohne Shell und ist damit frei von
    Shell-Auswertung; ein **String** läuft wie bisher (unter Windows über die Shell, sonst per
    ``shlex``). ``on_start`` bekommt den Prozess, damit der Not-Halt ihn beenden kann.
    """
    if isinstance(command, (list, tuple)):
        args: list[str] | str = [str(part) for part in command]
        if not args or not args[0].strip():
            return False, "Kein Befehl konfiguriert."
        use_shell = False
    else:
        text = str(command or "")
        if not text.strip():
            return False, "Kein Befehl konfiguriert."
        use_shell = os.name == "nt"
        try:
            args = text if use_shell else shlex.split(text, posix=True)
        except ValueError as exc:
            return False, f"Befehl fehlgeschlagen: {exc}"
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=use_shell)
    except (OSError, ValueError) as exc:
        return False, f"Befehl fehlgeschlagen: {exc}"
    if on_start is not None:
        on_start(proc)
    try:
        stdout, _stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, f"Befehl fehlgeschlagen: Zeitlimit von {timeout:g} s überschritten."
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Befehl fehlgeschlagen: {exc}"
    output = (stdout or "").strip()
    if proc.returncode != 0:
        if proc.returncode < 0:
            return False, output or "Befehl wurde abgebrochen."
        return False, output or f"Befehl endete mit Code {proc.returncode}."
    return True, output


def door_state_from_output(output: str) -> str | None:
    """Liest DOOR:OPEN/CLOSED/UNKNOWN aus der Ausgabe des Tür-Befehls."""
    text = (output or "").upper()
    if "DOOR:OPEN" in text:
        return "open"
    if "DOOR:CLOSED" in text:
        return "closed"
    if "DOOR:UNKNOWN" in text:
        return "unknown"
    return None


class HardwareExtension:
    """Zustand und Abläufe für Tür und Plattenwechsler."""

    def __init__(self, config_path: Path = CONFIG_PATH, magazine_path: Path = MAGAZINE_PATH):
        self.config_path = config_path
        self.magazine_path = magazine_path
        self._lock = threading.Lock()
        self._busy = False
        self._last_error: str | None = None
        self._door = "closed"
        self._plate_on_bed = True
        self._proc: subprocess.Popen | None = None
        self._estop = False  # nach Not-Halt gesperrt, bis Konfiguration neu geladen / Magazin aufgefüllt wird
        self._incomplete: dict[str, Any] | None = None  # Wechsel mitten im Ablauf gescheitert
        self._config = self._load_config()
        self._magazine = self._load_magazine()
        self._plate_on_bed = bool(self._magazine.get("plate_on_bed", True))

    # --- Konfiguration und Magazin ---------------------------------------

    def _load_config(self) -> dict[str, Any]:
        data = _read_json(self.config_path, {})
        config = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            config.update({key: data[key] for key in DEFAULT_CONFIG if key in data})
        if config.get("mode") not in ("simulated", "command"):
            config["mode"] = "simulated"
        for key in COMMAND_KEYS:
            if not _valid_command(config.get(key)):
                config[key] = ""
        try:
            config["timeout_seconds"] = max(1.0, float(config.get("timeout_seconds") or TIMEOUT))
        except (TypeError, ValueError):
            config["timeout_seconds"] = TIMEOUT
        if not self.config_path.exists():
            _write_json(self.config_path, config)
        return config

    def reload_config(self) -> dict[str, Any]:
        with self._lock:
            self._config = self._load_config()
            self._estop = False
            return dict(self._config)

    def _load_magazine(self) -> dict[str, Any]:
        data = _read_json(self.magazine_path, {})
        slots = data.get("slots") if isinstance(data, dict) else None
        if not isinstance(slots, list) or len(slots) != 6:
            slots = [dict(slot) for slot in DEFAULT_SLOTS]
        return {
            "slots": slots,
            "plate_on_bed": bool(data.get("plate_on_bed", True)) if isinstance(data, dict) else True,
            "changes": int(data.get("changes", 0)) if isinstance(data, dict) else 0,
            "last_change": data.get("last_change") if isinstance(data, dict) else None,
        }

    def _save_magazine(self) -> None:
        _write_json(self.magazine_path, {
            "slots": self._magazine["slots"],
            "plate_on_bed": self._plate_on_bed,
            "changes": self._magazine["changes"],
            "last_change": self._magazine["last_change"],
        })

    # --- Status ------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            slots = [dict(slot) for slot in self._magazine["slots"]]
            return {
                "mode": self._config["mode"],
                "door": self._door,
                "plate_on_bed": self._plate_on_bed,
                "busy": self._busy,
                "error": self._last_error,
                "estop": self._estop,
                "incomplete": dict(self._incomplete) if self._incomplete else None,
                "slots": slots,
                "supply_ready": sum(1 for s in slots if s.get("type") == "supply" and s.get("status") == "ready"),
                "storage_empty": sum(1 for s in slots if s.get("type") == "storage" and s.get("status") == "empty"),
                "changes": self._magazine["changes"],
                "last_change": self._magazine["last_change"],
            }

    # --- Tür ---------------------------------------------------------------

    def _command(self, key: str) -> tuple[bool, str]:
        return _run(self._config.get(key, ""), float(self._config["timeout_seconds"]), self._set_proc)

    def _set_proc(self, proc: subprocess.Popen | None) -> None:
        with self._lock:
            self._proc = proc

    def _set_door(self, state: str) -> None:
        with self._lock:
            self._door = state

    def _enter(self, *, allow_incomplete: bool = False) -> str | None:
        """Vorgang beginnen: gibt eine Fehlermeldung zurück oder markiert die Hardware als beschäftigt."""
        with self._lock:
            if self._busy:
                return "Es läuft bereits ein Hardware-Vorgang."
            if self._estop:
                return "Not-Halt aktiv — Hardware-Konfiguration neu laden oder Magazin auffüllen, um fortzufahren."
            if self._incomplete and not allow_incomplete:
                return (f"Letzter Wechsel unvollständig ({self._incomplete.get('step')}) — "
                        "Mechanik prüfen, dann den Wechsel als geprüft bestätigen.")
            self._busy = True
            self._last_error = None
            return None

    def open_door(self) -> tuple[bool, str]:
        refusal = self._enter(allow_incomplete=True)
        if refusal:
            return False, refusal
        try:
            if self._config["mode"] == "simulated":
                self._door = "open"
                return True, "Tür geöffnet (Simulation)."
            ok, output = self._command("door_open_command")
            if not ok:
                self._last_error = output
                return False, output
            reported = door_state_from_output(output)
            if reported == "unknown":
                self._last_error = "Tür-Endschalter meldet UNKNOWN."
                return False, self._last_error
            if reported == "closed":
                self._last_error = "Tür ist nach dem Öffnen noch geschlossen."
                return False, self._last_error
            self._set_door("open")
            return True, "Tür geöffnet."
        finally:
            with self._lock:
                self._busy = False

    def close_door(self) -> tuple[bool, str]:
        refusal = self._enter(allow_incomplete=True)
        if refusal:
            return False, refusal
        try:
            if self._config["mode"] == "simulated":
                self._door = "closed"
                return True, "Tür geschlossen (Simulation)."
            ok, output = self._command("door_close_command")
            if not ok:
                self._last_error = output
                return False, output
            reported = door_state_from_output(output)
            if reported == "unknown":
                self._last_error = "Tür-Endschalter meldet UNKNOWN."
                return False, self._last_error
            if reported == "open":
                self._last_error = "Tür ist nach dem Schließen noch offen."
                return False, self._last_error
            self._set_door("closed")
            with self._lock:
                if self._incomplete and self._incomplete.get("step") == "Tür schließen":
                    self._incomplete = None  # Tür ist zu, der Wechsel war sonst vollständig
            return True, "Tür geschlossen."
        finally:
            with self._lock:
                self._busy = False

    def check_door_status(self) -> tuple[bool, str]:
        """Tür-Endschalter mit dem konfigurierten ``door_status_command`` abfragen.

        Der Ausgabewert (``DOOR:OPEN``/``DOOR:CLOSED``/``DOOR:UNKNOWN``) setzt den
        internen Türzustand. Ohne konfigurierten Befehl oder im Simulationsmodus
        wird der gespeicherte Zustand gemeldet.
        """
        status_cmd = self._config.get("door_status_command")
        configured = bool(status_cmd) and (not isinstance(status_cmd, str) or bool(status_cmd.strip()))
        if self._config["mode"] == "simulated" or not configured:
            return True, f"Tür: {self._door}"
        with self._lock:
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            self._busy = True
        try:
            ok, output = self._command("door_status_command")
            if not ok:
                self._last_error = output
                return False, output
            reported = door_state_from_output(output)
            if reported is None:
                self._last_error = "Tür-Befehl meldet keinen Zustand (DOOR:OPEN/CLOSED/UNKNOWN erwartet)."
                return False, self._last_error
            self._set_door(reported)
            return True, f"Tür: {reported}"
        finally:
            with self._lock:
                self._busy = False

    # --- Plattenwechsel ----------------------------------------------------

    def change_plate(self, job_name: str = "") -> tuple[bool, str]:
        refusal = self._enter()
        if refusal:
            return False, refusal
        try:
            slots = self._magazine["slots"]
            supply = next((s for s in slots if s.get("type") == "supply" and s.get("status") == "ready"), None)
            storage = next((s for s in slots if s.get("type") == "storage" and s.get("status") == "empty"), None)
            if supply is None:
                return False, "Keine frische Platte im Magazin."
            if storage is None:
                return False, "Kein freies Ablagefach."
            if self._config["mode"] == "simulated":
                self._apply_change(supply, storage, job_name)
                self._set_door("closed")
                return True, f"Platte aus Fach {supply['id']} eingesetzt (Simulation)."
            # Echter Ablauf: Tür auf -> Wechsel -> Tür zu; jeder Schritt muss gelingen.
            for key, label in (("door_open_command", "Tür öffnen"),
                               ("plate_change_command", "Plattenwechsel"),
                               ("door_close_command", "Tür schließen")):
                ok, output = self._command(key)
                if ok:
                    continue
                self._last_error = f"{label}: {output}"
                if key == "door_open_command":
                    return False, self._last_error  # nichts bewegt, nichts zu korrigieren
                # Ab hier ist die Mechanik möglicherweise halb durch: Zustand merken und sperren.
                plate_swapped = key == "door_close_command"
                if plate_swapped:
                    self._apply_change(supply, storage, job_name)  # Platte ist mechanisch getauscht
                self._set_door("unknown")
                with self._lock:
                    self._incomplete = {"step": label, "plate_swapped": plate_swapped, "job": job_name}
                note = " (Platte getauscht, Magazin nachgeführt)" if plate_swapped else ""
                return False, f"{self._last_error} — Wechsel unvollständig{note}; Mechanik prüfen."
            self._apply_change(supply, storage, job_name)
            self._set_door("closed")
            return True, f"Platte aus Fach {supply['id']} eingesetzt."
        finally:
            with self._lock:
                self._busy = False
                self._proc = None

    def _apply_change(self, supply: dict[str, Any], storage: dict[str, Any], job_name: str) -> None:
        supply["status"] = "used"
        storage["status"] = "occupied"
        storage["print"] = job_name or None
        self._plate_on_bed = True
        self._register_change(supply, storage)

    def resolve_incomplete(self) -> tuple[bool, str]:
        """Nach Prüfung der Mechanik bestätigen: der unvollständige Wechsel ist erledigt."""
        with self._lock:
            if self._incomplete is None:
                return False, "Es gibt keinen unvollständigen Wechsel."
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            self._incomplete = None
            self._last_error = None
            if self._door == "unknown":
                self._door = "closed"
            return True, "Unvollständiger Wechsel bestätigt."

    def _register_change(self, supply: dict[str, Any], storage: dict[str, Any]) -> None:
        self._magazine["changes"] += 1
        self._magazine["last_change"] = datetime.now(timezone.utc).isoformat()
        self._save_magazine()
        logger.info("[Hardware] Plattenwechsel: Fach %s -> Ablage %s", supply["id"], storage["id"])

    def refill_magazine(self) -> tuple[bool, str]:
        with self._lock:
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            self._magazine["slots"] = [dict(slot) for slot in DEFAULT_SLOTS]
            self._magazine["plate_on_bed"] = True
            self._estop = False
            self._incomplete = None
            self._save_magazine()
            return True, "Magazin aufgefüllt, Ablage geleert."

    def edit_slots(self, slots_in: list[dict[str, Any]]) -> tuple[bool, str]:
        """Einzelne Fächer setzen (Status/Etikett); der Rest bleibt.

        ``slots_in``: Elemente mit ``id`` (1..6) und optional ``status``
        (ready/used/empty/occupied) und ``label``. Der laufende
        Hardware-Vorgang blockiert den Edit, um widersprüchliche Zustände zu
        vermeiden.
        """
        with self._lock:
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            changes: list[str] = []
            by_id = {slot["id"]: slot for slot in self._magazine["slots"]}
            for item in slots_in:
                try:
                    slot_id = int(item.get("id"))
                except (TypeError, ValueError):
                    return False, "Fach-Id fehlt oder ist keine Zahl."
                slot = by_id.get(slot_id)
                if slot is None:
                    return False, f"Unbekanntes Fach {slot_id}."
                label = item.get("label")
                if label is not None:
                    slot["label"] = str(label)[:60]
                    changes.append(f"Fach {slot_id}: Etikett '{slot['label']}'")
                status = item.get("status")
                if status is not None:
                    if status not in VALID_SLOT_STATUSES:
                        return False, (
                            f"Unbekannter Status '{status}' für Fach {slot_id} "
                            f"(erlaubt: {', '.join(sorted(VALID_SLOT_STATUSES))})."
                        )
                    slot["status"] = status
                    if status in ("empty", "ready"):
                        slot.pop("print", None)
                    changes.append(f"Fach {slot_id}: {status}")
            if not changes:
                return False, "Keine gültigen Änderungen übermittelt."
            self._save_magazine()
            return True, "; ".join(changes)

    def config(self) -> dict[str, Any]:
        """Aktuelle Konfiguration (Kopie; Befehle sind lokale, vertrauenswürdige Werte)."""
        with self._lock:
            return dict(self._config)

    def update_config(self, data: dict[str, Any]) -> tuple[bool, str]:
        """Konfiguration schreiben und neu laden (nur bekannte Schlüssel)."""
        with self._lock:
            try:
                data = json.loads(json.dumps(data)) if not isinstance(data, dict) else data
                unknown = [key for key in data if key not in DEFAULT_CONFIG]
                if unknown:
                    return False, f"Unbekannte Schlüssel: {', '.join(sorted(unknown))}."
                merged = dict(self._config)
                merged.update({key: data[key] for key in DEFAULT_CONFIG if key in data})
                if merged.get("mode") not in ("simulated", "command"):
                    return False, "Modus nur 'simulated' oder 'command'."
                for key in COMMAND_KEYS:
                    if not _valid_command(merged.get(key)):
                        return False, f"{key} muss ein Text oder eine Liste von Texten sein."
                try:
                    merged["timeout_seconds"] = max(1.0, float(merged.get("timeout_seconds") or TIMEOUT))
                except (TypeError, ValueError):
                    return False, "timeout_seconds muss eine Zahl sein."
                _write_json(self.config_path, merged)
                self._config = merged
                return True, "Hardware-Konfiguration gespeichert."
            except (OSError, ValueError, TypeError) as exc:
                return False, f"Konfiguration nicht gespeichert: {exc}"

    def emergency_stop(self) -> tuple[bool, str]:
        """Not-Halt: beendet den laufenden Befehl, sperrt die Hardware und fährt in den sicheren Zustand.

        Im Simulationsmodus wird nur der Zustand geführt. Im Befehlsmodus läuft zusätzlich der
        konfigurierte Not-Halt-Befehl. Danach bleibt jeder weitere Vorgang gesperrt, bis die
        Hardware-Konfiguration neu geladen oder das Magazin aufgefüllt wird.
        """
        with self._lock:
            self._last_error = None
            self._door = "unknown"
            self._estop = True
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()  # laufenden Hardware-Befehl hart beenden
            except OSError:
                pass
        if self._config["mode"] == "simulated":
            return True, "Not-Halt ausgelöst (Simulation)."
        ok, output = _run(self._config.get("emergency_stop_command", ""), float(self._config["timeout_seconds"]))
        if not ok:
            with self._lock:
                self._last_error = output
            return False, output
        logger.warning("[Hardware] Not-Halt ausgelöst: %s", output or "Befehl ausgeführt")
        return True, "Not-Halt ausgelöst."


_hardware: HardwareExtension | None = None
_per_printer: dict[int, HardwareExtension] = {}
_per_printer_lock = threading.Lock()


def _printer_paths(printer_id: int) -> tuple[Path, Path]:
    return (CONFIG_PATH.with_name(f"hardware_{printer_id}.json"),
            MAGAZINE_PATH.with_name(f"magazine_{printer_id}.json"))


def get_hardware(printer_id: int | None = None) -> HardwareExtension:
    """Hardware-Instanz; mit ``printer_id`` hat jeder Drucker sein eigenes Magazin und seine eigene Konfiguration.

    Beim ersten Zugriff eines Druckers wird die bisherige gemeinsame Konfiguration (``hardware.json``) als
    Vorlage kopiert, und das bisherige gemeinsame Magazin (``magazine.json``) geht an diesen ersten Drucker
    über; weitere Drucker beginnen mit einem frisch gefüllten Magazin. Ohne ``printer_id`` gilt die alte,
    gemeinsame Instanz (nur noch für Altcode und Tests).
    """
    global _hardware
    if printer_id is None:
        if _hardware is None:
            _hardware = HardwareExtension()
        return _hardware
    with _per_printer_lock:
        instance = _per_printer.get(printer_id)
        if instance is None:
            config_path, magazine_path = _printer_paths(printer_id)
            if not config_path.exists() and CONFIG_PATH.exists():
                try:
                    shutil.copyfile(CONFIG_PATH, config_path)
                except OSError as exc:
                    logger.warning("[Hardware] Vorlage nicht kopiert: %s", exc)
            if not magazine_path.exists() and MAGAZINE_PATH.exists():
                try:
                    MAGAZINE_PATH.replace(magazine_path)  # erster Drucker übernimmt den bisherigen Magazinstand
                except OSError as exc:
                    logger.warning("[Hardware] Magazinstand nicht übernommen: %s", exc)
            instance = HardwareExtension(config_path, magazine_path)
            _per_printer[printer_id] = instance
        return instance

"""Tür- und Plattenwechsler-Steuerung (Port aus dem Bambu-Monitor).

Bambuddy steuert den Drucker, aber nicht die eigene Mechanik. Dieser Dienst
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
import subprocess
import threading
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


def _run(command: str, timeout: float) -> tuple[bool, str]:
    """Führt einen lokalen Hardware-Befehl aus (Konfiguration ist vertrauenswürdig)."""
    if not command.strip():
        return False, "Kein Befehl konfiguriert."
    try:
        if os.name == "nt":
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=timeout, check=False, shell=True)
        else:
            args = shlex.split(command, posix=True)
            result = subprocess.run(args, capture_output=True, text=True,
                                    timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return False, f"Befehl fehlgeschlagen: {exc}"
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        return False, output or f"Befehl endete mit Code {result.returncode}."
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
                "slots": slots,
                "supply_ready": sum(1 for s in slots if s.get("type") == "supply" and s.get("status") == "ready"),
                "storage_empty": sum(1 for s in slots if s.get("type") == "storage" and s.get("status") == "empty"),
                "changes": self._magazine["changes"],
                "last_change": self._magazine["last_change"],
            }

    # --- Tür ---------------------------------------------------------------

    def _command(self, key: str) -> tuple[bool, str]:
        return _run(str(self._config.get(key, "")), float(self._config["timeout_seconds"]))

    def open_door(self) -> tuple[bool, str]:
        with self._lock:
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            self._busy = True
            self._last_error = None
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
            self._door = "open"
            return True, "Tür geöffnet."
        finally:
            with self._lock:
                self._busy = False

    def close_door(self) -> tuple[bool, str]:
        with self._lock:
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            self._busy = True
            self._last_error = None
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
            self._door = "closed"
            return True, "Tür geschlossen."
        finally:
            with self._lock:
                self._busy = False

    # --- Plattenwechsel ----------------------------------------------------

    def change_plate(self, job_name: str = "") -> tuple[bool, str]:
        with self._lock:
            if self._busy:
                return False, "Es läuft bereits ein Hardware-Vorgang."
            self._busy = True
            self._last_error = None
        try:
            slots = self._magazine["slots"]
            supply = next((s for s in slots if s.get("type") == "supply" and s.get("status") == "ready"), None)
            storage = next((s for s in slots if s.get("type") == "storage" and s.get("status") == "empty"), None)
            if supply is None:
                return False, "Keine frische Platte im Magazin."
            if storage is None:
                return False, "Kein freies Ablagefach."
            if self._config["mode"] == "simulated":
                supply["status"] = "used"
                storage["status"] = "occupied"
                storage["print"] = job_name or None
                self._plate_on_bed = True
                self._door = "closed"
                self._register_change(supply, storage)
                return True, f"Platte aus Fach {supply['id']} eingesetzt (Simulation)."
            # Echter Ablauf: Tür auf -> Wechsel -> Tür zu; jeder Schritt muss gelingen.
            for key, label in (("door_open_command", "Tür öffnen"),
                               ("plate_change_command", "Plattenwechsel"),
                               ("door_close_command", "Tür schließen")):
                ok, output = self._command(key)
                if not ok:
                    self._last_error = f"{label}: {output}"
                    return False, self._last_error
            supply["status"] = "used"
            storage["status"] = "occupied"
            storage["print"] = job_name or None
            self._plate_on_bed = True
            self._door = "closed"
            self._register_change(supply, storage)
            return True, f"Platte aus Fach {supply['id']} eingesetzt."
        finally:
            with self._lock:
                self._busy = False

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
            self._save_magazine()
            return True, "Magazin aufgefüllt, Ablage geleert."

    def emergency_stop(self) -> tuple[bool, str]:
        """Not-Halt: bricht den laufenden Vorgang ab und fährt die Mechanik in den sicheren Zustand.

        Im Simulationsmodus wird nur der Zustand geführt. Im Befehlsmodus läuft der
        konfigurierte Not-Halt-Befehl; der Vorgang bleibt danach gesperrt, bis die
        Hardware-Konfiguration neu geladen oder das Magazin aufgefüllt wird.
        """
        with self._lock:
            self._last_error = None
            self._door = "unknown"
            self._busy = False
            if self._config["mode"] == "simulated":
                return True, "Not-Halt ausgelöst (Simulation)."
            ok, output = self._command("emergency_stop_command")
            if not ok:
                self._last_error = output
                return False, output
            logger.warning("[Hardware] Not-Halt ausgelöst: %s", output or "Befehl ausgeführt")
            return True, "Not-Halt ausgelöst."


_hardware: HardwareExtension | None = None


def get_hardware() -> HardwareExtension:
    """Einmalige Instanz; erst beim ersten Zugriff angelegt (keine Dateien beim Import)."""
    global _hardware
    if _hardware is None:
        _hardware = HardwareExtension()
    return _hardware

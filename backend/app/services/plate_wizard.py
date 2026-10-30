"""Einmess-Assistent für den Plattenwechsel.

Die Bewegungsfolge des Wechslers lässt sich nicht am Schreibtisch erfinden: sie
hängt von den tatsächlichen Positionen der Mechanik ab. Dieser Assistent führt
deshalb durch das Einmessen und hält das Ergebnis fest:

1. ``reference`` — Referenzpunkt anfahren und Koordinaten eintragen
2. ``pickup`` — Position, an der die Platte aufgenommen wird
3. ``drop`` — Ablageposition im Magazin
4. ``magazine`` — Übergabeposition Magazin/Wechsler (optional, wenn die Mechanik sie braucht)
5. ``door`` — Tür öffnen/schließen geprüft, Endschalter meldet den Zustand
6. ``dry_run`` — Probelauf ohne Platte von Hand bestätigt

Erst wenn alle Pflichtschritte vorliegen, ein Probelauf bestätigt und ein Name
eingetragen ist, gilt der Drucker als eingemessen. Solange der Assistent
**begonnen, aber nicht abgeschlossen** ist, verweigert ``change_plate`` den
Wechsel — eine halb eingemessene Mechanik darf sich nicht bewegen.

Was der Assistent nicht tut: Er fährt nichts von selbst an und erzeugt keine
Bewegungsfolge. Die Werte sind die Grundlage dafür; die Folge selbst muss am
Gerät erprobt und freigegeben werden.

Ablage: ``data/plate_wizard/<printer_id>.json``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

STORE_DIR = settings.base_dir / "plate_wizard"
MAX_COORD_MM = 500.0
MAX_Z_MM = 400.0
REQUIRED_STEPS = ("reference", "pickup", "drop", "door", "dry_run")
OPTIONAL_STEPS = ("magazine",)
STEPS = REQUIRED_STEPS + OPTIONAL_STEPS
COORD_STEPS = ("reference", "pickup", "drop", "magazine")
_lock = threading.Lock()


class WizardError(ValueError):
    """Meldung, die der Benutzer lesen darf."""


def _path_for(printer_id: int) -> Path:
    return STORE_DIR / f"{int(printer_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(printer_id: int) -> dict[str, Any]:
    """Gespeicherten Stand lesen; fehlt die Datei, ist der Assistent unberührt."""
    path = _path_for(printer_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    steps = data.get("steps") if isinstance(data.get("steps"), dict) else {}
    return {
        "printer_id": int(printer_id),
        "steps": {key: value for key, value in steps.items() if key in STEPS and isinstance(value, dict)},
        "started_at": data.get("started_at"),
        "completed_at": data.get("completed_at"),
        "operator": data.get("operator") or "",
        "revision": int(data.get("revision") or 0),
    }


def _write(printer_id: int, data: dict[str, Any]) -> dict[str, Any]:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(printer_id)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _coordinate(payload: dict[str, Any]) -> dict[str, float] | None:
    if not any(key in payload for key in ("x", "y", "z")):
        return None
    values: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        if axis not in payload:
            raise WizardError(f"Achse „{axis}“ fehlt.")
        try:
            number = float(payload[axis])
        except (TypeError, ValueError):
            raise WizardError(f"Achse „{axis}“ ist keine Zahl.") from None
        limit = MAX_Z_MM if axis == "z" else MAX_COORD_MM
        if not -limit <= number <= limit:
            raise WizardError(f"Achse „{axis}“ liegt außerhalb ±{limit:g} mm.")
        values[axis] = round(number, 2)
    return values


def save_step(printer_id: int, step: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Einen Schritt festhalten. Koordinaten werden geprüft, nicht geschätzt."""
    if step not in STEPS:
        raise WizardError("Unbekannter Schritt.")
    payload = payload if isinstance(payload, dict) else {}
    with _lock:
        data = read(printer_id)
        if data.get("completed_at"):
            raise WizardError("Der Assistent ist bereits abgeschlossen — zum Neuvermessen erst zurücksetzen.")
        entry: dict[str, Any] = {"at": _now()}
        if step in COORD_STEPS:
            coordinate = _coordinate(payload)
            if coordinate is None:
                raise WizardError("Für diesen Schritt fehlen die Koordinaten (x, y, z in mm).")
            entry["position"] = coordinate
            entry["note"] = str(payload.get("note") or "").strip()[:200]
        elif step == "door":
            if payload.get("confirmed") is not True:
                raise WizardError("Bitte bestätigen, dass die Tür öffnet, schließt und der Endschalter meldet.")
            entry["confirmed"] = True
            entry["sensor"] = bool(payload.get("sensor"))
            entry["note"] = str(payload.get("note") or "").strip()[:200]
        else:  # dry_run
            if payload.get("confirmed") is not True:
                raise WizardError("Bitte den Probelauf ohne Platte bestätigen.")
            entry["confirmed"] = True
            entry["note"] = str(payload.get("note") or "").strip()[:300]
        data["steps"][step] = entry
        data.setdefault("started_at", _now())
        data["revision"] = int(data.get("revision") or 0) + 1
        _write(printer_id, data)
        return status(printer_id)


def _positions_distinct(steps: dict[str, Any]) -> str | None:
    seen: dict[tuple[float, float, float], str] = {}
    for step in COORD_STEPS:
        entry = steps.get(step)
        if not entry:
            continue
        position = entry["position"]
        key = (position["x"], position["y"], position["z"])
        if key in seen:
            return f"„{seen[key]}“ und „{step}“ liegen auf derselben Position — bitte prüfen."
        seen[key] = step
    return None


def missing(printer_id: int) -> list[str]:
    steps = read(printer_id)["steps"]
    return [step for step in REQUIRED_STEPS if step not in steps]


def complete(printer_id: int, operator: str = "") -> dict[str, Any]:
    """Abschließen — nur mit allen Pflichtschritten, bestandenem Probelauf und Namen."""
    operator = str(operator or "").strip()[:80]
    with _lock:
        data = read(printer_id)
        if data.get("completed_at"):
            raise WizardError("Der Assistent ist bereits abgeschlossen.")
        missing_steps = [step for step in REQUIRED_STEPS if step not in data["steps"]]
        if missing_steps:
            raise WizardError("Es fehlen noch Schritte: " + ", ".join(missing_steps) + ".")
        if not data["steps"]["dry_run"].get("confirmed"):
            raise WizardError("Der Probelauf ohne Platte ist nicht bestätigt.")
        if not operator:
            raise WizardError("Bitte den Namen der Person eintragen, die eingemessen hat.")
        problem = _positions_distinct(data["steps"])
        if problem:
            raise WizardError(problem)
        data["operator"] = operator
        data["completed_at"] = _now()
        data["revision"] = int(data.get("revision") or 0) + 1
        _write(printer_id, data)
        return status(printer_id)


def reset(printer_id: int) -> dict[str, Any]:
    """Alles verwerfen (z. B. nach Umbau der Mechanik)."""
    with _lock:
        try:
            _path_for(printer_id).unlink()
        except OSError:
            pass
        return status(printer_id)


def status(printer_id: int) -> dict[str, Any]:
    """Stand für Oberfläche und Gate: Schritte, fehlende Schritte, abgeschlossen."""
    data = read(printer_id)
    missing_steps = [step for step in REQUIRED_STEPS if step not in data["steps"]]
    started = bool(data["steps"]) and not data.get("completed_at")
    return {
        **data,
        "steps_required": list(REQUIRED_STEPS),
        "steps_optional": list(OPTIONAL_STEPS),
        "missing": missing_steps,
        "started": started,
        "complete": bool(data.get("completed_at")),
        "position_problem": _positions_distinct(data["steps"]),
    }


def blocks_plate_change(printer_id: int) -> str | None:
    """Grund, warum ein Wechsel jetzt nicht starten darf — ``None`` heißt frei.

    Nur ein *begonnener, nicht abgeschlossener* Assistent sperrt. Wer ihn nie
    gestartet hat, arbeitet wie bisher (die Mechanik ist dann nicht eingemessen,
    aber der Assistent ist auch keine Vorschrift).
    """
    state = status(printer_id)
    if state["started"]:
        return "Einmess-Assistent für den Plattenwechsel ist begonnen, aber nicht abgeschlossen."
    return None

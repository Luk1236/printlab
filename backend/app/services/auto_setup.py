"""Auto-Einrichtung: erledigt selbst, was bei der Inbetriebnahme ohne Zugangsdaten des Benutzers geht.

Jeder Schritt ist idempotent und meldet einen Zustand statt eines Textes (die Oberfläche übersetzt ihn):

- ``done``: war schon eingerichtet, nichts zu tun
- ``todo``: kann das System jetzt selbst einrichten (nur in der Vorschau)
- ``changed``: wurde eben eingerichtet
- ``needs_user``: eingerichtet, aber ein Handgriff des Benutzers fehlt noch (zum Beispiel der Anmelde-Link)
- ``manual``: geht nicht von allein (fehlende Voraussetzung, anderes System)
- ``failed``: der Versuch ist gescheitert, ``detail`` nennt die Fehlerart

Nicht automatisch: Anmeldung (Passwort wählt der Benutzer), Drucker (Zugangscode), Meldewege (Token), Signaturschlüssel
(der private Teil gehört nicht auf den Pi). Das steht weiter im Einrichtungsassistenten.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.services import assistant_config, update_guard

logger = logging.getLogger(__name__)

STEPS = ("guard", "assistant", "remote")


@dataclass
class Deps:
    data_dir: Path
    app_dir: Path
    auth_enabled: bool
    port: int
    linux: Callable[[], bool] = lambda: sys.platform.startswith("linux")
    python: str = sys.executable
    unit_path: Path | None = None
    assistant_status: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None
    remote_status: Callable[[], Awaitable[dict[str, Any]]] | None = None
    remote_setup: Callable[[int], Awaitable[dict[str, Any]]] | None = None


def _item(step: str, state: str, detail: str = "") -> dict[str, str]:
    return {"id": step, "state": state, "detail": detail}


def _unit(d: Deps) -> Path:
    return d.unit_path or Path.home() / ".config" / "systemd" / "user" / "printlab.service"


def _guard_state(d: Deps) -> dict[str, str]:
    if not d.linux():
        return _item("guard", "manual", "not_linux")
    unit = _unit(d)
    if not unit.is_file():
        return _item("guard", "manual", "no_unit")  # Docker oder Start von Hand: keine systemd-Unit
    return _item("guard", "done" if update_guard.guard_in_unit(unit) else "todo")


async def _assistant_state(d: Deps) -> dict[str, str]:
    config = assistant_config.read(d.data_dir)
    if config["enabled"]:
        return _item("assistant", "done")
    if d.assistant_status is None:
        return _item("assistant", "manual", "no_probe")
    status = await d.assistant_status(config)
    if not status.get("reachable"):
        return _item("assistant", "manual", "no_server")
    if not status.get("model_present"):
        return _item("assistant", "manual", "no_model")
    return _item("assistant", "todo", config["model"])


async def _remote_state(d: Deps) -> dict[str, str]:
    if not d.linux():
        return _item("remote", "manual", "not_linux")
    if not d.auth_enabled:
        return _item("remote", "manual", "needs_auth")  # Fernzugriff nur mit Anmeldung (wie der Knopf selbst)
    if d.remote_status is None:
        return _item("remote", "manual", "no_probe")
    status = await d.remote_status()
    if status.get("state") == "connected" and status.get("serving"):
        return _item("remote", "done")
    return _item("remote", "todo")


async def plan(d: Deps) -> dict[str, Any]:
    """Was das System selbst einrichten würde (ändert nichts)."""
    items = [_guard_state(d), await _assistant_state(d), await _remote_state(d)]
    return {"items": items, "todo": sum(1 for item in items if item["state"] == "todo")}


async def _run_guard(d: Deps) -> dict[str, str]:
    changed = update_guard.ensure_systemd_guard(d.app_dir, d.python, _unit(d))
    return _item("guard", "changed" if changed else "failed", "" if changed else "write")


async def _run_assistant(d: Deps) -> dict[str, str]:
    assistant_config.write(d.data_dir, {"enabled": True})
    return _item("assistant", "changed")


async def _run_remote(d: Deps) -> dict[str, str]:
    assert d.remote_setup is not None  # noqa: S101 - plan() liefert "todo" nur mit remote_status; run() prüft beides
    result = await d.remote_setup(d.port)
    if result.get("state") == "connected":
        return _item("remote", "changed")
    return _item("remote", "needs_user", str(result.get("login_url") or ""))


_RUNNERS: dict[str, Callable[[Deps], Awaitable[dict[str, str]]]] = {
    "guard": _run_guard,
    "assistant": _run_assistant,
    "remote": _run_remote,
}


async def run(d: Deps, only: list[str] | None = None) -> dict[str, Any]:
    """Alle Schritte mit Zustand ``todo`` ausführen (oder nur die in ``only``). Ein Fehler stoppt die übrigen nicht."""
    current = await plan(d)
    results: list[dict[str, str]] = []
    for item in current["items"]:
        if item["state"] != "todo" or (only is not None and item["id"] not in only):
            results.append(item)
            continue
        try:
            results.append(await _RUNNERS[item["id"]](d))
        except Exception as exc:  # noqa: BLE001 - ein Schritt darf die anderen nicht verhindern
            logger.warning("Auto-Einrichtung %s fehlgeschlagen: %s", item["id"], exc, exc_info=True)
            results.append(_item(item["id"], "failed", type(exc).__name__))
    return {"items": results, "changed": sum(1 for item in results if item["state"] in ("changed", "needs_user"))}

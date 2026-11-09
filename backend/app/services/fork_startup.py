"""Eigene Start- und Torprüfungen von PrintLab, aus ``main.py`` herausgelöst (diese Datei ist 11 000 Zeilen lang).

- ``on_startup``: bestätigt ein offenes Update nach einer Weile stabilen Laufs und warnt, wenn die Anmeldung aus ist,
  das Backend aber im Netz lauscht.
- ``auth_gate``: bei vorgeschriebener Anmeldung (``PRINTLAB_REQUIRE_AUTH=1``) sperrt es die Schnittstelle, bis die
  Anmeldung eingerichtet ist.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Starke Referenzen auf Hintergrund-Aufgaben, damit sie nicht vorzeitig vom Garbage Collector beendet werden.
_BACKGROUND_TASKS: set[Any] = set()


async def on_startup(base_dir: Path, session_factory: Callable[[], Any]) -> None:
    """Nach ``init_db`` aufrufen. Wirft nie: ein Fehler hier darf den Start nicht verhindern."""
    try:
        from backend.app.services.update_guard import schedule_confirmation

        schedule_confirmation(base_dir)
    except Exception as exc:  # pragma: no cover - darf den Start nie verhindern
        logger.warning("Update-Bestätigung nicht geplant: %s", exc)

    # Absturz-Diagnose: Prüfen, ob Rechner oder Dienst unerwartet neu gestartet wurden
    try:
        import asyncio

        from backend.app.services import crash_diagnostics

        task = asyncio.get_running_loop().create_task(
            crash_diagnostics.check_crash_and_notify(base_dir, session_factory)
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[PrintLab] Absturzprüfung übersprungen: %s", exc)

    # Integrierten Slicer auf 127.0.0.1:3001 / 3003 starten und Slicer-API standardmäßig einschalten
    if os.environ.get("PRINTLAB_DISABLE_BUILTIN_SLICER", "").strip() not in ("1", "true", "yes"):
        try:
            import asyncio

            from backend.app.api.routes.settings import get_setting, set_setting
            from backend.app.services.builtin_slicer import ensure_builtin_slicer_running

            await asyncio.to_thread(ensure_builtin_slicer_running)
            async with session_factory() as slicer_db:
                cur_use = await get_setting(slicer_db, "use_slicer_api")
                if cur_use is None:
                    await set_setting(slicer_db, "use_slicer_api", "true")
                    await slicer_db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[PrintLab] Integrierter Slicer-Start übersprungen: %s", exc)

    # Lokalen KI-Assistenten automatisch einrichten (Ollama suchen, Modell wählen, vorladen). Läuft im Hintergrund,
    # damit ein langsamer oder fehlender Modell-Server den Start nicht aufhält.
    if os.environ.get("PRINTLAB_DISABLE_ASSISTANT_AUTOSETUP", "").strip() not in ("1", "true", "yes"):
        try:
            import asyncio

            from backend.app.services.assistant_autoconfig import ensure_on_startup

            task = asyncio.get_running_loop().create_task(ensure_on_startup(base_dir))
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[PrintLab] KI-Auto-Einrichtung nicht geplant: %s", exc)

    # Warnen, wenn die Anmeldung aus ist, das Backend aber nicht nur am Loopback lauscht (Docker/systemd binden
    # standardmäßig an 0.0.0.0). Dann wäre die Instanz ungeschützt im Netz steuerbar.
    try:
        from backend.app.core.auth import is_auth_enabled

        listen_host = (os.environ.get("HOST") or "127.0.0.1").strip()
        if listen_host not in ("127.0.0.1", "localhost", "::1"):
            async with session_factory() as boot_db:
                auth_on = await is_auth_enabled(boot_db)
            if not auth_on:
                logger.warning(
                    "[PrintLab] Anmeldung ist ausgeschaltet und HOST=%s: die Oberfläche ist "
                    "für das gesamte Netz erreichbar. Anmeldung einschalten "
                    "(werkzeuge\\admin_passwort_setzen.py) oder HOST auf 127.0.0.1 setzen.",
                    listen_host,
                )
    except Exception as exc:  # noqa: BLE001 - Warnung darf den Start nie blockieren
        logger.debug("[PrintLab] Bindungs-/Anmeldeprüfung übersprungen: %s", exc)


async def auth_gate(session_factory: Callable[[], Any], path: str = "") -> tuple[int, dict[str, Any]] | None:
    """None = durchlassen; sonst (Status, Inhalt) der Sperre. Fail-closed bei Fehlern der Prüfung."""
    from backend.app.core import auth_policy

    if not auth_policy.is_required():
        return None
    try:
        from backend.app.core.auth import is_auth_enabled

        async with session_factory() as db:
            auth_set_up = await is_auth_enabled(db)
    except Exception:
        logger.exception("auth_gate: failing closed on auth-probe error from %s", path)
        return 503, {"detail": "Authentication service temporarily unavailable"}
    if not auth_set_up:
        return 403, {"detail": auth_policy.SETUP_HINT, "auth_setup_required": True}
    return None

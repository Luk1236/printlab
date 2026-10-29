"""Systemprüfung: ein Aufruf prüft, ob die wichtigen Teile von PrintLab laufen (siehe ``services/selftest.py``).

Die Prüfung liest nur, mit zwei Ausnahmen, die bewusst mitlaufen: eine Probemeldung über die Kanäle, die „Termin in Gefahr"
wollen, und eine Probefrage an das Modell des Assistenten.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, is_auth_enabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.i18n.fork_messages import wants_english
from backend.app.services import assistant_config, assistant_llm, pi_health, queue_due_watch, selftest, update_guard
from backend.app.services.print_scheduler import scheduler as print_scheduler
from backend.app.services.printer_manager import printer_manager

router = APIRouter(prefix="/selftest", tags=["selftest"])
_lock = asyncio.Lock()


def _guard_state() -> str:
    unit = Path.home() / ".config" / "systemd" / "user" / "printlab.service"
    if not unit.is_file():
        return "no_unit"
    return "ok" if update_guard.guard_in_unit(unit) else "missing"


@router.post("")
async def run_selftest(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Alle Prüfungen einmal ausführen (mit Probemeldung und Probefrage); Texte in der Sprache der Anfrage."""
    if _lock.locked():
        raise HTTPException(429, "Die Systemprüfung läuft bereits.")
    async with _lock:
        deps = selftest.Deps(
            db=db,
            data_dir=settings.base_dir,
            now=datetime.now(timezone.utc),
            scheduler_running=lambda: bool(getattr(print_scheduler, "_running", False)),
            printer_connected=printer_manager.is_connected,
            due_watch_state=queue_due_watch.STATE,
            assistant_config=assistant_config.read(settings.base_dir),
            assistant_status=assistant_llm.status,
            assistant_probe=assistant_llm.probe,
            send_test_notification=queue_due_watch.send_test,
            health=pi_health.snapshot,
            guard_state=_guard_state,
            auth_enabled=is_auth_enabled,
            due_watch_interval=queue_due_watch.CHECK_INTERVAL_SECONDS,
        )
        language = "en" if wants_english(request.headers.get("accept-language")) else "de"
        return await selftest.run(deps, language)

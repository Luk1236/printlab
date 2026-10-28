"""Inbetriebnahme-Checkliste: was ist schon eingerichtet, was fehlt noch.

Liest nur vorhandenen Zustand (Anmeldung, Drucker, Meldewege, Sicherung, Signatur, Fernzugriff, Gerät) und ändert nichts.
``done`` ist True/False oder None, wenn der Punkt hier nicht zutrifft (zum Beispiel Update-Schutz unter Windows).
``level``: ``required`` (ohne das ist PrintLab nicht sicher nutzbar), ``recommended`` oder ``optional``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import is_auth_enabled
from backend.app.models.printer import Printer
from backend.app.services import alert_channels, pi_health, update_guard, update_signature

ORDER = (
    ("auth", "required"),
    ("printer", "required"),
    ("alerts", "recommended"),
    ("external_backup", "recommended"),
    ("guard", "recommended"),
    ("signature", "recommended"),
    ("storage", "recommended"),
    ("remote", "optional"),
    ("https", "optional"),
)


async def collect(db: AsyncSession, data_dir: Path, remote: dict[str, Any] | None = None) -> dict[str, Any]:
    """``remote`` ist der Zustand des Fernzugriffs (``remote_access.status()``), falls schon geholt."""
    printers = (await db.execute(select(func.count()).select_from(Printer))).scalar_one()
    alerts = alert_channels.status(data_dir)
    external = pi_health.external_backup_status(data_dir)
    target = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    storage = pi_health.storage_kind(data_dir)
    remote = remote or {}
    connected = remote.get("state") == "connected"

    results: dict[str, bool | None] = {
        "auth": await is_auth_enabled(db),
        "printer": printers > 0,
        "alerts": bool(alerts["telegram"] or alerts["ntfy"]),
        "external_backup": bool(target and external and external.get("ok")),
        "guard": update_guard.guard_in_unit() if sys.platform.startswith("linux") else None,
        "signature": update_signature.policy(data_dir)["enforced"],
        "storage": None if storage is None else storage["kind"] in ("usb", "nvme"),
        "remote": bool(connected and remote.get("serving")),
        "https": bool(remote.get("https")) if connected and remote.get("serving") else None,
    }
    items = [{"id": key, "level": level, "done": results[key]} for key, level in ORDER]
    applicable = [item for item in items if item["done"] is not None]
    return {
        "items": items,
        "done": sum(1 for item in applicable if item["done"]),
        "total": len(applicable),
        "required_open": sum(1 for item in applicable if item["level"] == "required" and not item["done"]),
    }

"""Fehlerhilfe: Fehlerbild-Bibliothek und optionale Gegenmaßnahmen am Druck.

Lesen (Katalog und Einstellungen) braucht ``PRINTERS_READ``, Änderungen an den
Gegenmaßnahmen ``SETTINGS_UPDATE``, ein Sofort-Eingriff am laufenden Druck
``PRINTERS_CONTROL``. Jeder Eingriff wird im Audit-Log protokolliert.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.models.user import User
from backend.app.services import audit_log, countermeasures, error_patterns

router = APIRouter(prefix="/error-help", tags=["error-help"])


class Thresholds(BaseModel):
    hot_c: float | None = Field(default=None, ge=20, le=70)
    cold_c: float | None = Field(default=None, ge=20, le=80)


class PrinterRules(BaseModel):
    enabled: bool | None = None
    rules: dict[str, bool] | None = None


class CountermeasuresConfig(BaseModel):
    enabled: bool | None = None
    dry_run: bool | None = None
    printers: dict[str, PrinterRules] | None = None
    thresholds: Thresholds | None = None
    cooldown_seconds: int | None = Field(default=None, ge=60, le=3600)
    max_per_print: int | None = Field(default=None, ge=1, le=10)


class ManualActionRequest(BaseModel):
    action_id: str


@router.get("")
async def get_catalog(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Fehlerbilder, Kategorien und Sofort-Eingriffe (deutsche Fließtexte)."""
    return {**error_patterns.catalog(), "rules": countermeasures.RULES}


@router.get("/countermeasures")
async def get_countermeasures(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Einstellungen und je Drucker der aktuelle Zustand (Material, Bauraum, Regeln)."""
    from backend.app.services.printer_manager import printer_manager, supports_chamber_temp

    config = countermeasures.load_config()
    printers = list((await db.execute(select(Printer).where(Printer.is_active.is_(True)))).scalars().all())
    rows = []
    for printer in printers:
        state = printer_manager.get_status(printer.id)
        model = printer_manager.get_model(printer.id) or printer.model
        entry = {
            "id": printer.id,
            "name": printer.name,
            "model": model,
            "chamber_supported": supports_chamber_temp(model),
            **countermeasures.printer_config(config, printer.id),
            "running": bool(state and state.state == "RUNNING"),
            "state": getattr(state, "state", None),
            "layer": int(getattr(state, "layer_num", 0) or 0) if state else 0,
            "material": countermeasures.material_group(state) if state else None,
            "chamber_c": None,
            "available_actions": [],
        }
        if state:
            chamber = (getattr(state, "temperatures", None) or {}).get("chamber")
            try:
                entry["chamber_c"] = None if chamber is None else float(chamber)
            except (TypeError, ValueError):
                entry["chamber_c"] = None
            for action in error_patterns.MANUAL_ACTIONS:
                command, error = countermeasures.build_manual_command(action, state, model)
                if not error:
                    entry["available_actions"].append({"id": action["id"], "command": command})
        rows.append(entry)
    return {"config": config, "rules": countermeasures.RULES, "printers": rows}


@router.put("/countermeasures")
async def put_countermeasures(
    payload: CountermeasuresConfig,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Einstellungen speichern; nur die mitgeschickten Felder ändern sich."""
    update = payload.model_dump(exclude_none=True)
    if "printers" in update:
        cleaned: dict[str, dict] = {}
        for key, value in update["printers"].items():
            if not str(key).isdigit():
                raise HTTPException(400, f"Ungültige Drucker-Nummer: {key}")
            rules = value.get("rules")
            if rules:
                unknown = set(rules) - set(countermeasures.RULES)
                if unknown:
                    raise HTTPException(400, f"Unbekannte Regel(n): {', '.join(sorted(unknown))}")
            cleaned[str(key)] = value
        update["printers"] = cleaned
    countermeasures.reset_memory()
    return countermeasures.save_config(update)


@router.post("/countermeasures/{printer_id}/action")
async def run_manual_action(
    printer_id: int,
    payload: ManualActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Einen Sofort-Eingriff senden (nur während des Drucks, mit Audit-Log)."""
    from backend.app.services.printer_manager import printer_manager

    printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Drucker nicht gefunden")
    state = printer_manager.get_status(printer_id)
    if state is None:
        raise HTTPException(400, "Drucker ist nicht verbunden")
    model = printer_manager.get_model(printer_id) or printer.model
    result = countermeasures.apply_manual(
        printer_id, payload.action_id, printer_manager.get_client(printer_id), state, model
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "Eingriff fehlgeschlagen")
    return result


@router.get("/countermeasures/log")
async def get_action_log(
    limit: int = Query(default=30, ge=1, le=200),
    printer_id: int | None = Query(default=None),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Letzte Gegenmaßnahmen (Trockenlauf und echte Eingriffe) aus dem Audit-Log."""
    entries = audit_log.entries(limit=200, printer_id=printer_id)
    selected = [
        entry for entry in entries if str(entry.get("action", "")).startswith(("countermeasure:", "errorhelp:"))
    ]
    return selected[:limit]

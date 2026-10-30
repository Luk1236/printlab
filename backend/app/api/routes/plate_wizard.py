"""API: Einmess-Assistent für den Plattenwechsel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services import plate_wizard

router = APIRouter(prefix="/printers", tags=["plate-wizard"])


class StepPayload(BaseModel):
    x: float | None = Field(None, ge=-500, le=500, description="X in mm")
    y: float | None = Field(None, ge=-500, le=500, description="Y in mm")
    z: float | None = Field(None, ge=-400, le=400, description="Z in mm")
    confirmed: bool | None = None
    sensor: bool | None = None
    note: str | None = Field(None, max_length=300)


class CompletePayload(BaseModel):
    operator: str = Field("", max_length=80, description="Wer hat eingemessen?")


async def _printer(printer_id: int, db: AsyncSession) -> Printer:
    printer = await db.scalar(select(Printer).where(Printer.id == printer_id))
    if printer is None:
        raise HTTPException(404, "Drucker nicht gefunden.")
    return printer


@router.get("/{printer_id}/hardware/plate-wizard")
async def get_wizard(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Stand des Assistenten: Schritte, fehlende Schritte, abgeschlossen und Sperre."""
    await _printer(printer_id, db)
    state = plate_wizard.status(printer_id)
    return {**state, "blocks_plate_change": bool(plate_wizard.blocks_plate_change(printer_id))}


@router.put("/{printer_id}/hardware/plate-wizard/steps/{step}")
async def save_wizard_step(
    printer_id: int,
    step: str,
    payload: StepPayload,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer(printer_id, db)
    try:
        return plate_wizard.save_step(printer_id, step, payload.model_dump(exclude_none=True))
    except plate_wizard.WizardError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{printer_id}/hardware/plate-wizard/complete")
async def complete_wizard(
    printer_id: int,
    payload: CompletePayload,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer(printer_id, db)
    try:
        return plate_wizard.complete(printer_id, payload.operator)
    except plate_wizard.WizardError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{printer_id}/hardware/plate-wizard/reset")
async def reset_wizard(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer(printer_id, db)
    return plate_wizard.reset(printer_id)


@router.get("/{printer_id}/hardware/plate-wizard/report", response_class=PlainTextResponse)
async def wizard_report(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Einmessprotokoll zum Ablegen: Werte, Prüfungen, wer wann eingemessen hat."""
    printer = await _printer(printer_id, db)
    state = plate_wizard.status(printer_id)
    lines = [
        f"Einmessprotokoll Plattenwechsel — {printer.name}",
        f"Stand: {state.get('completed_at') or state.get('started_at') or 'nicht begonnen'}",
        f"Eingemessen von: {state.get('operator') or '—'}",
        "",
    ]
    labels = {
        "reference": "Referenzpunkt",
        "pickup": "Aufnahmeposition",
        "drop": "Ablageposition",
        "magazine": "Übergabe Magazin",
        "door": "Tür / Endschalter",
        "dry_run": "Probelauf ohne Platte",
    }
    for step in plate_wizard.STEPS:
        entry = state["steps"].get(step)
        if entry is None:
            lines.append(f"{labels[step]}: offen")
            continue
        if "position" in entry:
            pos = entry["position"]
            detail = f"X={pos['x']:.2f} Y={pos['y']:.2f} Z={pos['z']:.2f} mm"
        else:
            detail = "bestätigt" + (" (Endschalter meldet)" if entry.get("sensor") else " (ohne Endschalter)")
        note = f" — {entry['note']}" if entry.get("note") else ""
        lines.append(f"{labels[step]}: {detail}{note} ({entry.get('at')})")
    if state["position_problem"]:
        lines += ["", f"Prüfhinweis: {state['position_problem']}"]
    lines += [
        "",
        "Hinweis: Die Bewegungsfolge selbst ist hier nicht erzeugt. Sie muss am Gerät",
        "erprobt und freigegeben werden; dieses Protokoll hält nur die Messwerte fest.",
    ]
    name = "".join(ch for ch in printer.name if ch.isalnum() or ch in "-_") or str(printer_id)
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        headers={"Content-Disposition": f'attachment; filename="Einmessprotokoll-{name}.txt"'},
    )

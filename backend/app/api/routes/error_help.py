"""Fehlerhilfe: Fehlerbild-Bibliothek und optionale Gegenmaßnahmen am Druck.

Lesen (Katalog und Einstellungen) braucht ``PRINTERS_READ``, Änderungen an den
Gegenmaßnahmen ``SETTINGS_UPDATE``, ein Sofort-Eingriff am laufenden Druck
``PRINTERS_CONTROL``. Jeder Eingriff wird im Audit-Log protokolliert.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.models.user import User
from backend.app.services import (
    ai_error_scan,
    assistant_config,
    assistant_llm,
    audit_log,
    countermeasures,
    error_patterns,
    local_ai_watch,
)
from backend.app.utils import failure_images

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


class AiScanConfig(BaseModel):
    vision_model: str | None = Field(default=None, max_length=100)
    error_scan_enabled: bool | None = None
    error_scan_min_confidence: int | None = Field(default=None, ge=0, le=100)
    error_scan_notify: bool | None = None


async def _ai_payload() -> dict:
    config = assistant_config.read(settings.base_dir)
    server = await assistant_llm.status(config)
    vision_model = str(config.get("vision_model") or config.get("model") or "")
    return {
        "config": {
            "vision_model": config.get("vision_model", ""),
            "error_scan_enabled": bool(config.get("error_scan_enabled", False)),
            "error_scan_min_confidence": int(config.get("error_scan_min_confidence", 60)),
            "error_scan_notify": bool(config.get("error_scan_notify", True)),
            "model": config.get("model", ""),
        },
        "server": server,
        "vision_model": vision_model,
        "vision_present": vision_model in (server.get("models") or []),
        "findings": ai_error_scan.list_findings(30),
        "counts": ai_error_scan.counts(),
        "feedback": ai_error_scan.feedback_summary(),
        "feedback_by_pattern": ai_error_scan.feedback_by_pattern(),
        "batch": ai_error_scan.batch_status(),
    }


class FeedbackRequest(BaseModel):
    verdict: Literal["correct", "wrong"]


class BatchRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class WatchConfigRequest(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=120, le=86400)
    min_confidence: int | None = Field(default=None, ge=0, le=100)
    min_consecutive: int | None = Field(default=None, ge=1, le=10)
    action: Literal["notify", "pause"] | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    printers: list[int] | None = None
    frames: int | None = Field(default=None, ge=1, le=3)
    frame_gap_seconds: int | None = Field(default=None, ge=1, le=15)
    thresholds: dict[str, int] | None = None


class WatchCheckRequest(BaseModel):
    printer_id: int | None = None


@router.get("/ai-scan")
async def get_ai_scan(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """KI-Fehlererkennung: Einstellungen, Modellstatus, Treffer und Zählungen."""
    return await _ai_payload()


@router.put("/ai-scan")
async def put_ai_scan(
    payload: AiScanConfig,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Bildmodell, Freigabe und Mindest-Sicherheit ändern."""
    update = payload.model_dump(exclude_none=True)
    try:
        assistant_config.write(settings.base_dir, update)
    except assistant_config.AssistantConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await _ai_payload()


@router.post("/ai-scan/upload")
async def scan_upload(
    file: UploadFile = File(...),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Ein hochgeladenes Bild klassifizieren und den Treffer ablegen."""
    image = await file.read()
    if not image:
        raise HTTPException(400, "Die Datei ist leer.")
    try:
        result = await ai_error_scan.scan_and_record(image, source="upload")
    except ai_error_scan.AiScanError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"result": result, "findings": ai_error_scan.list_findings(30), "counts": ai_error_scan.counts()}


@router.post("/ai-scan/failure-image/{name}")
async def scan_failure_image(
    name: str,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.CAMERA_VIEW),
):
    """Ein Bild aus der Fehlerbild-Sammlung klassifizieren."""
    path = failure_images.find_failure_image(name)
    if path is None:
        raise HTTPException(404, "Fehlerbild nicht gefunden")
    try:
        image = await asyncio.to_thread(path.read_bytes)
        result = await ai_error_scan.scan_and_record(image, source="failure_image", image_name=name)
    except ai_error_scan.AiScanError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"result": result, "findings": ai_error_scan.list_findings(30), "counts": ai_error_scan.counts()}


@router.get("/ai-watch")
async def get_ai_watch(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Laufende lokale Fehlerüberwachung: Einstellungen und Zustand je Drucker."""
    return local_ai_watch.status()


@router.put("/ai-watch")
async def put_ai_watch(
    payload: WatchConfigRequest,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Abstand, Bestätigung, Aktion und Druckerauswahl ändern."""
    try:
        local_ai_watch.save_config(payload.model_dump(exclude_none=True))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return local_ai_watch.status()


@router.post("/ai-watch/check")
async def check_ai_watch(
    payload: WatchCheckRequest,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Sofort eine Runde prüfen (kann wegen des Bildmodells Minuten dauern)."""
    try:
        results = await local_ai_watch.check_once(payload.printer_id)
    except ai_error_scan.AiScanError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"results": results, "status": local_ai_watch.status()}


@router.get("/ai-scan/findings")
async def get_ai_findings(
    limit: int = Query(default=50, ge=1, le=200),
    pattern_id: str | None = Query(default=None),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Erkannte Fehlerbilder, neueste zuerst."""
    return {"findings": ai_error_scan.list_findings(limit, pattern_id), "counts": ai_error_scan.counts()}


@router.post("/ai-scan/findings/{finding_id}/feedback")
async def rate_finding(
    finding_id: str,
    payload: FeedbackRequest,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Rückmeldung zu einem Treffer: richtig oder falsch."""
    try:
        ai_error_scan.record_feedback(finding_id, payload.verdict)
    except KeyError as exc:
        raise HTTPException(404, "Treffer nicht gefunden") from exc
    return {
        "findings": ai_error_scan.list_findings(30),
        "feedback": ai_error_scan.feedback_summary(),
        "feedback_by_pattern": ai_error_scan.feedback_by_pattern(),
    }


@router.post("/ai-scan/scan-collection")
async def scan_collection(
    payload: BatchRequest,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Gesammelte Fehlerbilder im Hintergrund durchprüfen."""
    try:
        status = ai_error_scan.start_batch(payload.limit)
    except ai_error_scan.AiScanError as exc:
        raise HTTPException(400, str(exc)) from exc
    return status


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
    error = countermeasures.threshold_error(countermeasures.merged_config(update))
    if error:
        raise HTTPException(400, error)
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

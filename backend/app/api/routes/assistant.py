"""Lokaler KI-Assistent: Einstellungen, Erreichbarkeit des Modell-Servers und Chat.

Das Modell läuft auf einem lokalen Modell-Server (Ollama o. ä., siehe ``services/assistant_llm.py``). Der Assistent liest eine
kleine Datenübersicht (Drucker, Warteschlange, Prognose) und kann Änderungen nur *vorschlagen*; ausgeführt werden sie erst
nach Bestätigung in der Oberfläche über die normalen Warteschlangen-Funktionen.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import assistant_actions, assistant_config, assistant_context, assistant_llm
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])

_lock = assistant_llm.LOCK  # der Pi schafft nur eine Antwort zur Zeit


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    lang: Literal["de", "en"] = "de"


@router.get("/status")
async def get_status(_=RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ)):
    """Einstellungen und ob der Modell-Server erreichbar ist (und das gewählte Modell hat)."""
    config = assistant_config.read(settings.base_dir)
    return {"config": config, "server": await assistant_llm.status(config)}


@router.put("/config")
async def set_config(payload: dict, _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE)):
    try:
        config = assistant_config.write(settings.base_dir, payload)
    except assistant_config.AssistantConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"config": config, "server": await assistant_llm.status(config)}


@router.post("/chat")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.QUEUE_READ_ALL),
):
    """Eine Frage an den Assistenten; Antwort mit geprüften Aktionsvorschlägen (ohne etwas zu ändern)."""
    config = assistant_config.read(settings.base_dir)
    if not config["enabled"]:
        raise HTTPException(409, "Der Assistent ist ausgeschaltet. Schalte ihn unter Wartung → Assistent ein.")
    if body.messages[-1].role != "user":
        raise HTTPException(400, "Die letzte Nachricht muss vom Benutzer sein.")
    if _lock.locked():
        raise HTTPException(429, "Der Assistent beantwortet gerade eine andere Frage. Bitte kurz warten.")
    async with _lock:
        started = time.monotonic()
        data, pending = await assistant_context.snapshot(db, printer_manager.get_status)
        header = "DATEN" if body.lang != "en" else "DATA"
        messages = [{"role": "system", "content": f"{assistant_context.system_prompt(body.lang)}\n\n{header}:\n{data}"}]
        messages += [{"role": m.role, "content": m.content} for m in body.messages]
        try:
            reply = await assistant_llm.chat(config, messages)
        except assistant_llm.AssistantError as exc:
            raise HTTPException(502, str(exc)) from exc
    text, raw_actions = assistant_actions.split_reply(reply)
    actions, rejected = assistant_actions.validate(raw_actions, pending, body.lang)
    return {"reply": text, "actions": actions, "rejected": rejected, "seconds": round(time.monotonic() - started, 1)}


# Das Modell hängt seine Aktionsliste an ``ACTIONS:`` an — dieser Teil wird im
# Live-Text zurückgehalten und nur im Abschluss-Ereignis geprüft ausgegeben.
_ACTION_MARKER = "ACTIONS:"
_ACTION_MARKER_PREFIXES = [_ACTION_MARKER[: i + 1] for i in range(len(_ACTION_MARKER))]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat-stream")
async def chat_stream(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.QUEUE_READ_ALL),
):
    """Wie /chat, aber die Antwort kommt Wort für Wort (SSE); Aktionen nur im Abschluss-Ereignis.

    Ereignisse: ``{type: "delta", text}``, ``{type: "done", reply, actions, rejected, seconds}``,
    ``{type: "error", detail}``. Die Bestätigungslogik bleibt unangetastet — ein Delta kann
    keinerlei Änderung auslösen; Aktionen kommen geprüft und nur am Ende.
    """
    config = assistant_config.read(settings.base_dir)
    if not config["enabled"]:
        raise HTTPException(409, "Der Assistent ist ausgeschaltet. Schalte ihn unter Wartung → Assistent ein.")
    if body.messages[-1].role != "user":
        raise HTTPException(400, "Die letzte Nachricht muss vom Benutzer sein.")
    if _lock.locked():
        raise HTTPException(429, "Der Assistent beantwortet gerade eine andere Frage. Bitte kurz warten.")

    started = time.monotonic()

    async def _events():
        await _lock.acquire()
        try:
            try:
                data, pending = await assistant_context.snapshot(db, printer_manager.get_status)
                header = "DATEN" if body.lang != "en" else "DATA"
                messages = [
                    {"role": "system", "content": f"{assistant_context.system_prompt(body.lang)}\n\n{header}:\n{data}"}
                ]
                messages += [{"role": m.role, "content": m.content} for m in body.messages]
                buffer = ""
                sent_upto = 0
                async for piece in assistant_llm.chat_stream(config, messages):
                    buffer += piece
                    marker_at = buffer.find(_ACTION_MARKER)
                    if marker_at == -1:
                        # einen möglichen unvollständigen Marker am Ende zurückhalten
                        emit_to = len(buffer)
                        for prefix in _ACTION_MARKER_PREFIXES[:-1]:
                            if buffer.endswith(prefix):
                                emit_to = len(buffer) - len(prefix)
                                break
                        if emit_to > sent_upto:
                            yield _sse({"type": "delta", "text": buffer[sent_upto:emit_to]})
                            sent_upto = emit_to
                    else:
                        if marker_at > sent_upto:
                            yield _sse({"type": "delta", "text": buffer[sent_upto:marker_at]})
                            sent_upto = marker_at
                text, raw_actions = assistant_actions.split_reply(buffer)
                actions, rejected = assistant_actions.validate(raw_actions, pending, body.lang)
                yield _sse(
                    {
                        "type": "done",
                        "reply": text,
                        "actions": actions,
                        "rejected": rejected,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )
            except assistant_llm.AssistantError as exc:
                yield _sse({"type": "error", "detail": str(exc)})
        finally:
            _lock.release()

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

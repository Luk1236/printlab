"""Telegram bot command handler for PrintLab.

Handles interactive chat commands received via getUpdates:
- /status: Overview of active printers, print progress, ETA, and temperatures
- /live, /foto, /photo, /snap: Live camera snapshot directly in Telegram chat with control buttons
- /pause: Pause current active print
- /resume, /weiter: Resume current paused print
- /licht, /light: Toggle chamber light
- /stop, /abbrechen: Safe cancellation prompt for current print
- /help, /start: Command listing and guidance
- callback_query: Button interactions (live photo, pause, resume, light, stop)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

from backend.app.core.database import async_session
from backend.app.models.printer import Printer
from backend.app.services.notification_service import telegram_markdown_escape
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)


async def resolve_target_printer(printer_id: int | None = None) -> Printer | None:
    """Find target printer by id or pick currently printing printer."""
    active_printers: list[Printer] = []
    try:
        async with async_session() as db:
            query = select(Printer).where(Printer.is_active.is_(True))
            result = await db.execute(query)
            active_printers = list(result.scalars().all())
    except Exception as exc:
        logger.debug("Failed to resolve printer from DB: %s", exc)

    if not active_printers:
        return None

    if printer_id is not None:
        target = next((p for p in active_printers if p.id == printer_id), None)
        if target:
            return target

    # Prefer a printer that is currently actively printing
    for p in active_printers:
        st = printer_manager.get_status(p.id)
        if st and st.state in ("RUNNING", "PAUSE"):
            return p

    return active_printers[0]


def build_printer_inline_keyboard(printer_id: int | None) -> list[list[dict[str, str]]]:
    """Build interactive action inline keyboard for a specific printer."""
    if printer_id is None:
        return [[{"text": "📷 Aktualisieren", "callback_data": "cmd:live"}]]

    st = printer_manager.get_status(printer_id)
    state = (st.state if st else "").upper()

    row1 = [
        {"text": "📷 Aktualisieren", "callback_data": f"cmd:live:{printer_id}"},
        {"text": "💡 Licht", "callback_data": f"cmd:light:{printer_id}"},
    ]

    keyboard = [row1]
    if state == "RUNNING":
        keyboard.append(
            [
                {"text": "⏸️ Pause", "callback_data": f"cmd:pause:{printer_id}"},
                {"text": "⏹️ Stopp", "callback_data": f"cmd:stop:{printer_id}"},
            ]
        )
    elif state == "PAUSE":
        keyboard.append(
            [
                {"text": "▶️ Weiter", "callback_data": f"cmd:resume:{printer_id}"},
                {"text": "⏹️ Stopp", "callback_data": f"cmd:stop:{printer_id}"},
            ]
        )

    return keyboard


async def capture_live_snapshot(printer_id: int | None = None) -> tuple[bytes | None, str, str]:
    """Capture a live camera snapshot from the target or currently printing printer.

    Returns:
        tuple of (image_bytes or None, printer_name, status_summary_markdown)
    """
    target_printer = await resolve_target_printer(printer_id)
    if not target_printer:
        return None, "Kein Drucker", "Keine aktiven Drucker in PrintLab eingerichtet."

    printer_name = target_printer.name or f"Drucker {target_printer.id}"
    st = printer_manager.get_status(target_printer.id)

    # Build status caption
    caption_lines = [f"📷 *{telegram_markdown_escape(printer_name)}*"]
    if st and st.state in ("RUNNING", "PAUSE"):
        icon = "⏸️ Pausiert" if st.state == "PAUSE" else "🟢 Druckt"
        file_name = st.subtask_name or st.current_print or st.gcode_file or "Unbenannt"
        caption_lines.append(f"{icon}: `{telegram_markdown_escape(file_name)}` ({int(st.progress)}%)")

        details = []
        if st.remaining_time and st.remaining_time > 0:
            hrs = st.remaining_time // 60
            mins = st.remaining_time % 60
            eta_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
            details.append(f"noch {eta_str}")
        if st.total_layers and st.total_layers > 0:
            details.append(f"Layer {st.layer_num}/{st.total_layers}")
        if details:
            caption_lines.append("• " + " • ".join(details))
    else:
        caption_lines.append("⚪ *Bereit / Leerlauf*")

    # Add temperatures if reported
    if st and isinstance(st.temperatures, dict):
        temp_parts = []
        nozzle = st.temperatures.get("nozzle")
        if nozzle is not None and nozzle > 0:
            temp_parts.append(f"Düse: {int(nozzle)}°C")
        bed = st.temperatures.get("bed")
        if bed is not None and bed > 0:
            temp_parts.append(f"Bett: {int(bed)}°C")
        chamber = st.temperatures.get("chamber")
        if chamber is not None and chamber > 0:
            temp_parts.append(f"Bauraum: {int(chamber)}°C")
        if temp_parts:
            caption_lines.append("• " + " | ".join(temp_parts))

    caption = "\n".join(caption_lines)

    # Attempt capture: external camera -> buffered fan-out frame -> fresh frame
    frame_data: bytes | None = None
    try:
        # 1. External camera
        if target_printer.external_camera_enabled and target_printer.external_camera_url:
            from backend.app.api.routes.camera import live_frame_for_capture
            from backend.app.services.external_camera import capture_frame

            defer, buffered = live_frame_for_capture(target_printer.id)
            if defer and buffered:
                frame_data = buffered
            else:
                frame_data = await capture_frame(
                    target_printer.external_camera_url,
                    target_printer.external_camera_type or "mjpeg",
                    snapshot_url=target_printer.external_camera_snapshot_url,
                    timeout=12,
                )

        # 2. Buffered frame from active live-stream fanout
        if not frame_data:
            from backend.app.api.routes.camera import (
                _active_chamber_streams,
                _active_streams,
                get_buffered_frame,
            )

            active_streams = [k for k in _active_streams if k.startswith(f"{target_printer.id}-")]
            active_chamber = [k for k in _active_chamber_streams if k.startswith(f"{target_printer.id}-")]
            if active_streams or active_chamber:
                buffered = get_buffered_frame(target_printer.id)
                if buffered and len(buffered) <= 2_500_000:
                    frame_data = buffered

        # 3. Fresh socket capture
        if not frame_data:
            from backend.app.services.camera import capture_camera_frame_bytes

            frame_data = await capture_camera_frame_bytes(
                target_printer.ip_address,
                target_printer.access_code,
                target_printer.model,
                timeout=12,
            )

        # Apply rotation if configured
        if frame_data and target_printer.camera_rotation:
            from backend.app.services.camera import apply_camera_rotation

            frame_data = apply_camera_rotation(frame_data, target_printer.camera_rotation, logger)

    except Exception as exc:
        logger.warning("Live snapshot capture failed for printer %s: %s", target_printer.id, exc)

    return frame_data, printer_name, caption


async def format_printers_status() -> tuple[str, list[list[dict]] | None]:
    """Format status of all active printers with an inline photo action button."""
    async with async_session() as db:
        query = select(Printer).where(Printer.is_active.is_(True))
        result = await db.execute(query)
        printers = list(result.scalars().all())

    if not printers:
        return "🖨️ *PrintLab*\nKeine aktiven Drucker eingerichtet.", None

    lines = ["🖨️ *PrintLab Drucker-Status*\n"]

    for p in printers:
        st = printer_manager.get_status(p.id)
        pname = telegram_markdown_escape(p.name or f"Drucker {p.id}")

        if not st or not st.connected:
            lines.append(f"🔴 *{pname}* — Offline / Nicht verbunden\n")
            continue

        if st.state in ("RUNNING", "PAUSE"):
            icon = "⏸️" if st.state == "PAUSE" else "🟢"
            file_name = telegram_markdown_escape(st.subtask_name or st.current_print or st.gcode_file or "Unbekannt")
            lines.append(f"{icon} *{pname}* — {st.state.capitalize()}")
            lines.append(f"• Datei: `{file_name}` ({int(st.progress)}%)")

            details = []
            if st.remaining_time and st.remaining_time > 0:
                hrs = st.remaining_time // 60
                mins = st.remaining_time % 60
                eta_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
                details.append(f"noch {eta_str}")
            if st.total_layers and st.total_layers > 0:
                details.append(f"Layer {st.layer_num}/{st.total_layers}")
            if details:
                lines.append("• " + " • ".join(details))
        else:
            lines.append(f"⚪ *{pname}* — Bereit / Leerlauf")

        if isinstance(st.temperatures, dict):
            temp_parts = []
            nozzle = st.temperatures.get("nozzle")
            if nozzle is not None and nozzle > 0:
                temp_parts.append(f"Düse: {int(nozzle)}°C")
            bed = st.temperatures.get("bed")
            if bed is not None and bed > 0:
                temp_parts.append(f"Bett: {int(bed)}°C")
            if temp_parts:
                lines.append("• " + " | ".join(temp_parts))
        lines.append("")

    keyboard = [[{"text": "📷 Live-Foto", "callback_data": "cmd:live"}]]
    return "\n".join(lines).strip(), keyboard


async def send_live_photo(
    bot_token: str,
    chat_id: str,
    message_thread_id: int | None,
    http_client: httpx.AsyncClient,
    printer_id: int | None = None,
) -> None:
    """Capture live camera photo and send it as a photo message to Telegram."""
    try:
        act_data: dict[str, Any] = {"chat_id": chat_id, "action": "upload_photo"}
        if message_thread_id is not None:
            act_data["message_thread_id"] = message_thread_id
        await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendChatAction", json=act_data)
    except Exception:
        logger.debug("Fehler ignoriert", exc_info=True)

    target = await resolve_target_printer(printer_id)
    target_id = target.id if target else printer_id
    keyboard = build_printer_inline_keyboard(target_id)

    frame_data, printer_name, caption = await capture_live_snapshot(printer_id)

    if frame_data:
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        form: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps({"inline_keyboard": keyboard}),
        }
        if message_thread_id is not None:
            form["message_thread_id"] = message_thread_id
        await http_client.post(
            url,
            data=form,
            files={"photo": ("live.jpg", frame_data, "image/jpeg")},
        )
    else:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        msg = f"⚠️ Live-Foto für *{telegram_markdown_escape(printer_name)}* konnte nicht abgerufen werden.\n\n{caption}"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        await http_client.post(url, json=payload)


async def send_status_message(
    bot_token: str,
    chat_id: str,
    message_thread_id: int | None,
    http_client: httpx.AsyncClient,
) -> None:
    """Format and send the status message with an inline photo action button."""
    text, keyboard = await format_printers_status()
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}

    await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)


async def handle_telegram_message(
    bot_token: str,
    message: dict,
    allowed_chat_ids: set[str],
    http_client: httpx.AsyncClient,
) -> None:
    """Handle incoming Telegram text commands."""
    chat_id = str((message.get("chat") or {}).get("id", "")).strip()
    text = (message.get("text") or "").strip()
    message_thread_id = message.get("message_thread_id")

    if not chat_id or not text:
        return

    # Check authorization against configured provider chats
    if allowed_chat_ids and chat_id not in allowed_chat_ids:
        logger.warning("[TELEGRAM-CMD] Unauthorized chat %s sent: %s", chat_id, text)
        await http_client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": "⛔ Dieser Chat ist nicht für PrintLab autorisiert."},
        )
        return

    # Command token without '@botname' and lowercase
    cmd = text.split()[0].lower().split("@")[0]

    if cmd in ("/live", "/foto", "/photo", "/snap"):
        await send_live_photo(bot_token, chat_id, message_thread_id, http_client)
    elif cmd in ("/status", "/drucker"):
        await send_status_message(bot_token, chat_id, message_thread_id, http_client)
    elif cmd in ("/pause",):
        target = await resolve_target_printer()
        if target:
            client = printer_manager.get_client(target.id)
            if client:
                client.pause_print()
                p_name = telegram_markdown_escape(target.name or f"Drucker {target.id}")
                await http_client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": f"⏸️ Druckauftrag auf *{p_name}* pausiert.",
                        "parse_mode": "Markdown",
                    },
                )
    elif cmd in ("/resume", "/weiter"):
        target = await resolve_target_printer()
        if target:
            client = printer_manager.get_client(target.id)
            if client:
                client.resume_print()
                p_name = telegram_markdown_escape(target.name or f"Drucker {target.id}")
                await http_client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": f"▶️ Druckauftrag auf *{p_name}* fortgesetzt.",
                        "parse_mode": "Markdown",
                    },
                )
    elif cmd in ("/licht", "/light"):
        target = await resolve_target_printer()
        if target:
            client = printer_manager.get_client(target.id)
            if client and client.state:
                new_l = not bool(client.state.chamber_light)
                client.set_chamber_light(new_l)
                s = "eingeschaltet 💡" if new_l else "ausgeschaltet 🌑"
                p_name = telegram_markdown_escape(target.name or f"Drucker {target.id}")
                await http_client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": f"💡 Gehäusebeleuchtung auf *{p_name}* {s}.",
                        "parse_mode": "Markdown",
                    },
                )
    elif cmd in ("/stop", "/abbrechen"):
        target = await resolve_target_printer()
        if target:
            pid = target.id
            p_name = telegram_markdown_escape(target.name or f"Drucker {pid}")
            confirm_kb = [
                [
                    {"text": "⚠️ Ja, Druck abbrechen", "callback_data": f"cmd:stop_confirm:{pid}"},
                    {"text": "❌ Nein, weiterdrucken", "callback_data": "cmd:dismiss"},
                ]
            ]
            await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"⚠️ *Druck wirklich abbrechen?*\nSoll der laufende Druck auf *{p_name}* wirklich gestoppt werden?",
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": confirm_kb},
                },
            )
    elif cmd in ("/help", "/hilfe", "/start"):
        help_text = (
            "👋 *PrintLab Telegram-Assistent*\n\n"
            "Verfügbare Befehle:\n"
            "• `/status` – Aktueller Druckstatus & Temperaturen\n"
            "• `/live` oder `/foto` – Aktuelles Live-Foto aus dem Bauraum\n"
            "• `/pause` – Laufenden Druck pausieren\n"
            "• `/resume` – Pausierten Druck fortsetzen\n"
            "• `/licht` – Gehäusebeleuchtung umschalten\n"
            "• `/stop` – Laufenden Druck sicher abbrechen\n"
            "• `/help` – Diese Hilfe"
        )
        payload = {
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        await http_client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)


async def handle_telegram_callback_query(
    bot_token: str,
    callback_query: dict,
    allowed_chat_ids: set[str],
    http_client: httpx.AsyncClient,
) -> None:
    """Handle inline button callback queries (live photo, pause, resume, light, stop)."""
    query_id = callback_query.get("id")
    data = callback_query.get("data", "")
    msg = callback_query.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", "")).strip()
    message_thread_id = msg.get("message_thread_id")

    if allowed_chat_ids and chat_id not in allowed_chat_ids:
        return

    # Parse command and optional printer_id: cmd:action[:printer_id]
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    target_id: int | None = None
    if len(parts) > 2 and parts[2].isdigit():
        target_id = int(parts[2])

    answer_text = ""
    if action == "live":
        answer_text = "📷 Foto wird abgerufen..."
    elif action == "light":
        answer_text = "💡 Licht wird umgeschaltet..."
    elif action == "pause":
        answer_text = "⏸️ Pause wird gesendet..."
    elif action == "resume":
        answer_text = "▶️ Fortsetzen wird gesendet..."
    elif action == "stop":
        answer_text = "⚠️ Bestätigung erforderlich"
    elif action == "stop_confirm":
        answer_text = "⏹️ Druck wird gestoppt..."
    elif action == "dismiss":
        answer_text = "Abgebrochen."

    if query_id:
        try:
            await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                json={
                    "callback_query_id": query_id,
                    "text": answer_text,
                },
            )
        except Exception:
            logger.debug("Fehler ignoriert", exc_info=True)

    if action == "live" or data == "cmd:live":
        await send_live_photo(bot_token, chat_id, message_thread_id, http_client, target_id)

    elif action == "light":
        client = printer_manager.get_client(target_id) if target_id else None
        if not client:
            target = await resolve_target_printer(target_id)
            if target:
                client = printer_manager.get_client(target.id)
        if client and client.state:
            new_light = not bool(client.state.chamber_light)
            client.set_chamber_light(new_light)
            state_str = "eingeschaltet 💡" if new_light else "ausgeschaltet 🌑"
            p_name = telegram_markdown_escape(client.printer_name or f"Drucker {client.printer_id}")
            await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"💡 Gehäusebeleuchtung für *{p_name}* {state_str}.",
                    "parse_mode": "Markdown",
                    **({"message_thread_id": message_thread_id} if message_thread_id is not None else {}),
                },
            )

    elif action == "pause":
        client = printer_manager.get_client(target_id) if target_id else None
        if not client:
            target = await resolve_target_printer(target_id)
            if target:
                client = printer_manager.get_client(target.id)
        if client:
            client.pause_print()
            p_name = telegram_markdown_escape(client.printer_name or f"Drucker {client.printer_id}")
            await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"⏸️ Druckauftrag auf *{p_name}* wurde pausiert.",
                    "parse_mode": "Markdown",
                    **({"message_thread_id": message_thread_id} if message_thread_id is not None else {}),
                },
            )

    elif action == "resume":
        client = printer_manager.get_client(target_id) if target_id else None
        if not client:
            target = await resolve_target_printer(target_id)
            if target:
                client = printer_manager.get_client(target.id)
        if client:
            client.resume_print()
            p_name = telegram_markdown_escape(client.printer_name or f"Drucker {client.printer_id}")
            await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"▶️ Druckauftrag auf *{p_name}* wird fortgesetzt.",
                    "parse_mode": "Markdown",
                    **({"message_thread_id": message_thread_id} if message_thread_id is not None else {}),
                },
            )

    elif action == "stop":
        target = await resolve_target_printer(target_id)
        pid = target.id if target else (target_id or 1)
        p_name = telegram_markdown_escape(target.name if target else f"Drucker {pid}")
        confirm_kb = [
            [
                {"text": "⚠️ Ja, Druck abbrechen", "callback_data": f"cmd:stop_confirm:{pid}"},
                {"text": "❌ Nein, weiterdrucken", "callback_data": "cmd:dismiss"},
            ]
        ]
        await http_client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"⚠️ *Druck wirklich abbrechen?*\nSoll der laufende Druck auf *{p_name}* wirklich gestoppt werden?",
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": confirm_kb},
                **({"message_thread_id": message_thread_id} if message_thread_id is not None else {}),
            },
        )

    elif action == "stop_confirm":
        client = printer_manager.get_client(target_id) if target_id else None
        if not client:
            target = await resolve_target_printer(target_id)
            if target:
                client = printer_manager.get_client(target.id)
        if client:
            client.stop_print()
            p_name = telegram_markdown_escape(client.printer_name or f"Drucker {client.printer_id}")
            await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"⏹️ Druckauftrag auf *{p_name}* wurde abgebrochen.",
                    "parse_mode": "Markdown",
                    **({"message_thread_id": message_thread_id} if message_thread_id is not None else {}),
                },
            )

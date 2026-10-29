"""Systemprüfung: prüft in einem Durchlauf, ob die wichtigen Teile von PrintLab wirklich laufen.

Gelesen werden Datenbank, Planer, Termin-Überwachung, Drucker, Prognose, Meldekanäle, Sicherungen, Gerätezustand, Anmeldung und
Update-Schutz. Zwei Proben haben Nebenwirkungen und laufen bewusst mit: eine Probemeldung über die Kanäle, die „Termin in
Gefahr" haben wollen, und eine Probefrage an das Modell des Assistenten. Jede Prüfung ist unabhängig; eine, die selbst
fehlschlägt, wird als Fehler gemeldet und stoppt die anderen nicht. Texte kommen in der Sprache der Anfrage (de oder en).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


def L(de: str, en: str) -> dict[str, str]:
    return {"de": de, "en": en}


@dataclass
class Result:
    id: str
    status: str
    detail: dict[str, str]
    fix: dict[str, str] | None = None


@dataclass
class Deps:
    db: AsyncSession
    data_dir: Path
    now: datetime
    scheduler_running: Callable[[], bool]
    printer_connected: Callable[[int], bool]
    due_watch_state: dict[str, Any]
    assistant_config: dict[str, Any]
    assistant_status: Callable[[dict], Awaitable[dict]]
    assistant_probe: Callable[[dict], Awaitable[float]]
    send_test_notification: Callable[[AsyncSession], Awaitable[tuple[int, list[str]]]]
    health: Callable[[Path], dict]
    guard_state: Callable[[], str]
    auth_enabled: Callable[[AsyncSession], Awaitable[bool]]
    due_watch_interval: float = 300.0
    extra: dict[str, Any] = field(default_factory=dict)


TITLES = {
    "database": L("Datenbank", "Database"),
    "scheduler": L("Druckplaner", "Print scheduler"),
    "due_watch": L("Termin-Überwachung", "Due-date watch"),
    "printers": L("Drucker", "Printers"),
    "forecast": L("Prognose der Warteschlange", "Queue forecast"),
    "channels": L("Meldekanäle", "Notification channels"),
    "probe_notification": L("Probemeldung „Termin in Gefahr“", "Test message “due date at risk”"),
    "assistant": L("KI-Assistent", "AI assistant"),
    "probe_assistant": L("Probefrage an das Modell", "Test question to the model"),
    "backup": L("Sicherungen", "Backups"),
    "device": L("Zustand des Geräts", "Device health"),
    "auth": L("Anmeldung", "Sign-in"),
    "update_guard": L("Update-Schutz", "Update guard"),
}

DEVICE_CODES = {
    "temp_critical": L("Der Prozessor ist sehr heiß.", "The processor is very hot."),
    "temp_hot": L("Der Prozessor ist heiß.", "The processor is hot."),
    "undervoltage": L("Unterspannung erkannt (Netzteil).", "Undervoltage detected (power supply)."),
    "throttled": L("Der Prozessor wurde gedrosselt.", "The processor was throttled."),
    "disk_low": L("Wenig Speicherplatz.", "Low disk space."),
    "sd_card": L("Die Daten liegen auf einer SD-Karte.", "The data lives on an SD card."),
    "memory_low": L("Wenig freier Arbeitsspeicher, kein Swap.", "Low free memory and no swap."),
}
BACKUP_CODES = {
    "backup_none": L("Es gibt noch keine Sicherung.", "There is no backup yet."),
    "backup_old": L("Die letzte Sicherung ist alt.", "The latest backup is old."),
    "external_failed": L("Die Sicherung nach außen ist fehlgeschlagen.", "The external backup failed."),
}


def _ago(moment: datetime, now: datetime) -> str:
    minutes = max(0, int((now - moment).total_seconds() // 60))
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h"


async def check_database(d: Deps) -> Result:
    missing = []
    for table, columns in (
        ("print_queue", "priority, due_at, due_risk_notified"),
        ("notification_providers", "on_queue_due_risk, on_invoice_reminder"),
        ("customers", "name, address"),
    ):
        try:
            await d.db.execute(text(f"SELECT {columns} FROM {table} LIMIT 0"))  # noqa: S608 (feste Namen)
        except Exception:
            await d.db.rollback()
            missing.append(table)
    if missing:
        return Result(
            "database",
            FAIL,
            L(f"Spalten fehlen in: {', '.join(missing)}.", f"Columns are missing in: {', '.join(missing)}."),
            L(
                "PrintLab neu starten, die Datenbank wird beim Start angepasst.",
                "Restart PrintLab; the database is upgraded on start.",
            ),
        )
    return Result("database", OK, L("Datenbank ist auf dem neuesten Stand.", "The database is up to date."))


async def check_scheduler(d: Deps) -> Result:
    if d.scheduler_running():
        return Result("scheduler", OK, L("Der Planer läuft.", "The scheduler is running."))
    return Result(
        "scheduler",
        FAIL,
        L(
            "Der Druckplaner läuft nicht: Aufträge starten nicht von allein.",
            "The print scheduler is not running: jobs will not start by themselves.",
        ),
        L(
            "PrintLab neu starten und das Protokoll ansehen (journalctl --user -u printlab).",
            "Restart PrintLab and look at the log (journalctl --user -u printlab).",
        ),
    )


async def check_due_watch(d: Deps) -> Result:
    state = d.due_watch_state
    started, last_run, error = state.get("started"), state.get("last_run"), state.get("last_error")
    if started is None:
        return Result(
            "due_watch", FAIL, L("Die Überwachung wurde nicht gestartet.", "The watch was not started."),
            L("PrintLab neu starten.", "Restart PrintLab."),
        )  # fmt: skip
    if error:
        return Result(
            "due_watch", WARN, L(f"Der letzte Durchlauf ist fehlgeschlagen: {error}", f"The last run failed: {error}"),
            L("Das Protokoll ansehen; die Überwachung versucht es weiter.", "Look at the log; the watch keeps trying."),
        )  # fmt: skip
    if last_run is None:
        waited = (d.now - started).total_seconds()
        if waited < 180:
            return Result(
                "due_watch", WARN,
                L("Wartet noch auf den ersten Durchlauf (er beginnt etwa eine Minute nach dem Start).", "Still waiting for the first run (it begins about a minute after start)."),
            )  # fmt: skip
        return Result(
            "due_watch",
            FAIL,
            L("Noch kein Durchlauf seit dem Start.", "No run since start."),
            L("PrintLab neu starten.", "Restart PrintLab."),
        )
    if (d.now - last_run).total_seconds() > 3 * d.due_watch_interval:
        return Result(
            "due_watch", WARN, L(f"Der letzte Durchlauf liegt {_ago(last_run, d.now)} zurück.", f"The last run was {_ago(last_run, d.now)} ago."),
            L("PrintLab neu starten, falls das so bleibt.", "Restart PrintLab if this persists."),
        )  # fmt: skip
    return Result(
        "due_watch", OK, L(f"Letzter Durchlauf vor {_ago(last_run, d.now)}.", f"Last run {_ago(last_run, d.now)} ago.")
    )


async def check_printers(d: Deps) -> Result:
    from backend.app.models.printer import Printer

    printers = list(
        (await d.db.execute(select(Printer).where(Printer.is_active.is_(True)).order_by(Printer.id))).scalars()
    )
    if not printers:
        return Result(
            "printers", WARN, L("Noch kein Drucker eingerichtet.", "No printer set up yet."),
            L("Unter „Drucker“ einen Drucker hinzufügen.", "Add a printer under “Printers”."),
        )  # fmt: skip
    offline = [p.name for p in printers if not d.printer_connected(p.id)]
    if not offline:
        return Result(
            "printers",
            OK,
            L(f"Alle {len(printers)} Drucker sind verbunden.", f"All {len(printers)} printers are connected."),
        )
    names = ", ".join(offline)
    return Result(
        "printers", WARN if len(offline) < len(printers) else FAIL,
        L(f"Nicht verbunden: {names}.", f"Not connected: {names}."),
        L("Drucker einschalten und die IP-Adresse und den Zugangscode prüfen.", "Switch the printer on and check its IP address and access code."),
    )  # fmt: skip


async def check_forecast(d: Deps) -> Result:
    from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant
    from backend.app.models.printer import Printer
    from backend.app.services.queue_forecast import forecast_ends

    items = list(
        (
            await d.db.execute(
                select(PrintQueueItem)
                .where(PrintQueueItem.status.in_(("pending", "printing")))
                .options(selectinload(PrintQueueItem.variants).selectinload(PrintQueueVariant.library_file))
            )
        ).scalars()
    )
    pending = [i for i in items if i.status == "pending" and not i.manual_start]
    if not pending:
        return Result(
            "forecast",
            OK,
            L("Keine wartenden Aufträge; es gibt nichts vorherzusagen.", "No waiting jobs; nothing to forecast."),
        )
    printers = list((await d.db.execute(select(Printer).where(Printer.is_active.is_(True)))).scalars())
    ends = forecast_ends(items, printers, {}, False, d.now)
    unknown = sum(1 for i in pending if not i.print_time_seconds)
    if unknown:
        return Result(
            "forecast", WARN,
            L(f"{unknown} von {len(pending)} Aufträgen haben keine Druckzeit und zählen nicht mit.", f"{unknown} of {len(pending)} jobs have no print time and are not counted."),
            L("Die Druckzeit stammt aus der Datei; Aufträge ohne Datei oder ungesliced haben keine.", "The print time comes from the file; jobs without a file or unsliced have none."),
        )  # fmt: skip
    unplaced = len(pending) - len(ends)
    if unplaced:
        return Result(
            "forecast", WARN,
            L(f"{unplaced} Aufträge lassen sich keinem Drucker zuordnen.", f"{unplaced} jobs cannot be placed on a printer."),
            L("Zieldrucker oder Modell des Auftrags prüfen.", "Check the job's target printer or model."),
        )  # fmt: skip
    return Result("forecast", OK, L(f"{len(pending)} Aufträge eingeplant.", f"{len(pending)} jobs scheduled."))


async def check_channels(d: Deps) -> Result:
    from backend.app.models.notification import NotificationProvider

    providers = list(
        (await d.db.execute(select(NotificationProvider).where(NotificationProvider.enabled.is_(True)))).scalars()
    )
    wanting = [p for p in providers if p.on_queue_due_risk]
    if not providers:
        return Result(
            "channels", WARN, L("Kein Meldekanal eingerichtet.", "No notification channel set up."),
            L("Einstellungen → Benachrichtigungen: ntfy, Telegram oder einen anderen Kanal anlegen.", "Settings → Notifications: add ntfy, Telegram or another channel."),
        )  # fmt: skip
    if not wanting:
        return Result(
            "channels", WARN, L("Kein Kanal hat „Termin in Gefahr“ eingeschaltet.", "No channel has “due date at risk” turned on."),
            L("Beim Kanal unter den Warteschlangen-Ereignissen einschalten.", "Turn it on at the channel under the queue events."),
        )  # fmt: skip
    return Result(
        "channels",
        OK,
        L(
            f"{len(providers)} Kanal/Kanäle aktiv, {len(wanting)} für „Termin in Gefahr“.",
            f"{len(providers)} channel(s) active, {len(wanting)} for “due date at risk”.",
        ),
    )


async def probe_notification(d: Deps) -> Result:
    try:
        sent, failed = await d.send_test_notification(d.db)
    except Exception as exc:
        logger.warning("selftest notification probe failed: %s", exc)
        return Result(
            "probe_notification",
            FAIL,
            L(f"Die Probemeldung ist fehlgeschlagen: {exc}", f"The test message failed: {exc}"),
            L(
                "Den Kanal unter Einstellungen → Benachrichtigungen testen.",
                "Test the channel under Settings → Notifications.",
            ),
        )
    if failed:
        names = "; ".join(failed)
        return Result(
            "probe_notification", FAIL, L(f"Die Probemeldung kam bei {len(failed)} Kanal/Kanälen nicht an: {names}", f"The test message did not reach {len(failed)} channel(s): {names}"),
            L("Den Kanal unter Einstellungen → Benachrichtigungen prüfen und testen.", "Check and test the channel under Settings → Notifications."),
        )  # fmt: skip
    if not sent:
        return Result(
            "probe_notification",
            SKIP,
            L(
                "Kein Kanal will diese Meldung; es wurde nichts gesendet.",
                "No channel wants this message; nothing was sent.",
            ),
        )
    return Result(
        "probe_notification",
        OK,
        L(
            f"Probemeldung an {sent} Kanal/Kanäle gesendet. Kommt sie auf dem Handy an?",
            f"Test message sent to {sent} channel(s). Did it arrive on your phone?",
        ),
    )


async def check_assistant(d: Deps) -> Result:
    config = d.assistant_config
    if not config.get("enabled"):
        return Result("assistant", SKIP, L("Der Assistent ist ausgeschaltet.", "The assistant is turned off."))
    server = await d.assistant_status(config)
    if not server.get("reachable"):
        return Result(
            "assistant", FAIL, L(f"Kein Modell-Server unter {config['base_url']} erreichbar.", f"No model server reachable at {config['base_url']}."),
            L("Auf dem Pi: werkzeuge/ki_einrichten.sh ausführen oder sudo systemctl enable --now ollama.", "On the Pi: run werkzeuge/ki_einrichten.sh or sudo systemctl enable --now ollama."),
        )  # fmt: skip
    if not server.get("model_present"):
        return Result(
            "assistant", WARN, L(f"Das Modell „{config['model']}“ fehlt auf dem Server.", f"The model “{config['model']}” is missing on the server."),
            L(f"ollama pull {config['model']}", f"ollama pull {config['model']}"),
        )  # fmt: skip
    return Result(
        "assistant", OK, L("Modell-Server erreichbar, Modell vorhanden.", "Model server reachable, model present.")
    )


async def probe_assistant(d: Deps, previous: Result) -> Result:
    if previous.status != OK:
        return Result(
            "probe_assistant",
            SKIP,
            L("Übersprungen, weil der Assistent nicht bereit ist.", "Skipped because the assistant is not ready."),
        )
    try:
        seconds = await d.assistant_probe(d.assistant_config)
    except Exception as exc:
        return Result(
            "probe_assistant",
            FAIL,
            L(f"Keine brauchbare Antwort: {exc}", f"No usable answer: {exc}"),
            L(
                "Zeitgrenze erhöhen, ein kleineres Modell wählen oder den Modell-Server prüfen.",
                "Raise the time limit, choose a smaller model or check the model server.",
            ),
        )
    if seconds is None:
        return Result(
            "probe_assistant",
            SKIP,
            L(
                "Der Assistent beantwortet gerade eine andere Frage.",
                "The assistant is answering another question right now.",
            ),
        )
    status = WARN if seconds > 60 else OK
    return Result(
        "probe_assistant",
        status,
        L(f"Antwort nach {seconds:.1f} s.", f"Answered in {seconds:.1f} s."),
        L(
            "Sehr langsam; ein kleineres Modell oder ein stärkerer Rechner hilft.",
            "Very slow; a smaller model or a stronger machine helps.",
        )
        if status == WARN
        else None,
    )


async def check_backup(d: Deps, info: dict) -> Result:
    found = [w for w in info.get("warnings", []) if w.get("code") in BACKUP_CODES]
    if not found:
        return Result("backup", OK, L("Eine aktuelle Sicherung ist vorhanden.", "A recent backup exists."))
    worst = FAIL if any(w.get("level") == "crit" for w in found) else WARN
    de = " ".join(BACKUP_CODES[w["code"]]["de"] for w in found)
    en = " ".join(BACKUP_CODES[w["code"]]["en"] for w in found)
    return Result(
        "backup",
        worst,
        L(de, en),
        L(
            "Einstellungen → System: Sicherung ansehen; nach außen: docs/INSTALLATION-PI.md.",
            "Settings → System: look at the backup; external: docs/INSTALLATION-PI.md.",
        ),
    )


async def check_device(d: Deps, info: dict) -> Result:
    found = [w for w in info.get("warnings", []) if w.get("code") in DEVICE_CODES]
    if not found:
        return Result(
            "device",
            OK,
            L(
                "Keine Auffälligkeiten (Temperatur, Spannung, Speicher).",
                "Nothing unusual (temperature, voltage, storage).",
            ),
        )
    worst = FAIL if any(w.get("level") == "crit" for w in found) else WARN
    return Result(
        "device", worst, L(" ".join(DEVICE_CODES[w["code"]]["de"] for w in found), " ".join(DEVICE_CODES[w["code"]]["en"] for w in found)),
        L("Details unter Wartung → System → Zustand des Geräts.", "Details under Maintenance → System → Device health."),
    )  # fmt: skip


async def check_auth(d: Deps) -> Result:
    if await d.auth_enabled(d.db):
        return Result("auth", OK, L("Die Anmeldung ist eingeschaltet.", "Sign-in is turned on."))
    return Result(
        "auth",
        WARN,
        L(
            "Die Anmeldung ist ausgeschaltet: jeder im Netz hat Zugriff.",
            "Sign-in is turned off: anyone on the network has access.",
        ),
        L("Einstellungen → Benutzer: Anmeldung einschalten.", "Settings → Users: turn sign-in on."),
    )


async def check_guard(d: Deps) -> Result:
    state = d.guard_state()
    if state == "ok":
        return Result(
            "update_guard",
            OK,
            L(
                "Sicherung vor dem Update und Rückbau sind eingerichtet.",
                "Backup before updates and rollback are set up.",
            ),
        )
    if state == "no_unit":
        return Result(
            "update_guard",
            SKIP,
            L(
                "Kein systemd-Dienst gefunden (nicht auf dem Pi oder anders installiert).",
                "No systemd service found (not on the Pi or installed differently).",
            ),
        )
    return Result(
        "update_guard",
        WARN,
        L("Der Dienst enthält den Update-Schutz nicht.", "The service does not contain the update guard."),
        L(
            "Den Pi-Installer einmal neu ausführen (werkzeuge/pi_neu_installieren.sh).",
            "Run the Pi installer once more (werkzeuge/pi_neu_installieren.sh).",
        ),
    )


async def _safe(check_id: str, call: Callable[[], Awaitable[Result]]) -> Result:
    try:
        return await call()
    except Exception as exc:  # eine kaputte Prüfung darf die anderen nicht stoppen
        logger.exception("selftest check %s crashed", check_id)
        return Result(
            check_id, FAIL, L(f"Die Prüfung selbst ist fehlgeschlagen: {exc}", f"The check itself failed: {exc}")
        )


async def run(d: Deps, lang: str = "de") -> dict[str, Any]:
    """Alle Prüfungen in fester Reihenfolge; Ergebnis mit Texten in ``lang`` und Zusammenfassung."""
    lang = "en" if lang == "en" else "de"
    results: list[Result] = []

    async def add(check_id: str, call: Callable[[], Awaitable[Result]]) -> Result:
        result = await _safe(check_id, call)
        results.append(result)
        return result

    try:
        health = d.health(d.data_dir)
    except Exception as exc:
        logger.warning("selftest health snapshot failed: %s", exc)
        health = {"warnings": []}

    await add("database", lambda: check_database(d))
    await add("scheduler", lambda: check_scheduler(d))
    await add("due_watch", lambda: check_due_watch(d))
    await add("printers", lambda: check_printers(d))
    await add("forecast", lambda: check_forecast(d))
    await add("channels", lambda: check_channels(d))
    await add("backup", lambda: check_backup(d, health))
    await add("device", lambda: check_device(d, health))
    await add("auth", lambda: check_auth(d))
    await add("update_guard", lambda: check_guard(d))
    assistant = await add("assistant", lambda: check_assistant(d))
    await add("probe_notification", lambda: probe_notification(d))
    await add("probe_assistant", lambda: probe_assistant(d, assistant))

    out = [
        {
            "id": r.id,
            "title": TITLES[r.id][lang],
            "status": r.status,
            "detail": r.detail[lang],
            "fix": r.fix[lang] if r.fix else None,
        }
        for r in results
    ]
    summary = {status: sum(1 for r in results if r.status == status) for status in (OK, WARN, FAIL, SKIP)}
    return {"checked_at": d.now.astimezone(timezone.utc).isoformat(), "results": out, "summary": summary}

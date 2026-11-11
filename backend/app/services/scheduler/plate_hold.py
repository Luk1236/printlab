"""Halten eines Auftrags, wenn die Kamera vor dem Start Objekte auf der Platte sieht.

Aus ``print_scheduler.py`` ausgelagert. Vorher schrieb eine Sperre der
Plattenprüfung nichts an den Auftrag: die Warteschlange zeigte ihn als
startbar (mit ETA), während jeder Durchlauf denselben freien Drucker wählte,
die Prüfung erneut sperrte und die Runde als "hat etwas abgesetzt" galt. Der
Planer lief dadurch im schnellen Takt, alle paar Sekunden ein Kamerabild, eine
KI-Prüfung und eine Benachrichtigung.

Jetzt bekommt der Auftrag den Grund als ``waiting_reason``, der Drucker sitzt
``PLATE_RECHECK_SECONDS`` aus (``QueuePass`` liest ``_plate_blocks``), und nur
die erste Sperre einer Folge benachrichtigt. Ist die Platte frei geräumt,
startet der Auftrag spätestens mit der nächsten Prüfung von selbst; bestätigt
der Benutzer die Platte, fällt die Wartezeit sofort weg.
"""

import importlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer

# Wie lange ein Drucker nach einer Sperre aus der Auswahl bleibt, bevor die Kamera wieder schaut.
PLATE_RECHECK_SECONDS = 60
# Ab so langer Zeit nach Ablauf des Fensters zählt eine neue Sperre wieder als neue Folge (meldet sich).
STALE_BLOCK_SECONDS = 3600


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    return importlib.import_module("backend.app.services.print_scheduler")


def plate_hold_reason(reason: str | None, printer_name: str) -> str:
    """Text für die Warteschlangen-Zeile: was die Kamera sah und was zu tun ist."""
    seen = reason or "Objekt auf Druckbett erkannt"
    return f"{seen} auf {printer_name} – Platte abräumen; PrintLab prüft jede Minute erneut"


class PlateHoldMixin:
    """Plattenprüfung vor dem Start, mit Wartegrund und Wartezeit; ``PrintScheduler`` erbt sie."""

    # Drucker-ID -> (monotone Zeit der nächsten Prüfung, Text an der Zeile). Angelegt in
    # ``PrintScheduler.__init__``; der Eintrag bleibt nach Ablauf stehen, bis eine Prüfung
    # durchgeht oder die Platte bestätigt wird, damit eine Wiederholung nicht erneut benachrichtigt.
    _plate_blocks: dict[int, tuple[float, str]]

    async def _plate_check_passes(self, db: AsyncSession, item: PrintQueueItem, printer: Printer) -> bool:
        """Platte prüfen; bei einer Sperre den Auftrag mit Grund halten und False liefern."""
        from backend.app.services.queue_plate_check import check_queue_plate_clear

        now = _rt().time.monotonic()
        previous = self._plate_blocks.get(printer.id)
        # Nur die erste Sperre einer Folge meldet sich. Eine Sperre, deren Fenster seit einer Stunde
        # abgelaufen ist, gehört zu einer Folge, auf die niemand mehr wartet (Auftrag gelöscht o. ä.).
        new_run = previous is None or now >= previous[0] + STALE_BLOCK_SECONDS
        plate_clear, reason = await check_queue_plate_clear(printer, item, db, notify=new_run)
        if plate_clear:
            self._plate_blocks.pop(printer.id, None)
            return True

        text = plate_hold_reason(reason, printer.name or f"Drucker {printer.id}")
        self._plate_blocks[printer.id] = (now + PLATE_RECHECK_SECONDS, text)
        # Die Zeile bleibt `pending`; nur der Grund wird geschrieben. Ein Fehler hier darf den
        # Abbruch des Starts nicht verhindern, der Drucker bleibt über `_plate_blocks` gesperrt.
        try:
            item.waiting_reason = text
            await db.commit()
        except Exception as exc:
            logger.warning("Queue item %s: could not record the plate-check hold: %s", item.id, exc)
        logger.info(
            "Queue item %s: plate check holds printer %s for %ds",
            item.id,
            printer.id,
            PLATE_RECHECK_SECONDS,
        )
        return False

    def clear_plate_block(self, printer_id: int) -> None:
        """Wartezeit nach einer Plattensperre aufheben, z. B. wenn der Benutzer die Platte bestätigt."""
        self._plate_blocks.pop(printer_id, None)

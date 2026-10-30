"""Zusammenbau des Startbefehls für den Druckplaner.

Aus ``print_scheduler._start_print`` ausgelagert: alles, was zwischen dem
erfolgreichen Upload und dem Absetzen von ``printer_manager.start_print``
entschieden wird — Zustand vor dem Absetzen (für den Watchdog), Zeitraffer,
Düsen-Rack-Zuordnung (#1784/#2800) und die Abschaltung von AMS, wenn die Platte
ausschließlich vom externen Halter druckt (#3087).

Das Absetzen selbst bleibt beim Planer, ebenso jede Datenbank- oder
Benachrichtigungsarbeit. Ist die Platte nicht mehr zustellbar, kommt statt eines
Plans eine :class:`StartRefusal` zurück; der Planer schreibt dann den Fehler und
räumt die bereits übertragene Datei weg.

``printer_manager`` wird über das Fassadenmodul ``print_scheduler`` aufgelöst,
weil die Tests genau diesen Namen ersetzen.
"""

import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.services.bambu_mqtt import resolve_rack_plan_mapping
from backend.app.services.scheduler.filament import (
    _consumed_mapping_entries,
    _is_external_tray,
    _might_be_dual_nozzle,
)
from backend.app.utils.printer_models import is_nozzle_rack_model
from backend.app.utils.threemf_tools import (
    extract_rack_plan_from_3mf,
    extract_slot_extruders_from_3mf,
)

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    return importlib.import_module("backend.app.services.print_scheduler")


@dataclass(frozen=True, slots=True)
class StartPlan:
    """Fertiger Startbefehl plus der Zustand, den der Watchdog davor braucht."""

    remote_filename: str
    plate_id: int
    ams_mapping: object
    bed_levelling: str
    flow_cali: str
    vibration_cali: bool
    layer_inspect: bool
    timelapse: bool
    use_ams: bool
    nozzle_offset_cali: str
    nozzle_mapping: str | None
    nozzle_slot_extruders: str | None
    pre_status: object
    pre_state: object
    pre_subtask_id: object
    pre_gcode_file: object

    def print_kwargs(self) -> dict[str, object]:
        """Die Schlüsselwortargumente für ``printer_manager.start_print``.

        Einzige Stelle, an der die Namen stehen: ein Tippfehler hier würde sonst
        erst beim Absetzen auffallen, und zwar als Ausnahme mitten im
        Warteschlangen-Durchlauf.
        """
        return {
            "plate_id": self.plate_id,
            "ams_mapping": self.ams_mapping,
            "bed_levelling": self.bed_levelling,
            "flow_cali": self.flow_cali,
            "vibration_cali": self.vibration_cali,
            "layer_inspect": self.layer_inspect,
            "timelapse": self.timelapse,
            "use_ams": self.use_ams,
            "nozzle_offset_cali": self.nozzle_offset_cali,
            "nozzle_mapping": self.nozzle_mapping,
            "nozzle_slot_extruders": self.nozzle_slot_extruders,
        }


@dataclass(frozen=True, slots=True)
class StartRefusal:
    """Die Platte lässt sich nicht mehr zustellen; der Planer schreibt den Fehler."""

    message: str


def prepare_start(
    *,
    item: PrintQueueItem,
    printer: Printer,
    file_path: Path | None,
    plate_id: int,
    ams_mapping: object,
    remote_filename: str,
) -> StartPlan | StartRefusal:
    """Entscheiden, womit der Auftrag an den Drucker geht."""
    rt = _rt()

    # Capture state before dispatch so the watchdog can detect whether the
    # printer actually transitioned (#967). Also capture subtask_id so the
    # watchdog can recognise "command landed but state hasn't flipped yet" on
    # slow H2D transitions (#1078).
    pre_status = rt.printer_manager.get_status(item.printer_id)
    pre_state = getattr(pre_status, "state", None) if pre_status else None
    pre_subtask_id = getattr(pre_status, "subtask_id", None) if pre_status else None
    pre_gcode_file = getattr(pre_status, "gcode_file", None) if pre_status else None

    # #1721: respect the user's explicit timelapse choice. The #1397 force-on at
    # dispatch was removed because it caused per-layer nozzle parking on slicer
    # profiles with Timelapse Type = Smooth. Finish-photo capture is now driven
    # by the stg_cur=22 transition in bambu_mqtt.py ("Filament unloading",
    # toolhead parked, bed not yet dropped) with a FINISH-state fallback — no
    # need to force a video.
    effective_timelapse = bool(item.timelapse)

    # Nozzle-rack fallback (#2800). A job that never passed through the Virtual
    # Printer carries no Bambu Studio nozzle pick, and an H2C then dispatches
    # with no nozzle field at all and chooses for itself — which is how a print
    # levelled on one hotend and then printed on another, millimetres above the
    # plate. Derive the per-slot extruder assignment from the file being
    # dispatched.
    #
    # Done here rather than at queue time because this is the first point that
    # knows both the actual printer and the actual file: an item can be created
    # without a printer (model-based assignment), reassigned afterwards, or have
    # its file swapped for a G-code-injected copy just before this. Every
    # queue-creation path — the print dialog, a bulk library add, the webhook, a
    # pipeline run — is covered by the one call. Skipped when the item already
    # carries a Bambu Studio capture: that one wins downstream anyway, so
    # reading the 3MF again would be work thrown away on every dispatch.
    # Rack position resolution (#1784), tried before the #2800 fallback below
    # because it can express what that one cannot: a plate wanting a *different*
    # hotend off the rack per filament group. The position per group is the
    # operator's pick — the 3MF states it nowhere, proven by sending one plate
    # twice with different picks and finding the two files identical bar float
    # noise — so it is resolved here against the rack as it stands right now,
    # after the upload, not at queue time.
    resolved_nozzle_mapping = None
    if not item.nozzle_mapping and file_path is not None and is_nozzle_rack_model(printer.model):
        rack_plan = extract_rack_plan_from_3mf(file_path, plate_id=plate_id)
        if rack_plan is not None:
            try:
                stored_choice = json.loads(item.nozzle_rack_choice) if item.nozzle_rack_choice else {}
            except (json.JSONDecodeError, TypeError):
                stored_choice = {}
                logger.warning(
                    "Queue item %s: unreadable nozzle_rack_choice %r, assigning rack positions instead",
                    item.id,
                    item.nozzle_rack_choice,
                )
            # JSON object keys are strings; the groups are ints.
            choice: dict[int, int] = {}
            for key, value in (stored_choice or {}).items():
                try:
                    choice[int(key)] = int(value)
                except (TypeError, ValueError):
                    continue

            live_rack = getattr(rt.printer_manager.get_status(item.printer_id), "nozzle_rack", None) or []
            resolved_nozzle_mapping, rack_error = resolve_rack_plan_mapping(
                rack_plan.slot_groups, rack_plan.group_dicts(), choice, live_rack
            )
            if resolved_nozzle_mapping is None and choice:
                # An explicit pick that no longer holds stops the print. The
                # operator named a hotend; printing from a different one is how
                # a plate gets levelled on one nozzle and drawn with another,
                # millimetres above the bed. Nothing has been sent to the
                # printer yet, so failing here costs only the upload.
                logger.warning(
                    "Queue item %s: refusing to dispatch to %s — %s (chose %s, rack %s)",
                    item.id,
                    printer.name,
                    rack_error,
                    choice,
                    [slot.get("id") for slot in live_rack],
                )
                return StartRefusal(
                    message=(
                        f"Nozzle rack pick no longer fits the printer: {rack_error}. "
                        "Edit the item to choose another position."
                    )
                )
            if resolved_nozzle_mapping is None:
                # Nothing was picked and nothing could be assigned. Falls
                # through to the #2800 path, which is what ran before this
                # existed — strictly not worse than today.
                logger.info(
                    "Queue item %s: no rack positions assignable (%s); falling back",
                    item.id,
                    rack_error,
                )
            else:
                logger.info(
                    "Queue item %s: rack mapping %s (groups %s, chosen %s)",
                    item.id,
                    resolved_nozzle_mapping,
                    rack_plan.slot_groups,
                    choice or "auto",
                )

    nozzle_slot_extruders = None
    if (
        not item.nozzle_mapping
        and resolved_nozzle_mapping is None
        and file_path is not None
        and is_nozzle_rack_model(printer.model)
    ):
        slot_extruders = extract_slot_extruders_from_3mf(file_path, plate_id=plate_id)
        if slot_extruders:
            nozzle_slot_extruders = json.dumps(slot_extruders)

    # Every filament this plate prints is on the external spool -> the print must
    # go out with use_ams=False. The firmware answers use_ams=true plus a mapping
    # it cannot resolve with 07FF_8012 "Failed to get AMS mapping table", which is
    # what held the reporter's P1S at Heatbed preheating for ten minutes before it
    # gave up (#3087). The MQTT command builder already downgrades a mapping that
    # is *only* external ([254]), but a multi-filament project pads the slots this
    # plate does not print with -1 — BambuStudio's own convention — and down there
    # a -1 is indistinguishable from a slot that never resolved, which must never
    # be sent to the spool holder (#2589). Here the plate's filament list says
    # which is which, so the answer is exact rather than a guess.
    #
    # Deliberately narrow: this fires only when every consumed slot is an explicit
    # 254/255. A consumed slot that did not resolve leaves use_ams alone and the
    # firmware still rejects the print, exactly as today. And only for
    # single-nozzle printers, mirroring the builder's own reconcile — on a
    # dual-nozzle machine use_ams is which extruder to feed, not whether to use
    # the AMS, so it is not ours to rewrite.
    effective_use_ams = item.use_ams
    if (
        effective_use_ams
        and ams_mapping
        and file_path is not None
        # Cheap gate before opening the file: with nothing on the spool holder
        # anywhere in the mapping, no subset of it can be all external, so most
        # dispatches never pay for the parse. The isinstance also keeps a
        # malformed stored mapping (a bare number from a hand-edited row)
        # failing where it always failed, in the command builder, rather than
        # here.
        and isinstance(ams_mapping, list)
        and any(_is_external_tray(t) for t in ams_mapping)
        and not _might_be_dual_nozzle(printer.model, pre_status)
    ):
        from backend.app.services.filament_requirements import extract_filament_requirements

        consumed = _consumed_mapping_entries(ams_mapping, extract_filament_requirements(file_path, plate_id=plate_id))
        if consumed and all(_is_external_tray(t) for t in consumed):
            effective_use_ams = False
            logger.info(
                "Queue item %s: every filament plate %s prints is on the external spool "
                "(mapping %s) — dispatching with use_ams=False (#3087)",
                item.id,
                plate_id,
                ams_mapping,
            )

    return StartPlan(
        remote_filename=remote_filename,
        plate_id=plate_id,
        ams_mapping=ams_mapping,
        bed_levelling=item.bed_levelling,
        flow_cali=item.flow_cali,
        vibration_cali=item.vibration_cali,
        layer_inspect=item.layer_inspect,
        timelapse=effective_timelapse,
        use_ams=effective_use_ams,
        nozzle_offset_cali=item.nozzle_offset_cali,
        # nozzle_mapping rides through verbatim — JSON string captured from Bambu
        # Studio's project_file on VP intake (#1780); the MQTT layer parses +
        # injects it only for dual-nozzle models so a null on every other model
        # is a transparent pass-through. The rack fallback is resolved down there
        # too, where the live rack position is known.
        nozzle_mapping=item.nozzle_mapping
        or (json.dumps(resolved_nozzle_mapping) if resolved_nozzle_mapping else None),
        nozzle_slot_extruders=nozzle_slot_extruders,
        pre_status=pre_status,
        pre_state=pre_state,
        pre_subtask_id=pre_subtask_id,
        pre_gcode_file=pre_gcode_file,
    )

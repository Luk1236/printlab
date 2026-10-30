"""Kammer- und Trocknungsregeln des Druckplaners.

Grenzwerte für Warmhalten, Vorkühlen und das Wiederanlaufen der
Trocknung. Aus ``print_scheduler.py`` ausgelagert; die Namen werden dort
weiterhin importiert, damit Konfiguration und Tests unverändert bleiben.
"""

from dataclasses import dataclass

# How far back chamber temperature samples are retained. 2h comfortably spans
# any soak a user can configure (capped at 30 min) plus the plate-clearing gap
# before the next print.
_CHAMBER_HISTORY_TTL_SECONDS = 7200
# Fallback for `queue_keep_warm_max_minutes` — how long the bed may be held
# warm on a printer sitting in FINISH before the heaters are shut off. Users
# who clear plates promptly will want far less than this; it is deliberately
# the cautious end, since the cost of it being too short is only a re-soak.
_KEEP_WARM_MAX_MINUTES_DEFAULT = 120
# Max acceptable gap between two consecutive chamber samples before we treat
# the older one as belonging to a separate observation run (printer went
# offline and came back). Above ~30s cadence with a safety margin.
_CHAMBER_SAMPLE_MAX_GAP_SECONDS = 60.0
# How long the chamber must read below target before we accept that it really
# cooled. An enclosed chamber's thermal mass cannot lose and regain several
# degrees quickly: measured on an X1C, falling from ~55°C to below 48°C took
# 23-73 minutes (~0.2 C/min), while the fastest drop ever recorded was
# 27 C/min — impossible for that mass, i.e. a sensor artifact. Brief
# sub-target readings are therefore a door opening or noise, not lost soak,
# and a plate swap (exactly when keep-warm is running) produces one. Six
# minutes clears the longest such artifact observed (~5 min once bracketed by
# its neighbouring samples) and still sits far below the 23-minute floor for
# real cooling.
_CHAMBER_DIP_GRACE_SECONDS = 360.0
# How often the preheat stage re-checks that the item it is heating for still
# wants to be printed. Cancelling only writes `status` to the database — it
# cannot interrupt a coroutine parked in `asyncio.sleep` — so without this the
# heaters run for the rest of max_wait + soak (45 min at the default settings)
# and the printer stays in `busy_printers`, blocking every other queued item
# behind a print that is not happening.
_PREHEAT_CANCEL_CHECK_SECONDS = 10.0
# set_airduct_mode modeId values (bambu_mqtt.py:5937 — 0 cooling, 1 heating).
_AIRDUCT_MODE_COOLING = 0
_AIRDUCT_MODE_HEATING = 1


@dataclass
class _KeepWarmEntry:
    """Per-printer keep-warm state.

    - ``started``: monotonic time when keep-warm first fired for this printer.
      Used by the max-duration timeout.
    - ``held_target``: last bed target we successfully published. On release
      we only send bed-off when firmware still reports this value, so a user
      or subsequent print that changed the target isn't clobbered.
    - ``expired``: latched True when the max-duration timeout fires. Prevents
      re-engagement (and re-seeding of ``started``) on subsequent ticks. The
      release sweep drops the entry entirely once the printer leaves the
      candidate set.
    """

    started: float
    held_target: int
    expired: bool = False


# Auto-drying re-arm guards (#2770).
#
# An AMS reports HIGHER relative humidity while it is warm than once it has
# cooled: measured on an H2D/AMS 2 Pro at 10-13% cold against 15-20% throughout
# every drying cycle, and the same unit read 16-20% across a full 12 h dry. A
# threshold set inside that band therefore cannot be satisfied while the box is
# hot, and the firmware is free to end a cycle whenever it decides the filament
# is dry — so the next 30 s pass sees dry_time 0 with the reading still above
# the threshold and arms another cycle. The reporter's log has five 12-hour
# cycles armed inside four hours, one of them six seconds after the previous
# ended.
#
# The cooldown stops the six-second re-arm; the unproductive-cycle cap stops the
# loop. Neither ever stops a running cycle — both only gate STARTING one, so a
# manual or firmware-run dry is untouched.
AUTO_DRY_REARM_COOLDOWN_SECONDS = 30 * 60
AUTO_DRY_MAX_UNPRODUCTIVE_CYCLES = 2
# Sustained-humidity wait (#2518): an above-threshold streak is only
# "continuous" if some pass observed it within the gap ceiling. A unit that
# goes unobserved longer (print running, printer disconnected, sensor silent)
# restarts its streak rather than inheriting a stale one. The ceiling is
# derived from the scheduler cadence — four missed passes — with this floor so
# a fast-polling configuration does not void streaks on a single hiccup.
AUTO_DRY_SUSTAINED_GAP_FLOOR_SECONDS = 120

# How long a finished scheduled drying row is kept before it is pruned.
SCHEDULED_DRYING_RETENTION_DAYS = 7
# How often that prune actually runs. The check itself is called on every queue
# pass — every 3s while dispatching — and issuing the DELETE is what begins a
# write transaction, which SQLite serialises against every other writer. Rows
# only become prunable a week after they finish, so anything short of hourly is
# paying that cost for nothing.
SCHEDULED_DRYING_PRUNE_INTERVAL_SECONDS = 60 * 60

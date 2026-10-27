"""Wartungsprogramme: Öl verteilen und Gewindestangen schmieren.

Portiert aus dem Bambu-Monitor (dort am P2S getestet). Die Programme laufen als
G-code über den vorhandenen MQTT-Client und bewegen nur den Drucker; es wird
nichts geheizt und kein Filament verwendet.

Sicherheitsregeln (vor dem Start und vor jedem Schritt):
- Drucker verbunden und Zustand bekannt,
- kein laufender/preparierter Druck,
- Düse und Bett höchstens 60 °C (Verbrennungsgefahr beim Ölen),
- nur Modelle mit 256-mm-Bett (aktuell P2S), weil die XY-Grenzen fest sind.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.core.tasks import spawn_background_task

logger = logging.getLogger(__name__)

ACTIVE_PRINT_STATES = frozenset({"PREPARE", "SLICING", "RUNNING", "PAUSE"})
SUPPORTED_MODELS = frozenset({"P2S"})

Z_LOW = 30.0
Z_HIGH = 150.0
Z_STEP = 10.0
FEED_Z = 600
FEED_XY = 3000
XY_MIN = 20.0
XY_MAX = 236.0
STEP_PAUSE = 0.35
PASS_PAUSE = 30.0
RUN_PAUSE = 60.0
SETTLE = 2.0
CYCLES = 5
XY_MOVE_SECONDS = 5.5

ProgramKey = str
SendFn = Callable[[str], bool]
GuardFn = Callable[[], tuple[bool, str]]


@dataclass(frozen=True)
class ProgramSpec:
    key: ProgramKey
    label: str
    description: str
    default_runs: int = 1
    run_pause: float = 0.0


PROGRAMS: dict[ProgramKey, ProgramSpec] = {
    "oil": ProgramSpec(
        key="oil",
        label="Öl verteilen",
        description="X, Y und Z je einmal abfahren und Öl verteilen (zwei Durchgänge).",
        default_runs=2,
        run_pause=RUN_PAUSE,
    ),
    "rods": ProgramSpec(
        key="rods",
        label="Gewindestangen schmieren",
        description="Fünfmal Z hoch/runter, 30 s ölen, noch einmal, danach X/Y abfahren.",
        default_runs=1,
    ),
}


class _Aborted(Exception):
    """Interner Abbruch des Programms."""


def _z_steps(count: int, sign: str) -> list[tuple[str, Any]]:
    return [("z", sign)] * count


def _z_move_mm(direction: str) -> str:
    return f"{Z_STEP:g}" if direction == "+" else f"-{Z_STEP:g}"


def build_plan(program: ProgramKey, runs: int | None = None) -> list[tuple[str, Any]]:
    """Liefert den Ablaufplan als (Art, Wert)-Liste.

    Arten: ``home``, ``z`` (Richtung ``+``/``-``), ``xy`` ((Achse, Ziel)), ``pause`` (Sekunden).
    """
    if program not in PROGRAMS:
        raise ValueError(f"Unbekanntes Programm: {program}")
    spec = PROGRAMS[program]
    count = max(1, min(3, int(runs if runs is not None else spec.default_runs)))
    steps_up = int(round((Z_HIGH - Z_LOW) / Z_STEP))
    steps_low = int(round(Z_LOW / Z_STEP))

    if program == "oil":
        base: list[tuple[str, Any]] = [("home", None)]
        base += _z_steps(steps_low, "+")           # 0 -> 30
        base += _z_steps(steps_up, "+")            # 30 -> 150
        base += _z_steps(steps_up, "-")            # 150 -> 30
        base += [
            ("xy", ("X", XY_MIN)), ("xy", ("X", XY_MAX)), ("xy", ("X", XY_MIN)),
            ("xy", ("Y", XY_MIN)), ("xy", ("Y", XY_MAX)), ("xy", ("Y", XY_MIN)),
        ]
        plan = list(base)
        for _ in range(count - 1):
            plan += [("pause", spec.run_pause)] + base
        return plan

    # Gewindestangen: ein Durchgang abwechselnd hoch/runter, Pause, zurück.
    plan = [("home", None)]
    plan += _z_steps(steps_low, "+")                # 0 -> 30
    plan += (_z_steps(steps_up, "+") + _z_steps(steps_up, "-")) * CYCLES
    plan += _z_steps(steps_up, "+")                # 30 -> 150 für die Ölpause
    plan += [("pause", PASS_PAUSE)]
    plan += (_z_steps(steps_up, "-") + _z_steps(steps_up, "+")) * CYCLES
    plan += [("pause", PASS_PAUSE)]
    plan += [
        ("xy", ("X", XY_MIN)), ("xy", ("X", XY_MAX)),
        ("xy", ("Y", XY_MIN)), ("xy", ("Y", XY_MAX)),
    ]
    return plan


def estimate_seconds(plan: list[tuple[str, Any]]) -> int:
    z_move = max(0.5, Z_STEP / (FEED_Z / 60.0))
    seconds = 0.0
    for kind, value in plan:
        if kind == "home":
            seconds += 3.0
        elif kind == "z":
            seconds += z_move + STEP_PAUSE
        elif kind == "xy":
            seconds += XY_MOVE_SECONDS
        elif kind == "pause":
            seconds += SETTLE + float(value)
    return int(round(seconds))


def check_ready(state: Any, model: str | None) -> tuple[bool, str]:
    """Prüft, ob das Wartungsprogramm jetzt laufen darf."""
    if (model or "").upper() not in SUPPORTED_MODELS:
        return False, "Dieses Wartungsprogramm ist nur für den P2S eingerichtet."
    if state is None or not getattr(state, "connected", False):
        return False, "Der Drucker ist nicht verbunden."
    gcode_state = str(getattr(state, "state", "") or "")
    if gcode_state == "unknown":
        return False, "Der Druckerzustand ist noch unbekannt. Bitte den ersten Status abwarten."
    if gcode_state in ACTIVE_PRINT_STATES:
        return False, "Das Wartungsprogramm ist während eines Drucks gesperrt."
    temperatures = getattr(state, "temperatures", {}) or {}
    nozzle = float(temperatures.get("nozzle", 0) or 0)
    bed = float(temperatures.get("bed", 0) or 0)
    if nozzle > 60 or bed > 60:
        return False, (
            f"Düse/Bett sind noch heiß ({nozzle:.0f}/{bed:.0f} °C). "
            "Bitte abkühlen lassen – Verbrennungsgefahr beim Ölen."
        )
    return True, ""


@dataclass
class _Runner:
    printer_id: int
    client: Any
    model: str
    program: ProgramKey
    plan: list[tuple[str, Any]]
    runs: int
    abort: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[Any] | None = None
    step: int = 0
    phase: str = "starting"
    message: str = "Wird vorbereitet …"
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()


class MaintenanceProgramService:
    """Ein Programm je Drucker; Status und Abbruch über die API."""

    def __init__(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._sleep = sleep
        self._runners: dict[int, _Runner] = {}

    # --- Status ------------------------------------------------------------

    def status(self, printer_id: int) -> dict[str, Any]:
        runner = self._runners.get(printer_id)
        if runner is None or (not runner.active and runner.finished_at is None):
            return {
                "printer_id": printer_id,
                "program": None,
                "label": None,
                "active": False,
                "phase": "idle",
                "message": "",
                "step": 0,
                "steps": 0,
                "percent": 0,
                "eta_seconds": 0,
                "error": None,
                "started_at": None,
                "finished_at": None,
                "runs": 0,
            }
        total = len(runner.plan)
        return {
            "printer_id": printer_id,
            "program": runner.program,
            "label": PROGRAMS[runner.program].label,
            "active": runner.active,
            "phase": runner.phase,
            "message": runner.message,
            "step": runner.step,
            "steps": total,
            "percent": int(round(100 * runner.step / total)) if total else 0,
            "eta_seconds": estimate_seconds(runner.plan[runner.step:]),
            "error": runner.error,
            "started_at": runner.started_at,
            "finished_at": runner.finished_at,
            "runs": runner.runs,
        }

    # --- Steuerung ---------------------------------------------------------

    def start(self, printer_id: int, program: ProgramKey, client: Any, model: str | None,
              runs: int | None = None) -> tuple[bool, str]:
        if program not in PROGRAMS:
            return False, f"Unbekanntes Programm: {program}"
        runner = self._runners.get(printer_id)
        if runner is not None and runner.active:
            return False, "Auf diesem Drucker läuft bereits ein Wartungsprogramm."
        ok, message = check_ready(getattr(client, "state", None), model)
        if not ok:
            return False, message
        spec = PROGRAMS[program]
        plan = build_plan(program, runs)
        runner = _Runner(
            printer_id=printer_id,
            client=client,
            model=model or "",
            program=program,
            plan=plan,
            runs=max(1, min(3, int(runs if runs is not None else spec.default_runs))),
            started_at=datetime.now(timezone.utc).isoformat(),
            message="Grundposition wird angefahren …",
        )
        self._runners[printer_id] = runner
        runner.task = spawn_background_task(
            self._execute(runner), name=f"maintenance-program-{printer_id}-{program}"
        )
        logger.info("[Wartung] %s auf Drucker %s gestartet (%s Schritte)",
                    program, printer_id, len(plan))
        return True, f"{spec.label} gestartet."

    def stop(self, printer_id: int) -> tuple[bool, str]:
        runner = self._runners.get(printer_id)
        if runner is None or not runner.active:
            return False, "Es läuft kein Wartungsprogramm."
        runner.abort.set()
        runner.message = "Stopp angefordert – der aktuelle Schritt wird noch beendet."
        return True, "Wartungsprogramm wird gestoppt."

    async def wait(self, printer_id: int, timeout: float | None = None) -> None:
        runner = self._runners.get(printer_id)
        if runner is not None and runner.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(runner.task), timeout)
            except asyncio.TimeoutError:
                pass

    # --- Ausführung --------------------------------------------------------

    async def _sleep_abortable(self, runner: _Runner, seconds: float) -> None:
        remaining = float(seconds)
        while remaining > 0:
            if runner.abort.is_set():
                raise _Aborted
            chunk = min(0.5, remaining)
            await self._sleep(chunk)
            remaining -= chunk
        if runner.abort.is_set():
            raise _Aborted

    def _send(self, runner: _Runner, gcode: str) -> None:
        ok, message = check_ready(getattr(runner.client, "state", None), runner.model)
        if not ok:
            raise RuntimeError(message)
        if not runner.client.send_gcode(gcode):
            raise RuntimeError("Der Drucker hat den Befehl nicht angenommen.")

    async def _execute(self, runner: _Runner) -> None:
        total = len(runner.plan)
        try:
            for index, (kind, value) in enumerate(runner.plan, start=1):
                if runner.abort.is_set():
                    raise _Aborted
                if kind == "home":
                    runner.phase, runner.message = "homing", "Grundposition wird angefahren …"
                    self._send(runner, "G28")
                    await self._sleep_abortable(runner, 3.0)
                elif kind == "z":
                    runner.phase = "z"
                    runner.message = f"Bett fährt ({index}/{total}) …"
                    self._send(runner, f"G91\nG1 Z{_z_move_mm(value)} F{FEED_Z}\nG90")
                    await self._sleep_abortable(runner, max(0.5, Z_STEP / (FEED_Z / 60.0)) + STEP_PAUSE)
                elif kind == "xy":
                    axis, target = value
                    runner.phase, runner.message = "xy", f"Kopf fährt {axis} auf {target:g} mm …"
                    self._send(runner, f"G90\nG1 {axis}{target:g} F{FEED_XY}")
                    await self._sleep_abortable(runner, XY_MOVE_SECONDS)
                elif kind == "pause":
                    await self._sleep_abortable(runner, SETTLE)
                    runner.phase = "pause"
                    if runner.program == "rods":
                        runner.message = f"{int(value)} s Pause – jetzt Öl auf die Gewindestangen geben."
                    else:
                        runner.message = f"{int(value)} s Pause – gleich folgt der nächste Durchgang."
                    await self._sleep_abortable(runner, float(value))
                runner.step = index
            runner.phase = "done"
            runner.message = "Wartungsprogramm abgeschlossen."
            runner.finished_at = datetime.now(timezone.utc).isoformat()
        except _Aborted:
            runner.phase = "stopped"
            runner.message = "Wartungsprogramm gestoppt."
            runner.finished_at = datetime.now(timezone.utc).isoformat()
            logger.info("[Wartung] Programm auf Drucker %s abgebrochen", runner.printer_id)
        except Exception as exc:  # noqa: BLE001 - Hintergrundtask darf nicht still sterben
            runner.phase = "error"
            runner.error = str(exc)
            runner.message = str(exc)
            runner.finished_at = datetime.now(timezone.utc).isoformat()
            logger.warning("[Wartung] Programm auf Drucker %s fehlgeschlagen: %s",
                           runner.printer_id, exc)


service = MaintenanceProgramService()

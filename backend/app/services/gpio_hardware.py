"""GPIO Hardware-Taster, Entprellung & Not-Halt-Dienst (Phase 5).

Verwaltet physische Hardware-Taster und Anzeigen am Raspberry Pi:
1. Not-Halt-Taster (E-Stop): Öffner (NC) / Schließer (NO) mit Software-Entprellung.
2. Quittiertaster (ACK): Plattenwechsel / Not-Halt-Rücksetzen.
3. Pause/Resume-Taster: Pausiert oder setzt den aktuellen Druckauftrag fort.
4. Status-LED: Optische Signalisierung (Bereit, Druckt, Not-Halt, Abkühlung).
5. Servo-Kalibrierungs-Assistent für Türschließer-Winkel.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from backend.app.services import audit_log
from backend.app.services.hardware_extension import get_hardware
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent.parent / "data")
GPIO_CONFIG_PATH = DATA_DIR / "gpio_hardware.json"

DEFAULT_GPIO_CONFIG = {
    "enabled": False,  # Standardmäßig deaktiviert bis in den Einstellungen aktiviert
    "is_simulation": False,  # Bei True: Simulierter GPIO-Modus ohne RPi.GPIO
    "estop_pin": 26,  # GPIO 26 (Pin 37), Not-Halt-Taster
    "estop_mode": "nc",  # "nc" (Normally Closed, Öffner) oder "no" (Normally Open, Schließer)
    "button_ack_pin": 16,  # GPIO 16 (Pin 36), Quittiertaste
    "button_pause_pin": 20,  # GPIO 20 (Pin 38), Pause/Resume-Taste
    "status_led_pin": 21,  # GPIO 21 (Pin 40), Status-LED
    "debounce_ms": 50,  # Entprellung in Millisekunden
    "door_servo_min_angle": 10.0,  # Servo-Winkel Tür ZU
    "door_servo_max_angle": 154.0,  # Servo-Winkel Tür OFFEN
}


class GpioHardwareService:
    """Verwaltet physische GPIO-Taster, Entprellung und den Not-Halt-Status."""

    def __init__(self, config_path: Path = GPIO_CONFIG_PATH):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._estop_triggered = False
        self._last_estop_source: str | None = None
        self._led_state = "ready"  # ready | printing | estop | cooldown | off
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._gpio = None
        self._is_simulated = True
        self._last_edge_time: dict[int, float] = {}

        self.config = self._load_config()
        self._init_gpio()

    def _load_config(self) -> dict[str, Any]:
        cfg = dict(DEFAULT_GPIO_CONFIG)
        if self.config_path.is_file():
            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg.update({k: v for k, v in raw.items() if k in DEFAULT_GPIO_CONFIG})
            except Exception as exc:
                logger.warning("[GPIO] Konnte %s nicht lesen: %s", self.config_path, exc)
        return cfg

    def save_config(self, new_cfg: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.config.update({k: v for k, v in new_cfg.items() if k in DEFAULT_GPIO_CONFIG})
            try:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                self.config_path.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.error("[GPIO] Fehler beim Speichern von %s: %s", self.config_path, exc)
            self._restart_if_needed()
            return dict(self.config)

    def _init_gpio(self) -> None:
        """Initialisiert RPi.GPIO bzw. rpi-lgpio auf dem Raspberry Pi falls vorhanden."""
        if self.config.get("is_simulation", False):
            self._is_simulated = True
            self._gpio = None
            return

        try:
            import RPi.GPIO as gpio  # noqa: N813

            gpio.setmode(gpio.BCM)
            gpio.setwarnings(False)
            self._gpio = gpio
            self._is_simulated = False
            logger.info("[GPIO] RPi.GPIO Hardware-Treiber erfolgreich initialisiert.")
        except Exception:
            self._gpio = None
            self._is_simulated = True
            logger.debug("[GPIO] Kein physisches RPi.GPIO verfügbar. Verwende Simulations-Modus.")

    def is_estop_active(self) -> bool:
        """Liefert True, wenn der Not-Halt aktuell verriegelt ist."""
        with self._lock:
            return self._estop_triggered

    def get_status(self) -> dict[str, Any]:
        """Gibt den Live-Status aller konfigurierten Pins und des Not-Halts zurück."""
        with self._lock:
            c = self.config
            estop_pin = int(c["estop_pin"])
            ack_pin = int(c["button_ack_pin"])
            pause_pin = int(c["button_pause_pin"])
            led_pin = int(c["status_led_pin"])

            # Physische Pegel auslesen falls Hardware vorhanden
            pin_levels = {}
            if self._gpio and not self._is_simulated:
                try:
                    pin_levels[estop_pin] = self._gpio.input(estop_pin)
                    pin_levels[ack_pin] = self._gpio.input(ack_pin)
                    pin_levels[pause_pin] = self._gpio.input(pause_pin)
                except Exception:
                    pass

            estop_raw = pin_levels.get(estop_pin, 0 if self._estop_triggered else 1)
            # Im NC-Modus bedeutet LOW (0) = Kontakt geöffnet = Not-Halt aktiv
            is_estop_btn_pressed = (estop_raw == 0) if c["estop_mode"] == "nc" else (estop_raw == 1)

            return {
                "enabled": bool(c["enabled"]),
                "is_simulated": self._is_simulated,
                "estop_triggered": self._estop_triggered,
                "estop_source": self._last_estop_source,
                "estop_button_physically_pressed": is_estop_btn_pressed,
                "led_state": self._led_state,
                "pins": {
                    "estop": {"pin": estop_pin, "mode": c["estop_mode"], "active": is_estop_btn_pressed},
                    "button_ack": {"pin": ack_pin, "active": pin_levels.get(ack_pin) == 0},
                    "button_pause": {"pin": pause_pin, "active": pin_levels.get(pause_pin) == 0},
                    "status_led": {"pin": led_pin, "state": self._led_state},
                },
                "servo_calibration": {
                    "min_angle": float(c["door_servo_min_angle"]),
                    "max_angle": float(c["door_servo_max_angle"]),
                },
            }

    def trigger_emergency_stop(self, source: str = "software", user: str | None = None) -> dict[str, Any]:
        """Löst den Not-Halt sofort aus: sperrt Drucke, schaltet Motoren stromlos, stoppt laufende Drucke."""
        with self._lock:
            self._estop_triggered = True
            self._last_estop_source = source
            self._led_state = "estop"

        logger.critical("[Not-Halt] NOT-HALT AUSGELÖST! Quelle: %s", source)

        # 1. Hardware-Mechanik stoppen (Motoren stromlos schalten)
        try:
            hw = get_hardware(1)
            hw.emergency_stop()
        except Exception as exc:
            logger.warning("[Not-Halt] HardwareExtension emergency_stop fehlgeschlagen: %s", exc)

        # 2. Alle aktiven Drucker sofort stoppen / pausieren
        try:
            printers = printer_manager.get_all_printers()
            for p in printers:
                client = printer_manager.get_client(p.id)
                if client and client.state and client.state.connected:
                    if getattr(client.state, "state", None) in ("RUNNING", "PREPARE", "SLICING"):
                        logger.warning("[Not-Halt] Sende sofortigen Not-Stopp an Drucker %s", p.id)
                        printer_manager.stop_print(p.id)
        except Exception as exc:
            logger.error("[Not-Halt] Drucker-Stopp-Signal fehlgeschlagen: %s", exc)

        # 3. Status-LED auf Rot setzen
        self._set_led_output("estop")

        # 4. Audit-Log schreiben
        audit_log.record(
            action="emergency_stop",
            ok=True,
            message=f"Not-Halt ausgelöst ({source})",
            printer_id=1,
            user=user or "hardware_button",
            details={"source": source},
        )

        return self.get_status()

    def reset_emergency_stop(self, user: str | None = None) -> tuple[bool, str]:
        """Quittiert die Not-Halt-Sperre, falls der physische Taster nicht mehr gedrückt ist."""
        status = self.get_status()
        if status.get("estop_button_physically_pressed") and not self._is_simulated:
            msg = "Physischer Not-Halt-Taster ist noch betätigt / verriegelt! Bitte zuerst mechanisch entriegeln."
            logger.warning("[Not-Halt] Reset verweigert: %s", msg)
            return False, msg

        with self._lock:
            self._estop_triggered = False
            self._last_estop_source = None
            self._led_state = "ready"

        try:
            hw = get_hardware(1)
            hw.reload_config()
        except Exception:
            pass

        self._set_led_output("ready")

        audit_log.record(
            action="emergency_stop_reset",
            ok=True,
            message="Not-Halt quittiert und System freigegeben.",
            printer_id=1,
            user=user or "admin",
        )
        logger.info("[Not-Halt] Not-Halt-Sperre erfolgreich aufgehoben.")
        return True, "Not-Halt erfolgreich quittiert. System ist wieder betriebsbereit."

    def _set_led_output(self, state: str) -> None:
        """Steuert die Hardware-Status-LED an."""
        self._led_state = state
        if not self._gpio or self._is_simulated:
            return
        try:
            led_pin = int(self.config["status_led_pin"])
            # High = Ein bei Not-Halt, Low = Aus / Bereit
            val = self._gpio.HIGH if state == "estop" else self._gpio.LOW
            self._gpio.output(led_pin, val)
        except Exception:
            pass

    def test_servo_angle(self, angle: float, printer_id: int = 1) -> tuple[bool, str]:
        """Fährt das Tür-Servo zu Testzwecken auf einen gewünschten Winkel (0 bis 180 Grad)."""
        if not 0.0 <= angle <= 180.0:
            return False, "Winkel muss zwischen 0 und 180 Grad liegen."

        try:
            from werkzeuge.gpio_mechanik import Mechanik, load_config

            mech = Mechanik(gpio=self._gpio, config=load_config())
            mech.move_servo(angle)
            mech.cleanup()
            return True, f"Servo erfolgreich auf {angle:.1f}° gefahren."
        except Exception as exc:
            logger.error("[GPIO] Servotest auf %.1f° fehlgeschlagen: %s", angle, exc)
            return False, f"Servotest fehlgeschlagen: {exc}"

    def save_servo_calibration(self, min_angle: float, max_angle: float) -> tuple[bool, str]:
        """Speichert kalibrierte Servowinkel für Tür-ZU und Tür-OFFEN."""
        if not (0.0 <= min_angle < max_angle <= 180.0):
            return False, "Ungültige Winkel: ZU muss kleiner als OFFEN sein und im Bereich 0..180° liegen."

        self.save_config({
            "door_servo_min_angle": round(min_angle, 1),
            "door_servo_max_angle": round(max_angle, 1),
        })

        # Auch in gpio_mechanik.json synchronisieren
        mpath = DATA_DIR / "gpio_mechanik.json"
        try:
            mcfg = json.loads(mpath.read_text(encoding="utf-8")) if mpath.is_file() else {}
            mcfg["zu_grad"] = round(min_angle, 1)
            mcfg["offen_grad"] = round(max_angle, 1)
            mpath.write_text(json.dumps(mcfg, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("[GPIO] Konnte gpio_mechanik.json nicht synchronisieren: %s", exc)

        return True, f"Servowinkel erfolgreich gespeichert: ZU={min_angle:.1f}°, OFFEN={max_angle:.1f}°."

    def _debounce(self, pin: int) -> bool:
        """Entprellt Tastendrücke über Zeitdifferenz."""
        now = time.monotonic()
        last = self._last_edge_time.get(pin, 0.0)
        debounce_sec = float(self.config.get("debounce_ms", 50)) / 1000.0
        if (now - last) < debounce_sec:
            return False
        self._last_edge_time[pin] = now
        return True

    def _loop(self) -> None:
        """Hintergrund-Überwachung für GPIO-Taster (Polling mit 20ms)."""
        logger.info("[GPIO] Hardware-Taster Überwachung gestartet.")
        while not self._stop_event.is_set():
            if self._gpio and not self._is_simulated and self.config.get("enabled"):
                try:
                    c = self.config
                    estop_pin = int(c["estop_pin"])
                    ack_pin = int(c["button_ack_pin"])
                    pause_pin = int(c["button_pause_pin"])

                    # 1. Not-Halt prüfen
                    val = self._gpio.input(estop_pin)
                    pressed = (val == 0) if c["estop_mode"] == "nc" else (val == 1)
                    if pressed and not self._estop_triggered and self._debounce(estop_pin):
                        self.trigger_emergency_stop(source="hardware_button")

                    # 2. Quittiertaster (Pull-Up, LOW = gedrückt)
                    if self._gpio.input(ack_pin) == 0 and self._debounce(ack_pin):
                        if self._estop_triggered:
                            self.reset_emergency_stop(user="hardware_ack_button")
                        else:
                            try:
                                get_hardware(1).refill_magazine()
                            except Exception:
                                pass

                    # 3. Pause/Resume-Taster
                    if self._gpio.input(pause_pin) == 0 and self._debounce(pause_pin):
                        try:
                            client = printer_manager.get_client(1)
                            if client and getattr(client.state, "state", None) == "RUNNING":
                                printer_manager.pause_print(1)
                            elif client and getattr(client.state, "state", None) == "PAUSE":
                                printer_manager.resume_print(1)
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug("[GPIO] Fehler in Polling-Schleife: %s", exc)

            time.sleep(0.02)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="PrintLab-GpioHardware", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _restart_if_needed(self) -> None:
        self.stop()
        self._init_gpio()
        if self.config.get("enabled"):
            self.start()


# Globales Singleton
gpio_service = GpioHardwareService()

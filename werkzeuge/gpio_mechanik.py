#!/usr/bin/env python3
"""GPIO-Treiber für Tür und Plattenwechsler am Raspberry Pi (Befehl für die Hardware-Erweiterung von PrintLab).

PrintLab ruft das Skript im Modus "command" auf. In den Hardware-Einstellungen (Wartung) eintragen:
  Tür öffnen:     ["/home/<benutzer>/printlab/.venv/bin/python", "/home/<benutzer>/printlab/werkzeuge/gpio_mechanik.py", "door_open"]
  Tür schließen:  ... "door_close"
  Türstatus:      ... "door_check"       (gibt DOOR:OPEN, DOOR:CLOSED oder DOOR:UNKNOWN aus)
  Not-Halt:       ... "stop"             (Motoren stromlos, Servo aus)

Weitere Befehle zum Einrichten:
  status          Zustand der Eingänge und der Konfiguration
  pins            Pinbelegung ausgeben
  servo 90        Servo langsam auf 90 Grad fahren (Drehrichtung und Hebel prüfen, bevor das Gestänge dran ist)
  selftest        Endschalter und Plattensensor einlesen
  swap            verweigert den Dienst, solange die Bewegungsfolge der Mechanik nicht vermessen ist

Auf dem Raspberry Pi 5 funktioniert das alte RPi.GPIO nicht, dort:  sudo apt install python3-rpi-lgpio
(In der venv von PrintLab:  .venv/bin/pip install rpi-lgpio  ; die venv muss dazu --system-site-packages kennen
oder das Paket selbst installieren.)

Einstellungen stehen in  $DATA_DIR/gpio_mechanik.json  (Vorlage: werkzeuge/gpio_mechanik.beispiel.json), die letzte
Servo-Stellung in  $DATA_DIR/gpio_servo_stand.json. Das Servo fährt in kleinen Schritten, damit die Glastür nicht
schlägt. Ohne Endschalter ("endschalter": false) meldet door_check immer DOOR:UNKNOWN; ob die Tür wirklich zu ist,
prüft dann PrintLab mit dem Türsensor des Druckers.

Der Freigabe-Pin der Motortreiber sollte auf der Platine einen Pull-Up haben, damit die Motoren auch bei
floatenden Pins stromlos bleiben.

Sicherheit: Es gibt keinen stillen Wechsel in einen Simulationsmodus. Fehlt GPIO, bricht das Skript mit Fehler ab,
damit PrintLab nie eine Tür für offen hält, die sich nie bewegt hat.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent)
CONFIG_PATH = DATA_DIR / "gpio_mechanik.json"
STATE_PATH = DATA_DIR / "gpio_servo_stand.json"

# Standard-Pinbelegung (BCM-Nummern, 40-Pin-Leiste); in gpio_mechanik.json unter "pins" überschreibbar
DEFAULT_PINS = {
    "door_servo": 18,  # PWM, Pin 12
    "endstop_open": 23,  # Endschalter Tür offen, Pull-Up, Pin 16
    "endstop_closed": 24,  # Endschalter/Reed Tür zu, Pull-Up, Pin 18
    "plate_sensor": 25,  # Platte liegt plan auf dem Bett, Pull-Up, Pin 22
    "motor_x_step": 17,
    "motor_x_dir": 27,
    "motor_z_step": 22,
    "motor_z_dir": 10,
    "motors_enable": 9,  # HIGH = Motoren stromlos
}

SERVO_DEFAULTS = {
    "zu_grad": 10.0,  # Servo-Stellung Tür zu
    "offen_grad": 154.0,  # Servo-Stellung Tür offen
    "puls_min_us": 500,  # 500 µs = 0 Grad
    "puls_max_us": 2500,  # 2500 µs = Bereichsende
    "servo_bereich_grad": 180,
    "grad_pro_schritt": 2.0,  # kleine Schritte = langsame Tür
    "pause_s": 0.03,
    "endschalter": True,  # False: keine Schalter verbaut, der Druckersensor prüft
    "timeout_s": 8.0,  # Wartezeit auf den Endschalter
}


class GpioError(RuntimeError):
    """GPIO nicht verfügbar oder Konfiguration unbrauchbar."""


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = dict(SERVO_DEFAULTS)
    pins = dict(DEFAULT_PINS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key == "pins" and isinstance(value, dict):
                pins.update({k: int(v) for k, v in value.items() if k in DEFAULT_PINS})
            elif key in SERVO_DEFAULTS:
                cfg[key] = value
    for key in ("zu_grad", "offen_grad"):
        if not 0 <= float(cfg[key]) <= float(cfg["servo_bereich_grad"]):
            raise GpioError(f"{key} muss zwischen 0 und {cfg['servo_bereich_grad']} liegen.")
    if len(set(pins.values())) != len(pins):
        raise GpioError("Zwei Funktionen liegen auf demselben Pin (gpio_mechanik.json, Abschnitt pins).")
    cfg["pins"] = pins
    return cfg


class Mechanik:
    def __init__(self, gpio=None, config: dict | None = None, state_path: Path | None = STATE_PATH, sleep=time.sleep):
        self.cfg = config or load_config()
        self.pins = self.cfg["pins"]
        self.state_path = state_path
        self.sleep = sleep
        self.moves: list[float] = []
        self._pwm = None
        if gpio is None:
            try:
                import RPi.GPIO as gpio  # noqa: N813
            except (ImportError, RuntimeError) as exc:
                raise GpioError(
                    f"GPIO nicht verfügbar ({exc}). Auf dem Pi: sudo apt install python3-rpi-lgpio"
                ) from exc
        self.gpio = gpio
        self._setup()

    def _setup(self) -> None:
        g, p = self.gpio, self.pins
        g.setmode(g.BCM)
        g.setwarnings(False)
        for name in ("endstop_open", "endstop_closed", "plate_sensor"):
            g.setup(p[name], g.IN, pull_up_down=g.PUD_UP)
        for name in ("door_servo", "motor_x_step", "motor_x_dir", "motor_z_step", "motor_z_dir", "motors_enable"):
            g.setup(p[name], g.OUT)
        g.output(p["motors_enable"], g.HIGH)  # Motoren stromlos
        self._pwm = g.PWM(p["door_servo"], 50)
        self._pwm.start(0)

    def cleanup(self) -> None:
        if self._pwm:
            self._pwm.stop()
        self.gpio.cleanup()

    # --- Eingänge ---------------------------------------------------------------------------------------------

    def switch_active(self, name: str) -> bool:
        return self.gpio.input(self.pins[name]) == self.gpio.LOW

    # --- Servo ------------------------------------------------------------------------------------------------

    def _duty(self, angle: float) -> float:
        c = self.cfg
        pulse = c["puls_min_us"] + (c["puls_max_us"] - c["puls_min_us"]) * angle / c["servo_bereich_grad"]
        return pulse / 20000.0 * 100.0  # 50 Hz = 20 ms Periode

    def _last_angle(self) -> float | None:
        if self.state_path is None:
            return None
        try:
            return float(json.loads(self.state_path.read_text(encoding="utf-8"))["winkel"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_angle(self, angle: float) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.write_text(json.dumps({"winkel": round(angle, 1)}), encoding="utf-8")
        except OSError:
            pass

    def move_servo(self, target: float) -> None:
        """In kleinen Schritten vom letzten bekannten Winkel zum Ziel, danach PWM aus (Servo stromlos).

        Ohne bekannten Startwinkel (erster Lauf) wird das Ziel direkt angefahren.
        """
        if not 0 <= target <= self.cfg["servo_bereich_grad"]:
            raise GpioError(f"Winkel außerhalb 0..{self.cfg['servo_bereich_grad']} Grad.")
        start = self._last_angle()
        step = max(0.5, float(self.cfg["grad_pro_schritt"]))
        angles = [target]
        if start is not None and abs(target - start) > step:
            n = int(abs(target - start) // step)
            direction = 1 if target > start else -1
            angles = [start + direction * step * i for i in range(1, n + 1)] + [target]
        for angle in angles:
            self.moves.append(round(angle, 1))
            self._pwm.ChangeDutyCycle(self._duty(angle))
            self.sleep(float(self.cfg["pause_s"]))
        self.sleep(0.3)  # letzte Stellung erreichen lassen
        self._pwm.ChangeDutyCycle(0)
        self._save_angle(target)

    def _wait_for(self, switch: str) -> bool:
        deadline = time.monotonic() + float(self.cfg["timeout_s"])
        while True:
            if self.switch_active(switch):
                return True
            if time.monotonic() >= deadline:
                return False
            self.sleep(0.05)

    # --- Befehle ----------------------------------------------------------------------------------------------

    def door_open(self) -> bool:
        self.move_servo(float(self.cfg["offen_grad"]))
        if not self.cfg["endschalter"]:
            print("DOOR:UNKNOWN")  # keine Schalter: PrintLab prüft mit dem Türsensor des Druckers
            return True
        if self._wait_for("endstop_open"):
            print("DOOR:OPEN")
            return True
        print("FEHLER: Tür öffnet nicht (Endschalter offen nicht ausgelöst).", file=sys.stderr)
        print("DOOR:UNKNOWN")
        return False

    def door_close(self) -> bool:
        self.move_servo(float(self.cfg["zu_grad"]))
        if not self.cfg["endschalter"]:
            print("DOOR:UNKNOWN")
            return True
        if self._wait_for("endstop_closed"):
            print("DOOR:CLOSED")
            return True
        print("FEHLER: Tür schließt nicht (Hindernis?).", file=sys.stderr)
        print("DOOR:UNKNOWN")
        return False

    def door_check(self) -> str:
        if not self.cfg["endschalter"]:
            state = "UNKNOWN"
        else:
            opened, closed = self.switch_active("endstop_open"), self.switch_active("endstop_closed")
            state = "UNKNOWN" if opened == closed else ("OPEN" if opened else "CLOSED")  # beide oder keiner: unklar
        print(f"DOOR:{state}")
        return state

    def stop(self) -> None:
        """Not-Halt: Motoren stromlos, Servo ohne Signal."""
        self.gpio.output(self.pins["motors_enable"], self.gpio.HIGH)
        self._pwm.ChangeDutyCycle(0)
        print("STOP:OK")

    def swap(self) -> bool:
        print(
            "FEHLER: Plattenwechsel ist für die GPIO-Variante noch nicht umgesetzt. Die Bewegungsfolge hängt von der "
            "fertigen Mechanik ab und muss erst vermessen werden; bis dahin bewegt das Skript keine Motoren blind.",
            file=sys.stderr,
        )
        return False

    def selftest(self) -> dict:
        result = {name: self.switch_active(name) for name in ("endstop_open", "endstop_closed", "plate_sensor")}
        for name, active in result.items():
            print(f"{name}: {'AKTIV (Kontakt geschlossen)' if active else 'inaktiv'}")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPIO-Treiber für Tür und Plattenwechsler (PrintLab)")
    parser.add_argument(
        "command",
        choices=["door_open", "door_close", "door_check", "stop", "swap", "status", "pins", "servo", "selftest"],
    )
    parser.add_argument("value", nargs="?", type=float, help="servo: Winkel in Grad")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        if args.command == "pins":
            for name, pin in config["pins"].items():
                print(f"{name}: GPIO {pin}")
            return 0
        mech = Mechanik(config=config)
    except GpioError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "door_open":
            return 0 if mech.door_open() else 1
        if args.command == "door_close":
            return 0 if mech.door_close() else 1
        if args.command == "door_check":
            return 0 if mech.door_check() in ("OPEN", "CLOSED") else 1
        if args.command == "stop":
            mech.stop()
            return 0
        if args.command == "swap":
            return 0 if mech.swap() else 1
        if args.command == "selftest":
            mech.selftest()
            return 0
        if args.command == "servo":
            if args.value is None:
                print("FEHLER: Winkel in Grad angeben, zum Beispiel: servo 90", file=sys.stderr)
                return 1
            mech.move_servo(args.value)
            print(f"Servo auf {args.value:g} Grad.")
            return 0
        if args.command == "status":
            print(f"DOOR={mech.door_check()} | ENDSCHALTER={'ja' if mech.cfg['endschalter'] else 'nein'} | READY=1")
            return 0
    except GpioError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.command != "stop":  # nach dem Not-Halt die Pins so lassen (Freigabe-Pin bleibt HIGH)
            mech.cleanup()
    return 1


if __name__ == "__main__":
    sys.exit(main())

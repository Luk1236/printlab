#!/usr/bin/env python3
"""Überwachung von außen: prüft, ob PrintLab antwortet, startet es bei Ausfall neu und meldet das aufs Handy.

Läuft jede Minute als systemd-Timer (siehe werkzeuge/pi_neu_installieren.sh), unabhängig von PrintLab selbst. Eine
Meldung aus PrintLab kann nicht kommen, wenn PrintLab nicht läuft, deshalb sitzt die Prüfung außerhalb.

Meldewege (Umgebungsvariablen, zum Beispiel in ~/.config/printlab.env):
  PRINTLAB_ALERT_TELEGRAM_TOKEN + PRINTLAB_ALERT_TELEGRAM_CHAT   Telegram-Bot
  PRINTLAB_ALERT_NTFY_URL                                        ntfy.sh-Thema, z. B. https://ntfy.sh/mein-thema
Ohne Meldeweg wird nur geprüft, neu gestartet und ins Journal geschrieben.

Weitere Einstellungen: PRINTLAB_WATCH_URL (Standard http://localhost:8000/api/v1/updates/version),
PRINTLAB_WATCH_FAILS (Fehlschläge bis zum Neustart, Standard 3), DATA_DIR (für Statusdatei und Speicherplatz).
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from backend.app.services import alert_channels  # noqa: E402

FAILS_BEFORE_RESTART = 3
MIN_SECONDS_BETWEEN_RESTARTS = 600
REMINDER_EVERY_FAILS = 30  # etwa alle 30 Minuten, solange der Ausfall anhält
LOW_DISK_BYTES = 1_000_000_000
DISK_REMINDER_SECONDS = 24 * 3600


def run_check(state: dict, *, probe, restart, notify, now: float, free_bytes: int | None = None, fail_limit: int = 3):
    """Ein Prüfdurchlauf. Verändert ``state`` und gibt es zurück; Probe, Neustart und Meldung werden übergeben."""
    state.setdefault("fails", 0)
    state.setdefault("alerted", False)
    state.setdefault("last_restart", -1e12)
    state.setdefault("last_disk_alert", -1e12)

    if probe():
        if state["alerted"]:
            notify("PrintLab läuft wieder.")
        state["fails"] = 0
        state["alerted"] = False
    else:
        state["fails"] += 1
        if state["fails"] == fail_limit:
            restarted = False
            if now - state["last_restart"] >= MIN_SECONDS_BETWEEN_RESTARTS:
                restarted = bool(restart())
                state["last_restart"] = now
            notify(
                f"PrintLab antwortet seit {state['fails']} Minuten nicht."
                + (
                    " Neustart wurde ausgelöst."
                    if restarted
                    else " Ein Neustart war nicht möglich oder lief erst vor Kurzem."
                )
            )
            state["alerted"] = True
        elif state["fails"] > fail_limit and state["fails"] % REMINDER_EVERY_FAILS == 0:
            notify(f"PrintLab antwortet weiterhin nicht (seit {state['fails']} Minuten). Bitte nachsehen.")

    if (
        free_bytes is not None
        and free_bytes < LOW_DISK_BYTES
        and now - state["last_disk_alert"] >= DISK_REMINDER_SECONDS
    ):
        notify(f"Wenig Speicherplatz auf dem Pi: noch {free_bytes / 1e9:.1f} GB frei.")
        state["last_disk_alert"] = now
    return state


def http_probe(url: str, timeout: float = 8.0) -> bool:
    if not url.lower().startswith(("http://", "https://")):  # nie file:// oder andere Schemata öffnen
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - feste, lokale Adresse
            return 200 <= response.status < 300
    except (OSError, ValueError):
        return False


def systemd_restart() -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            ["systemctl", "--user", "restart", "printlab.service"],  # noqa: S607
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def make_notifier(environ=os.environ, data_dir=None):
    """Baut die Meldefunktion. Wege kommen aus ``alert_channels.json`` im Datenordner (Oberfläche) und aus den
    Umgebungsvariablen (diese haben Vorrang). Fehler beim Senden werden nur ins Journal geschrieben, nie mit Adresse."""
    config = alert_channels.effective(data_dir, environ)
    host = socket.gethostname()

    def notify(message: str) -> None:
        text = f"[{host}] {message}"
        print(text, flush=True)
        result = alert_channels.send(config, text)
        for error in result["errors"]:
            print(f"Meldung konnte nicht gesendet werden: {error}", file=sys.stderr, flush=True)

    return notify


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        print(f"Statusdatei nicht schreibbar: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    data_dir = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent)
    url = os.environ.get("PRINTLAB_WATCH_URL", "http://localhost:8000/api/v1/updates/version")
    try:
        fail_limit = max(1, int(os.environ.get("PRINTLAB_WATCH_FAILS", FAILS_BEFORE_RESTART)))
    except ValueError:
        fail_limit = FAILS_BEFORE_RESTART
    state_path = data_dir / "watch_state.json"
    try:
        free = shutil.disk_usage(data_dir).free
    except OSError:
        free = None
    state = run_check(
        load_state(state_path),
        probe=lambda: http_probe(url),
        restart=systemd_restart,
        notify=make_notifier(data_dir=data_dir),
        now=time.time(),
        free_bytes=free,
        fail_limit=fail_limit,
    )
    save_state(state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

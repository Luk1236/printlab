#!/usr/bin/env python3
"""Abnahme-Check für den Raspberry Pi: prüft automatisch alles, was sich ohne Drucker und Hardware prüfen lässt.

Aufruf auf dem Pi (im Ordner ~/printlab):
  .venv/bin/python werkzeuge/abnahme.py            Ergebnis als Liste
  .venv/bin/python werkzeuge/abnahme.py --json     für Auswertung durch Programme
Rückgabecode: 0 = alles in Ordnung oder nur Hinweise, 1 = mindestens ein Fehler.

Stufen: OK (in Ordnung), WARN (sollte man beheben), FAIL (so nicht sicher/stabil), SKIP (hier nicht prüfbar).
Was echte Hardware braucht (Tür-Servo, Endschalter, Plattenwechsler, Drucker, Slicer): docs/ABNAHME-PI.md
Abschnitte 3 (Reihenfolge am Gerät) und docs/ABNAHME.md (alle Prüfungen).
"""

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # backup_pruefen.py liegt daneben

from backend.app.services import pi_health  # noqa: E402

HOME = Path.home()
DATA_DIR = Path(os.environ.get("DATA_DIR") or APP_DIR / "data")
UNIT = HOME / ".config" / "systemd" / "user" / "printlab.service"
ENV_FILE = HOME / ".config" / "printlab.env"
BASE_URL = os.environ.get("PRINTLAB_URL", "http://127.0.0.1:8000")

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"


def get_json(path: str, timeout: float = 8.0):
    """(Status, JSON oder None); nie eine Ausnahme."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as response:  # noqa: S310 - lokale Adresse
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError):
        return None, None


def systemctl(*args: str) -> str | None:
    if shutil.which("systemctl") is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            ["systemctl", "--user", *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def check_service():
    status, data = get_json("/api/v1/updates/version")
    if status == 200 and data:
        return OK, "PrintLab antwortet", f"Version {data.get('version')}"
    return FAIL, "PrintLab antwortet nicht", f"{BASE_URL} (journalctl --user -u printlab -n 40)"


def check_auth():
    status, data = get_json("/api/v1/auth/status")
    if status != 200 or not data:
        return SKIP, "Anmeldung", "Status nicht lesbar"
    if not data.get("auth_enabled"):
        return FAIL, "Anmeldung ist AUS", "Jeder im Netz kann PrintLab bedienen: Einrichtung unter /setup abschließen"
    if not data.get("auth_required"):
        return (
            WARN,
            "Anmeldung ist an, aber nicht vorgeschrieben",
            "Environment=PRINTLAB_REQUIRE_AUTH=1 in der Dienst-Datei",
        )
    return OK, "Anmeldung ist an und vorgeschrieben", ""


def check_unit():
    text = read_text(UNIT)
    if text is None:
        return SKIP, "Dienst-Datei", f"{UNIT} nicht gefunden (kein Installer-Aufbau?)"
    missing = [
        label
        for needle, label in (
            ("Restart=always", "Restart=always"),
            ("update_guard.py", "Update-Schutz (ExecStartPre)"),
            ("PRINTLAB_AUTO_RESTART=1", "PRINTLAB_AUTO_RESTART=1"),
            ("PRINTLAB_REQUIRE_AUTH=1", "PRINTLAB_REQUIRE_AUTH=1"),
        )
        if needle not in text
    ]
    if missing:
        return WARN, "Dienst-Datei unvollständig", "fehlt: " + ", ".join(missing) + " (Installer erneut ausführen)"
    return OK, "Dienst-Datei vollständig", ""


def check_watch_timer():
    active = systemctl("is-active", "printlab-watch.timer")
    if active is None:
        return SKIP, "Überwachung", "systemctl nicht verfügbar"
    if active == "active":
        return OK, "Überwachung läuft", "Timer printlab-watch.timer"
    return (
        WARN,
        "Überwachung läuft nicht",
        "Installer erneut ausführen oder systemctl --user enable --now printlab-watch.timer",
    )


def check_alert_channel():
    env_text = read_text(ENV_FILE) or ""
    configured = ("PRINTLAB_ALERT_TELEGRAM_TOKEN=" in env_text and "PRINTLAB_ALERT_TELEGRAM_CHAT=" in env_text) or (
        "PRINTLAB_ALERT_NTFY_URL=" in env_text
    )
    if configured:
        return OK, "Meldeweg für Ausfälle eingetragen", ""
    return (
        WARN,
        "Kein Meldeweg für Ausfälle",
        "PRINTLAB_ALERT_TELEGRAM_* oder PRINTLAB_ALERT_NTFY_URL in ~/.config/printlab.env",
    )


def check_env_permissions():
    if not ENV_FILE.exists():
        return SKIP, "Rechte der Zugangsdatei", "keine ~/.config/printlab.env"
    mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
    if mode & 0o077:
        return FAIL, "Zugangsdatei ist für andere lesbar", f"chmod 600 {ENV_FILE} (aktuell {oct(mode)})"
    return OK, "Zugangsdatei nur für dich lesbar", ""


def check_signature():
    path = DATA_DIR / "update_allowed_signers"
    if not path.is_file():
        return WARN, "Updates werden nicht auf Signatur geprüft", "docs/UPDATE-SIGNATUR.md"
    if shutil.which("ssh-keygen") is None:
        return (
            FAIL,
            "Signaturprüfung an, aber ssh-keygen fehlt",
            "sudo apt install openssh-client (sonst werden alle Updates abgelehnt)",
        )
    return OK, "Updates nur mit gültiger Signatur", ""


def check_backups():
    extra = [HOME / "printlab-backups"]
    target = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    if target:
        extra.append(Path(target))
    latest = pi_health.latest_backup(DATA_DIR, extra)
    if latest is None:
        return (
            WARN,
            "Keine Sicherung gefunden",
            "Wird beim nächsten Update angelegt; oder sicherung_extern.py einrichten",
        )
    import backup_pruefen  # noqa: PLC0415

    problems = backup_pruefen.check_folder(Path(latest["path"]))
    if problems:
        return FAIL, "Neueste Sicherung ist beschädigt", "; ".join(problems[:3])
    if latest["age_days"] > pi_health.BACKUP_MAX_AGE_DAYS:
        return WARN, "Neueste Sicherung ist alt", f"{latest['age_days']:g} Tage ({latest['path']})"
    return OK, "Neueste Sicherung ist in Ordnung", f"{latest['age_days']:g} Tage alt"


def check_external_backup():
    target = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    if not target:
        return WARN, "Keine Sicherung außerhalb der SD-Karte", "docs/INSTALLATION-PI.md → Sicherung nach außen"
    if not Path(target).is_dir():
        return FAIL, "Sicherungsziel nicht erreichbar", target
    return OK, "Sicherungsziel erreichbar", target


def check_health():
    info = pi_health.snapshot(DATA_DIR)
    crit = [w["text"] for w in info["warnings"] if w["level"] == "crit" and w["code"] != "external_failed"]
    warn = [w["text"] for w in info["warnings"] if w["level"] == "warn" and not w["code"].startswith("backup")]
    if crit:
        return FAIL, "Zustand des Rechners", " | ".join(crit)
    if warn:
        return WARN, "Zustand des Rechners", " | ".join(warn)
    if info["cpu_temp_c"] is None and info["storage"] is None and info["memory"] is None:
        return SKIP, "Zustand des Rechners", "auf diesem System nicht messbar (kein Raspberry Pi / Linux)"
    return OK, "Zustand des Rechners", "Temperatur, Spannung, Speicher in Ordnung"


def check_virtual_printer_ports():
    ports = {3000: "Erkennung", 3002: "Erkennung (TLS)", 990: "Datei-Upload", 8883: "Steuerung"}
    status, _ = get_json("/api/v1/updates/version")
    if status != 200:
        return SKIP, "Ports des virtuellen Druckers", "PrintLab nicht erreichbar"
    open_ports = [p for p in ports if port_open(p)]
    if len(open_ports) == len(ports):
        return OK, "Virtueller Drucker lauscht", "alle vier Ports offen"
    if not open_ports:
        return SKIP, "Virtueller Drucker", "ist nicht aktiviert (Einstellungen → Virtueller Drucker)"
    closed = ", ".join(f"{p} ({ports[p]})" for p in ports if p not in open_ports)
    return WARN, "Virtueller Drucker nur teilweise erreichbar", "geschlossen: " + closed


def check_git():
    if shutil.which("git") is None:
        return FAIL, "git fehlt", "sudo apt install git (ohne git kein Update)"
    if not (APP_DIR / ".git").exists():
        return WARN, "Kein Git-Ordner", "Update aus der Oberfläche nicht möglich"
    return OK, "git und Git-Ordner vorhanden", ""


CHECKS = [
    check_service,
    check_auth,
    check_unit,
    check_git,
    check_signature,
    check_watch_timer,
    check_alert_channel,
    check_env_permissions,
    check_backups,
    check_external_backup,
    check_health,
    check_virtual_printer_ports,
]


def run_all(checks=None) -> list[dict]:
    results = []
    for check in checks or CHECKS:
        try:
            level, title, detail = check()
        except Exception as exc:  # ein kaputter Check darf die anderen nicht verhindern
            level, title, detail = FAIL, check.__name__, f"Prüfung abgestürzt: {type(exc).__name__}"
        results.append({"level": level, "title": title, "detail": detail})
    return results


def main(argv: list[str]) -> int:
    results = run_all()
    if "--json" in argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"[{r['level']:<4}] {r['title']}" + (f" — {r['detail']}" if r["detail"] else ""))
        counts = {level: sum(1 for r in results if r["level"] == level) for level in (OK, WARN, FAIL, SKIP)}
        print(
            f"\n{counts[OK]} in Ordnung, {counts[WARN]} Hinweise, {counts[FAIL]} Fehler, {counts[SKIP]} nicht prüfbar."
        )
    return 1 if any(r["level"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Tägliche Sicherung auf einen Datenträger außerhalb der SD-Karte (USB-Stick/-Platte, NAS-Freigabe), mit Prüfung.

Einstellung in ~/.config/printlab.env (Rechte 600):
  PRINTLAB_BACKUP_TARGET=/media/usb/printlab-sicherung   vorhandener Ordner auf dem Datenträger (wird NICHT angelegt,
                                                          damit bei nicht eingehängtem Stick nichts auf der SD-Karte landet)
  PRINTLAB_BACKUP_KEEP=7                                  so viele Sicherungen bleiben (Standard 7)
  PRINTLAB_BACKUP_ALLOW_SAME_DISK=1                       Ziel auf demselben Datenträger erlauben (nicht empfohlen)
  PRINTLAB_BACKUP_INCLUDE_SECRETS=1                       Zugangsdatei als Kopie mit in die Sicherung legen (0600).
                                                          Nur einschalten, wenn das Ziel geschützt ist (verschlüsselter
                                                          Datenträger oder NAS mit Zugriffsbeschränkung), denn die
                                                          Datei enthält Telegram-/ntfy-/GitHub-Zugänge.
Meldung bei Fehlern wie bei der Überwachung (PRINTLAB_ALERT_TELEGRAM_* oder PRINTLAB_ALERT_NTFY_URL).

Was gesichert wird: alle Datenbanken (konsistente Kopie, auch bei laufendem PrintLab) und die Einstellungsdateien im
Datenordner. Die Zugangsdatei ~/.config/printlab.env nur mit PRINTLAB_BACKUP_INCLUDE_SECRETS=1 (0600-Kopie im
Sicherungsordner). Jede Sicherung wird nach dem Schreiben geprüft (Datenbank-Integrität, gültiges JSON); eine kaputte
Sicherung wird gelöscht und gemeldet. Läuft als systemd-Timer (printlab-backup.timer, vom Installer eingerichtet) oder
von Hand.
Rückgabecode: 0 = Sicherung ok oder nichts eingestellt, 1 = Fehler.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_pruefen  # noqa: E402
import ueberwachung  # noqa: E402

from backend.app.services import update_guard  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR") or APP_DIR / "data")
PREFIX = "printlab-"


def same_device(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False


def prune(target: Path, keep: int) -> list[str]:
    folders = sorted(p for p in target.iterdir() if p.is_dir() and p.name.startswith(PREFIX))
    removed = []
    for old in folders[: max(0, len(folders) - keep)]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    return removed


def copy_secrets(folder: Path, source: Path | None = None) -> bool:
    """Zugangsdatei als 0600-Kopie in die Sicherung legen (nur bei ausdrücklichem Opt-in).

    Ohne Kopie ist eine frische Wiederherstellung mühsam, weil Token und Ports fehlen —
    mit Kopie liegen Geheimnisse auf dem Sicherungsziel, deshalb keine Voreinstellung.
    """
    source = source or Path.home() / ".config" / "printlab.env"
    if not source.is_file():
        return False
    copy = folder / source.name
    shutil.copyfile(source, copy)
    try:
        os.chmod(copy, 0o600)
    except OSError:
        pass  # z. B. FAT/NAS-Dateisystem ohne Rechte; die Kopie bleibt der einzige Zweck
    return True


def run_backup(
    data_dir: Path, target: Path, keep: int = 7, allow_same_disk: bool = False, include_secrets: bool = False
) -> dict:
    """Eine Sicherung anlegen und prüfen. Wirft RuntimeError mit lesbarer Meldung bei jedem Problem."""
    if not target.is_dir():
        raise RuntimeError(f"Sicherungsziel nicht erreichbar: {target} (Stick nicht eingehängt?)")
    if not os.access(target, os.W_OK):
        raise RuntimeError(f"Sicherungsziel nicht beschreibbar: {target}")
    if not allow_same_disk and same_device(target, data_dir):
        raise RuntimeError(
            f"{target} liegt auf demselben Datenträger wie die Daten; das schützt nicht vor einem Ausfall der SD-Karte "
            "(PRINTLAB_BACKUP_ALLOW_SAME_DISK=1 erlaubt es trotzdem)."
        )
    folder = target / f"{PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        saved = update_guard.backup_data(data_dir, folder)
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError(f"Sicherung fehlgeschlagen: {exc}") from exc
    problems = backup_pruefen.check_folder(folder)
    if problems:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError("Die Sicherung war beschädigt und wurde gelöscht: " + "; ".join(problems[:3]))
    included_secrets = copy_secrets(folder) if include_secrets else None
    removed = prune(target, keep)
    result = {"folder": str(folder), "saved": saved, "removed": removed}
    if include_secrets:
        result["secrets"] = "printlab.env (0600)" if included_secrets else None
    return result


def write_status(data_dir: Path, ok: bool, detail: str) -> None:
    try:
        (data_dir / "last_external_backup.json").write_text(
            json.dumps({"ok": ok, "detail": detail, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8"
        )
    except OSError:
        pass


def main() -> int:
    target_text = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    if not target_text:
        print("Keine externe Sicherung eingestellt (PRINTLAB_BACKUP_TARGET fehlt), nichts zu tun.")
        return 0
    try:
        keep = max(1, int(os.environ.get("PRINTLAB_BACKUP_KEEP", "7")))
    except ValueError:
        keep = 7
    notify = ueberwachung.make_notifier(data_dir=DATA_DIR)
    try:
        result = run_backup(
            DATA_DIR,
            Path(target_text),
            keep,
            os.environ.get("PRINTLAB_BACKUP_ALLOW_SAME_DISK") == "1",
            os.environ.get("PRINTLAB_BACKUP_INCLUDE_SECRETS") == "1",
        )
    except RuntimeError as exc:
        write_status(DATA_DIR, False, str(exc))
        notify(f"Sicherung nach außen fehlgeschlagen: {exc}")
        return 1
    write_status(DATA_DIR, True, result["folder"])
    print(f"Sicherung ok: {result['folder']} ({len(result['saved'])} Dateien, {len(result['removed'])} alte gelöscht)")
    print(
        "Zugangsdatei: "
        + (
            result["secrets"]
            if result.get("secrets")
            else "nicht gesichert (Standard) — PRINTLAB_BACKUP_INCLUDE_SECRETS=1 legt eine 0600-Kopie bei, nur bei geschütztem Ziel"
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

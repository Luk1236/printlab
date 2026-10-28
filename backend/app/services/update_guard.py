"""Update-Schutz: Sicherung vor dem Update und automatischer Rückbau, wenn die neue Version nicht startet.

Ablauf:
1. Der Updater ruft ``prepare()`` auf, bevor er auf die neue Version wechselt. Das merkt sich den bisherigen
   Git-Stand, sichert Datenbank und Einstellungsdateien und legt die Marke ``update_pending.json`` an.
2. Bei jedem Start des Dienstes zählt ``werkzeuge/update_guard.py`` (systemd ``ExecStartPre``) mit ``guard()`` die
   Starts seit dem Update. Läuft die neue Version nicht stabil an, geht ``guard()`` zum bisherigen Stand zurück
   und spielt die gesicherte Datenbank wieder ein.
3. Hat die App nach dem Start ``CONFIRM_AFTER_SECONDS`` lang durchgehalten, löscht ``confirm()`` die Marke. Ab dann
   gilt das Update als gelungen.

Nur Standardbibliothek: das Modul läuft auch, wenn die App selbst nicht mehr importierbar ist.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_NAME = "update_pending.json"
ROLLED_BACK_NAME = "update_rolled_back.json"
BACKUP_FOLDER = "update-backups"
KEEP_BACKUPS = 3
MAX_STARTS = 3  # ab dem vierten Start ohne Bestätigung wird zurückgebaut
CONFIRM_AFTER_SECONDS = 90  # der erste Start auf dem Pi dauert gut eine Minute

_pending_tasks: set[asyncio.Task] = set()


class UpdateGuardError(RuntimeError):
    """Die Sicherung vor dem Update ist fehlgeschlagen; das Update wird nicht begonnen."""


def _in(data_dir: Path | str, *names: str) -> Path:
    """Pfad im Datenordner; nur mit festen Dateinamen aufrufen."""
    return Path(data_dir).joinpath(*names)  # SEC-PATH-OK: nur feste Namenskonstanten, nie Eingaben von außen


def _git(app_dir: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
        ["git", "-c", f"safe.directory={app_dir}", *args],  # noqa: S607
        cwd=str(app_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def current_commit(app_dir: Path) -> str | None:
    try:
        result = _git(app_dir, "rev-parse", "HEAD", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_marker(data_dir: Path) -> dict | None:
    return _read_json(_in(data_dir, MARKER_NAME))


def read_rollback_notice(data_dir: Path) -> dict | None:
    return _read_json(_in(data_dir, ROLLED_BACK_NAME))


def clear_rollback_notice(data_dir: Path) -> None:
    _in(data_dir, ROLLED_BACK_NAME).unlink(missing_ok=True)


def _copy_sqlite(source: Path, target: Path) -> None:
    """Konsistente Kopie auch bei laufender App (WAL), über die Backup-Schnittstelle von SQLite."""
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def verify_sqlite(path: Path) -> bool:
    """True, wenn die Datenbankdatei sich öffnen lässt und ``PRAGMA integrity_check`` "ok" meldet."""
    try:
        con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.Error:
        return False


def backup_data(data_dir: Path, backup_dir: Path) -> list[str]:
    """Sichert alle Datenbanken und Einstellungsdateien im obersten Ordner des Datenverzeichnisses."""
    data_dir = Path(data_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for db in sorted(data_dir.glob("*.db")):
        _copy_sqlite(db, backup_dir / db.name)
        if not verify_sqlite(backup_dir / db.name):
            raise sqlite3.DatabaseError(f"Die Sicherung von {db.name} ist nicht in Ordnung.")
        saved.append(db.name)
    for cfg in sorted(data_dir.glob("*.json")):
        if cfg.name in (MARKER_NAME, ROLLED_BACK_NAME):
            continue
        shutil.copy2(cfg, backup_dir / cfg.name)
        saved.append(cfg.name)
    return saved


def _prune_backups(data_dir: Path) -> None:
    root = _in(data_dir, BACKUP_FOLDER)
    folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    for old in folders[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)


def prepare(app_dir: Path, data_dir: Path, target_ref: str, version: str) -> dict:
    """Vor dem Wechsel auf die neue Version aufrufen. Wirft ``UpdateGuardError``, wenn die Sicherung scheitert."""
    app_dir, data_dir = Path(app_dir), Path(data_dir)
    commit = current_commit(app_dir)
    if not commit:
        raise UpdateGuardError("Der aktuelle Git-Stand ist nicht lesbar.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = _in(data_dir, BACKUP_FOLDER, stamp)
    try:
        saved = backup_data(data_dir, backup_dir)
    except (OSError, sqlite3.Error) as exc:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise UpdateGuardError(f"Sicherung nicht möglich: {exc}") from exc
    marker = {
        "previous_commit": commit,
        "previous_version": version,
        "target_ref": target_ref,
        "backup_dir": str(backup_dir),
        "saved": saved,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "starts": 0,
    }
    _write_json(_in(data_dir, MARKER_NAME), marker)
    clear_rollback_notice(data_dir)
    _prune_backups(data_dir)
    return marker


def confirm(data_dir: Path) -> bool:
    """Das Update gilt als gelungen: Marke löschen. True, wenn eine Marke da war."""
    marker = _in(data_dir, MARKER_NAME)
    existed = marker.exists()
    marker.unlink(missing_ok=True)
    return existed


def _restore_data(data_dir: Path, backup_dir: Path) -> list[str]:
    restored: list[str] = []
    if not backup_dir.is_dir():
        return restored
    for item in sorted(backup_dir.iterdir()):
        if not item.is_file():
            continue
        target = Path(data_dir) / item.name
        shutil.copy2(item, target)
        if item.suffix == ".db":
            for extra in (".db-wal", ".db-shm"):
                (Path(data_dir) / (item.stem + extra)).unlink(missing_ok=True)
        restored.append(item.name)
    return restored


def rollback(app_dir: Path, data_dir: Path, marker: dict, reason: str) -> bool:
    """Auf den vor dem Update gemerkten Git-Stand zurück und die gesicherten Daten wieder einspielen."""
    app_dir, data_dir = Path(app_dir), Path(data_dir)
    commit = marker.get("previous_commit")
    if not isinstance(commit, str) or not commit:
        return False
    try:
        result = _git(app_dir, "reset", "--hard", commit)
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        logger.error("Rückbau: git reset fehlgeschlagen: %s", result.stderr.strip())
        return False
    restored = _restore_data(data_dir, Path(str(marker.get("backup_dir", ""))))
    _write_json(
        _in(data_dir, ROLLED_BACK_NAME),
        {
            "from_ref": marker.get("target_ref"),
            "to_commit": commit,
            "to_version": marker.get("previous_version"),
            "reason": reason,
            "restored": restored,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    _in(data_dir, MARKER_NAME).unlink(missing_ok=True)
    return True


def guard(app_dir: Path, data_dir: Path) -> str:
    """Beim Start des Dienstes (vor der App). Rückgabe: ``none``, ``counted`` oder ``rolled_back``/``rollback_failed``."""
    data_dir = Path(data_dir)
    marker = read_marker(data_dir)
    if marker is None:
        return "none"
    starts = int(marker.get("starts", 0)) + 1
    if starts > MAX_STARTS:
        reason = f"Die neue Version ist {starts - 1}-mal nicht stabil gestartet."
        return "rolled_back" if rollback(Path(app_dir), data_dir, marker, reason) else "rollback_failed"
    marker["starts"] = starts
    _write_json(_in(data_dir, MARKER_NAME), marker)
    return "counted"


async def _confirm_later(data_dir: Path, delay: float) -> None:
    await asyncio.sleep(delay)
    if confirm(data_dir):
        logger.info("Update bestätigt: die neue Version läuft stabil")


def schedule_confirmation(data_dir: Path, delay: float = CONFIRM_AFTER_SECONDS) -> bool:
    """Beim App-Start aufrufen: bestätigt ein offenes Update, sobald die App ``delay`` Sekunden durchgehalten hat."""
    if read_marker(data_dir) is None:
        return False
    task = asyncio.get_running_loop().create_task(_confirm_later(Path(data_dir), delay))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    return True


def ensure_systemd_guard(app_dir: Path, python: str, unit_path: Path | None = None) -> bool:
    """Trägt den Update-Schutz in eine bestehende systemd-Benutzer-Unit nach (ältere Installationen). True, wenn geändert."""
    unit = unit_path or Path.home() / ".config" / "systemd" / "user" / "printlab.service"
    try:
        text = unit.read_text(encoding="utf-8")
    except OSError:
        return False
    if "update_guard.py" in text or "\nExecStart=" not in text:
        return False
    line = f"ExecStartPre=-{python} {Path(app_dir) / 'werkzeuge' / 'update_guard.py'}\n"
    try:
        unit.write_text(text.replace("\nExecStart=", "\n" + line + "ExecStart=", 1), encoding="utf-8")
        subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            ["systemctl", "--user", "daemon-reload"],  # noqa: S607
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True

#!/usr/bin/env python3
"""Sicherungen prüfen (Windows, Linux, Pi): Datenbanken auf Integrität, Einstellungsdateien auf gültiges JSON.

Ohne Argument wird die jeweils neueste Sicherung aus diesen Ordnern geprüft:
  <Datenordner>/update-backups   (automatisch vor jedem Update in PrintLab)
  ~/printlab-backups             (vom Neuaufspielen mit pi_neu_installieren.sh)
  <Projektordner>/backup         (lokale Sicherung unter Windows)
Mit einem Ordner als Argument wird genau dieser geprüft. Rückgabecode 0 = alles in Ordnung, 1 = Mangel, 2 = nichts
gefunden. Gut als regelmäßige Prüfung, damit eine kaputte Sicherung auffällt, bevor man sie braucht.
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or APP_DIR / "data")


def newest_backup() -> Path | None:
    roots = [DATA_DIR / "update-backups", Path.home() / "printlab-backups", APP_DIR / "backup"]
    candidates = [p for root in roots if root.is_dir() for p in root.iterdir() if p.is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def check_database(path: Path) -> str | None:
    """None, wenn in Ordnung, sonst die Fehlermeldung."""
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            result = con.execute("PRAGMA integrity_check").fetchone()[0]
            tables = con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        return f"nicht lesbar ({exc})"
    if result != "ok":
        return f"Integritätsprüfung meldet: {result}"
    return "keine Tabellen" if tables == 0 else None


def check_folder(folder: Path) -> list[str]:
    """Liste der Mängel; leer, wenn die Sicherung in Ordnung ist."""
    problems: list[str] = []
    files = [p for p in folder.rglob("*") if p.is_file()]
    databases = [p for p in files if p.suffix == ".db"]
    if not databases:
        problems.append("keine Datenbank in der Sicherung")
    for db in databases:
        if db.stat().st_size == 0:
            problems.append(f"{db.name}: leer")
            continue
        problem = check_database(db)
        if problem:
            problems.append(f"{db.name}: {problem}")
    for cfg in (p for p in files if p.suffix == ".json"):
        try:
            json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{cfg.name}: kein gültiges JSON")
    return problems


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else newest_backup()
    if folder is None or not folder.is_dir():
        print("Keine Sicherung gefunden.")
        return 2
    age_days = (time.time() - folder.stat().st_mtime) / 86400
    problems = check_folder(folder)
    print(f"Sicherung: {folder} (vor {age_days:.1f} Tagen)")
    if problems:
        for problem in problems:
            print(f"  MANGEL: {problem}")
        return 1
    print("  alles in Ordnung")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

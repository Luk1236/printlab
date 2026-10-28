#!/usr/bin/env python3
"""Vor dem Start des Dienstes: baut nach einem fehlgeschlagenen Update auf die vorherige Version zurück.

Wird von systemd als ``ExecStartPre`` aufgerufen (siehe werkzeuge/pi_neu_installieren.sh). Ohne offenes Update
macht das Skript nichts. Der Rückgabecode ist immer 0, damit der Dienst auf jeden Fall startet.
"""

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from backend.app.services import update_guard  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR") or APP_DIR)


def main() -> int:
    result = update_guard.guard(APP_DIR, DATA_DIR)
    if result == "rolled_back":
        print("Update-Schutz: die neue Version startete nicht stabil, vorheriger Stand wiederhergestellt.")
        ok = update_guard.reinstall_requirements(APP_DIR, sys.executable)
        print("Update-Schutz: Pakete des alten Stands " + ("neu eingespielt." if ok else "nicht neu eingespielt."))
    elif result == "rollback_failed":
        print("Update-Schutz: Rückbau nicht möglich, bitte von Hand prüfen.", file=sys.stderr)
    elif result == "restored":
        print("Update-Schutz: die vorgemerkte Sicherung wurde wiederhergestellt (der Stand davor ist auch gesichert).")
    elif result == "restore_failed":
        print("Update-Schutz: Wiederherstellung nicht möglich, der bisherige Stand bleibt.", file=sys.stderr)
    elif result == "counted":
        print("Update-Schutz: Start nach dem Update gezählt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Trägt Wechselzyklus und Konstruktionsprüfung in die 3D-Ansicht ein.

Die Quelle ist ``backend/app/services/plate_changer.py``. Die Ansicht trägt eine Kopie im Block
``<script id="plate-changer-data">``; ein Test (``test_plate_changer.py``) schlägt fehl, wenn sie nicht stimmt.

    python werkzeuge/automation_hardware/sync_viewer.py            # Kopie aktualisieren
    python werkzeuge/automation_hardware/sync_viewer.py --check    # nur prüfen (Exit 1, wenn veraltet)
    python werkzeuge/automation_hardware/sync_viewer.py --report   # Konstruktionsprüfung als Tabelle
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services import plate_changer  # noqa: E402

VIEWER = Path(__file__).with_name("printlab_3d_assembly_explosion_viewer.html")
MARK = {"ok": "ok", "warn": "KNAPP", "fail": "PASST NICHT"}


def report() -> str:
    lines = ["| Prüfung | Wert | Empfohlen | Status | Hinweis |", "| :--- | ---: | ---: | :---: | :--- |"]
    for c in plate_changer.design_checks():
        lines.append(
            f"| {c['label']} | {c['value']} {c['unit']} | {c['limit']} {c['unit']} | {MARK[c['status']]} | {c['note']} |"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if "--report" in argv:
        print(report())
        return 0
    current = plate_changer.sync_viewer_html(VIEWER, write="--check" not in argv)
    if "--check" in argv:
        print("3D-Ansicht ist aktuell." if current else "3D-Ansicht ist veraltet: ohne --check ausführen.")
        return 0 if current else 1
    print("3D-Ansicht war schon aktuell." if current else "3D-Ansicht aktualisiert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Trägt Wechselzyklus und Konstruktionsprüfung in die 3D-Ansicht ein.

Die Quelle ist ``backend/app/services/plate_changer.py``. Die Ansicht trägt eine Kopie im Block
``<script id="plate-changer-data">``; ein Test (``test_plate_changer.py``) schlägt fehl, wenn sie nicht stimmt.

    python werkzeuge/automation_hardware/sync_viewer.py            # Kopie aktualisieren
    python werkzeuge/automation_hardware/sync_viewer.py --check    # nur prüfen (Exit 1, wenn veraltet)
    python werkzeuge/automation_hardware/sync_viewer.py --report   # Konstruktionsprüfung als Tabelle
    python werkzeuge/automation_hardware/sync_viewer.py --plan     # Antriebe, Fahrzeiten, Strom, Pins als Tabellen
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services import plate_changer, plate_changer_plan as plan  # noqa: E402

VIEWER = Path(__file__).with_name("printlab_3d_assembly_explosion_viewer.html")
MARK = {"ok": "ok", "warn": "KNAPP", "fail": "PASST NICHT"}


def report() -> str:
    lines = ["| Prüfung | Wert | Empfohlen | Status | Hinweis |", "| :--- | ---: | ---: | :---: | :--- |"]
    for c in plate_changer.design_checks():
        lines.append(
            f"| {c['label']} | {c['value']} {c['unit']} | {c['limit']} {c['unit']} | {MARK[c['status']]} | {c['note']} |"
        )
    return "\n".join(lines)


def plan_report() -> str:
    """Tabellen für Abschnitt 5 bis 9 des Konstruktionsplans (die Rechnung steht in plate_changer_plan.py)."""
    names = {a.id: a for a in plan.AXES}
    out = [
        "### Antriebe",
        "",
        "| Achse | Schritte/mm | Auflösung | Drehzahl | Schrittfrequenz | Moment nötig | Moment nutzbar | Reserve |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in plan.axis_checks():
        out.append(
            f"| {names[r['axis']].name} | {r['steps_per_mm']} | {r['resolution_um']} µm | {r['rpm']:.0f} U/min | "
            f"{r['step_rate_khz']} kHz | {r['torque_need_nm']} N·m | {r['torque_have_nm']} N·m | {r['torque_ratio']} × |"
        )
    out += [
        "",
        "### Fahrzeiten (leeres Fach 1, frische Platte in Fach 2)",
        "",
        "| Nr. | Phase | Dauer | Bewegt |",
        "| :---: | :--- | ---: | :--- |",
    ]
    rep = plan.cycle_report()
    for i, ph in enumerate(rep["phases"], 1):
        out.append(f"| {i} | {ph['label']} | {ph['seconds']} s | {ph['by']} |")
    lo, hi = plan.cycle_range()
    out.append(f"| | **Summe** | **{rep['total_s']} s** | kürzester Wechsel {lo} s, längster {hi} s |")
    out += [
        "",
        "### Strombedarf (12 V, Netzteil 8,5 A)",
        "",
        "| Fall | Strom | Auslastung | Reserve 25 % |",
        "| :--- | ---: | ---: | :---: |",
    ]
    for r in plan.power_budget():
        out.append(f"| {r['case']} | {r['amps']} A | {r['load_pct']:.0f} % | {'ok' if r['ok'] else 'nein'} |")
    out += [
        "",
        "### Pins am Raspberry Pi",
        "",
        "| Signal | BCM | Pin | Richtung | Funktion |",
        "| :--- | ---: | ---: | :---: | :--- |",
    ]
    for name, (bcm, pin, direction, text) in plan.PI_PINS.items():
        out.append(f"| `{name}` | {bcm} | {pin} | {direction} | {text} |")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if "--plan" in argv:
        print(plan_report())
        return 0
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

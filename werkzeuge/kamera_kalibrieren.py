#!/usr/bin/env python3
"""Kamera der Leerbett-Prüfung einmessen: Schwellwert aus echten Beispielbildern ableiten.

Vorbereitung: Mit der Kamera des Druckers (Kamerabild speichern) Fotos aufnehmen und in zwei Ordner legen:
  leer/     Bett leer, bei verschiedenem Licht (Tag, Abend, Lampe an/aus), 5 bis 10 Bilder
  belegt/   Bett mit Teilen darauf, auch kleine Teile und helle Teile auf heller Platte, 5 bis 10 Bilder
Die Referenz für die Prüfung muss im Drucker angelegt sein (Kamera-Seite: Referenz aufnehmen) oder mit
--referenz DATEI hier aus einem Bild mit leerem Bett angelegt werden.

Aufruf auf dem Pi (im Ordner ~/printlab):
  DATA_DIR=~/printlab/data .venv/bin/python werkzeuge/kamera_kalibrieren.py --printer-id 1 --leer leer --belegt belegt
Mit --anwenden wird der Schwellwert gespeichert (Datei plate_detection_tuning.json im Datenordner) und gilt sofort für
neue Prüfungen. Mit --zuruecksetzen kehrt die Prüfung zum Standardwert zurück.
Die Mindest-Sicherheit für "Platte frei automatisch bestätigen" trägt man in den Einstellungen des Plattenwechsels ein.
"""

import argparse
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("DATA_DIR", str(APP_DIR / "data"))

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def images_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise SystemExit(f"Ordner nicht gefunden: {folder}")
    found = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not found:
        raise SystemExit(f"Keine Bilder (jpg/png) in {folder}")
    return found


def score(detector, printer_id: int, paths: list[Path]) -> list[tuple[str, float]]:
    scores = []
    for path in paths:
        result = detector.analyze_frame(path.read_bytes(), printer_id)
        if result.needs_calibration:
            raise SystemExit("Keine Referenz vorhanden: erst Referenz aufnehmen oder --referenz DATEI angeben.")
        scores.append((path.name, result.difference_percent))
    return scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Schwellwert der Leerbett-Prüfung einmessen")
    parser.add_argument("--printer-id", type=int, required=True, help="Nummer des Druckers in PrintLab")
    parser.add_argument("--leer", type=Path, help="Ordner mit Bildern bei leerem Bett")
    parser.add_argument("--belegt", type=Path, help="Ordner mit Bildern bei belegtem Bett")
    parser.add_argument("--referenz", type=Path, help="Bild mit leerem Bett als neue Referenz anlegen")
    parser.add_argument("--anwenden", action="store_true", help="vorgeschlagenen Schwellwert speichern")
    parser.add_argument("--zuruecksetzen", action="store_true", help="gespeicherten Schwellwert löschen")
    args = parser.parse_args(argv)

    from backend.app.services import camera_calibration as cc

    if args.zuruecksetzen:
        print(
            "Schwellwert zurückgesetzt." if cc.clear_difference_threshold() else "Es war kein Schwellwert gespeichert."
        )
        return 0
    if not args.leer or not args.belegt:
        parser.error("--leer und --belegt sind nötig (oder --zuruecksetzen).")

    from backend.app.services.plate_detection import OPENCV_AVAILABLE, PlateDetector

    if not OPENCV_AVAILABLE:
        print("OpenCV fehlt: .venv/bin/pip install opencv-python-headless", file=sys.stderr)
        return 2
    detector = PlateDetector(
        difference_threshold=1.0
    )  # nur zum Messen; der Schwellwert spielt für die Abweichung keine Rolle
    if args.referenz:
        ok, message, _count = detector.calibrate(
            args.referenz.read_bytes(), args.printer_id, label="kamera_kalibrieren"
        )
        print(("Referenz angelegt: " if ok else "FEHLER: ") + message)
        if not ok:
            return 1

    empty = score(detector, args.printer_id, images_in(args.leer))
    occupied = score(detector, args.printer_id, images_in(args.belegt))
    print("\nLeeres Bett (Abweichung in Prozent):")
    for name, value in empty:
        print(f"  {name:<30} {value:6.2f}")
    print("Belegtes Bett:")
    for name, value in occupied:
        print(f"  {name:<30} {value:6.2f}")

    result = cc.suggest([v for _, v in empty], [v for _, v in occupied])
    print(f"\nVorschlag: Schwellwert {result['threshold']} %  |  Mindest-Sicherheit {result['min_confidence']}")
    print(f"Übersehene Objekte: {result['missed_objects']}  |  Falsche Alarme: {result['false_alarms']}")
    print(result["message"])
    if args.anwenden:
        if result["missed_objects"]:
            print("Nicht gespeichert: mit diesem Wert würden belegte Betten als leer gelten.", file=sys.stderr)
            return 1
        print(f"Gespeichert in {cc.save_difference_threshold(result['threshold'])}")
    else:
        print("Zum Speichern erneut mit --anwenden aufrufen.")
    return 0 if result["separable"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Einmessen der Kamera-Prüfungen: Schwellwert aus echten Beispielbildern ableiten.

Die Leerbett-Prüfung (``plate_detection``) vergleicht das Kamerabild mit einer Referenz und meldet die Abweichung in
Prozent. Ab welcher Abweichung ein Bett als "belegt" gilt, hängt von Licht, Kamera und Platte ab. Dieses Modul nimmt
die gemessenen Abweichungen von Bildern mit leerem und mit belegtem Bett und schlägt daraus den Schwellwert und die
Mindest-Sicherheit für "Platte frei automatisch bestätigen" vor.

Reine Rechenlogik ohne OpenCV, damit sie überall getestet werden kann. Das Bilder-Einlesen macht
``werkzeuge/kamera_kalibrieren.py``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TUNING_NAME = "plate_detection_tuning.json"
MISSED_OBJECT_WEIGHT = (
    3  # ein übersehenes Objekt wiegt schwerer als ein falscher Alarm (nächster Druck auf belegte Platte)
)


def tuning_path(data_dir: Path | str | None = None) -> Path:
    if data_dir is None:
        from backend.app.core.config import settings

        data_dir = settings.base_dir
    return Path(data_dir) / TUNING_NAME


def load_difference_threshold(data_dir: Path | str | None = None) -> float | None:
    """Der eingemessene Schwellwert (Prozent) oder None, wenn keiner gespeichert ist."""
    try:
        data = json.loads(tuning_path(data_dir).read_text(encoding="utf-8"))
        value = float(data["difference_threshold"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if 0.05 <= value <= 50 else None


def save_difference_threshold(value: float, data_dir: Path | str | None = None) -> Path:
    if not 0.05 <= value <= 50:
        raise ValueError("Schwellwert muss zwischen 0,05 und 50 Prozent liegen.")
    path = tuning_path(data_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"difference_threshold": round(float(value), 3)}, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def clear_difference_threshold(data_dir: Path | str | None = None) -> bool:
    path = tuning_path(data_dir)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def _candidate_thresholds(scores: list[float]) -> list[float]:
    ordered = sorted(set(scores))
    mids = [(a + b) / 2 for a, b in zip(ordered, ordered[1:], strict=False)]
    return [ordered[0] / 2, *mids, ordered[-1] * 1.5]


def suggest(empty: list[float], occupied: list[float]) -> dict:
    """Schlägt Schwellwert und Mindest-Sicherheit vor.

    ``empty``/``occupied``: gemessene Abweichungen (Prozent) von Bildern mit leerem bzw. belegtem Bett.
    Rückgabe: ``threshold``, ``min_confidence``, ``separable``, ``quality`` (good/ok/weak/overlap), Fehlerzahlen
    und ein Hinweistext.
    """
    if not empty or not occupied:
        raise ValueError("Es werden Bilder mit leerem UND mit belegtem Bett gebraucht.")
    if any(v < 0 for v in empty + occupied):
        raise ValueError("Abweichungen können nicht negativ sein.")

    e_max, o_min = max(empty), min(occupied)
    if e_max < o_min:
        separable = True
        # Näher an die leeren Bilder legen: lieber einmal zu viel von Hand bestätigen als eine belegte Platte übersehen
        threshold = e_max + 0.35 * (o_min - e_max)
        ratio = o_min / max(e_max, 0.01)
        quality = "good" if ratio >= 2 else "ok" if ratio >= 1.3 else "weak"
    else:
        separable = False
        quality = "overlap"
        best_cost, threshold = None, 0.0
        for candidate in _candidate_thresholds(empty + occupied):
            missed = sum(1 for v in occupied if v < candidate)
            false_alarms = sum(1 for v in empty if v >= candidate)
            cost = MISSED_OBJECT_WEIGHT * missed + false_alarms
            if best_cost is None or cost < best_cost:  # bei Gleichstand der niedrigere Wert
                best_cost, threshold = cost, candidate
    threshold = round(max(threshold, 0.05), 2)

    missed = sum(1 for v in occupied if v < threshold)
    false_alarms = sum(1 for v in empty if v >= threshold)
    confidences = [max(0.0, 1.0 - v / threshold) for v in empty]
    min_conf = max(0.2, min(0.9, round(0.8 * min(confidences), 2)))

    messages = {
        "good": "Gut trennbar: leeres und belegtes Bett liegen deutlich auseinander.",
        "ok": "Trennbar, aber mit wenig Abstand. Mehr Beispielbilder und gleichmäßiges Licht helfen.",
        "weak": "Kaum Abstand zwischen leer und belegt. Bereich (ROI) enger auf das Bett legen und Licht prüfen.",
        "overlap": "Leer und belegt überlappen: kein sauberer Schwellwert möglich. Referenzbilder neu aufnehmen, "
        "Bereich (ROI) anpassen oder das Licht vereinheitlichen.",
    }
    return {
        "threshold": threshold,
        "min_confidence": min_conf,
        "separable": separable,
        "quality": quality,
        "missed_objects": missed,
        "false_alarms": false_alarms,
        "empty_max": round(e_max, 3),
        "occupied_min": round(o_min, 3),
        "message": messages[quality],
    }

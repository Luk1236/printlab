"""Export der Fehlerbild-Sammlung als Trainingsset.

Ein ZIP mit allen gesammelten Bildern, ``labels.jsonl`` (je Bild das erkannte Fehlerbild, die Sicherheit,
die Begründung und die eigene Bewertung) und ``README.txt`` mit der Feldbeschreibung. Damit lässt sich die
Sammlung auf dem PC ansehen, mit einem eigenen Modell prüfen oder als Trainingsset weitergeben — ohne
Bild für Bild durch die Oberfläche zu klicken.

Nur lesend: der Export verändert weder Bilder noch Bewertungen.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from backend.app.services import ai_error_scan
from backend.app.utils import failure_images

README = """PrintLab — Fehlerbild-Sammlung (Trainingsset)

Inhalt
  images/        die gesammelten Kamerabilder (*.jpg)
  labels.jsonl   eine Zeile je Bild
  meta.json      Zeitpunkt und Anzahl

Felder in labels.jsonl
  image       Dateiname des Bildes (wie in images/)
  event       Anlass der Aufnahme (z. B. plate_not_empty, first_layer, ai_failure_detection)
  timestamp   Aufnahmezeit (Ortszeit des Servers)
  ai          Erkennung des Bildmodells oder null:
                pattern_id  Fehlerbild-Kennung (services/error_patterns.py)
                confidence  0.0 bis 1.0
                reason      Begründung des Modells
                model       Modellname
                ts          Zeitpunkt der Erkennung
  verdict     eigene Bewertung: "correct", "wrong" oder null (unbewertet)

Hinweis: Die Bilder sind Kamerabilder deines Druckers. Vor einer Weitergabe prüfen, ob darauf
Bauteile, Kundenaufträge oder Teile des Raums zu sehen sind.
"""


def _latest_finding_per_image() -> dict[str, dict[str, Any]]:
    """Neueste Erkennung je Bild (``list_findings`` liefert neueste zuerst)."""
    by_image: dict[str, dict[str, Any]] = {}
    for finding in ai_error_scan.list_findings(ai_error_scan.MAX_FINDINGS):
        name = str(finding.get("image_name") or "")
        if name and name not in by_image:
            by_image[name] = finding
    return by_image


def build_zip() -> bytes:
    """ZIP als Bytes (für ``Response``); fehlende Bilder werden übersprungen."""
    findings = _latest_finding_per_image()
    labels: list[dict[str, Any]] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for image in failure_images.list_failure_images():
            name = str(image.get("name") or "")
            path = failure_images.find_failure_image(name) if name else None
            if path is None:
                continue
            archive.write(path, arcname=f"images/{name}")
            finding = findings.get(name)
            labels.append(
                {
                    "image": name,
                    "event": image.get("event"),
                    "timestamp": image.get("timestamp"),
                    "ai": (
                        {
                            "pattern_id": finding.get("pattern_id"),
                            "confidence": finding.get("confidence"),
                            "reason": finding.get("reason"),
                            "model": finding.get("model"),
                            "ts": finding.get("ts"),
                        }
                        if finding
                        else None
                    ),
                    "verdict": (finding or {}).get("verdict"),
                }
            )
        archive.writestr(
            "labels.jsonl",
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in labels),
        )
        archive.writestr(
            "meta.json",
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "images": len(labels),
                    "rated": sum(1 for entry in labels if entry["verdict"]),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.writestr("README.txt", README)
    return buffer.getvalue()

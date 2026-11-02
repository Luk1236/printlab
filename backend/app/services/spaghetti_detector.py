"""Live-Fehldruck- und Spaghetti-Erkennung während des Drucks für Bambu Lab P2S.

Analysiert periodisch Kamerabilder während des laufenden Druckauftrags:
- Kantendichte & Entropie (chaotische Spaghetti-Filamentfäden vs. geordnete Schichtgeometrie)
- Rolling-Window Fehlerzähler zur Vermeidung von Fehlalarmen
- Automatischer Pausierungsvorschlag und Alarmierung bei Fehldrucken
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np

    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None
    OPENCV_AVAILABLE = False


class FailureDetectionResult:
    """Ergebnis der In-Print Fehldruck-Analyse."""

    def __init__(
        self,
        is_failure: bool,
        confidence: float,
        chaos_score: float,
        consecutive_failures: int,
        should_pause: bool,
        message: str,
    ):
        self.is_failure = is_failure
        self.confidence = float(round(confidence, 2))
        self.chaos_score = float(round(chaos_score, 2))
        self.consecutive_failures = consecutive_failures
        self.should_pause = should_pause
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_failure": self.is_failure,
            "confidence": self.confidence,
            "chaos_score": self.chaos_score,
            "consecutive_failures": self.consecutive_failures,
            "should_pause": self.should_pause,
            "message": self.message,
        }


class SpaghettiDetector:
    """Erkennt Druckfehler (Spaghetti / Ablösung) anhand von Struktur- und Kantendichten."""

    # Schwellwert für chaotische Kantendichte
    CHAOS_THRESHOLD = 0.58
    # Anzahl aufeinanderfolgender Fehler bis zum Not-Pausieren
    TRIGGER_CONSECUTIVE_COUNT = 3

    def __init__(self):
        # Rolling-Zähler je Drucker
        self._consecutive_counts: dict[str, int] = {}
        self._history_scores: dict[str, list[float]] = {}

    def reset_printer(self, printer_id: str = "default") -> None:
        """Setzt den Fehlerzähler für einen neuen Druckauftrag zurück."""
        self._consecutive_counts[printer_id] = 0
        self._history_scores[printer_id] = []

    def compute_chaos_score(self, frame: np.ndarray) -> float:
        """Berechnet den Spaghetti-/Chaos-Score (0.0 bis 1.0) eines Bildes.

        Spaghetti-Fäden erzeugen hochfrequente, ungerichtete Kanten mit hoher Streuung
        im Vergleich zu sauberen Linien oder glatten Flächen.
        """
        if not OPENCV_AVAILABLE or frame is None:
            return 0.0

        # Graustufen und Rauschfilter
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Canny-Kantenerkennung für feine Filamentfäden
        edges = cv2.Canny(blurred, 60, 160)
        edge_pixels = float(np.count_nonzero(edges))
        total_pixels = float(edges.size)

        edge_density = edge_pixels / total_pixels

        # Laplace-Varianz zur Messung von Schärfe und Unruhe
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(laplacian.var())

        # Normierung: Chaotische Spaghetti haben hohe Kantendichte (> 12 %) und hohe Varianz
        score = min(1.0, (edge_density * 4.5) + (min(variance, 600.0) / 1200.0))
        return float(round(score, 3))

    def analyze_frame(
        self,
        image_data: bytes,
        printer_id: str = "default",
        layer_num: int = 1,
    ) -> FailureDetectionResult:
        """Analysiert einen Frame während des Drucks."""
        if not OPENCV_AVAILABLE:
            return FailureDetectionResult(
                is_failure=False,
                confidence=0.0,
                chaos_score=0.0,
                consecutive_failures=0,
                should_pause=False,
                message="OpenCV nicht verfügbar - Live-Fehlererkennung inaktiv",
            )

        try:
            nparr = np.frombuffer(image_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return FailureDetectionResult(
                    is_failure=False,
                    confidence=0.0,
                    chaos_score=0.0,
                    consecutive_failures=0,
                    should_pause=False,
                    message="Bild konnte nicht dekodiert werden",
                )

            chaos = self.compute_chaos_score(frame)

            # Erste 3 Schichten haben oft Infill/Bettmuster; ab Schicht 4 volle Sensitivität
            effective_threshold = self.CHAOS_THRESHOLD if layer_num >= 4 else (self.CHAOS_THRESHOLD + 0.15)
            is_suspicious = chaos >= effective_threshold

            current_consecutive = self._consecutive_counts.get(printer_id, 0)
            if is_suspicious:
                current_consecutive += 1
            else:
                current_consecutive = max(0, current_consecutive - 1)

            self._consecutive_counts[printer_id] = current_consecutive

            history = self._history_scores.setdefault(printer_id, [])
            history.append(chaos)
            if len(history) > 10:
                history.pop(0)

            should_pause = current_consecutive >= self.TRIGGER_CONSECUTIVE_COUNT
            confidence = min(1.0, 0.5 + (current_consecutive * 0.18)) if is_suspicious else (1.0 - chaos)

            if should_pause:
                msg = f"Kritischer Fehldruck (Spaghetti) erkannt! Chaos-Score: {chaos:.2f} ({current_consecutive}× in Folge). Automatischer Stopp empfohlen."
            elif is_suspicious:
                msg = f"Verdacht auf Fehldruck (Score: {chaos:.2f}). Beobachte nächste Schichten ({current_consecutive}/{self.TRIGGER_CONSECUTIVE_COUNT})."
            else:
                msg = f"Druckbild in Ordnung (Chaos-Score: {chaos:.2f})."

            return FailureDetectionResult(
                is_failure=is_suspicious,
                confidence=confidence,
                chaos_score=chaos,
                consecutive_failures=current_consecutive,
                should_pause=should_pause,
                message=msg,
            )

        except Exception as exc:
            logger.exception("Fehler bei der Spaghetti-Erkennung")
            return FailureDetectionResult(
                is_failure=False,
                confidence=0.0,
                chaos_score=0.0,
                consecutive_failures=0,
                should_pause=False,
                message=f"Analysefehler: {exc}",
            )


# Globale Instanz
detector = SpaghettiDetector()


def analyze_frame_for_failure(
    image_data: bytes, printer_id: str = "default", layer_num: int = 1
) -> FailureDetectionResult:
    """Komfort-Funktion zur Einzelbild-Analyse."""
    return detector.analyze_frame(image_data, printer_id=printer_id, layer_num=layer_num)

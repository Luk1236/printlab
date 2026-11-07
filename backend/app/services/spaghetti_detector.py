"""Schneller lokaler Edge-Spaghetti-Detektor für kontinuierliche Schichtanalyse.

Verwendet OpenCV CLAHE-Beleuchtungsnormalisierung im LAB-Farbraum,
Sobel-Orientierungsentropie zur Unterscheidung geordneter Druckbahnen von
chaotischem Filament-Salat, sowie Kantendichte- und Kontur-Clusterung.
Läuft lokal auf Pi 5 / CPU in unter 30 ms ohne Cloud- oder LLM-Latenz.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np

    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    OPENCV_AVAILABLE = False


class SpaghettiAnalysisResult:
    """Strukturiertes Ergebnis einer Schicht- und Spaghetti-Prüfung."""

    def __init__(
        self,
        is_failure: bool,
        confidence: float,
        chaos_score: float,
        orientation_entropy: float,
        edge_density: float,
        fragment_count: int,
        bounding_box: tuple[int, int, int, int] | None = None,
        message: str = "",
        debug_image: bytes | None = None,
    ):
        self.is_failure = bool(is_failure)
        self.confidence = float(round(confidence, 3))
        self.chaos_score = float(round(chaos_score, 3))
        self.orientation_entropy = float(round(orientation_entropy, 3))
        self.edge_density = float(round(edge_density, 4))
        self.fragment_count = int(fragment_count)
        self.bounding_box = bounding_box
        self.message = message
        self.debug_image = debug_image

    def to_dict(self, include_image_b64: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "is_failure": self.is_failure,
            "confidence": self.confidence,
            "chaos_score": self.chaos_score,
            "orientation_entropy": self.orientation_entropy,
            "edge_density": self.edge_density,
            "fragment_count": self.fragment_count,
            "bounding_box": list(self.bounding_box) if self.bounding_box else None,
            "message": self.message,
            "has_debug_image": self.debug_image is not None,
        }
        if include_image_b64 and self.debug_image:
            b64_str = base64.b64encode(self.debug_image).decode("ascii")
            data["debug_image_b64"] = f"data:image/jpeg;base64,{b64_str}"
        return data


class SpaghettiDetector:
    """Analysiert Bilddaten auf Fehldrucke, Fäden und Spaghetti-Strukturen."""

    # Standard-ROI für Bambu Druckbett (x_pct, y_pct, w_pct, h_pct)
    DEFAULT_ROI = (0.18, 0.22, 0.64, 0.60)

    def __init__(self, default_threshold: float = 0.65):
        self.default_threshold = default_threshold

    def normalize_lighting(self, img_bgr: np.ndarray) -> np.ndarray:
        """Kompensiert Lichtschwankungen (Kammerbeleuchtung, Schattenwurf) via CLAHE im LAB-Farbraum."""
        if not OPENCV_AVAILABLE:
            return img_bgr
        lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        norm_l = clahe.apply(l_channel)
        norm_lab = cv2.merge((norm_l, a_channel, b_channel))
        return cv2.cvtColor(norm_lab, cv2.COLOR_LAB2BGR)

    def extract_roi(
        self,
        img: np.ndarray,
        roi: tuple[float, float, float, float] | None = None,
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Schneidet das Druckbett aus dem Kamerabild aus."""
        h, w = img.shape[:2]
        r = roi or self.DEFAULT_ROI
        rx, ry, rw, rh = r
        x0 = max(0, int(w * rx))
        y0 = max(0, int(h * ry))
        x1 = min(w, int(w * (rx + rw)))
        y1 = min(h, int(h * (ry + rh)))
        return img[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0)

    def analyze_image(
        self,
        image_bytes: bytes,
        threshold: float | None = None,
        roi: tuple[float, float, float, float] | None = None,
        is_warped: bool = False,
    ) -> SpaghettiAnalysisResult:
        """Hauptanalyse: Entropie, Kanten, Fragmente und Visualisierung."""
        if not OPENCV_AVAILABLE:
            return SpaghettiAnalysisResult(
                is_failure=False,
                confidence=0.0,
                chaos_score=0.0,
                orientation_entropy=0.0,
                edge_density=0.0,
                fragment_count=0,
                message="OpenCV nicht verfügbar - Schichtanalyse inaktiv.",
            )

        eff_threshold = threshold if threshold is not None else self.default_threshold

        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return SpaghettiAnalysisResult(
                    is_failure=False,
                    confidence=0.0,
                    chaos_score=0.0,
                    orientation_entropy=0.0,
                    edge_density=0.0,
                    fragment_count=0,
                    message="Bild konnte nicht dekodiert werden.",
                )

            # Frame bei Bedarf für Rechenzeit optimieren (max 800px Breite)
            orig_h, orig_w = frame.shape[:2]
            if orig_w > 800:
                scale = 800.0 / orig_w
                frame = cv2.resize(frame, (800, int(orig_h * scale)), interpolation=cv2.INTER_AREA)

            # Wenn bereits von der Platteneinmessung gewarpt, ist das gesamte Bild das Bett
            if is_warped:
                roi_frame = frame
                roi_rect = (0, 0, frame.shape[1], frame.shape[0])
            else:
                roi_frame, roi_rect = self.extract_roi(frame, roi)

            # CLAHE-Normalisierung
            norm_bgr = self.normalize_lighting(roi_frame)
            gray = cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2GRAY)

            # Gradienten & Orientierungs-Entropie (Sobel)
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
            ang = ang % 180.0  # Ungerichtete Kanten [0, 180)

            # Maske für signifikante Kanten
            mag_mask = mag > 32.0
            valid_angles = ang[mag_mask]

            # Canny Kanten für Dichte und Konturen
            edges = cv2.Canny(gray, 50, 150)
            edge_density = float(np.count_nonzero(edges)) / float(edges.size)

            # Berechne Shannon-Entropie der Kantenorientierungen
            if len(valid_angles) < 60 or edge_density < 0.012:
                # Glattes Druckbett, leere Fläche oder kaum Struktur -> keine Spaghetti
                entropy = 0.0
                fragments = 0
                chaos_score = 0.0
                cluster_box = None
            else:
                hist, _ = np.histogram(valid_angles, bins=18, range=(0.0, 180.0))
                p = hist / float(hist.sum())
                p = p[p > 0]
                # Normalisierte Entropie: 0.0 (alle Kanten parallel) bis 1.0 (vollständig chaotisch/kreisförmig)
                entropy = float(-np.sum(p * np.log2(p)) / np.log2(18.0))

                # Konturen analysieren (Spaghetti erzeugt viele kleine gewundene Fragmente)
                contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                fragments = len(
                    [c for c in contours if cv2.arcLength(c, True) > 12 and cv2.contourArea(c) < 700]
                )

                # Chaos-Score Formel:
                # Hohe Entropie (>0.72) + hohe Kantendichte + zerfaserte Konturen
                density_factor = min(1.0, edge_density / 0.055)
                fragment_factor = min(1.0, fragments / 35.0)
                entropy_factor = float(np.clip(entropy ** 1.7, 0.0, 1.0))

                raw_score = (0.50 * entropy_factor) + (0.30 * density_factor) + (0.20 * fragment_factor)

                # Dämpfung für geordnete Gitter-/Wandstrukturen (niedrige Entropie)
                if entropy < 0.62:
                    raw_score *= 0.35

                chaos_score = float(np.clip(raw_score, 0.0, 1.0))

                # Bounding-Box für den chaotischsten Cluster finden
                cluster_box = self._find_cluster_box(edges, roi_rect)

            is_failure = chaos_score >= eff_threshold
            confidence = min(1.0, max(0.5, chaos_score)) if is_failure else max(0.0, 1.0 - chaos_score)

            # Annotiertes Vorschaubild erstellen
            debug_image = self._render_debug_overlay(
                frame=frame,
                roi_rect=roi_rect,
                cluster_box=cluster_box,
                chaos_score=chaos_score,
                entropy=entropy,
                edge_density=edge_density,
                threshold=eff_threshold,
                is_failure=is_failure,
            )

            if is_failure:
                msg = f"Fehldruck/Spaghetti erkannt! Chaos-Score: {chaos_score:.2f} (Schwelle: {eff_threshold:.2f}, Entropie: {entropy:.2f})."
            else:
                msg = f"Schichtbild normal (Chaos-Score: {chaos_score:.2f}, Entropie: {entropy:.2f})."

            return SpaghettiAnalysisResult(
                is_failure=is_failure,
                confidence=confidence,
                chaos_score=chaos_score,
                orientation_entropy=entropy,
                edge_density=edge_density,
                fragment_count=fragments,
                bounding_box=cluster_box,
                message=msg,
                debug_image=debug_image,
            )

        except Exception as exc:
            logger.exception("Fehler bei der Schichtanalyse: %s", exc)
            return SpaghettiAnalysisResult(
                is_failure=False,
                confidence=0.0,
                chaos_score=0.0,
                orientation_entropy=0.0,
                edge_density=0.0,
                fragment_count=0,
                message=f"Analysefehler: {exc}",
            )

    def _find_cluster_box(
        self,
        edges: np.ndarray,
        roi_offset: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        """Findet das umschließende Rechteck der dichtesten Kantenansammlung im Gesamtbild."""
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        dilated = cv2.dilate(edges, kernel, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        rx, ry, _, _ = roi_offset
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            if w > 25 and h > 25 and area > 1000:
                candidates.append((x + rx, y + ry, w, h, area))

        if not candidates:
            return None

        # Sortiere nach Fläche/Cluster-Größe
        candidates.sort(key=lambda item: item[4], reverse=True)
        best = candidates[0]
        return (best[0], best[1], best[2], best[3])

    def _render_debug_overlay(
        self,
        frame: np.ndarray,
        roi_rect: tuple[int, int, int, int],
        cluster_box: tuple[int, int, int, int] | None,
        chaos_score: float,
        entropy: float,
        edge_density: float,
        threshold: float,
        is_failure: bool,
    ) -> bytes:
        """Zeichnet Messwerte, ROI und Erkennungs-Boxen auf das Bild."""
        vis = frame.copy()
        rx, ry, rw, rh = roi_rect

        # 1. Druckbett-ROI einzeichnen
        roi_color = (0, 0, 255) if is_failure else (0, 200, 200)
        cv2.rectangle(vis, (rx, ry), (rx + rw, ry + rh), roi_color, 2)
        cv2.putText(
            vis,
            "ROI BETT",
            (rx + 6, ry + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            roi_color,
            1,
            cv2.LINE_AA,
        )

        # 2. Fehler-Cluster hervorheben
        if is_failure and cluster_box:
            bx, by, bw, bh = cluster_box
            cv2.rectangle(vis, (bx, by), (bx + bw, by + bh), (0, 0, 255), 3)
            # Rotes Label über dem Kasten
            badge_h = 24
            badge_w = 160
            cv2.rectangle(vis, (bx, max(0, by - badge_h)), (bx + badge_w, by), (0, 0, 255), -1)
            cv2.putText(
                vis,
                f"SPAGHETTI {int(chaos_score * 100)}%",
                (bx + 6, max(16, by - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        # 3. Informationsleiste oben
        bar_h = 32
        overlay = vis.copy()
        cv2.rectangle(overlay, (0, 0), (vis.shape[1], bar_h), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.75, vis, 0.25, 0, vis)

        status_text = "ALARM: FEHLDRUCK" if is_failure else "STATUS: NORMAL"
        status_color = (60, 60, 255) if is_failure else (80, 220, 80)

        info = f"Score: {chaos_score:.2f} (Ziel <{threshold:.2f}) | Entropie: {entropy:.2f} | Kanten: {edge_density * 100:.1f}% | {status_text}"
        cv2.putText(
            vis,
            info,
            (10, 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            status_color,
            1,
            cv2.LINE_AA,
        )

        # In JPEG kodieren
        success, encoded = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not success:
            return b""
        return encoded.tobytes()


# Globale Instanz
spaghetti_detector = SpaghettiDetector()

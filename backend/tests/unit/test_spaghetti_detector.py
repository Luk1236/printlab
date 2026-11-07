"""Unit-Tests für den schnellen lokalen Edge-Spaghetti-Detektor."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.app.services.spaghetti_detector import (
    SpaghettiAnalysisResult,
    SpaghettiDetector,
    spaghetti_detector,
)


def _create_clean_grid_image() -> bytes:
    """Erzeugt ein synthetisches sauberes Schichtbild (parallele Gitterlinien)."""
    img = np.zeros((480, 640, 3), dtype=np.uint8) + 35
    # Gitter / Wände mit 90-Grad-Winkeln
    for y in range(80, 400, 25):
        cv2.line(img, (120, y), (520, y), (210, 210, 210), 2)
    for x in range(120, 520, 25):
        cv2.line(img, (x, 80), (x, 400), (210, 210, 210), 2)
    success, encoded = cv2.imencode(".jpg", img)
    assert success
    return encoded.tobytes()


def _create_spaghetti_failure_image() -> bytes:
    """Erzeugt ein synthetisches Fehldruck-Bild mit wirren Filament-Schlaufen."""
    img = np.zeros((480, 640, 3), dtype=np.uint8) + 30
    np.random.seed(99)
    # Chaotische, gekrümmte Ellipsen / Schleifen
    for _ in range(80):
        center = (int(np.random.randint(180, 460)), int(np.random.randint(140, 360)))
        axes = (int(np.random.randint(12, 50)), int(np.random.randint(12, 50)))
        angle = int(np.random.randint(0, 360))
        cv2.ellipse(img, center, axes, angle, 0, 360, (230, 230, 230), 2)
    success, encoded = cv2.imencode(".jpg", img)
    assert success
    return encoded.tobytes()


def test_detector_lighting_normalization():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    norm = spaghetti_detector.normalize_lighting(img)
    assert norm.shape == (100, 100, 3)


def test_detector_extract_roi():
    img = np.zeros((200, 300, 3), dtype=np.uint8)
    roi_img, rect = spaghetti_detector.extract_roi(img, (0.1, 0.2, 0.5, 0.6))
    assert rect == (30, 40, 150, 120)
    assert roi_img.shape == (120, 150, 3)


def test_clean_grid_print_is_not_failure():
    clean_bytes = _create_clean_grid_image()
    result = spaghetti_detector.analyze_image(clean_bytes, threshold=0.65)

    assert isinstance(result, SpaghettiAnalysisResult)
    assert not result.is_failure
    # Gitter hat geordnete Orientierungen -> niedrige Entropie & niedriger Chaos-Score
    assert result.chaos_score < 0.45
    assert result.orientation_entropy < 0.65
    assert "normal" in result.message.lower() or "unauffällig" in result.message.lower()


def test_spaghetti_failure_detected():
    spaghetti_bytes = _create_spaghetti_failure_image()
    result = spaghetti_detector.analyze_image(spaghetti_bytes, threshold=0.65)

    assert isinstance(result, SpaghettiAnalysisResult)
    assert result.is_failure
    assert result.chaos_score >= 0.65
    assert result.orientation_entropy >= 0.70
    assert result.fragment_count > 15
    assert result.bounding_box is not None
    assert result.debug_image is not None
    assert len(result.debug_image) > 500

    data = result.to_dict(include_image_b64=True)
    assert data["is_failure"] is True
    assert "debug_image_b64" in data
    assert data["debug_image_b64"].startswith("data:image/jpeg;base64,")


def test_invalid_image_bytes():
    result = spaghetti_detector.analyze_image(b"invalid data string")
    assert not result.is_failure
    assert result.chaos_score == 0.0
    assert "konnte nicht dekodiert werden" in result.message.lower()

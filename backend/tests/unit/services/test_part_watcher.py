"""Tests für den Bauteil-Wächter (Kamera-Vergleich)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.app.services.part_watcher import PartWatcher, compare_images


def jpeg(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


def frame(kind: str = "noise", seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    if kind == "noise":
        image = rng.integers(0, 255, (240, 320), dtype=np.uint8)
    elif kind == "shifted":
        image = rng.integers(0, 255, (240, 320), dtype=np.uint8)
        image = np.roll(image, 40, axis=1)
    else:
        image = np.full((240, 320), 128, dtype=np.uint8)
    return jpeg(image)


class TestCompare:
    def test_identisch_ist_null(self):
        image = frame("noise")
        assert compare_images(image, image) < 0.5

    def test_verschieden_ist_gross(self):
        assert compare_images(frame("noise", 1), frame("shifted", 2)) > 5

    def test_kaputtes_bild(self):
        with pytest.raises(ValueError):
            compare_images(b"kein-jpeg", frame("noise"))


class TestWatcher:
    def test_konfiguration_und_status(self, tmp_path):
        watcher = PartWatcher(tmp_path / "part.json")
        assert watcher.status(1)["enabled"] is False
        data = watcher.configure(1, True, 2.5)
        assert data["enabled"] is True
        assert data["threshold"] == 2.5
        wieder = PartWatcher(tmp_path / "part.json")
        assert wieder.status(1)["threshold"] == 2.5

    def test_referenz_und_warnung_bei_gleichem_bild(self, tmp_path):
        watcher = PartWatcher(tmp_path / "part.json")
        watcher.configure(1, True, 1.0)
        assert watcher.needs_frame(1, 2, 100, "job-a") is True
        assert watcher.observe(1, "P2S", 2, 100, frame("noise"), "job-a") is None
        assert watcher.needs_frame(1, 50, 100, "job-a") is True
        warning = watcher.observe(1, "P2S", 50, 100, frame("noise"), "job-a")
        assert warning is not None
        assert warning["layer"] == 50
        assert watcher.status(1)["warning"]["layer"] == 50
        assert watcher.needs_frame(1, 60, 100, "job-a") is False

    def test_veraendertes_bild_keine_warnung(self, tmp_path):
        watcher = PartWatcher(tmp_path / "part.json")
        watcher.configure(1, True, 1.0)
        watcher.observe(1, "P2S", 2, 100, frame("noise", 1), "job-a")
        warning = watcher.observe(1, "P2S", 50, 100, frame("shifted", 2), "job-a")
        assert warning is None
        assert watcher.status(1)["warning"] is None

    def test_neuer_druck_setzt_zurueck(self, tmp_path):
        watcher = PartWatcher(tmp_path / "part.json")
        watcher.configure(1, True, 1.0)
        watcher.observe(1, "P2S", 2, 100, frame("noise"), "job-a")
        assert watcher.needs_frame(1, 3, 100, "job-b") is True

    def test_aus_oder_ohne_bild(self, tmp_path):
        watcher = PartWatcher(tmp_path / "part.json")
        assert watcher.needs_frame(1, 2, 100, "a") is False
        watcher.configure(1, True, 1.0)
        assert watcher.observe(1, "P2S", 2, 100, None, "a") is None

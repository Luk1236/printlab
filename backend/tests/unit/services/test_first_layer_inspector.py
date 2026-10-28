"""Tests für den Erste-Schicht-Inspektor."""

from __future__ import annotations

import cv2
import numpy as np

from backend.app.services.first_layer_inspector import FirstLayerInspector, inspect_image


def jpeg(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


def noise(seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    return jpeg(rng.integers(0, 255, (240, 320), dtype=np.uint8))


class TestInspect:
    def test_einfarbig_ist_auffaellig(self):
        result = inspect_image(jpeg(np.full((240, 320), 128, dtype=np.uint8)))
        assert result["ok"] is False
        assert "kontrastarm" in result["message"]
        assert result["contrast"] < 8

    def test_schwarz_ist_zu_dunkel(self):
        result = inspect_image(jpeg(np.zeros((240, 320), dtype=np.uint8)))
        assert result["ok"] is False
        assert "dunkel" in result["message"]

    def test_struktur_ist_ok(self):
        result = inspect_image(noise())
        assert result["ok"] is True
        assert "unauffällig" in result["message"]

    def test_kaputtes_bild(self):
        import pytest

        with pytest.raises(ValueError):
            inspect_image(b"kein-jpeg")


class TestInspector:
    def test_konfiguration_und_einmalige_pruefung(self, tmp_path):
        inspector = FirstLayerInspector(tmp_path / "fl.json")
        assert inspector.needs_frame(1, 2, "a") is False
        inspector.configure(1, True)
        assert inspector.needs_frame(1, 2, "a") is True
        warning = inspector.observe(1, 2, jpeg(np.full((240, 320), 128, dtype=np.uint8)), "a")
        assert warning is not None
        assert inspector.needs_frame(1, 3, "a") is False
        assert inspector.status(1)["checked"] is True

    def test_guenstige_schicht_keine_warnung(self, tmp_path):
        inspector = FirstLayerInspector(tmp_path / "fl.json")
        inspector.configure(1, True)
        assert inspector.observe(1, 2, noise(), "a") is None
        assert inspector.status(1)["result"]["ok"] is True

    def test_neuer_druck_setzt_zurueck(self, tmp_path):
        inspector = FirstLayerInspector(tmp_path / "fl.json")
        inspector.configure(1, True)
        inspector.observe(1, 2, noise(), "a")
        assert inspector.needs_frame(1, 2, "b") is True

    def test_ohne_bild(self, tmp_path):
        inspector = FirstLayerInspector(tmp_path / "fl.json")
        inspector.configure(1, True)
        assert inspector.observe(1, 2, None, "a") is None

    def test_pause_on_warning_konfigurierbar(self, tmp_path):
        inspector = FirstLayerInspector(tmp_path / "fl.json")
        # Standard aus.
        assert inspector.pause_on_warning(1) is False
        inspector.configure(1, True, pause_on_warning=True)
        assert inspector.pause_on_warning(1) is True
        # Status liefert ihn zum Anzeigen.
        assert inspector.status(1)["pause_on_warning"] is True
        # Ohne Angabe (nur enable/disable) bleibt er erhalten.
        inspector.configure(1, False)
        assert inspector.pause_on_warning(1) is True
        inspector.configure(1, True, pause_on_warning=False)
        assert inspector.pause_on_warning(1) is False
        # Persistiert für neue Instanzen.
        assert FirstLayerInspector(tmp_path / "fl.json").pause_on_warning(1) is False

    def test_paused_markiert_ergebnis(self, tmp_path):
        inspector = FirstLayerInspector(tmp_path / "fl.json")
        inspector.configure(1, True, pause_on_warning=True)
        warning = inspector.observe(1, 2, jpeg(np.full((240, 320), 128, dtype=np.uint8)), "a")
        assert warning is not None
        assert warning.get("paused") is None  # Pause setzt der Callback nach dem Pausieren

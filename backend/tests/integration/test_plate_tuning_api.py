"""Leerbett-Prüfung einmessen über die Schnittstelle (ohne OpenCV: der Detektor wird ersetzt)."""

import pytest
from httpx import AsyncClient

from backend.app.api.routes import plate_tuning
from backend.app.services import audit_log, camera_calibration

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


class FakeResult:
    def __init__(self, diff, needs_calibration=False):
        self.difference_percent = diff
        self.needs_calibration = needs_calibration


class FakeDetector:
    """Liefert die Abweichung aus dem Dateiinhalt: Bytes 'diff=1.5' ergeben 1.5."""

    def analyze_frame(self, data, printer_id):
        if data.startswith(b"nocal"):
            return FakeResult(0, needs_calibration=True)
        return FakeResult(float(data.decode().split("=")[1]))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(
        camera_calibration, "tuning_path", lambda data_dir=None: tmp_path / camera_calibration.TUNING_NAME
    )
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(plate_tuning, "_load_detector", lambda: FakeDetector())


@pytest.fixture
async def printer(printer_factory):
    return await printer_factory()


def files(name, values, ctype="image/png"):
    return [(name, (f"{name}{i}.png", f"diff={v}".encode(), ctype)) for i, v in enumerate(values)]


class TestTuningApi:
    @pytest.mark.asyncio
    async def test_analyze_returns_scores_and_a_suggestion(self, async_client: AsyncClient, printer):
        resp = await async_client.post(
            f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning/analyze",
            files=files("empty", [0.2, 0.3]) + files("occupied", [3.0, 5.0]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert [s["score"] for s in data["empty"]] == [0.2, 0.3]
        assert data["suggestion"]["separable"] is True and data["suggestion"]["missed_objects"] == 0
        assert 0.3 < data["suggestion"]["threshold"] < 3.0

    @pytest.mark.asyncio
    async def test_overlapping_sets_are_reported_as_not_separable(self, async_client: AsyncClient, printer):
        resp = await async_client.post(
            f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning/analyze",
            files=files("empty", [0.5, 1.5]) + files("occupied", [1.0, 3.0]),
        )
        assert resp.json()["suggestion"]["quality"] == "overlap"

    @pytest.mark.asyncio
    async def test_missing_group_is_a_422_or_400(self, async_client: AsyncClient, printer):
        resp = await async_client.post(
            f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning/analyze", files=files("empty", [0.2])
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_only_images_and_limited_count_and_size(self, async_client: AsyncClient, printer):
        url = f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning/analyze"
        text = await async_client.post(
            url, files=files("empty", [0.2], "text/plain") + files("occupied", [3.0]), headers={"Accept-Language": "en"}
        )
        assert text.status_code == 400 and "Only images" in text.json()["detail"]
        many = await async_client.post(url, files=files("empty", [0.1] * 21) + files("occupied", [3.0]))
        assert many.status_code == 400
        big = [("empty", ("gross.png", b"diff=1" + b"0" * (plate_tuning.MAX_IMAGE_BYTES + 1), "image/png"))]
        too_big = await async_client.post(url, files=big + files("occupied", [3.0]))
        assert too_big.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_reference_is_explained(self, async_client: AsyncClient, printer):
        resp = await async_client.post(
            f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning/analyze",
            files=[("empty", ("a.png", b"nocal", "image/png"))] + files("occupied", [3.0]),
            headers={"Accept-Language": "en"},
        )
        assert resp.status_code == 400 and "capture a reference first" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_opencv_missing_is_a_503(self, async_client: AsyncClient, printer, monkeypatch):
        from fastapi import HTTPException

        def missing():
            raise HTTPException(503, "Plate detection not available")

        monkeypatch.setattr(plate_tuning, "_load_detector", missing)
        resp = await async_client.post(
            f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning/analyze",
            files=files("empty", [0.2]) + files("occupied", [3.0]),
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_unknown_printer_is_a_404(self, async_client: AsyncClient):
        assert (await async_client.get("/api/v1/printers/99999/camera/plate-detection/tuning")).status_code == 404

    @pytest.mark.asyncio
    async def test_save_read_and_reset(self, async_client: AsyncClient, printer):
        url = f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning"
        initial = (await async_client.get(url)).json()
        assert initial["saved"] is None and initial["effective"] == initial["default"]
        assert (await async_client.put(url, json={"threshold": 1.75})).json() == {"saved": 1.75}
        assert (await async_client.get(url)).json()["effective"] == 1.75
        assert (await async_client.delete(url)).json() == {"reset": True}
        assert (await async_client.get(url)).json()["saved"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [None, "abc", 0, 0.01, 99, -1])
    async def test_absurd_thresholds_are_refused(self, async_client: AsyncClient, printer, value):
        url = f"/api/v1/printers/{printer.id}/camera/plate-detection/tuning"
        assert (await async_client.put(url, json={"threshold": value})).status_code == 400
        assert (await async_client.get(url)).json()["saved"] is None

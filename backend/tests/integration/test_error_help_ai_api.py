"""Fehlerhilfe-API für die KI-Erkennung: Einstellungen, Upload und Treffer."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.app.services import ai_error_scan, assistant_config, assistant_llm


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assistant_config, "_path", lambda data_dir: tmp_path / "assistant.json")
    monkeypatch.setattr(ai_error_scan, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(ai_error_scan, "FEEDBACK_PATH", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(
        assistant_llm,
        "status",
        AsyncMock(return_value={"reachable": True, "models": ["qwen3.5:4b"], "model_present": True, "error": ""}),
    )


class TestScanConfig:
    @pytest.mark.asyncio
    async def test_defaults_are_off_and_use_the_assistant_model(self, async_client: AsyncClient):
        body = (await async_client.get("/api/v1/error-help/ai-scan")).json()
        assert body["config"]["error_scan_enabled"] is False
        # Das Assistenten-Standardmodell ist hier nicht installiert; die Karte
        # soll das ehrlich melden, statt ein Bildmodell zu versprechen.
        assert body["vision_present"] is False
        assert body["findings"] == [] and body["counts"] == {}

    @pytest.mark.asyncio
    async def test_round_trip(self, async_client: AsyncClient):
        response = await async_client.put(
            "/api/v1/error-help/ai-scan",
            json={"vision_model": "qwen3.5:4b", "error_scan_enabled": True, "error_scan_min_confidence": 70},
        )
        assert response.status_code == 200
        assert response.json()["config"] == {
            "vision_model": "qwen3.5:4b",
            "error_scan_enabled": True,
            "error_scan_min_confidence": 70,
            "error_scan_notify": True,
            "model": "qwen2.5:3b",
        }
        assert response.json()["vision_present"] is True

    @pytest.mark.asyncio
    async def test_rejects_an_out_of_range_threshold(self, async_client: AsyncClient):
        response = await async_client.put("/api/v1/error-help/ai-scan", json={"error_scan_min_confidence": 101})
        assert response.status_code == 422


class TestScan:
    @pytest.mark.asyncio
    async def test_an_uploaded_image_is_classified(self, async_client: AsyncClient):
        result = {"pattern_id": "stringing", "confidence": 0.8, "reason": "Fäden", "model": "qwen3.5:4b"}
        with patch.object(ai_error_scan, "scan_and_record", AsyncMock(return_value=result)) as scan:
            response = await async_client.post(
                "/api/v1/error-help/ai-scan/upload",
                files={"file": ("frame.jpg", b"fake-jpeg", "image/jpeg")},
            )
        assert response.status_code == 200
        assert response.json()["result"]["pattern_id"] == "stringing"
        assert scan.call_args.kwargs["source"] == "upload"

    @pytest.mark.asyncio
    async def test_an_empty_upload_is_refused(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/error-help/ai-scan/upload", files={"file": ("empty.jpg", b"", "image/jpeg")}
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_a_collected_failure_image_can_be_reused(self, async_client: AsyncClient, tmp_path):
        image = tmp_path / ("fail_stringing_20261030_120000_" + "a" * 32 + ".jpg")
        image.write_bytes(b"fake-jpeg")
        result = {"pattern_id": "stringing", "confidence": 0.9, "reason": "Fäden", "model": "m"}
        with (
            patch("backend.app.api.routes.error_help.failure_images.find_failure_image", return_value=image),
            patch.object(ai_error_scan, "scan_and_record", AsyncMock(return_value=result)) as scan,
        ):
            response = await async_client.post(f"/api/v1/error-help/ai-scan/failure-image/{image.name}")
        assert response.status_code == 200
        assert scan.call_args.kwargs["image_name"] == image.name
        assert scan.call_args.kwargs["source"] == "failure_image"

    @pytest.mark.asyncio
    async def test_an_unknown_failure_image_is_a_404(self, async_client: AsyncClient):
        with patch("backend.app.api.routes.error_help.failure_images.find_failure_image", return_value=None):
            response = await async_client.post("/api/v1/error-help/ai-scan/failure-image/nope.jpg")
        assert response.status_code == 404


class TestFindings:
    @pytest.mark.asyncio
    async def test_findings_and_counts_are_listed(self, async_client: AsyncClient):
        ai_error_scan.record(
            {"pattern_id": "warping", "confidence": 0.8, "reason": "Ecken", "model": "m"}, source="upload"
        )
        ai_error_scan.record(
            {"pattern_id": "stringing", "confidence": 0.7, "reason": "Fäden", "model": "m"}, source="upload"
        )
        body = (await async_client.get("/api/v1/error-help/ai-scan/findings")).json()
        assert body["counts"] == {"warping": 1, "stringing": 1}
        assert body["findings"][0]["pattern_id"] == "stringing"

    @pytest.mark.asyncio
    async def test_filter_by_pattern(self, async_client: AsyncClient):
        ai_error_scan.record({"pattern_id": "warping", "confidence": 0.8, "reason": "", "model": "m"}, source="upload")
        ai_error_scan.record(
            {"pattern_id": "stringing", "confidence": 0.7, "reason": "", "model": "m"}, source="upload"
        )
        body = (await async_client.get("/api/v1/error-help/ai-scan/findings?pattern_id=warping")).json()
        assert [entry["pattern_id"] for entry in body["findings"]] == ["warping"]

    @pytest.mark.asyncio
    async def test_feedback_marks_a_finding_and_survives_in_the_list(self, async_client: AsyncClient):
        finding = ai_error_scan.record(
            {"pattern_id": "warping", "confidence": 0.8, "reason": "", "model": "m"}, source="upload"
        )
        assert finding is not None
        response = await async_client.post(
            f"/api/v1/error-help/ai-scan/findings/{finding['id']}/feedback", json={"verdict": "wrong"}
        )
        assert response.status_code == 200
        assert response.json()["feedback"] == {"correct": 0, "wrong": 1}
        assert response.json()["findings"][0]["verdict"] == "wrong"

    @pytest.mark.asyncio
    async def test_feedback_for_an_unknown_finding_is_a_404(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/error-help/ai-scan/findings/does-not-exist/feedback", json={"verdict": "correct"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_a_collection_scan_can_be_started(self, async_client: AsyncClient):
        with patch.object(ai_error_scan, "start_batch", return_value={"running": True, "total": 4}) as start:
            response = await async_client.post("/api/v1/error-help/ai-scan/scan-collection", json={"limit": 4})
        assert response.status_code == 200
        assert start.call_args.args[0] == 4
        assert response.json()["running"] is True

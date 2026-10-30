"""KI-Fehlererkennung: Antwort lesen, Treffer ablegen und zählen."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services import ai_error_scan


class TestParseReply:
    def test_reads_the_json_even_inside_a_code_fence(self):
        result = ai_error_scan._parse_reply(
            '```json\n{"pattern_id": "stringing", "confidence": 0.72, "reason": "Fäden"}\n```'
        )
        assert result == {"pattern_id": "stringing", "confidence": 0.72, "reason": "Fäden"}

    def test_percent_values_are_normalised(self):
        result = ai_error_scan._parse_reply('{"pattern_id": "warping", "confidence": 85, "reason": "Ecken"}')
        assert result["confidence"] == 0.85

    def test_none_means_no_finding(self):
        assert (
            ai_error_scan._parse_reply('{"pattern_id": "none", "confidence": 0.9, "reason": "ok"}')["pattern_id"]
            is None
        )

    def test_an_unknown_pattern_is_rejected(self):
        with pytest.raises(ai_error_scan.AiScanError):
            ai_error_scan._parse_reply('{"pattern_id": "warp_drive", "confidence": 0.9, "reason": "?"}')

    def test_garbage_is_rejected(self):
        with pytest.raises(ai_error_scan.AiScanError):
            ai_error_scan._parse_reply("Das Bild ist schön.")


class TestFindings:
    @pytest.fixture(autouse=True)
    def _tmp_paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ai_error_scan, "FINDINGS_PATH", tmp_path / "findings.jsonl")

    def test_records_only_patterns_and_counts_them(self):
        assert ai_error_scan.record({"pattern_id": None, "confidence": 0.9}, source="upload") is None
        ai_error_scan.record(
            {"pattern_id": "stringing", "confidence": 0.7, "reason": "Fäden", "model": "m"}, source="upload"
        )
        ai_error_scan.record(
            {"pattern_id": "stringing", "confidence": 0.8, "reason": "mehr", "model": "m"}, source="failure_image"
        )
        ai_error_scan.record(
            {"pattern_id": "warping", "confidence": 0.6, "reason": "Ecken", "model": "m"}, source="upload"
        )
        assert ai_error_scan.counts() == {"stringing": 2, "warping": 1}
        findings = ai_error_scan.list_findings(10)
        assert [entry["pattern_id"] for entry in findings] == ["warping", "stringing", "stringing"]
        assert ai_error_scan.list_findings(10, "stringing")[0]["reason"] == "mehr"

    def test_scan_records_only_above_the_threshold(self):
        config = {"error_scan_min_confidence": 70, "vision_model": "m"}
        low = AsyncMock(return_value={"pattern_id": "stringing", "confidence": 0.5, "reason": "", "model": "m"})
        high = AsyncMock(return_value={"pattern_id": "stringing", "confidence": 0.9, "reason": "", "model": "m"})
        import asyncio

        with patch.object(ai_error_scan, "classify", low):
            asyncio.run(ai_error_scan.scan_and_record(b"x", source="upload", config=config))
        assert ai_error_scan.counts() == {}
        with patch.object(ai_error_scan, "classify", high):
            asyncio.run(ai_error_scan.scan_and_record(b"x", source="upload", config=config))
        assert ai_error_scan.counts() == {"stringing": 1}


def test_a_broken_image_is_refused():
    with pytest.raises(ai_error_scan.AiScanError):
        ai_error_scan._prepare_image(b"not an image")


def test_entries_are_json_lines(tmp_path, monkeypatch):
    path = tmp_path / "findings.jsonl"
    monkeypatch.setattr(ai_error_scan, "FINDINGS_PATH", path)
    ai_error_scan.record({"pattern_id": "ghosting", "confidence": 1, "reason": "", "model": "m"}, source="upload")
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["pattern_id"] == "ghosting" and line["source"] == "upload"

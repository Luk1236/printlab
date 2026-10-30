"""Trainingsset-Export der Fehlerbild-Sammlung (services/error_export.py)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from backend.app.core.config import settings
from backend.app.services import ai_error_scan, error_export
from backend.app.utils import failure_images


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(ai_error_scan, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(ai_error_scan, "FEEDBACK_PATH", tmp_path / "feedback.jsonl")
    return tmp_path


def _zip(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


def test_export_contains_images_labels_and_metadata():
    name = failure_images.save_failure_image(b"\xff\xd8jpeg", "plate_not_empty")
    finding = ai_error_scan.record(
        {"pattern_id": "stringing", "confidence": 0.82, "reason": "Fäden", "model": "m"},
        source="failure_image",
        image_name=name,
    )
    ai_error_scan.record_feedback(finding["id"], "correct")

    archive = _zip(error_export.build_zip())
    names = archive.namelist()
    assert f"images/{name}" in names
    assert {"labels.jsonl", "meta.json", "README.txt"} <= set(names)

    labels = [json.loads(line) for line in archive.read("labels.jsonl").decode("utf-8").splitlines()]
    assert labels == [
        {
            "image": name,
            "event": "plate_not_empty",
            "timestamp": labels[0]["timestamp"],
            "ai": labels[0]["ai"],
            "verdict": "correct",
        }
    ]
    assert labels[0]["ai"]["pattern_id"] == "stringing"
    assert labels[0]["ai"]["confidence"] == 0.82
    assert labels[0]["ai"]["reason"] == "Fäden"

    meta = json.loads(archive.read("meta.json"))
    assert meta["images"] == 1 and meta["rated"] == 1
    assert "Trainingsset" in archive.read("README.txt").decode("utf-8")


def test_export_without_images_is_a_valid_empty_zip():
    archive = _zip(error_export.build_zip())
    assert archive.read("labels.jsonl") == b""
    meta = json.loads(archive.read("meta.json"))
    assert meta["images"] == 0 and meta["rated"] == 0


def test_unrated_image_has_no_ai_and_no_verdict():
    failure_images.save_failure_image(b"\xff\xd8jpeg", "first_layer")
    archive = _zip(error_export.build_zip())
    label = json.loads(archive.read("labels.jsonl").decode("utf-8").splitlines()[0])
    assert label["ai"] is None and label["verdict"] is None

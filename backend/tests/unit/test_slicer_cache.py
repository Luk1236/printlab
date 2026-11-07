"""Unit-Tests fuer Slicer-Cache-Verwaltung und Temp-Bereinigung."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from backend.app.services.slicer_cache import (
    SLICE_TEMP_PREFIX,
    clean_slicer_cache,
    get_slicer_cache_stats,
)


def test_get_slicer_cache_stats():
    stats = get_slicer_cache_stats()
    assert "temp_folders_count" in stats
    assert "temp_total_bytes" in stats
    assert "temp_total_mb" in stats
    assert "free_disk_bytes" in stats
    assert isinstance(stats["temp_folders_count"], int)
    assert stats["free_disk_bytes"] >= 0


def test_clean_slicer_cache_removes_old_folders(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    old_dir = tmp_path / f"{SLICE_TEMP_PREFIX}test_old_1"
    old_dir.mkdir()
    dummy_file = old_dir / "plate_1.gcode"
    dummy_file.write_bytes(b"G1 X10 Y10\n" * 100)

    # Set mtime to 4 hours ago
    four_hours_ago = time.time() - 14400
    os.utime(old_dir, (four_hours_ago, four_hours_ago))

    result = clean_slicer_cache(max_age_seconds=7200)
    assert result["deleted_folders"] == 1
    assert result["freed_bytes"] > 0
    assert not old_dir.exists()


def test_clean_slicer_cache_preserves_recent_folders(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    recent_dir = tmp_path / f"{SLICE_TEMP_PREFIX}test_recent_1"
    recent_dir.mkdir()
    (recent_dir / "plate_1.gcode").write_bytes(b"G1 X10 Y10\n")

    # Regular cleanup (age threshold 2h)
    result = clean_slicer_cache(max_age_seconds=7200, force_all=False)
    assert result["deleted_folders"] == 0
    assert recent_dir.exists()
    assert result["remaining_folders"] == 1

    # Force cleanup deletes everything
    force_result = clean_slicer_cache(force_all=True)
    assert force_result["deleted_folders"] == 1
    assert not recent_dir.exists()

"""Tests für den Zeitraffer-Export aus aufbewahrten Schichtbildern."""

import asyncio
from pathlib import Path

import pytest

from backend.app.services import timelapse_export


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(timelapse_export, "CONFIG_PATH", tmp_path / "timelapse_export.json")
    monkeypatch.setattr(timelapse_export, "KEPT_ROOT", tmp_path / "kept")
    monkeypatch.setattr(timelapse_export, "EXPORT_ROOT", tmp_path / "exports")
    return tmp_path


def _frames(folder: Path, count: int = 3) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(1, count + 1):
        (folder / f"layer_{index:05d}.jpg").write_bytes(b"jpg")
    return folder


class TestConfig:
    def test_defaults_without_file(self):
        cfg = timelapse_export.read_config()
        assert cfg["keep_frames"] is False
        assert cfg["fps"] == 24

    def test_unknown_keys_are_ignored_and_ranges_enforced(self):
        cfg = timelapse_export.write_config({"fps": 999, "bogus": 1, "retention_days": 0})
        assert cfg["fps"] == 24  # außerhalb 1..60 -> Vorgabe
        assert cfg["retention_days"] == 14  # 0 ist ungültig -> Vorgabe
        assert "bogus" not in cfg

    def test_known_values_round_trip(self):
        cfg = timelapse_export.write_config({"keep_frames": True, "fps": 12, "max_exports_per_archive": 2})
        assert cfg == {**timelapse_export.read_config(), "keep_frames": True, "fps": 12}
        assert cfg["max_exports_per_archive"] == 2


class TestConcat:
    def test_each_frame_gets_duration_and_last_is_repeated(self):
        files = [Path("/a/layer_00001.jpg"), Path("/a/layer_00002.jpg")]
        text = timelapse_export.build_concat_text(files, 20)
        assert text.count("file '") == 3  # zwei Bilder + Wiederholung des letzten
        assert "duration 0.050000" in text
        assert text.strip().endswith(f"file '{files[-1]}'")

    def test_quotes_in_paths_are_escaped(self):
        text = timelapse_export.build_concat_text([Path("/a/it's.jpg")], 24)
        assert "'\\''" in text


class TestKeepFrames:
    def test_moves_frames_under_archive(self, tmp_path):
        source = _frames(tmp_path / "session1")
        target = timelapse_export.keep_frames(7, source, "20260101_120000")
        assert target is not None
        assert target == tmp_path / "kept" / "7" / "20260101_120000"
        assert len(timelapse_export.frame_files(target)) == 3
        assert not source.exists()

    def test_without_archive_or_frames_nothing_happens(self, tmp_path):
        assert timelapse_export.keep_frames(None, _frames(tmp_path / "a"), "s") is None
        assert timelapse_export.keep_frames(1, tmp_path / "empty", "s") is None

    def test_keeps_only_newest_sessions(self, tmp_path):
        timelapse_export.write_config({"max_kept_per_archive": 2})
        for day in ("20260101_100000", "20260102_100000", "20260103_100000"):
            timelapse_export.keep_frames(3, _frames(tmp_path / f"src_{day}"), day)
        sessions = [s["session"] for s in timelapse_export.list_sources(3)]
        assert sessions == ["20260103_100000", "20260102_100000"]

    def test_list_counts_frames(self, tmp_path):
        timelapse_export.keep_frames(5, _frames(tmp_path / "src", 4), "20260101_120000")
        sources = timelapse_export.list_sources(5)
        assert sources[0]["frames"] == 4


class TestExports:
    def test_prune_keeps_newest(self, tmp_path):
        exports = tmp_path / "exports"
        exports.mkdir()
        for index in range(4):
            path = exports / f"archiv_9_2026010{index}_24fps_x.mp4"
            path.write_bytes(b"mp4")
            import os

            os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        timelapse_export.write_config({"max_exports_per_archive": 2})
        timelapse_export.prune_exports(9)
        assert len(timelapse_export.list_exports(9)) == 2

    def test_resolve_rejects_traversal_and_foreign_files(self, tmp_path):
        exports = tmp_path / "exports"
        exports.mkdir()
        (exports / "archiv_4_x.mp4").write_bytes(b"mp4")
        (exports / "archiv_5_y.mp4").write_bytes(b"mp4")
        assert timelapse_export.resolve_export(4, "archiv_4_x.mp4") is not None
        assert timelapse_export.resolve_export(4, "../archiv_4_x.mp4") is None
        assert timelapse_export.resolve_export(4, "archiv_5_y.mp4") is None
        assert timelapse_export.resolve_export(4, "archiv_4_x.txt") is None


class TestRender:
    @pytest.mark.asyncio
    async def test_without_sources_raises_readable_error(self):
        with pytest.raises(ValueError, match="Keine aufbewahrten Schichtbilder"):
            await timelapse_export.render(1)

    @pytest.mark.asyncio
    async def test_render_writes_mp4(self, tmp_path, monkeypatch):
        timelapse_export.write_config({"fps": 10})
        timelapse_export.keep_frames(2, _frames(tmp_path / "src", 3), "20260101_120000")
        monkeypatch.setattr("backend.app.services.camera.get_ffmpeg_path", lambda: "ffmpeg")

        calls: list[list[str]] = []

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            Path(args[-1]).write_bytes(b"fake-mp4")
            return FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        result = await timelapse_export.render(2, None, None)
        assert result["frames"] == 3
        assert result["fps"] == 10
        assert result["bytes"] == len(b"fake-mp4")
        assert calls and "-r" in calls[0]
        assert timelapse_export.resolve_export(2, result["name"]) is not None

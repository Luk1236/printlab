"""Regressionstests zu T5-01, T5-02 und T5-03 der Code-Analyse (docs/analyse/T5-...).

Grenzen für das Entpacken von Zip-Dateien (``utils/zip_limits``) und für Uploads (``utils/upload_limits``),
dazu die Stellen, die sie benutzen: der 3MF-Parser und die Modellanalyse des Kundenportals.
"""

from __future__ import annotations

import io
import tracemalloc
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.utils import upload_limits
from backend.app.utils.upload_limits import read_upload_limited, save_upload_limited
from backend.app.utils.zip_limits import (
    MAX_LARGE_MEMBER_BYTES,
    MAX_SMALL_MEMBER_BYTES,
    ZipLimitError,
    check_zip,
    extract_member_limited,
    member_limit,
    read_member,
    read_member_large,
)

MB = 1024 * 1024


def _zip_with(members: dict[str, int]) -> zipfile.ZipFile:
    """Zip im Speicher; je Teil ein Name und die entpackte Größe in Bytes (aus Leerzeichen, komprimiert stark)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, size in members.items():
            with zf.open(name, "w") as member:
                remaining = size
                while remaining > 0:
                    step = min(remaining, MB)
                    member.write(b" " * step)
                    remaining -= step
    buf.seek(0)
    return zipfile.ZipFile(buf)


class TestReadMember:
    def test_small_members_pass_and_return_their_bytes(self):
        zf = _zip_with({"Metadata/slice_info.config": 1000})
        assert read_member(zf, "Metadata/slice_info.config") == b" " * 1000

    def test_a_config_over_the_small_limit_is_refused_before_it_is_unpacked(self):
        zf = _zip_with({"Metadata/slice_info.config": MAX_SMALL_MEMBER_BYTES + 1})
        tracemalloc.start()
        try:
            with pytest.raises(ZipLimitError, match="slice_info.config"):
                read_member(zf, "Metadata/slice_info.config")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 8 * MB, "refused from the directory, nothing was unpacked"

    @pytest.mark.parametrize("name", ["3D/Objects/a.model", "Metadata/plate_1.gcode", "x.STL", "p.3mf", "m.step"])
    def test_models_and_gcode_get_the_large_limit(self, name):
        assert member_limit(name) == MAX_LARGE_MEMBER_BYTES

    @pytest.mark.parametrize("name", ["Metadata/plate_1.png", "Metadata/slice_info.config", "[Content_Types].xml"])
    def test_everything_else_gets_the_small_limit(self, name):
        assert member_limit(name) == MAX_SMALL_MEMBER_BYTES

    def test_a_model_larger_than_the_small_limit_is_allowed(self):
        zf = _zip_with({"3D/3dmodel.model": MAX_SMALL_MEMBER_BYTES + MB})
        assert len(read_member(zf, "3D/3dmodel.model")) == MAX_SMALL_MEMBER_BYTES + MB

    def test_explicit_limit_overrides_the_default(self):
        zf = _zip_with({"Metadata/big.bin": 2000})
        with pytest.raises(ZipLimitError):
            read_member(zf, "Metadata/big.bin", max_bytes=1000)
        assert len(read_member_large(zf, "Metadata/big.bin")) == 2000

    def test_a_missing_member_still_raises_keyerror(self):
        with pytest.raises(KeyError):
            read_member(_zip_with({"a.txt": 1}), "nope.txt")


class TestCheckZip:
    def test_too_many_entries(self):
        zf = _zip_with({f"f{i}.txt": 1 for i in range(5)})
        with pytest.raises(ZipLimitError, match="5 entries"):
            check_zip(zf, max_members=4)

    def test_unpacked_total_over_the_limit(self):
        zf = _zip_with({"a.txt": 3 * MB, "b.txt": 3 * MB})
        with pytest.raises(ZipLimitError, match="unpacks to"):
            check_zip(zf, max_total_bytes=5 * MB)

    def test_a_normal_zip_passes(self):
        check_zip(_zip_with({"a.txt": 10, "b.txt": 20}))


class TestExtractMemberLimited:
    def test_streams_to_disk_and_reports_the_size(self, tmp_path: Path):
        zf = _zip_with({"a.stl": 3 * MB})
        dest = tmp_path / "out.stl"
        assert extract_member_limited(zf, "a.stl", dest, max_bytes=5 * MB) == 3 * MB
        assert dest.stat().st_size == 3 * MB

    def test_over_the_limit_leaves_nothing_behind(self, tmp_path: Path):
        zf = _zip_with({"a.stl": 3 * MB})
        dest = tmp_path / "out.stl"
        with pytest.raises(ZipLimitError):
            extract_member_limited(zf, "a.stl", dest, max_bytes=1 * MB)
        assert not dest.exists()


class _Upload:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self.reads = 0

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        return self._buf.read(size)


class TestUploadLimits:
    @pytest.mark.asyncio
    async def test_a_small_upload_is_read_whole(self):
        assert await read_upload_limited(_Upload(b"x" * 1000), 2 * MB) == b"x" * 1000

    @pytest.mark.asyncio
    async def test_an_oversized_upload_gets_413_and_is_not_read_to_the_end(self):
        upload = _Upload(b"x" * (10 * MB))
        with pytest.raises(HTTPException) as err:
            await read_upload_limited(upload, 2 * MB)
        assert err.value.status_code == 413
        assert upload.reads <= 4, "reading stops shortly after the limit"

    @pytest.mark.asyncio
    async def test_save_streams_to_disk_and_returns_size_and_head(self, tmp_path: Path):
        dest = tmp_path / "a.3mf"
        size, head = await save_upload_limited(_Upload(b"PK\x03\x04" + b"y" * (2 * MB)), dest, 5 * MB)
        assert (size, head[:4]) == (2 * MB + 4, b"PK\x03\x04")
        assert dest.stat().st_size == size

    @pytest.mark.asyncio
    async def test_save_over_the_limit_removes_the_partial_file(self, tmp_path: Path):
        dest = tmp_path / "b.3mf"
        with pytest.raises(HTTPException) as err:
            await save_upload_limited(_Upload(b"z" * (6 * MB)), dest, 5 * MB)
        assert err.value.status_code == 413
        assert not dest.exists()

    def test_limits_come_from_the_settings(self, monkeypatch):
        monkeypatch.setattr(upload_limits.settings, "max_upload_mb", 7)
        monkeypatch.setattr(upload_limits.settings, "max_portal_upload_mb", 3)
        assert upload_limits.max_upload_bytes() == 7 * MB
        assert upload_limits.max_portal_upload_bytes() == 3 * MB


class TestThreeMFParserRefusesBombs:
    def test_a_bomb_in_slice_info_costs_no_memory_and_yields_no_metadata(self, tmp_path: Path):
        from backend.app.services.archive import ThreeMFParser

        bomb = tmp_path / "bomb.gcode.3mf"
        with (
            zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf,
            zf.open("Metadata/slice_info.config", "w") as member,
        ):
            member.write(b"<config>")
            for _ in range(MAX_SMALL_MEMBER_BYTES // MB + 8):  # über der kleinen Grenze
                member.write(b" " * MB)
            member.write(b"</config>")
        assert bomb.stat().st_size < 200 * 1024

        tracemalloc.start()
        try:
            metadata = ThreeMFParser(str(bomb)).parse()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak < 20 * MB, f"the parser unpacked the bomb ({peak / MB:.0f} MB peak)"
        assert not metadata.get("filament_type")


class TestPortalMeshAnalysis:
    def test_a_3mf_bomb_is_refused_before_trimesh_sees_it(self, monkeypatch):
        from backend.app.services import mesh_analysis

        monkeypatch.setattr(mesh_analysis, "PORTAL_MAX_UNPACKED_BYTES", 1 * MB)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr("3D/3dmodel.model", b" " * (3 * MB))

        tracemalloc.start()
        try:
            with pytest.raises(ValueError, match="unpacks to"):
                mesh_analysis.analyze_mesh_data(buf.getvalue(), "modell.3mf")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 4 * MB

    def test_a_broken_3mf_is_a_value_error_not_a_crash(self):
        from backend.app.services import mesh_analysis

        with pytest.raises(ValueError):
            mesh_analysis.analyze_mesh_data(b"PK\x03\x04" + b"not really a zip" * 20, "modell.3mf")

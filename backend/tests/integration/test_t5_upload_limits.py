"""Uploads über der Grenze und Zip-Bomben an den echten Routen (T5-01 bis T5-04 der Code-Analyse)."""

import io
import zipfile

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

MB = 1024 * 1024


def _zip_bytes(members: dict[str, int]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, size in members.items():
            zf.writestr(name, b" " * size)
    return buf.getvalue()


@pytest.fixture
def small_upload_cap(monkeypatch):
    """Obergrenze 1 MB für große Uploads und das Portal, damit die Tests klein bleiben."""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    monkeypatch.setattr(settings, "max_portal_upload_mb", 1)


@pytest.fixture
def library_dirs(tmp_path, monkeypatch):
    """Bibliotheksdateien und Vorschauen in ein Temp-Verzeichnis statt in den echten Datenordner."""
    from backend.app.api.routes import library, library_helpers

    files_dir = tmp_path / "files"
    thumbs_dir = tmp_path / "thumbs"
    files_dir.mkdir()
    thumbs_dir.mkdir()
    for module in (library, library_helpers):
        if hasattr(module, "get_library_files_dir"):
            monkeypatch.setattr(module, "get_library_files_dir", lambda: files_dir)
        if hasattr(module, "get_library_thumbnails_dir"):
            monkeypatch.setattr(module, "get_library_thumbnails_dir", lambda: thumbs_dir)
    return files_dir


@pytest.mark.asyncio
async def test_library_upload_over_the_cap_gets_413_and_leaves_no_file(
    async_client: AsyncClient, small_upload_cap, library_dirs
):
    files_dir = library_dirs

    resp = await async_client.post(
        "/api/v1/library/files", files={"file": ("big.stl", b"\x00" * (2 * MB), "application/octet-stream")}
    )

    assert resp.status_code == 413
    assert list(files_dir.iterdir()) == [], "the partial file is removed again"


@pytest.mark.asyncio
async def test_library_upload_under_the_cap_still_works(async_client: AsyncClient, small_upload_cap, library_dirs):
    resp = await async_client.post(
        "/api/v1/library/files", files={"file": ("tiny.stl", b"solid x\nendsolid x\n", "application/octet-stream")}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["file_size"] == len(b"solid x\nendsolid x\n")


@pytest.mark.asyncio
async def test_library_rejects_a_renamed_gcode_after_streaming_and_removes_it(async_client: AsyncClient, library_dirs):
    """The magic-byte check now runs on the first bytes only; a rejected upload must not stay on disk."""
    files_dir = library_dirs

    resp = await async_client.post(
        "/api/v1/library/files", files={"file": ("x.3mf", b"G28\nG1 X0\n" * 10, "application/octet-stream")}
    )

    assert resp.status_code == 400
    assert list(files_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_extract_zip_reports_an_oversized_member_and_keeps_the_rest(
    async_client: AsyncClient, small_upload_cap, library_dirs
):
    payload = _zip_bytes({"ok.stl": 1000, "bomb.stl": 3 * MB})
    assert len(payload) < MB

    resp = await async_client.post(
        "/api/v1/library/files/extract-zip", files={"file": ("pack.zip", payload, "application/zip")}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [f["filename"] for f in body["files"]] == ["ok.stl"]
    assert [e["filename"] for e in body["errors"]] == ["bomb.stl"]
    assert "limit" in body["errors"][0]["error"]


@pytest.mark.asyncio
async def test_extract_zip_over_the_upload_cap_gets_413(async_client: AsyncClient, small_upload_cap, library_dirs):
    resp = await async_client.post(
        "/api/v1/library/files/extract-zip", files={"file": ("pack.zip", b"PK" + b"\x00" * (2 * MB), "application/zip")}
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_archive_photo_upload_over_the_image_cap_gets_413(
    async_client: AsyncClient, printer_factory, archive_factory, tmp_path, monkeypatch
):
    from backend.app.core.config import settings

    # The archive's directory is derived from base_dir; keep it out of the working tree.
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "base_dir", data)
    printer = await printer_factory(name="P")
    archive = await archive_factory(printer.id, with_run=False)

    resp = await async_client.post(
        f"/api/v1/archives/{archive.id}/photos",
        files={"file": ("p.png", b"\x89PNG" + b"\x00" * (26 * MB), "image/png")},
    )

    assert resp.status_code == 413
    assert list(data.rglob("*")) == [], "a refused photo leaves neither a file nor directories"


@pytest.mark.asyncio
async def test_f3d_upload_on_an_archive_without_3mf_stays_inside_the_data_directory(
    async_client: AsyncClient, printer_factory, archive_factory, tmp_path, monkeypatch
):
    """T5-04: used to write `<data dir>/../f3d/design.f3d` and then fail with a 500."""
    from backend.app.api.routes import archives as archives_mod
    from backend.app.core.config import settings

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(archives_mod.settings, "base_dir", data)
    monkeypatch.setattr(settings, "archive_dir", data / "archive")
    printer = await printer_factory(name="P")
    archive = await archive_factory(printer.id, file_path="", with_run=False)

    resp = await async_client.post(
        f"/api/v1/archives/{archive.id}/f3d", files={"file": ("design.f3d", b"F3D", "application/octet-stream")}
    )

    assert resp.status_code == 200, resp.text
    written = list(tmp_path.rglob("design.f3d"))
    assert len(written) == 1
    assert data in written[0].parents, f"written outside the data directory: {written[0]}"
    assert resp.json()["f3d_path"].startswith("archive/")


@pytest.mark.asyncio
async def test_portal_analyze_model_over_the_cap_gets_413(async_client: AsyncClient, small_upload_cap):
    resp = await async_client.post(
        "/api/v1/portal/analyze-model", files={"file": ("m.stl", b"\x00" * (2 * MB), "application/octet-stream")}
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_portal_analyze_model_refuses_a_3mf_bomb_without_unpacking_it(
    async_client: AsyncClient, small_upload_cap, monkeypatch
):
    from backend.app.services import mesh_analysis

    monkeypatch.setattr(mesh_analysis, "PORTAL_MAX_UNPACKED_BYTES", 1 * MB)
    bomb = _zip_bytes({"3D/3dmodel.model": 4 * MB})
    assert len(bomb) < MB

    resp = await async_client.post(
        "/api/v1/portal/analyze-model", files={"file": ("bomb.3mf", bomb, "application/octet-stream")}
    )

    assert resp.status_code == 400
    assert "unpacks to" in resp.json()["detail"]

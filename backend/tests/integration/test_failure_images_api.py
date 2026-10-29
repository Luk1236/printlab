"""Integration-Tests für die Fehlerbild-Routen (Liste, Bild, Löschen)."""

import pytest
from httpx import AsyncClient

from backend.app.core.config import settings
from backend.app.utils import failure_images


@pytest.fixture
def images_dir(tmp_path, monkeypatch):
    dir_path = tmp_path / "failure_images"
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    return dir_path


class TestFailureImagesAPI:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_empty_list(self, async_client: AsyncClient, images_dir):
        response = await async_client.get("/api/v1/failure-images/")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_saved_image_lists_and_serves(self, async_client: AsyncClient, images_dir):
        name = failure_images.save_failure_image(b"\xff\xd8\xff" + b"0" * 50, "ai")
        assert name is not None

        listing = (await async_client.get("/api/v1/failure-images/")).json()
        assert listing and listing[0]["name"] == name and listing[0]["event"] == "ai"

        image = await async_client.get(f"/api/v1/failure-images/{name}")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/jpeg")
        assert image.content == b"\xff\xd8\xff" + b"0" * 50

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unknown_and_foreign_names_are_not_found(self, async_client: AsyncClient, images_dir):
        assert (
            await async_client.get("/api/v1/failure-images/fail_ai_20260101_000000_" + "a" * 32 + ".jpg")
        ).status_code == 404
        assert (
            await async_client.delete("/api/v1/failure-images/fail_ai_20260101_000000_" + "a" * 32 + ".jpg")
        ).status_code == 404
        assert (await async_client.get("/api/v1/failure-images/irgendwas.jpg")).status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_delete_removes_the_entry(self, async_client: AsyncClient, images_dir):
        name = failure_images.save_failure_image(b"x", "plate_not_empty")
        assert (await async_client.delete(f"/api/v1/failure-images/{name}")).status_code == 200
        assert not (images_dir / name).exists()
        assert (await async_client.get("/api/v1/failure-images/")).json() == []

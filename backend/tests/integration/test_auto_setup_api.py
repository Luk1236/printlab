"""Auto-Einrichtung: Schnittstelle (Vorschau, Ausführen, Eingabeprüfung)."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from backend.app.api.routes import auto_setup as route


async def test_preview_returns_every_step_and_changes_nothing(async_client: AsyncClient, tmp_path):
    with patch.object(route.settings, "base_dir", tmp_path):
        body = (await async_client.get("/api/v1/system/auto-setup")).json()

    assert [item["id"] for item in body["items"]] == ["guard", "assistant", "remote"]
    assert not (tmp_path / "assistant.json").exists()


async def test_unknown_step_is_rejected(async_client: AsyncClient):
    response = await async_client.post("/api/v1/system/auto-setup", json={"only": ["format_disk"]})

    assert response.status_code == 400


async def test_run_reports_the_result_of_each_step(async_client: AsyncClient, tmp_path):
    fake = {"items": [{"id": "guard", "state": "changed", "detail": ""}], "changed": 1}
    with patch.object(route.auto_setup, "run", AsyncMock(return_value=fake)):
        response = await async_client.post("/api/v1/system/auto-setup", json={"only": ["guard"]})

    assert response.status_code == 200
    assert response.json() == fake


async def test_second_run_at_the_same_time_gets_429(async_client: AsyncClient):
    await route._lock.acquire()
    try:
        response = await async_client.post("/api/v1/system/auto-setup", json={})
    finally:
        route._lock.release()

    assert response.status_code == 429

"""Statusabfrage des Slicer-Sidecars vor dem Slicen.

Die Slice-Maske sperrt den Knopf, wenn der Dienst nicht antwortet, und nennt
die tatsächlich benutzte Adresse — der häufigste Grund ist eine Adresse, die
nur auf dem PC stimmt (``localhost`` auf dem Pi).
"""

from __future__ import annotations

import pytest

from backend.app.api.routes import slicer_presets as sp
from backend.app.services.slicer_api import SlicerApiUnavailableError


class _FakeService:
    def __init__(self, base_url: str, payload: dict | None = None, error: Exception | None = None):
        self.base_url = base_url
        self.payload = payload
        self.error = error

    async def health(self) -> dict:
        if self.error is not None:
            raise self.error
        return self.payload or {}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_reachable_reports_url_and_version(monkeypatch):
    async def fake_url(_db):
        return "http://192.168.1.20:3001"

    seen: list[str] = []

    def fake_service(base_url: str):
        seen.append(base_url)
        return _FakeService(base_url, {"status": "healthy", "checks": {"bambustudio": {"version": "2.4.0"}}})

    monkeypatch.setattr(sp, "_resolve_slicer_api_url", fake_url)
    monkeypatch.setattr(sp, "SlicerApiService", fake_service)

    result = await sp.get_slicer_status(db=None, _=None)

    assert result == {
        "configured": True,
        "reachable": True,
        "url": "http://192.168.1.20:3001",
        "version": "2.4.0",
        "error": None,
    }
    assert seen == ["http://192.168.1.20:3001"]


@pytest.mark.asyncio
async def test_unreachable_keeps_the_reason(monkeypatch):
    async def fake_url(_db):
        return "http://localhost:3001"

    monkeypatch.setattr(sp, "_resolve_slicer_api_url", fake_url)
    monkeypatch.setattr(
        sp,
        "SlicerApiService",
        lambda base_url: _FakeService(base_url, error=SlicerApiUnavailableError("Slicer sidecar unreachable: refused")),
    )

    result = await sp.get_slicer_status(db=None, _=None)

    assert result["configured"] is True
    assert result["reachable"] is False
    assert result["url"] == "http://localhost:3001"
    assert "unreachable" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_not_configured_is_not_an_error(monkeypatch):
    async def fake_url(_db):
        return None

    monkeypatch.setattr(sp, "_resolve_slicer_api_url", fake_url)

    result = await sp.get_slicer_status(db=None, _=None)

    assert result == {"configured": False, "reachable": False, "url": None, "version": None, "error": None}

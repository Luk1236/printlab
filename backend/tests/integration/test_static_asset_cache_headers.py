"""Cache-Kopfzeilen für die gebaute Oberfläche.

Vite schreibt den Inhalts-Hash in jeden Dateinamen im Ordner ``assets`` (``client-CDk7AWno.js``). Ändert sich der
Inhalt, ändert sich der Name — der Browser darf eine solche Datei deshalb dauerhaft behalten, ohne nachzufragen.
Das spart über Tailscale bei jedem Seitenaufruf die Rückfragen (``304``) für jeden Baustein.

``index.html`` ist davon ausgenommen und muss weiterhin jedes Mal nachfragen; das prüft
``test_static_html_cache_headers.py``. Hier geht es um die andere Hälfte: Die gehashten Dateien bekommen die
Anweisung wirklich, und eine fehlende Datei bleibt ein 404 statt eines leeren 200.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.api.frontend_routes import CachedStaticFiles

ASSET_NAME = "client-CDk7AWno.js"
ASSET_BODY = "console.log('PrintLab');"
BIG_NAME = "settings-AAAA1111.js"
BIG_BODY = "export const settings = [\n" + "  { label: 'Einstellung', value: 123456789 },\n" * 200 + "];\n"
IMAGE_NAME = "logo-AAAA1111.png"
IMAGE_BODY = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096


@pytest.fixture
def asset_app(tmp_path) -> FastAPI:
    """Kleine App mit genau dem Mount, den ``register_frontend`` für ``/assets`` anlegt."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / ASSET_NAME).write_text(ASSET_BODY, encoding="utf-8")
    (assets / BIG_NAME).write_bytes(BIG_BODY.encode("utf-8"))
    (assets / IMAGE_NAME).write_bytes(IMAGE_BODY)
    app = FastAPI()
    app.mount(
        "/assets",
        CachedStaticFiles(directory=assets, cache_control="public, max-age=31536000, immutable"),
        name="assets",
    )
    return app


@pytest.mark.asyncio
async def test_hashed_asset_is_cached_immutably(asset_app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=asset_app), base_url="http://test") as client:
        response = await client.get(f"/assets/{ASSET_NAME}")

    assert response.status_code == 200
    assert response.text == ASSET_BODY
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.asyncio
async def test_missing_asset_stays_a_404(asset_app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=asset_app), base_url="http://test") as client:
        response = await client.get("/assets/gibt-es-nicht.js")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_large_script_is_gzipped(asset_app: FastAPI):
    """Textdateien über 1 KB werden gepackt ausgeliefert; der Browser bekommt denselben Inhalt zurück."""
    async with AsyncClient(transport=ASGITransport(app=asset_app), base_url="http://test") as client:
        response = await client.get(f"/assets/{BIG_NAME}", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    assert response.headers.get("vary") == "Accept-Encoding"
    assert response.text == BIG_BODY
    # Die Kopfzeile nennt die gepackte Größe (httpx entpackt den Rumpf beim Lesen bereits).
    assert int(response.headers["content-length"]) < len(BIG_BODY.encode("utf-8")) / 4


@pytest.mark.asyncio
async def test_binary_and_small_files_stay_uncompressed(asset_app: FastAPI):
    """Bilder und kurze Skripte werden nicht gepackt — das spart nur Arbeit, keine Bytes."""
    async with AsyncClient(transport=ASGITransport(app=asset_app), base_url="http://test") as client:
        image = await client.get(f"/assets/{IMAGE_NAME}", headers={"Accept-Encoding": "gzip"})
        small = await client.get(f"/assets/{ASSET_NAME}", headers={"Accept-Encoding": "gzip"})

    assert image.status_code == small.status_code == 200
    assert "content-encoding" not in image.headers
    assert "content-encoding" not in small.headers


def test_real_app_mounts_assets_with_cache_header():
    """Die App selbst muss den Cache-Mount benutzen, nicht das nackte ``StaticFiles``."""
    from backend.app.main import app

    mounts = {getattr(route, "path", None): route for route in app.routes}
    if "/assets" not in mounts:
        pytest.skip("static/ ist in dieser Umgebung nicht gebaut (Docker-Test ohne Oberfläche)")
    mounted = mounts["/assets"].app
    assert isinstance(mounted, CachedStaticFiles)
    assert mounted.cache_control == "public, max-age=31536000, immutable"

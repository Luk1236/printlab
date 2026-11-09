"""Integrationstests für Kundenportal 2.0 & Sofort-Kalkulator API."""

from __future__ import annotations

import io

import pytest
import trimesh
from httpx import AsyncClient

from backend.app.core.config import settings as app_settings

PREFIX = app_settings.api_prefix


def _make_test_stl_bytes(size: tuple[float, float, float] = (30.0, 20.0, 10.0)) -> bytes:
    mesh = trimesh.creation.box(extents=size)
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_portal_materials(async_client: AsyncClient):
    res = await async_client.get(f"{PREFIX}/portal/materials")
    assert res.status_code == 200
    data = res.json()
    assert "materials" in data
    assert "PLA" in data["materials"]
    assert "PETG" in data["materials"]
    assert data["materials"]["PLA"]["density"] > 0


@pytest.mark.asyncio
async def test_portal_analyze_model(async_client: AsyncClient):
    stl_bytes = _make_test_stl_bytes((40.0, 30.0, 20.0))
    files = {"file": ("part.stl", io.BytesIO(stl_bytes), "application/octet-stream")}
    res = await async_client.post(f"{PREFIX}/portal/analyze-model", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["filename"] == "part.stl"
    # 40 * 30 * 20 mm = 24,000 mm³ = 24.0 cm³
    assert 23.0 <= data["volume_cm3"] <= 25.0
    assert data["dimensions_mm"]["x"] >= 19.0
    assert data["fits_bed"] is True
    assert data["has_thumbnail"] is True
    assert data["thumbnail_b64"] is not None


@pytest.mark.asyncio
async def test_portal_quote_from_model_and_pdf_export(async_client: AsyncClient):
    stl_bytes = _make_test_stl_bytes((50.0, 50.0, 10.0))
    files = {"file": ("bracket.stl", io.BytesIO(stl_bytes), "application/octet-stream")}
    form_data = {
        "filament_type": "PETG",
        "infill_percent": "25",
        "layer_height": "0.20",
        "quantity": "5",
        "customer_name": "Mustermann 3D GmbH",
        "customer_address": "Industriestr. 42, 80331 München",
    }
    res = await async_client.post(
        f"{PREFIX}/portal/quote-from-model",
        files=files,
        data=form_data,
    )
    assert res.status_code == 200
    quote = res.json()
    quote_id = quote["quote_id"]
    assert quote_id
    assert quote["quantity"] == 5
    assert quote["filament_type"] == "PETG"
    assert quote["customer_name"] == "Mustermann 3D GmbH"
    assert quote["pricing"]["gross_total_eur"] > 0
    assert "analysis" in quote

    # 1. GET Quote by ID
    get_res = await async_client.get(f"{PREFIX}/portal/quote/{quote_id}")
    assert get_res.status_code == 200
    assert get_res.json()["quote_id"] == quote_id

    # 2. GET Delivery Note PDF
    dn_res = await async_client.get(f"{PREFIX}/portal/delivery-note/{quote_id}/pdf")
    assert dn_res.status_code == 200
    assert dn_res.headers["content-type"] == "application/pdf"
    assert dn_res.content.startswith(b"%PDF")

    # 3. GET Thermal Shipping Label PDF (100x150)
    label_res = await async_client.get(f"{PREFIX}/portal/shipping-label/{quote_id}/pdf?format=100x150")
    assert label_res.status_code == 200
    assert label_res.headers["content-type"] == "application/pdf"
    assert label_res.content.startswith(b"%PDF")

    # 4. GET Compact Label (62x29)
    label_small_res = await async_client.get(f"{PREFIX}/portal/shipping-label/{quote_id}/pdf?format=62x29")
    assert label_small_res.status_code == 200
    assert label_small_res.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_portal_not_found(async_client: AsyncClient):
    res = await async_client.get(f"{PREFIX}/portal/quote/nonexistent-id-999")
    assert res.status_code == 404

"""Firmendaten und Angebots-PDF über die API."""

import pytest
from httpx import AsyncClient

from backend.app.services import company_profile, quote_history

BODY = {
    "customer": "Kunde",
    "description": "Teil",
    "material": 1,
    "energy": 1,
    "labor": 1,
    "subtotal": 3,
    "markup": 0.6,
    "total": 3.6,
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")
    monkeypatch.setattr(company_profile, "COMPANY_PATH", tmp_path / "company.json")


class TestCompanyApi:
    @pytest.mark.asyncio
    async def test_roundtrip(self, async_client: AsyncClient):
        resp = await async_client.put(
            "/api/v1/quote/company", json={"name": "PrintLab", "vat_percent": 19, "number_prefix": "PL"}
        )
        assert resp.status_code == 200
        got = (await async_client.get("/api/v1/quote/company")).json()
        assert got["name"] == "PrintLab" and got["vat_percent"] == 19

    @pytest.mark.asyncio
    async def test_invalid_value_is_a_400_with_a_translated_message(self, async_client: AsyncClient):
        resp = await async_client.put(
            "/api/v1/quote/company", json={"vat_percent": 99}, headers={"Accept-Language": "en"}
        )
        assert resp.status_code == 400
        assert "between 0 and 30" in resp.json()["detail"]


class TestPdfApi:
    @pytest.mark.asyncio
    async def test_saved_quote_gets_the_company_prefix_and_a_pdf(self, async_client: AsyncClient):
        await async_client.put("/api/v1/quote/company", json={"name": "PrintLab", "number_prefix": "PL"})
        entry = (await async_client.post("/api/v1/quote/history", json=BODY)).json()
        assert entry["number"].startswith("PL-")
        resp = await async_client.get(f"/api/v1/quote/history/{entry['id']}/pdf?lang=en")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        assert f"Angebot-{entry['number']}.pdf" in resp.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_unknown_entry_is_a_404(self, async_client: AsyncClient):
        assert (await async_client.get("/api/v1/quote/history/gibtsnicht/pdf")).status_code == 404

    @pytest.mark.asyncio
    async def test_unknown_language_is_refused(self, async_client: AsyncClient):
        entry = (await async_client.post("/api/v1/quote/history", json=BODY)).json()
        assert (await async_client.get(f"/api/v1/quote/history/{entry['id']}/pdf?lang=zz")).status_code == 422


class TestLogoApi:
    @pytest.mark.asyncio
    async def test_upload_read_and_delete(self, async_client: AsyncClient):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buffer, format="PNG")
        resp = await async_client.put(
            "/api/v1/quote/company/logo", files={"file": ("logo.png", buffer.getvalue(), "image/png")}
        )
        assert resp.status_code == 200 and resp.json() == {"has_logo": True}
        assert (await async_client.get("/api/v1/quote/company")).json()["has_logo"] is True
        got = await async_client.get("/api/v1/quote/company/logo")
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert (await async_client.delete("/api/v1/quote/company/logo")).json() == {"deleted": True}
        assert (await async_client.get("/api/v1/quote/company/logo")).status_code == 404

    @pytest.mark.asyncio
    async def test_a_bad_logo_is_a_400_with_a_translated_message(self, async_client: AsyncClient):
        resp = await async_client.put(
            "/api/v1/quote/company/logo",
            files={"file": ("x.png", b"kein bild", "image/png")},
            headers={"Accept-Language": "en"},
        )
        assert resp.status_code == 400 and "could not be read" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_pdf_uses_the_logo_and_the_number_format(self, async_client: AsyncClient):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGBA", (300, 100), (10, 20, 30, 255)).save(buffer, format="PNG")
        await async_client.put("/api/v1/quote/company/logo", files={"file": ("l.png", buffer.getvalue(), "image/png")})
        await async_client.put(
            "/api/v1/quote/company", json={"number_prefix": "PL", "number_format": "{prefix}{yy}/{seq}"}
        )
        entry = (
            await async_client.post("/api/v1/quote/history", json={**BODY, "customer_address": "Weg 1\n12345 Ort"})
        ).json()
        assert entry["number"].startswith("PL") and entry["number"].endswith("/1")
        assert entry["customer_address"] == "Weg 1\n12345 Ort"
        pdf = await async_client.get(f"/api/v1/quote/history/{entry['id']}/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    @pytest.mark.asyncio
    async def test_invalid_number_format_is_a_400(self, async_client: AsyncClient):
        resp = await async_client.put(
            "/api/v1/quote/company", json={"number_format": "ohne-nummer"}, headers={"Accept-Language": "en"}
        )
        assert resp.status_code == 400 and "number format" in resp.json()["detail"].lower()

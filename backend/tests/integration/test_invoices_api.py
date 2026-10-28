"""Rechnungen und Inbetriebnahme-Checkliste über die Schnittstelle."""

import pytest
from httpx import AsyncClient

from backend.app.services import company_profile, invoices, quote_history, quote_pdf

BODY = {
    "customer": "Kunde",
    "customer_address": "Weg 1\n12345 Ort",
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
    monkeypatch.setattr(invoices, "INVOICES_PATH", tmp_path / "invoices.json")


async def quote_id(client: AsyncClient) -> str:
    return (await client.post("/api/v1/quote/history", json=BODY)).json()["id"]


class TestInvoicesApi:
    @pytest.mark.asyncio
    async def test_create_list_pay_and_pdf(self, async_client: AsyncClient):
        await async_client.put(
            "/api/v1/quote/company", json={"invoice_prefix": "RE", "payment_days": 30, "name": "PrintLab"}
        )
        qid = await quote_id(async_client)
        resp = await async_client.post(f"/api/v1/quote/history/{qid}/invoice", json={"service_date": "2026-10-20"})
        assert resp.status_code == 200, resp.text
        invoice = resp.json()
        assert invoice["number"].startswith("RE-") and invoice["service_date"] == "2026-10-20"
        listed = (await async_client.get("/api/v1/quote/invoices")).json()
        assert [i["id"] for i in listed["invoices"]] == [invoice["id"]]
        assert listed["totals"] == {"EUR": {"open": 3.6, "overdue": 0.0, "paid": 0.0}}
        paid = await async_client.post(f"/api/v1/quote/invoices/{invoice['id']}/paid", json={"paid_at": "2026-11-02"})
        assert paid.json()["status"] == "paid"
        pdf = await async_client.get(f"/api/v1/quote/invoices/{invoice['id']}/pdf?lang=en")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert f"Rechnung-{invoice['number']}.pdf" in pdf.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_a_second_invoice_for_the_same_quote_is_a_409(self, async_client: AsyncClient):
        qid = await quote_id(async_client)
        assert (await async_client.post(f"/api/v1/quote/history/{qid}/invoice")).status_code == 200
        again = await async_client.post(f"/api/v1/quote/history/{qid}/invoice", headers={"Accept-Language": "en"})
        assert again.status_code == 409 and "already an invoice" in again.json()["detail"]

    @pytest.mark.asyncio
    async def test_unknown_quote_bad_date_and_unknown_invoice(self, async_client: AsyncClient):
        assert (await async_client.post("/api/v1/quote/history/nix/invoice")).status_code == 400
        qid = await quote_id(async_client)
        bad = await async_client.post(f"/api/v1/quote/history/{qid}/invoice", json={"service_date": "gestern"})
        assert bad.status_code == 400
        assert (await async_client.post("/api/v1/quote/invoices/nix/paid")).status_code == 404
        assert (await async_client.get("/api/v1/quote/invoices/nix/pdf")).status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_reopen_rules_and_no_delete_route(self, async_client: AsyncClient):
        qid = await quote_id(async_client)
        invoice = (await async_client.post(f"/api/v1/quote/history/{qid}/invoice")).json()
        cancelled = await async_client.post(f"/api/v1/quote/invoices/{invoice['id']}/cancel", json={"reason": "Irrtum"})
        assert cancelled.json()["status"] == "cancelled"
        assert (await async_client.post(f"/api/v1/quote/invoices/{invoice['id']}/reopen")).status_code == 400
        assert (await async_client.delete(f"/api/v1/quote/invoices/{invoice['id']}")).status_code in (404, 405)
        assert (await async_client.get("/api/v1/quote/invoices?status=cancelled")).json()["invoices"][0][
            "id"
        ] == invoice["id"]

    @pytest.mark.asyncio
    async def test_status_filter_is_validated(self, async_client: AsyncClient):
        assert (await async_client.get("/api/v1/quote/invoices?status=egal")).status_code == 422


class TestCompanyInvoiceFields:
    @pytest.mark.asyncio
    async def test_payment_term_and_prefix(self, async_client: AsyncClient):
        saved = (
            await async_client.put(
                "/api/v1/quote/company",
                json={"payment_days": 21, "invoice_prefix": "R/E", "invoice_format": "{prefix}{yy}-{seq5}"},
            )
        ).json()
        assert saved["payment_days"] == 21 and saved["invoice_prefix"] == "RE"
        assert (await async_client.put("/api/v1/quote/company", json={"payment_days": 999})).status_code == 400
        assert (await async_client.put("/api/v1/quote/company", json={"invoice_format": "ohne"})).status_code == 400


class TestInvoicePdf:
    def invoice(self):
        q = quote_history.add(BODY)
        return invoices.create_from_quote(q["id"], {**company_profile.DEFAULTS, "payment_days": 14})

    def test_renders_in_both_languages_with_vat(self):
        company = {**company_profile.DEFAULTS, "name": "PrintLab", "vat_percent": 19.0, "iban": "DE00"}
        inv = self.invoice()
        for lang in ("de", "en"):
            assert quote_pdf.render(inv, company, lang, kind="invoice").startswith(b"%PDF")

    def test_invoice_pdf_differs_from_the_quote_pdf(self):
        inv = self.invoice()
        assert quote_pdf.render(inv, company_profile.DEFAULTS, "de", kind="invoice") != quote_pdf.render(
            inv, company_profile.DEFAULTS, "de"
        )

    def test_incomplete_invoice_entry_still_renders(self):
        assert quote_pdf.render(
            {"id": "x", "customer": "K", "total": 5}, company_profile.DEFAULTS, kind="invoice"
        ).startswith(b"%PDF")


class TestSetupStatusApi:
    @pytest.mark.asyncio
    async def test_returns_items_with_levels_and_counts(self, async_client: AsyncClient, monkeypatch):
        from backend.app.api.routes import system as system_routes

        monkeypatch.setattr(system_routes.settings, "base_dir", system_routes.settings.base_dir)
        data = (await async_client.get("/api/v1/system/setup-status")).json()
        ids = [i["id"] for i in data["items"]]
        assert ids == [
            "auth",
            "printer",
            "alerts",
            "external_backup",
            "guard",
            "signature",
            "storage",
            "remote",
            "https",
        ]
        assert {i["level"] for i in data["items"]} == {"required", "recommended", "optional"}
        assert data["total"] >= 1 and 0 <= data["done"] <= data["total"]
        assert data["required_open"] == sum(1 for i in data["items"] if i["level"] == "required" and i["done"] is False)

    @pytest.mark.asyncio
    async def test_a_printer_and_alerts_turn_their_items_green(
        self, async_client: AsyncClient, printer_factory, tmp_path, monkeypatch
    ):
        from backend.app.api.routes import system as system_routes
        from backend.app.services import alert_channels

        monkeypatch.setattr(system_routes.settings, "base_dir", tmp_path)
        before = {i["id"]: i["done"] for i in (await async_client.get("/api/v1/system/setup-status")).json()["items"]}
        await printer_factory()
        alert_channels.write(tmp_path, {"ntfy_url": "https://ntfy.sh/x"})
        after = {i["id"]: i["done"] for i in (await async_client.get("/api/v1/system/setup-status")).json()["items"]}
        assert before["printer"] is False and after["printer"] is True
        assert before["alerts"] is False and after["alerts"] is True

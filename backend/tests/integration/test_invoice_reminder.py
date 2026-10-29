"""Integration-Tests für Kunden-Stamm und Zahlungserinnerung."""

import json

import pytest
from httpx import AsyncClient

from backend.app.services import invoice_reminder, invoices


@pytest.fixture
def invoices_file(tmp_path, monkeypatch):
    path = tmp_path / "invoices.json"
    monkeypatch.setattr(invoices, "INVOICES_PATH", path)
    return path


def _write(path, entries: list[dict]) -> None:
    path.write_text(json.dumps(entries), encoding="utf-8")


class TestInvoiceReminder:
    @staticmethod
    def _invoice(number: str, due: str, status: str = "open") -> dict:
        return {
            "id": number.lower(),
            "number": number,
            "ts": "2026-10-05T09:00:00",
            "issued": "2026-10-05",
            "due": due,
            "status": status,
            "currency": "EUR",
            "total": 120.0,
            "customer": "Kunde",
        }

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_reminds_once_per_overdue_invoice(self, async_client: AsyncClient, invoices_file):
        sent: list[str] = []

        async def notifier(db, invoice):
            sent.append(invoice["number"])
            return True

        _write(
            invoices_file,
            [
                self._invoice("A-1", "2026-10-19"),
                self._invoice("A-2", "2026-10-19", status="paid"),  # bezahlt: ruhend
                self._invoice("A-3", "2026-10-19", status="cancelled"),  # storniert: ruhend
                self._invoice("A-4", "2099-01-01"),  # noch nicht fällig
                self._invoice("A-5", "gar-kein-datum"),  # ohne Ziel: keine Erinnerung
            ],
        )
        new = await invoice_reminder.check_reminders(None, notifier)
        assert sent == ["A-1"]
        assert new == ["A-1"]
        # zweite Runde: nichts mehr (markiert)
        assert await invoice_reminder.check_reminders(None, notifier) == []

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_failed_notification_is_retried_next_round(self, invoices_file):
        sent: list[str] = []

        async def failing(db, invoice):
            sent.append(invoice["number"])
            return False

        _write(invoices_file, [self._invoice("A-1", "2026-10-19")])
        assert await invoice_reminder.check_reminders(None, failing) == []
        assert await invoice_reminder.check_reminders(None, failing) == []  # nicht markiert → erneut versucht

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_reopen_resets_the_reminder(self, invoices_file):
        _write(invoices_file, [self._invoice("A-1", "2026-10-19")])
        sent: list[str] = []

        async def notifier(db, invoice):
            sent.append(invoice["number"])
            return True

        assert await invoice_reminder.check_reminders(None, notifier) == ["A-1"]
        # bezahlt (Status von Hand gesetzt, wie in einer späteren Runde) → wieder geöffnet: Erinnerung darf erneut kommen
        rows = json.loads(invoices_file.read_text(encoding="utf-8"))
        rows[0]["status"] = "open"
        rows[0]["reminder_sent_at"] = "2026-10-20T08:00:00"
        invoices_file.write_text(json.dumps(rows), encoding="utf-8")
        assert await invoice_reminder.check_reminders(None, notifier) == []  # markiert bleibt stumm
        invoices.reopen("a-1")
        rows = json.loads(invoices_file.read_text(encoding="utf-8"))
        assert rows[0]["reminder_sent_at"] is None
        assert await invoice_reminder.check_reminders(None, notifier) == ["A-1"]


class TestCustomersAPI:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_list_and_dedupe(self, async_client: AsyncClient):
        created = await async_client.post("/api/v1/customers/", json={"name": "Werkbank", "address": "Straße 1"})
        assert created.status_code == 200 and created.json()["name"] == "Werkbank"
        duplicate = await async_client.post("/api/v1/customers/", json={"name": "werkbank"})
        assert duplicate.status_code == 400
        listing = await async_client.get("/api/v1/customers/")
        assert listing.status_code == 200 and len(listing.json()) == 1

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_and_delete(self, async_client: AsyncClient):
        created = (await async_client.post("/api/v1/customers/", json={"name": "A"})).json()
        updated = await async_client.patch(f"/api/v1/customers/{created['id']}", json={"name": "B", "email": "b@x"})
        assert updated.status_code == 200 and updated.json()["email"] == "b@x"
        assert (await async_client.delete(f"/api/v1/customers/{created['id']}")).status_code == 200
        assert (await async_client.get("/api/v1/customers/")).json() == []

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unknown_customer_is_404(self, async_client: AsyncClient):
        assert (await async_client.patch("/api/v1/customers/999", json={"name": "X"})).status_code == 404
        assert (await async_client.delete("/api/v1/customers/999")).status_code == 404

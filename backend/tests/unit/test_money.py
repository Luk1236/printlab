"""Geldbeträge (utils/money.py) und die Summen der Rechnungen."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.services import invoices
from backend.app.utils.money import as_float, money, to_decimal


class TestMoney:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1.005, 1.01),  # kaufmännisch, nicht banker's rounding
            ("2.675", 2.68),
            (0, 0.0),
            (None, 0.0),
            ("keine Zahl", 0.0),
            (Decimal("12.344"), 12.34),
        ],
    )
    def test_rounds_half_up_to_cents(self, value, expected):
        assert money(value) == Decimal(str(expected))

    def test_cent_sums_are_exact(self):
        # 0.1 + 0.2 ergibt in float 0.30000000000000004; in Cent gerechnet bleibt es 0.30.
        total = money("0.1") + money("0.2")
        assert as_float(total) == 0.3
        assert str(money(total)) == "0.30"

    def test_negative_and_bool(self):
        assert as_float(money("-1.005")) == -1.01  # HALF_UP rundet vom Nullpunkt weg
        assert money(True) == Decimal("1.00")


class TestInvoiceTotals:
    def test_totals_sum_without_cent_drift(self, monkeypatch):
        rows = [
            {"id": "a", "status": "open", "currency": "EUR", "total": 0.1},
            {"id": "b", "status": "open", "currency": "EUR", "total": 0.2},
            {"id": "c", "status": "paid", "currency": "EUR", "total": "0.1"},
            {"id": "d", "status": "cancelled", "currency": "EUR", "total": 99.0},
        ]
        monkeypatch.setattr(invoices, "_read", lambda: rows)
        monkeypatch.setattr(invoices, "overdue", lambda today=None: [])
        assert invoices.totals() == {"EUR": {"open": 0.3, "overdue": 0, "paid": 0.1}}

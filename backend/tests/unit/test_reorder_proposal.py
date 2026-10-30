"""Tests für den Nachbestellvorschlag (Bestellmenge, Lieferant, Preis)."""

from types import SimpleNamespace

import pytest

from backend.app.services import reorder_proposal


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    from backend.app.core import config

    monkeypatch.setattr(config.settings, "base_dir", tmp_path)
    return tmp_path


def _forecast(rate=50.0, remaining=200.0, days=4, lead=7, reorder=True, brk=False):
    return SimpleNamespace(
        daily_rate_g=rate,
        remaining_g=remaining,
        days_remaining=days,
        effective_lead_time_days=lead,
        reorder_alert=reorder,
        stock_break_alert=brk,
    )


def _spool(spool_id=1, label_weight=1000.0):
    return SimpleNamespace(id=spool_id, label_weight=label_weight, color_name_is_synthesized=False)


class TestOrderQuantity:
    def test_covers_lead_time_and_target(self):
        rolls, grams = reorder_proposal.order_quantity(50, 200, 7, 14, 1000, 100)
        assert (rolls, grams) == (1, 1000.0)  # 50 * 21 - 200 = 850 g -> eine Rolle

    def test_rounds_up_to_whole_rolls(self):
        rolls, grams = reorder_proposal.order_quantity(100, 0, 7, 14, 1000, 0)
        assert rolls == 3  # 2100 g -> drei Rollen
        assert grams == 3000.0

    def test_minimum_order_and_enough_stock(self):
        assert reorder_proposal.order_quantity(1, 5000, 7, 14, 1000, 100) == (0, 0.0)
        rolls, grams = reorder_proposal.order_quantity(0.5, 0, 0, 1, 1000, 500)
        assert (rolls, grams) == (1, 1000.0)  # Mindestmenge erzwingt eine Rolle


class TestBuildProposals:
    def test_only_due_skus_and_cheapest_supplier(self):
        key = ("PLA", "Basic", "Polymaker", "Schwarz")
        meta = {
            1: {
                "key": key,
                "label_weight": 1000.0,
                "cost_per_kg": 25.0,
                "quotes": [
                    {"supplier": "Teuer", "price_per_kg": 24.0},
                    {"supplier": "Günstig", "price_per_kg": 19.5},
                ],
            }
        }
        proposals = reorder_proposal.build_proposals({key: (_forecast(), _spool())}, meta)
        assert len(proposals) == 1
        entry = proposals[0]
        assert entry["supplier"] == "Günstig"
        assert entry["price_per_kg"] == 19.5
        assert entry["rolls"] == 1
        assert entry["estimated_cost"] == 19.5
        assert entry["material"] == "PLA"
        assert entry["stock_break"] is False

    def test_not_due_is_skipped(self):
        key = ("PETG", "", "", "")
        proposals = reorder_proposal.build_proposals({key: (_forecast(reorder=False), _spool())}, {1: {"key": key}})
        assert proposals == []

    def test_missing_rate_is_skipped(self):
        key = ("ABS", "", "", "")
        proposals = reorder_proposal.build_proposals({key: (_forecast(rate=None), _spool())}, {1: {"key": key}})
        assert proposals == []

    def test_without_supplier_price_stays_empty(self):
        key = ("TPU", "", "", "")
        meta = {1: {"key": key, "label_weight": 500.0, "quotes": []}}
        entry = reorder_proposal.build_proposals({key: (_forecast(), _spool(label_weight=500.0))}, meta)[0]
        assert entry["supplier"] is None
        assert entry["estimated_cost"] is None
        assert entry["spool_size_g"] == 500.0

    def test_sorted_by_days_remaining(self):
        slow = ("PLA", "", "", "A")
        fast = ("PLA", "", "", "B")
        meta = {
            1: {"key": slow, "label_weight": 1000.0, "quotes": []},
            2: {"key": fast, "label_weight": 1000.0, "quotes": []},
        }
        proposals = reorder_proposal.build_proposals(
            {slow: (_forecast(days=9), _spool(1)), fast: (_forecast(days=1), _spool(2))}, meta
        )
        assert [p["days_remaining"] for p in proposals] == [1, 9]


class TestConfig:
    def test_defaults_and_clamping(self):
        assert reorder_proposal.read_config()["coverage_days"] == 14
        cfg = reorder_proposal.write_config({"coverage_days": 999, "min_order_grams": -5})
        assert cfg["coverage_days"] == 14
        assert cfg["min_order_grams"] == 100

    def test_roundtrip(self):
        cfg = reorder_proposal.write_config({"coverage_days": 30, "min_order_grams": 0})
        assert cfg["coverage_days"] == 30
        assert cfg["min_order_grams"] == 0

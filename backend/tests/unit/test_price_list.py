"""Unit tests for the material price list (quote calculator rates)."""

import pytest

from backend.app.services import price_list


@pytest.fixture(autouse=True)
def isolated_path(tmp_path, monkeypatch):
    path = tmp_path / "price_list.json"
    monkeypatch.setattr(price_list, "PRICE_LIST_PATH", path)
    return path


class TestRoundtrip:
    def test_empty_and_corrupt(self, isolated_path):
        assert price_list.read_list() == []
        isolated_path.write_text("nope", encoding="utf-8")
        assert price_list.read_list() == []

    def test_write_cleans_entries(self, isolated_path):
        result = price_list.write_list([
            {"material": "PLA", "rate_per_kg": 22},
            {"material": "TPU", "rate_per_kg": 45.5},
            {"material": "", "rate_per_kg": 5},      # dropped
            {"material": "Bad", "rate_per_kg": -1},  # dropped
            "not a dict",                             # dropped
            {"material": "PETG", "rate_per_kg": "30"},
        ])
        assert result["entries"] == [
            {"material": "PLA", "rate_per_kg": 22.0},
            {"material": "TPU", "rate_per_kg": 45.5},
            {"material": "PETG", "rate_per_kg": 30.0},
        ]
        assert price_list.read_list() == result["entries"]


class TestRateFor:
    def test_case_insensitive_hit(self, isolated_path):
        price_list.write_list([{"material": "TPU", "rate_per_kg": 45}])
        rate, matched = price_list.rate_for(" tpu ", 22.0)
        assert rate == 45.0
        assert matched == "TPU"

    def test_miss_falls_back_to_default(self, isolated_path):
        rate, matched = price_list.rate_for("ASA", 22.0)
        assert rate == 22.0
        assert matched is None

    def test_empty_material_uses_default(self, isolated_path):
        price_list.write_list([{"material": "PLA", "rate_per_kg": 18}])
        assert price_list.rate_for(None, 22.0) == (22.0, None)

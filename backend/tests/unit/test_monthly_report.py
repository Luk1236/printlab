"""Monats-Report: Grenzen der Aggregation (Datum, Status) und der PDF-Schreiber.

Die datenbanknahen Teile (SQL-Aggregation, JSON-Ablagen) laufen in den
Integration-Tests; hier nur das, was ohne Session prüfbar ist.
"""

from __future__ import annotations

import re

import pytest

from backend.app.services import monthly_report, monthly_report_pdf


class TestBoundaries:
    def test_month_bounds_respect_leap_years(self):
        start, end = monthly_report._month_bounds(2026, 2)
        assert (start.isoformat(), end.isoformat()) == ("2026-02-01", "2026-02-28")
        start, end = monthly_report._month_bounds(2028, 2)
        assert end.isoformat() == "2028-02-29"
        start, end = monthly_report._month_bounds(2026, 12)
        assert (start.isoformat(), end.isoformat()) == ("2026-12-01", "2026-12-31")

    def test_in_month_day_accepts_dates_and_timestamps(self):
        start, end = monthly_report._month_bounds(2026, 10)
        assert monthly_report._in_month_day("2026-10-15", start, end)
        assert monthly_report._in_month_day("2026-10-15T22:30:00", start, end)
        assert not monthly_report._in_month_day("2026-11-01", start, end)
        assert not monthly_report._in_month_day("2026-09-30T23:59:00", start, end)
        assert not monthly_report._in_month_day(None, start, end)
        assert not monthly_report._in_month_day("kein-datum", start, end)

    def test_empty_money_shape_and_summing(self):
        bucket = monthly_report._empty_money()
        monthly_report._add(bucket, {"status": "paid", "total": 120.0}, "total")
        monthly_report._add(bucket, {"status": "open", "total": "30.5"}, "total")
        monthly_report._add(bucket, {"status": "komisch", "total": 1.0}, "total")
        assert bucket == {
            "count": 3,
            "open": 30.5,
            "paid": 120.0,
            "cancelled": 0.0,
            "total": 151.5,
            "overdue_count": 0,
            "overdue": 0.0,
        }


def _full_report() -> dict:
    return {
        "year": 2026,
        "month": 10,
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "invoices": {
            "EUR": {
                "count": 2,
                "open": 10.0,
                "paid": 220.0,
                "cancelled": 0.0,
                "total": 230.0,
                "overdue_count": 1,
                "overdue": 10.0,
            }
        },
        "quotes": {"EUR": 333.0},
        "profit": {
            "quotes": 1,
            "estimated_quotes": 1,
            "per_currency": {"EUR": {"revenue": 333.0, "actual_cost": 210.5, "profit": 122.5}},
        },
        "production": {
            "prints": 7,
            "failed": 1,
            "minutes": 300,
            "grams": 450,
            "material_cost": 9.9,
            "energy_cost": 0.5,
            "by_filament_type": [{"type": "PLA", "grams": 450}],
            "by_printer": [{"name": "P2S", "prints": 7, "minutes": 300}],
        },
    }


class TestPdf:
    def test_renders_a_valid_pdf_for_empty_data(self):
        report = {
            "year": 2026,
            "month": 10,
            "invoices": {},
            "quotes": {},
            "profit": {"quotes": 0, "estimated_quotes": 0, "per_currency": {}},
            "production": {
                "prints": 0,
                "failed": 0,
                "minutes": 0,
                "grams": 0,
                "material_cost": 0.0,
                "energy_cost": 0.0,
                "by_filament_type": [],
                "by_printer": [],
            },
        }
        pdf = monthly_report_pdf.render(report, {"name": "Werkstatt"}, lang="de")
        assert pdf.startswith(b"%PDF") and b"MONATSREPORT" in pdf

    def test_renders_full_report_with_money_and_profit(self):
        raw = monthly_report_pdf.render(_full_report(), {"name": "Werkstatt", "tax_id": "DE123"}, lang="de")
        assert raw.startswith(b"%PDF")
        # ReportLab schreibt Umlaute als Oktal-Escape (\334 = Ü) — decodieren, dann prüfen.
        text = re.sub(rb"\\(\d{3})(?!\d)", lambda m: bytes([int(m.group(1), 8)]), raw).decode("latin-1")
        assert "Gewinn" in text and "122,50 EUR" in text
        assert "P2S" in text and "Überfällig" in text
        assert "5.0 h" in text  # 300 Minuten

    def test_month_label_is_localized(self):
        text = monthly_report_pdf.render(
            {
                "year": 2026,
                "month": 10,
                "production": {
                    "prints": 1,
                    "minutes": 0,
                    "grams": 0,
                    "material_cost": 0.0,
                    "energy_cost": 0.0,
                    "by_filament_type": [],
                    "by_printer": [],
                },
                "invoices": {
                    "EUR": {
                        "count": 1,
                        "open": 0.0,
                        "paid": 0.0,
                        "cancelled": 0.0,
                        "total": 0.0,
                        "overdue_count": 0,
                        "overdue": 0.0,
                    }
                },
                "quotes": {},
                "profit": {"quotes": 0, "estimated_quotes": 0, "per_currency": {}},
            },
            {"name": "W"},
            lang="en",
        ).decode("latin-1")
        assert "October 2026" in text

    @pytest.mark.parametrize("lang", ["de", "en"])
    def test_lang_falls_back_to_german(self, lang):
        pdf = monthly_report_pdf.render({"year": 2026, "month": 1, "production": {"prints": 1}}, {"name": "W"})
        assert pdf.startswith(b"%PDF")

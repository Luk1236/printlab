"""Unit-Tests für Live Customer Tracking & Volume Tier Pricing (Phase 15)."""

import pytest
from httpx import AsyncClient

from backend.app.services.customer_tracking import (
    VOLUME_TIERS,
    calculate_order_total,
    calculate_volume_tier_pricing,
    generate_tracking_token,
    get_tier_for_quantity,
    resolve_mock_or_simulated_tracking,
)


def test_volume_tier_selection():
    """Prüft die korrekte Zuordnung von Stückzahlen zu Mengenstaffeln."""
    t1 = get_tier_for_quantity(1)
    assert t1["discount_percent"] == 0.0

    t5 = get_tier_for_quantity(5)
    assert t5["discount_percent"] == 0.0

    t10 = get_tier_for_quantity(10)
    assert t10["discount_percent"] == 10.0

    t50 = get_tier_for_quantity(50)
    assert t50["discount_percent"] == 18.0

    t100 = get_tier_for_quantity(100)
    assert t100["discount_percent"] == 25.0

    t500 = get_tier_for_quantity(500)
    assert t500["discount_percent"] == 32.0


def test_volume_tier_pricing_calculation():
    """Prüft die Preisberechnung und Rabatte über Mengenstaffeln."""
    # Basispreis: 10,00 € = 1000 Cent
    base_price = 1000

    # 1 Stück -> 10,00 €
    res_1 = calculate_volume_tier_pricing(base_price, 1)
    assert res_1["unit_price_cents"] == 1000
    assert res_1["total_parts_cents"] == 1000
    assert res_1["savings_cents"] == 0

    # 10 Stück -> 10% Rabatt = 9,00 € pro Stück, Summe 90,00 €
    res_10 = calculate_volume_tier_pricing(base_price, 10)
    assert res_10["unit_price_cents"] == 900
    assert res_10["total_parts_cents"] == 9000
    assert res_10["savings_cents"] == 1000

    # 100 Stück -> 25% Rabatt = 7,50 € pro Stück, Summe 750,00 €
    res_100 = calculate_volume_tier_pricing(base_price, 100)
    assert res_100["unit_price_cents"] == 750
    assert res_100["total_parts_cents"] == 75000
    assert res_100["savings_cents"] == 25000


def test_order_total_with_post_processing_and_express():
    """Prüft Nachbearbeitungsaufschläge und Expressfertigung."""
    base_price = 1000  # 10.00 €
    qty = 20  # Tier 10+: 10% Rabatt -> 9.00 € = 180.00 € Teilepreis

    res = calculate_order_total(
        base_unit_price_cents=base_price,
        quantity=qty,
        selected_options=["support_removal", "express_24h"],
    )

    assert res["is_express"] is True
    assert res["pricing_tier"]["unit_price_cents"] == 900
    assert res["pricing_tier"]["total_parts_cents"] == 18000

    # Support removal: 20 * 150 = 3000 Cent (30.00 €)
    # Express 24h: 2500 Cent Grundgebühr + 20% auf 18000 = 2500 + 3600 = 6100 Cent
    # Options Total = 3000 + 6100 = 9100 Cent
    assert res["options_total_cents"] == 9100
    # Net = 18000 + 9100 = 27100 Cent (271.00 €)
    assert res["net_total_cents"] == 27100
    # Gross = Net + 19%
    assert res["gross_total_cents"] == int(round(27100 * 1.19))


def test_tracking_token_generation_and_resolution():
    """Prüft die kryptografische Generierung und Auflösung des Tracking-Tokens."""
    tok1 = generate_tracking_token("ORD-2026-001")
    tok2 = generate_tracking_token("ORD-2026-001")
    tok3 = generate_tracking_token("ORD-2026-002")

    assert tok1.startswith("tr_")
    assert tok1 == tok2
    assert tok1 != tok3

    data = resolve_mock_or_simulated_tracking(tok1)
    assert data["token"] == tok1
    assert data["order_status"] == "PRINTING"
    assert "current_stage" in data
    assert len(data["stages"]) == 6


@pytest.mark.asyncio
async def test_tracking_api_endpoints(async_client: AsyncClient):
    """Testet die API-Routen unter /api/v1/portal/."""
    # 1. Options Catalog
    cat_resp = await async_client.get("/api/v1/portal/pricing/options")
    assert cat_resp.status_code == 200
    assert "volume_tiers" in cat_resp.json()
    assert "post_processing_options" in cat_resp.json()

    # 2. Tier Calculation
    calc_resp = await async_client.post(
        "/api/v1/portal/pricing/calculate-tiers",
        json={
            "base_unit_price_cents": 2000,
            "quantity": 50,
            "selected_options": ["support_removal"],
        },
    )
    assert calc_resp.status_code == 200
    data = calc_resp.json()
    assert data["pricing_tier"]["discount_percent"] == 18.0
    assert data["net_total_cents"] > 0

    # 3. Token Generation
    tok_resp = await async_client.post(
        "/api/v1/portal/tracking/token",
        json={"order_id": "AUFTRAG-8821"},
    )
    assert tok_resp.status_code == 200
    token = tok_resp.json()["tracking_token"]

    # 4. Status Tracking
    track_resp = await async_client.get(f"/api/v1/portal/tracking/{token}")
    assert track_resp.status_code == 200
    tdata = track_resp.json()
    assert tdata["token"] == token
    assert tdata["order_status"] == "PRINTING"

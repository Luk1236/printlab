"""Tests für das Kunden-Selfservice-Portal & Sofortkalkulation."""

from backend.app.services import customer_portal


class TestCustomerPortal:
    def test_calculate_instant_quote_single(self):
        quote = customer_portal.calculate_instant_quote(
            volume_cm3=30.0,
            filament_type="PLA",
            infill_percent=20,
            quantity=1,
        )
        assert quote["filament_type"] == "PLA"
        assert quote["quantity"] == 1
        assert quote["total_weight_grams"] > 0
        pricing = quote["pricing"]
        assert pricing["material_cost_eur"] > 0
        assert pricing["machine_cost_eur"] > 0
        assert pricing["gross_total_eur"] > pricing["net_total_eur"]
        assert pricing["currency"] == "EUR"

    def test_calculate_instant_quote_quantity_discount(self):
        quote_single = customer_portal.calculate_instant_quote(volume_cm3=50.0, quantity=1)
        quote_bulk = customer_portal.calculate_instant_quote(volume_cm3=50.0, quantity=10)

        assert quote_single["pricing"]["discount_percent"] == 0.0
        assert quote_bulk["pricing"]["discount_percent"] == 10.0
        assert quote_bulk["pricing"]["discount_amount_eur"] > 0

    def test_create_stripe_checkout_session(self):
        quote = customer_portal.calculate_instant_quote(volume_cm3=40.0)
        session = customer_portal.create_stripe_checkout_session(
            quote,
            customer_email="kunde@example.org",
        )
        assert session["session_id"].startswith("cs_test_")
        assert session["customer_email"] == "kunde@example.org"
        assert session["amount_cents"] > 0
        assert "checkout.stripe.com" in session["checkout_url"]

    def test_confirm_payment(self):
        quote = customer_portal.calculate_instant_quote(volume_cm3=25.0)
        res = customer_portal.confirm_payment("cs_test_12345", quote)
        assert res["status"] == "PAID"
        assert res["action"] == "QUEUED_FOR_PRINT"

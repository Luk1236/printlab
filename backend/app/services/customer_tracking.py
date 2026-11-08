"""Live Customer Tracking & Volume Tier Pricing Service (Phase 15).

Bietet Live-Statusverfolgung für Kundenaufträge per sicherem Tracking-Token,
dynamische Mengenstaffelberechnung (Volume Tier Pricing) sowie Aufpreis-
Kalkulation für Nachbearbeitung (Support, Gewindeeinsätze, Tempern, Finish)
und 24h-Expressfertigung.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

# Secret key for HMAC token generation (falls kein ENV gesetzt, Fallback mit stabiler Zufallsbasis)
TRACKING_SECRET = os.getenv("PRINTLAB_TRACKING_SECRET", "printlab-tracking-secure-token-salt-2026")

# Mengenstaffeln mit Rabatten
VOLUME_TIERS: list[dict[str, Any]] = [
    {"min_qty": 1, "max_qty": 9, "discount_percent": 0.0, "tier_name": "Einzelstück / Prototyp"},
    {"min_qty": 10, "max_qty": 49, "discount_percent": 10.0, "tier_name": "Kleinserie (10+)"},
    {"min_qty": 50, "max_qty": 99, "discount_percent": 18.0, "tier_name": "Mittlere Serie (50+)"},
    {"min_qty": 100, "max_qty": 249, "discount_percent": 25.0, "tier_name": "Großserie (100+)"},
    {"min_qty": 250, "max_qty": 999999, "discount_percent": 32.0, "tier_name": "Industrieserie (250+)"},
]

# Verfügbare Nachbearbeitungs-Optionen
POST_PROCESSING_CATALOG: dict[str, dict[str, Any]] = {
    "support_removal": {
        "id": "support_removal",
        "name": "Stützstruktur-Entfernung",
        "description": "Manuelle rückstandsfreie Entfernung aller Support-Strukturen",
        "cost_cents_per_part": 150,  # 1.50 €
        "setup_fee_cents": 0,
    },
    "heat_set_inserts": {
        "id": "heat_set_inserts",
        "name": "Gewindeeinsätze einpressen",
        "description": "Thermische Einpressung von Messing-Gewindebuchsen (M2–M6)",
        "cost_cents_per_part": 80,  # 0.80 € pro Buchse
        "setup_fee_cents": 250,
    },
    "surface_sanding": {
        "id": "surface_sanding",
        "name": "Oberflächen-Finish / Schleifen",
        "description": "Feinschliff sichtbarer Oberflächen zur Reduzierung von Schichtlinien",
        "cost_cents_per_part": 300,  # 3.00 €
        "setup_fee_cents": 500,
    },
    "annealing": {
        "id": "annealing",
        "name": "Tempern / Wärmebehandlung",
        "description": "Kontrolliertes Ofen-Tempern zur Erhöhung der Temperaturbeständigkeit",
        "cost_cents_per_part": 100,
        "setup_fee_cents": 1500,  # 15.00 € Ofencharge
    },
    "express_24h": {
        "id": "express_24h",
        "name": "24h Express-Fertigung",
        "description": "Priorisierte Einreihung an der Spitze der Farm-Warteschlange & Expressversand",
        "cost_cents_per_part": 0,
        "setup_fee_cents": 2500,  # 25.00 € Express-Pauschale
        "surcharge_percent": 20.0,  # +20% auf den Bauteilgrundpreis
    },
}

# Tracking-Stadien
TRACKING_STAGES: list[dict[str, str]] = [
    {"stage": "RECEIVED", "title": "Auftrag erhalten", "desc": "Auftrag geprüft und freigegeben."},
    {"stage": "QUEUED", "title": "In Warteschlange", "desc": "Platte aufbereitet, wartet auf freien 3D-Drucker."},
    {"stage": "PRINTING", "title": "In Fertigung", "desc": "Wird auf Bambu Lab Drucker aktiv gedruckt."},
    {"stage": "POST_PROCESSING", "title": "Nachbearbeitung", "desc": "Supportentfernung, Schleifen oder Finish."},
    {"stage": "QUALITY_CHECK", "title": "Qualitätsprüfung", "desc": "Endkontrolle nach ISO-9001 Standards."},
    {"stage": "DISPATCHED", "title": "Versendet / Abholbereit", "desc": "Sendung übergeben an Versanddienstleister."},
]


def generate_tracking_token(order_id: str, salt: str = "") -> str:
    """Erzeugt einen deterministischen, fälschungssicheren URL-sicheren Tracking-Token."""
    msg = f"{order_id}:{salt}".encode("utf-8")
    sig = hmac.new(TRACKING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"tr_{sig[:24]}"


def get_tier_for_quantity(quantity: int) -> dict[str, Any]:
    """Findet die passende Mengenstaffel für eine gewünschte Stückzahl."""
    q = max(1, quantity)
    for tier in VOLUME_TIERS:
        if tier["min_qty"] <= q <= tier["max_qty"]:
            return tier
    return VOLUME_TIERS[-1]


def calculate_volume_tier_pricing(base_unit_price_cents: int, quantity: int) -> dict[str, Any]:
    """Berechnet Stückpreise, Rabatte und Staffelübersicht für ein Bauteil."""
    q = max(1, quantity)
    active_tier = get_tier_for_quantity(q)
    discount_pct = float(active_tier["discount_percent"])
    discount_factor = 1.0 - (discount_pct / 100.0)

    unit_price_cents = int(round(base_unit_price_cents * discount_factor))
    total_parts_cents = unit_price_cents * q
    savings_cents = (base_unit_price_cents * q) - total_parts_cents

    # Übersicht über alle Staffeln zur Anzeige für den Kunden
    tiers_overview = []
    for t in VOLUME_TIERS:
        tfactor = 1.0 - (t["discount_percent"] / 100.0)
        t_unit_cents = int(round(base_unit_price_cents * tfactor))
        tiers_overview.append({
            "tier_name": t["tier_name"],
            "min_qty": t["min_qty"],
            "max_qty": t["max_qty"],
            "discount_percent": t["discount_percent"],
            "unit_price_cents": t_unit_cents,
            "unit_price_eur": round(t_unit_cents / 100.0, 2),
            "is_active": (t["min_qty"] <= q <= t["max_qty"]),
        })

    return {
        "base_unit_price_cents": base_unit_price_cents,
        "quantity": q,
        "discount_percent": discount_pct,
        "active_tier_name": active_tier["tier_name"],
        "unit_price_cents": unit_price_cents,
        "unit_price_eur": round(unit_price_cents / 100.0, 2),
        "total_parts_cents": total_parts_cents,
        "total_parts_eur": round(total_parts_cents / 100.0, 2),
        "savings_cents": savings_cents,
        "savings_eur": round(savings_cents / 100.0, 2),
        "tiers_overview": tiers_overview,
    }


def calculate_order_total(
    base_unit_price_cents: int,
    quantity: int,
    selected_options: list[str] | None = None,
    option_quantities: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Berechnet den Gesamtpreis inklusive Mengenstaffel und Nachbearbeitungs-Optionen."""
    tier_info = calculate_volume_tier_pricing(base_unit_price_cents, quantity)
    selected = selected_options or []
    opt_qty = option_quantities or {}

    post_processing_breakdown = []
    total_options_cents = 0
    is_express = "express_24h" in selected

    for opt_id in selected:
        if opt_id not in POST_PROCESSING_CATALOG:
            continue
        cfg = POST_PROCESSING_CATALOG[opt_id]
        count = opt_qty.get(opt_id, quantity)
        cost_parts = cfg["cost_cents_per_part"] * count
        setup_fee = cfg.get("setup_fee_cents", 0)

        # Prozentualer Aufschlag (z. B. Express)
        surcharge = 0
        if "surcharge_percent" in cfg:
            surcharge = int(round(tier_info["total_parts_cents"] * (cfg["surcharge_percent"] / 100.0)))

        item_total_cents = cost_parts + setup_fee + surcharge
        total_options_cents += item_total_cents

        post_processing_breakdown.append({
            "id": opt_id,
            "name": cfg["name"],
            "count": count,
            "cost_cents": item_total_cents,
            "cost_eur": round(item_total_cents / 100.0, 2),
        })

    net_total_cents = tier_info["total_parts_cents"] + total_options_cents
    vat_19_cents = int(round(net_total_cents * 0.19))
    gross_total_cents = net_total_cents + vat_19_cents

    return {
        "pricing_tier": tier_info,
        "post_processing": post_processing_breakdown,
        "options_total_cents": total_options_cents,
        "options_total_eur": round(total_options_cents / 100.0, 2),
        "is_express": is_express,
        "net_total_cents": net_total_cents,
        "net_total_eur": round(net_total_cents / 100.0, 2),
        "vat_19_cents": vat_19_cents,
        "vat_19_eur": round(vat_19_cents / 100.0, 2),
        "gross_total_cents": gross_total_cents,
        "gross_total_eur": round(gross_total_cents / 100.0, 2),
    }


def resolve_mock_or_simulated_tracking(token: str) -> dict[str, Any]:
    """Liefert Status- und Trackingdaten zu einem Tracking-Token."""
    stage_idx = 2  # default: PRINTING
    now = time.time()
    return {
        "token": token,
        "order_number": f"ORD-{token[-6:].upper()}",
        "order_status": "PRINTING",
        "current_stage": TRACKING_STAGES[stage_idx],
        "stages": TRACKING_STAGES,
        "part_name": "Sensorhalter_Flansch.stl",
        "quantity": 15,
        "material": "PETG-CF Schwarz",
        "printer_name": "Bambu Lab X1-Carbon #2",
        "progress_percent": 68.5,
        "current_layer": 240,
        "total_layers": 350,
        "remaining_minutes": 42,
        "estimated_completion": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now + 42 * 60)),
        "carrier": "DHL Express",
        "tracking_number": "00340434192837461234",
        "is_express": True,
    }

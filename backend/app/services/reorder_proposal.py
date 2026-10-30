"""Nachbestellvorschlag: was jetzt bestellt werden sollte, wie viel und wo.

Die Prognose selbst gibt es schon (``services/stock_forecast.py``, Panel und
Meldungen im Warteschlangen-Lauf). Was fehlte, ist der Schritt danach: aus
„Vorrat reicht noch 6 Tage“ wird „2 Rollen bestellen, günstigster Lieferant X,
voraussichtlich Y €“. Dieses Modul rechnet das aus derselben Prognose:

* Bestellmenge = Verbrauch × (Lieferzeit + ``coverage_days``) − vorhandener
  Vorrat, aufgerundet auf ganze Rollen; mindestens eine Rolle und mindestens
  ``min_order_grams``.
* Lieferant und Preis stammen aus den gepflegten Lieferanten-Verknüpfungen der
  Rollen (günstigster Angebotspreis je kg). Ohne Verknüpfung bleibt beides leer.
* Im Spoolman-Betrieb kommen die Rollen aus Spoolman; Lieferantenpreise liegen
  dort nicht vor, die Kosten bleiben deshalb leer.

Vorgeschlagen wird nur, was die Prognose als „Nachbestellpunkt erreicht“ oder
„Vorrat bricht“ führt. Das ist ein Vorschlag, keine Bestellung — bestellt wird
von Hand beim Lieferanten.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from backend.app.utils.money import money

DEFAULTS: dict[str, Any] = {
    "coverage_days": 14,  # nach Ankunft der Lieferung soll der Vorrat so lange reichen
    "min_order_grams": 100,
    "history_limit": 5000,
}
MAX_COVERAGE_DAYS = 180
MIN_COVERAGE_DAYS = 1
MAX_MIN_ORDER_GRAMS = 100_000


def read_config() -> dict[str, Any]:
    import json

    from backend.app.core.config import settings

    path = settings.base_dir / "reorder_proposal.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    coverage = data.get("coverage_days", DEFAULTS["coverage_days"])
    minimum = data.get("min_order_grams", DEFAULTS["min_order_grams"])
    try:
        coverage = int(coverage)
    except (TypeError, ValueError):
        coverage = DEFAULTS["coverage_days"]
    try:
        minimum = int(minimum)
    except (TypeError, ValueError):
        minimum = DEFAULTS["min_order_grams"]
    return {
        "coverage_days": coverage if MIN_COVERAGE_DAYS <= coverage <= MAX_COVERAGE_DAYS else DEFAULTS["coverage_days"],
        "min_order_grams": minimum if 0 <= minimum <= MAX_MIN_ORDER_GRAMS else DEFAULTS["min_order_grams"],
        "history_limit": DEFAULTS["history_limit"],
    }


def write_config(update: dict[str, Any]) -> dict[str, Any]:
    import json

    from backend.app.core.config import settings

    path = settings.base_dir / "reorder_proposal.json"
    merged = {**read_config(), **{k: v for k, v in (update or {}).items() if k in ("coverage_days", "min_order_grams")}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return read_config()


def order_quantity(
    daily_rate_g: float,
    remaining_g: float,
    lead_time_days: int,
    coverage_days: int,
    spool_size_g: float,
    min_order_grams: int,
) -> tuple[int, float]:
    """Ganze Rollen, die Lieferzeit und Zielbestand abdecken. Rückgabe: (Rollen, Gramm)."""
    spool = max(100.0, float(spool_size_g or 1000))
    needed = float(daily_rate_g) * (max(0, lead_time_days) + coverage_days) - float(remaining_g)
    if needed <= 0:
        # Der Vorrat deckt Lieferzeit und Zielbestand — nichts zu bestellen.
        return 0, 0.0
    needed = max(needed, float(min_order_grams or 0))
    rolls = max(1, math.ceil(needed / spool))
    return rolls, float(rolls) * spool


def _spool_size(meta: Mapping[int, dict[str, Any]], spool_ids: list[int], fallback: float) -> float:
    sizes = [float(meta.get(sid, {}).get("label_weight") or 0) for sid in spool_ids]
    sizes = [size for size in sizes if size > 0]
    return sum(sizes) / len(sizes) if sizes else fallback


def _cheapest_price(meta: Mapping[int, dict[str, Any]], spool_ids: list[int]) -> tuple[float | None, str | None]:
    best: tuple[float, str] | None = None
    fallback: tuple[float, str] | None = None
    for spool_id in spool_ids:
        info = meta.get(spool_id, {})
        for quote in info.get("quotes") or []:
            price = quote.get("price_per_kg")
            supplier = quote.get("supplier")
            if not price or not supplier:
                continue
            if best is None or float(price) < best[0]:
                best = (float(price), str(supplier))
        cost = info.get("cost_per_kg")
        if cost and (fallback is None or float(cost) < fallback[0]):
            fallback = (float(cost), "eigene Kostenbasis")
    chosen = best or fallback
    return (chosen[0], chosen[1]) if chosen else (None, None)


def build_proposals(
    forecasts: Mapping[Any, tuple[Any, Any]],
    meta: Mapping[int, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Aus den Prognosen die Bestellvorschläge ableiten (nur fällige SKUs).

    ``forecasts`` ist das Ergebnis von ``stock_forecast.forecast_all``:
    SKU-Schlüssel → (Prognose, eine Rolle der Gruppe). ``meta`` hält je Rollen-ID
    Rollengröße, Kostenbasis und Lieferantenpreise.
    """
    cfg = config or read_config()
    proposals: list[dict[str, Any]] = []
    for key, (forecast, spool) in forecasts.items():
        if not (forecast.reorder_alert or forecast.stock_break_alert):
            continue
        rate = forecast.daily_rate_g
        if rate is None or rate <= 0:
            continue
        # Alle Rollen derselben Gruppe zählen für Größe und Preis, nicht nur die
        # eine Rolle, die die Prognose zum Benennen mitgibt.
        spool_ids = [sid for sid, info in meta.items() if info.get("key") == key] or [spool.id]
        size = _spool_size(meta, spool_ids, float(spool.label_weight or 1000))
        rolls, grams = order_quantity(
            rate,
            forecast.remaining_g,
            forecast.effective_lead_time_days,
            cfg["coverage_days"],
            size,
            cfg["min_order_grams"],
        )
        if rolls == 0:
            continue
        price_per_kg, supplier = _cheapest_price(meta, spool_ids)
        estimated = money(Decimal(str(grams)) / 1000 * Decimal(str(price_per_kg))) if price_per_kg else None
        material, subtype, brand, color = key
        proposals.append(
            {
                "material": material,
                "subtype": subtype or None,
                "brand": brand or None,
                "color_name": None if spool.color_name_is_synthesized else (color or None),
                "remaining_g": round(float(forecast.remaining_g), 1),
                "daily_rate_g": round(float(rate), 1),
                "days_remaining": forecast.days_remaining,
                "lead_time_days": forecast.effective_lead_time_days,
                "coverage_days": cfg["coverage_days"],
                "stock_break": bool(forecast.stock_break_alert),
                "rolls": rolls,
                "grams": round(grams, 1),
                "spool_size_g": round(size, 1),
                "supplier": supplier,
                "price_per_kg": price_per_kg,
                "estimated_cost": float(estimated) if estimated is not None else None,
                "reason": (
                    f"Vorrat reicht noch {forecast.days_remaining} Tage — Lieferzeit {forecast.effective_lead_time_days} Tage"
                    if forecast.days_remaining is not None
                    else "Nachbestellpunkt erreicht"
                ),
            }
        )
    proposals.sort(
        key=lambda p: (p["days_remaining"] is None, p["days_remaining"] if p["days_remaining"] is not None else 0)
    )
    return proposals


async def _load_internal(db) -> tuple[list[Any], dict[int, dict[str, Any]]]:
    """Rollen und Zusatzangaben (Kosten, Lieferantenpreise) aus der eigenen Verwaltung."""
    from sqlalchemy import select

    from backend.app.models.spool import Spool
    from backend.app.models.supplier import SpoolSupplier, Supplier
    from backend.app.services import stock_forecast

    spools = (await db.execute(select(Spool).where(Spool.archived_at.is_(None)))).scalars().all()
    meta: dict[int, dict[str, Any]] = {
        spool.id: {
            "label_weight": float(spool.label_weight or 0),
            "cost_per_kg": float(spool.cost_per_kg) if spool.cost_per_kg else None,
            "quotes": [],
            "key": stock_forecast.sku_key(spool.material, spool.subtype, spool.brand, spool.color_name),
        }
        for spool in spools
    }
    if meta:
        rows = (
            await db.execute(
                select(SpoolSupplier.spool_id, Supplier.name, SpoolSupplier.quoted_price_per_kg).join(
                    Supplier, Supplier.id == SpoolSupplier.supplier_id
                )
            )
        ).all()
        for spool_id, supplier_name, price in rows:
            if spool_id in meta and price:
                meta[spool_id]["quotes"].append({"supplier": supplier_name, "price_per_kg": float(price)})

    forecast_spools = [
        stock_forecast.StockSpool(
            id=spool.id,
            material=spool.material,
            subtype=spool.subtype,
            brand=spool.brand,
            color_name=spool.color_name,
            label_weight=float(spool.label_weight or 0),
            weight_used=float(spool.weight_used or 0),
            weight_used_baseline=float(spool.weight_used_baseline or 0),
            created_at=spool.created_at,
        )
        for spool in spools
    ]
    return forecast_spools, meta


async def _load_spoolman() -> tuple[list[Any], dict[int, dict[str, Any]]] | None:
    """Spoolman-Rollen; None, wenn Spoolman nicht erreichbar ist."""
    from datetime import datetime as _datetime

    from backend.app.api.routes._spoolman_helpers import _map_spoolman_spool
    from backend.app.services import stock_forecast
    from backend.app.services.spoolman import SpoolmanUnavailableError, get_spoolman_client

    client = await get_spoolman_client()
    if client is None:
        return None
    try:
        raw_spools = await client.get_all_spools()
    except SpoolmanUnavailableError:
        return None
    spools: list[Any] = []
    meta: dict[int, dict[str, Any]] = {}
    for raw in raw_spools:
        try:
            mapped = _map_spoolman_spool(raw)
        except ValueError:
            continue
        created_at = None
        if mapped.get("created_at"):
            try:
                created_at = _datetime.fromisoformat(str(mapped["created_at"]).replace("Z", "+00:00"))
            except ValueError:
                created_at = None
        spools.append(
            stock_forecast.StockSpool(
                id=mapped["id"],
                material=mapped["material"],
                subtype=mapped.get("subtype"),
                brand=mapped.get("brand"),
                color_name=mapped.get("color_name"),
                label_weight=float(mapped.get("label_weight") or 0),
                weight_used=float(mapped.get("weight_used") or 0),
                weight_used_baseline=float(mapped.get("weight_used_baseline") or 0),
                created_at=created_at,
                color_name_is_synthesized=bool(mapped.get("color_name_is_synthesized")),
            )
        )
        meta[mapped["id"]] = {
            "label_weight": float(mapped.get("label_weight") or 0),
            "quotes": [],
            "key": stock_forecast.sku_key(
                mapped["material"], mapped.get("subtype"), mapped.get("brand"), mapped.get("color_name")
            ),
        }
    return spools, meta


async def _usage_history(db, limit: int) -> dict[int, list[Any]]:
    from sqlalchemy import select

    from backend.app.models.spool_usage_history import SpoolUsageHistory
    from backend.app.services import stock_forecast

    rows = (
        await db.execute(
            select(SpoolUsageHistory.spool_id, SpoolUsageHistory.created_at, SpoolUsageHistory.weight_used)
            .order_by(SpoolUsageHistory.created_at.desc())
            .limit(limit)
        )
    ).all()
    history: dict[int, list[Any]] = {}
    for spool_id, created_at, weight_used in rows:
        if created_at is None:
            continue
        history.setdefault(spool_id, []).append(stock_forecast.UsageRecord(created_at, float(weight_used or 0)))
    return history


async def generate(db) -> dict[str, Any]:
    """Die vollständige Vorschlagsliste für die aktuelle Betriebsart."""
    from sqlalchemy import select

    from backend.app.api.routes.settings import get_setting
    from backend.app.models.filament_sku_settings import FilamentSkuSettings
    from backend.app.services import stock_forecast
    from backend.app.services.inventory_mode import spoolman_owns_assignments
    from backend.app.utils.local_time import utcnow_naive

    cfg = read_config()
    spoolman = await spoolman_owns_assignments(db)
    if spoolman:
        loaded = await _load_spoolman()
        if loaded is None:
            raise RuntimeError("Spoolman ist nicht erreichbar — ohne Bestand kein Vorschlag.")
        spools, meta = loaded
        history: dict[int, list[Any]] = {}
    else:
        spools, meta = await _load_internal(db)
        history = await _usage_history(db, cfg["history_limit"])

    try:
        global_lead = max(0, int(await get_setting(db, "forecast_global_lead_time_days") or 0))
    except (TypeError, ValueError):
        global_lead = 0
    sku_rows = (await db.execute(select(FilamentSkuSettings))).scalars().all()
    sku_settings = {
        stock_forecast.sku_key(row.material, row.subtype, row.brand, row.color_name): stock_forecast.SkuSettings(
            lead_time_days=row.lead_time_days,
            safety_margin_value=row.safety_margin_value,
            safety_margin_unit=row.safety_margin_unit,
            alerts_snoozed=bool(row.alerts_snoozed),
        )
        for row in sku_rows
    }
    forecasts = stock_forecast.forecast_all(spools, history, sku_settings, global_lead, utcnow_naive())
    proposals = build_proposals(forecasts, meta, cfg)
    return {
        "mode": "spoolman" if spoolman else "internal",
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": cfg,
        "proposals": proposals,
        "checked_skus": len(forecasts),
    }

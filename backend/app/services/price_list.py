"""Preisliste: Materialtarife für den Angebotskalkulator (Roadmap P4).

Eine stehende Liste ``data/price_list.json``:
``[{"material": "PLA", "rate_per_kg": 22.0},
    {"material": "TPU", "rate_per_kg": 45.0}, ...]``

Das Kalkulator-Frontend schlägt die Rate für ein Material vor; die
Berechnung selbst bleibt im Quote-Endpunkt (Rate wird übergeben). Ohne
Treffer gilt ``default_filament_cost``.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

PRICE_LIST_PATH = settings.base_dir / "price_list.json"
_lock = threading.Lock()


def read_list() -> list[dict[str, Any]]:
    try:
        data = json.loads(PRICE_LIST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def write_list(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Liste speichern; Materialnamen eingedampft, Raten typisiert."""
    cleaned: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        material = str(entry.get("material", "")).strip()[:40]
        if not material:
            continue
        try:
            rate = float(entry.get("rate_per_kg", 0))
            if rate < 0:
                continue
        except (TypeError, ValueError):
            continue
        cleaned.append({"material": material, "rate_per_kg": rate})
    PRICE_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = PRICE_LIST_PATH.with_name(PRICE_LIST_PATH.name + ".tmp")
        tmp.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PRICE_LIST_PATH)
    return {"entries": cleaned}


def rate_for(material: str | None, default: float) -> tuple[float, str | None]:
    """(Rate, Treffer-Material) — ohne Treffer (default, None)."""
    if not material:
        return default, None
    target = material.strip().lower()
    for entry in read_list():
        if str(entry.get("material", "")).strip().lower() == target:
            return float(entry["rate_per_kg"]), entry["material"]
    return default, None

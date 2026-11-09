"""Intelligenter AMS Rollentausch & Spool-Auto-Fallback (Phase 4).

Erkennt automatisch kompatible Filamentrollen im AMS (gleiches Material,
kompatible Farbe) und aktiviert Bambus natives Filament-Backup (Auto-Refill),
sobald ein Schacht zur Neige geht oder für einen Druckauftrag zu wenig
Restfilament vorhanden ist.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.printer_manager import printer_manager
from backend.app.utils.color_utils import colors_similar
from backend.app.utils.filament_types import printer_filament_type

logger = logging.getLogger(__name__)


def _normalize_hex(color_str: str | None) -> str:
    """Normalisiert Hex-Farbstring auf 6-stelligen RGB Hexcode."""
    if not color_str:
        return ""
    c = color_str.strip().lstrip("#").upper()
    return c[:6] if len(c) >= 6 else c


def are_trays_backup_compatible(tray_a: dict[str, Any], tray_b: dict[str, Any], strict_color: bool = False) -> bool:
    """Prüft, ob zwei Trays für automatisches AMS-Refill kompatibel sind.

    Bedingungen:
    1. Beide Trays müssen geladen sein (nicht leer/None).
    2. Identischer Materialtyp (z.B. PLA == PLA, PETG == PETG).
    3. Kompatible Farbe (exakter Hex-Match oder sehr geringe Farbdistanz).
    4. Gleicher Düsendurchmesser (falls in Metadaten vorhanden).
    """
    type_a = printer_filament_type(tray_a.get("tray_type") or "")
    type_b = printer_filament_type(tray_b.get("tray_type") or "")
    if not type_a or not type_b or type_a != type_b:
        return False

    # Nozzle-Check falls gepflegt
    noz_a = tray_a.get("nozzle_diameter")
    noz_b = tray_b.get("nozzle_diameter")
    if noz_a and noz_b and str(noz_a) != str(noz_b):
        return False

    col_a = _normalize_hex(tray_a.get("tray_color"))
    col_b = _normalize_hex(tray_b.get("tray_color"))
    if not col_a or not col_b:
        return False

    if col_a == col_b:
        return True

    if strict_color:
        return False

    # Bambu Studio toleriert leichte Farbabweichungen nicht für RFID,
    # für manuelle Zuweisungen jedoch ähnliche Farbtöne
    return colors_similar(col_a, col_b, threshold=30)


def find_ams_backup_pairs(status: Any) -> list[dict[str, Any]]:
    """Findet alle redundanten/kompatiblen Rollenpaare in allen AMS-Einheiten des Druckers.

    Rückgabe:
    Liste von Paaren mit AMS-ID, Slot-Nummern (1-basiert), Material, Farbe und Restprozent.
    """
    if not status or not getattr(status, "ams", None):
        return []

    ams_list = status.ams
    if not isinstance(ams_list, list):
        return []

    pairs: list[dict[str, Any]] = []

    for ams_unit in ams_list:
        if not isinstance(ams_unit, dict):
            continue
        ams_id = int(ams_unit.get("id", 0))
        trays = ams_unit.get("tray", [])
        if not isinstance(trays, list) or len(trays) < 2:
            continue

        n = len(trays)
        for i in range(n):
            tray_i = trays[i]
            if not isinstance(tray_i, dict) or not tray_i.get("tray_type"):
                continue

            remain_i = int(tray_i.get("remain", -1) or -1)

            for j in range(i + 1, n):
                tray_j = trays[j]
                if not isinstance(tray_j, dict) or not tray_j.get("tray_type"):
                    continue

                if are_trays_backup_compatible(tray_i, tray_j):
                    remain_j = int(tray_j.get("remain", -1) or -1)

                    # Bestimme primäre Rolle (weniger Restfilament) und Backup-Rolle
                    if 0 <= remain_i < remain_j or (remain_j < 0 <= remain_i):
                        primary_idx, backup_idx = i, j
                        p_tray, b_tray = tray_i, tray_j
                        p_remain, b_remain = remain_i, remain_j
                    else:
                        primary_idx, backup_idx = j, i
                        p_tray, b_tray = tray_j, tray_i
                        p_remain, b_remain = remain_j, remain_i

                    pairs.append(
                        {
                            "ams_id": ams_id,
                            "material": printer_filament_type(p_tray.get("tray_type") or ""),
                            "color": p_tray.get("tray_color") or "",
                            "primary_slot": primary_idx + 1,
                            "primary_tray_id": primary_idx,
                            "primary_remain_pct": p_remain,
                            "backup_slot": backup_idx + 1,
                            "backup_tray_id": backup_idx,
                            "backup_remain_pct": b_remain,
                            "same_color_exact": _normalize_hex(p_tray.get("tray_color"))
                            == _normalize_hex(b_tray.get("tray_color")),
                        }
                    )

    return pairs


def auto_enable_ams_filament_backup_if_eligible(printer_id: int) -> bool:
    """Aktiviert ams_filament_backup auf dem Drucker, falls kompatible Backup-Paare vorhanden sind.

    Wird vor Druckstart oder bei Defizit-Erkennung aufgerufen.
    """
    client = printer_manager.get_client(printer_id)
    if not client or not client.state.connected:
        return False

    status = printer_manager.get_status(printer_id)
    pairs = find_ams_backup_pairs(status)
    if not pairs:
        logger.debug("[Auto-Fallback] Drucker %s hat keine kompatiblen Backup-Spulen im AMS.", printer_id)
        return False

    # Falls bereits aktiv, nichts tun
    if getattr(client.state, "ams_filament_backup", None) is True:
        return True

    success = client.set_ams_filament_backup(True)
    if success:
        logger.info(
            "[Auto-Fallback] AMS Filament Backup für Drucker %s automatisch aktiviert. Gefundene Backup-Paare: %s",
            printer_id,
            [f"AMS {p['ams_id']}: Schacht {p['primary_slot']} -> {p['backup_slot']} ({p['material']})" for p in pairs],
        )
    return success

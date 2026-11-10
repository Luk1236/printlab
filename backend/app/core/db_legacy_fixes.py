"""Einmalige Datenkorrekturen für Altbestände, aus ``database.py`` ausgelagert (Größenbegrenzung der Datei)."""

from __future__ import annotations

from sqlalchemy import text


async def reset_legacy_sku_lead_time(conn) -> None:
    """Einmalig: den alten Standard-Lieferzeitwert 7 auf den neuen Standard 0 zurücksetzen.

    Früher war der Standard für ``filament_sku_settings.lead_time_days`` 7, heute ist er 0. Die Zeile
    dazu lief bei **jedem** Start und setzte damit auch Werte zurück, die jemand bewusst auf 7 Tage
    gestellt hatte (T3-01 der Code-Analyse).

    Die Spalte ``safety_margin_value`` kam erst nach der Umstellung hinzu. Fehlt sie noch, stammt die
    Tabelle aus der alten Zeit und die 7 ist unbearbeiteter Altbestand; ist sie da, sind die Werte
    gewollt und bleiben unangetastet. Muss deshalb **vor** dem ALTER TABLE laufen, das die Spalte anlegt.
    """
    # Erst zur Laufzeit importieren: database.py importiert dieses Modul, ein Import oben wäre ein Kreis.
    from backend.app.core.database import _table_has_column

    if await _table_has_column(conn, "filament_sku_settings", "safety_margin_value"):
        return
    async with conn.begin_nested():
        await conn.execute(text("UPDATE filament_sku_settings SET lead_time_days = 0 WHERE lead_time_days = 7"))

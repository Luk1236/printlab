"""Unit-Tests für Intelligenter Rollentausch & AMS Spool Auto-Fallback (Phase 4)."""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.services.spool_auto_fallback import (
    are_trays_backup_compatible,
    find_ams_backup_pairs,
    auto_enable_ams_filament_backup_if_eligible,
)


def test_are_trays_backup_compatible():
    # Identisches Material und Farbe
    tray_1 = {"tray_type": "PLA", "tray_color": "16A34AFF", "remain": 20}
    tray_2 = {"tray_type": "PLA", "tray_color": "16A34AFF", "remain": 90}
    assert are_trays_backup_compatible(tray_1, tray_2) is True

    # Unterschiedliches Material -> Nicht kompatibel
    tray_petg = {"tray_type": "PETG", "tray_color": "16A34AFF", "remain": 90}
    assert are_trays_backup_compatible(tray_1, tray_petg) is False

    # Sehr unterschiedliche Farbe -> Nicht kompatibel
    tray_red = {"tray_type": "PLA", "tray_color": "EF4444FF", "remain": 90}
    assert are_trays_backup_compatible(tray_1, tray_red) is False

    # Unterschiedlicher Düsendurchmesser -> Nicht kompatibel
    tray_02 = {"tray_type": "PLA", "tray_color": "16A34AFF", "nozzle_diameter": 0.2}
    tray_04 = {"tray_type": "PLA", "tray_color": "16A34AFF", "nozzle_diameter": 0.4}
    assert are_trays_backup_compatible(tray_02, tray_04) is False


def test_find_ams_backup_pairs():
    # Simuliere Drucker-Status mit einer AMS-Einheit und 4 Slots:
    # Slot 1: PLA Weiß 15%
    # Slot 2: PETG Schwarz 80%
    # Slot 3: PLA Weiß 95% (Backup zu Slot 1!)
    # Slot 4: leer
    status = SimpleNamespace(
        ams=[
            {
                "id": 0,
                "tray": [
                    {"id": 0, "tray_type": "PLA", "tray_color": "FFFFFFFF", "remain": 15},
                    {"id": 1, "tray_type": "PETG", "tray_color": "000000FF", "remain": 80},
                    {"id": 2, "tray_type": "PLA", "tray_color": "FFFFFFFF", "remain": 95},
                    {"id": 3, "tray_type": None, "tray_color": None, "remain": 0},
                ],
            }
        ]
    )

    pairs = find_ams_backup_pairs(status)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["ams_id"] == 0
    assert pair["material"] == "PLA"
    assert pair["primary_slot"] == 1  # 1-indexiert
    assert pair["primary_remain_pct"] == 15
    assert pair["backup_slot"] == 3
    assert pair["backup_remain_pct"] == 95
    assert pair["same_color_exact"] is True


def test_auto_enable_ams_filament_backup():
    status = SimpleNamespace(
        ams=[
            {
                "id": 0,
                "tray": [
                    {"id": 0, "tray_type": "PLA", "tray_color": "16A34AFF", "remain": 10},
                    {"id": 1, "tray_type": "PLA", "tray_color": "16A34AFF", "remain": 100},
                ],
            }
        ]
    )

    mock_client = MagicMock()
    mock_client.state.connected = True
    mock_client.state.ams_filament_backup = False
    mock_client.set_ams_filament_backup.return_value = True

    with patch("backend.app.services.spool_auto_fallback.printer_manager.get_client", return_value=mock_client), \
         patch("backend.app.services.spool_auto_fallback.printer_manager.get_status", return_value=status):
        
        res = auto_enable_ams_filament_backup_if_eligible(1)
        assert res is True
        mock_client.set_ams_filament_backup.assert_called_once_with(True)



@pytest.mark.asyncio
async def test_api_ams_backup_pairs(async_client):
    status = SimpleNamespace(
        ams=[
            {
                "id": 0,
                "tray": [
                    {"id": 0, "tray_type": "PLA", "tray_color": "16A34AFF", "remain": 10},
                    {"id": 1, "tray_type": "PLA", "tray_color": "16A34AFF", "remain": 100},
                ],
            }
        ]
    )
    with patch("backend.app.api.routes.printers.printer_manager.get_status", return_value=status), \
         patch("backend.app.api.routes.printers.printer_manager.get_client", return_value=None):
        resp = await async_client.get("/api/v1/printers/1/ams-backup-pairs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pairs_count"] == 1
        assert data["pairs"][0]["primary_slot"] == 1
        assert data["pairs"][0]["backup_slot"] == 2


@pytest.mark.asyncio
async def test_api_apply_ams_auto_fallback(async_client):
    with patch("backend.app.services.spool_auto_fallback.auto_enable_ams_filament_backup_if_eligible", return_value=True):
        resp = await async_client.post("/api/v1/printers/1/ams-auto-fallback/apply")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

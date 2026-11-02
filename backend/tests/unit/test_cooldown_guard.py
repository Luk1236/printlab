"""Tests für die thermische Abkühlüberwachung vor Plattenwechsel."""

from backend.app.services import cooldown_guard


class TestCooldownGuard:
    def test_check_swap_safety_when_hot(self):
        # Bei 65°C Betttemperatur (z. B. nach PETG-Druck)
        is_safe, msg, delta = cooldown_guard.check_swap_safety(65.0, max_safe_temp=36.0)
        assert is_safe is False
        assert delta == 29.0
        assert "gesperrt" in msg
        assert "zu heiß" in msg

    def test_check_swap_safety_when_cooled_down(self):
        # Bei 30°C Betttemperatur
        is_safe, msg, delta = cooldown_guard.check_swap_safety(30.0, max_safe_temp=36.0)
        assert is_safe is True
        assert delta == 0.0
        assert "freigegeben" in msg

    def test_estimate_cooldown_seconds(self):
        # Abkühlung von 65°C auf 36°C dauert typischerweise mehrere Minuten (> 120s)
        sec = cooldown_guard.estimate_cooldown_seconds(65.0, target_temp=36.0, ambient_temp=22.0)
        assert sec > 120

        # Wenn bereits kühler als Soll: 0 Sekunden
        sec_zero = cooldown_guard.estimate_cooldown_seconds(32.0, target_temp=36.0)
        assert sec_zero == 0

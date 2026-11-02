"""Thermische Abkühlüberwachung für automatischen Plattenwechsel am Bambu Lab P2S.

Verhindert das vorzeitige mechanische Abwerfen oder Wechseln der Druckplatte,
solange das Druckbett noch heiß ist (> 36 °C). Dies schützt vor:
- Bauteilverzug durch zu frühes Biegen/Entformen
- Beschädigung der PEI-Beschichtung durch Festkleben
- Verformung der Führungsnasen und mechanischen Halterungen
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_MAX_SWAP_TEMP = 36.0  # Maximale sichere Plattenwechseltemperatur in °C
DEFAULT_AMBIENT_TEMP = 22.0  # Angenommene Werkstatt-Raumtemperatur in °C
COOLING_CONSTANT_K = 0.0032  # Abkühlkoeffizient für das 256x256 Bambu-Alu-Magnetbett


def check_swap_safety(
    current_bed_temp: float,
    max_safe_temp: float = DEFAULT_MAX_SWAP_TEMP,
) -> tuple[bool, str, float]:
    """Prüft, ob das Druckbett ausreichend abgekühlt ist, um gefahrlos gewechselt zu werden.

    Returns:
        (is_safe, message, remaining_delta_temp)
    """
    temp = float(current_bed_temp)
    max_t = float(max_safe_temp)

    if temp > max_t:
        delta = round(temp - max_t, 1)
        est_sec = estimate_cooldown_seconds(temp, target_temp=max_t)
        est_min = max(1, int(round(est_sec / 60.0)))
        msg = (
            f"Druckbett ist noch zu heiß ({temp:.1f} °C > {max_t:.1f} °C). "
            f"Plattenwechsel gesperrt zum Schutz von Bauteil und PEI-Platte (ca. noch {est_min} min Abkühlzeit)."
        )
        return False, msg, delta

    return True, f"Druckbett ausreichend abgekühlt ({temp:.1f} °C <= {max_t:.1f} °C). Plattenwechsel freigegeben.", 0.0


def estimate_cooldown_seconds(
    current_bed_temp: float,
    target_temp: float = DEFAULT_MAX_SWAP_TEMP,
    ambient_temp: float = DEFAULT_AMBIENT_TEMP,
) -> int:
    """Schätzt die verbleibende Abkühldauer in Sekunden nach Newtons Abkühlungsgesetz."""
    t0 = float(current_bed_temp)
    t_target = float(target_temp)
    t_amb = float(ambient_temp)

    if t0 <= t_target:
        return 0

    # Falls Raumtemperatur unrealistisch hoch ist, Mindestdifferenz erzwingen
    effective_amb = min(t_amb, t_target - 2.0)
    delta_init = t0 - effective_amb
    delta_target = t_target - effective_amb

    if delta_target <= 0 or delta_init <= 0:
        return 60

    try:
        seconds = -math.log(delta_target / delta_init) / COOLING_CONSTANT_K
        return max(0, int(round(seconds)))
    except (ValueError, ZeroDivisionError):
        return 120

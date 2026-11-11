"""Bremse gegen das Durchprobieren des Zugangscodes am virtuellen Drucker (T6-02 der Code-Analyse).

Der MQTT-Server zählt Fehlversuche je Quell-IP schon länger selbst (``mqtt_server.py``). Der FTP-Server prüfte denselben
Code ohne jede Bremse; diese Klasse gibt ihm dieselbe Regel: nach ``max_attempts`` Fehlversuchen innerhalb von
``window_seconds`` wird die Adresse abgewiesen, bis das Fenster abgelaufen ist. Kein manuelles Entsperren nötig.
"""

from __future__ import annotations

import time
from collections.abc import Callable

AUTH_MAX_ATTEMPTS = 5
AUTH_WINDOW_SECONDS = 60.0


class AuthRateLimiter:
    """Fehlversuche je Quell-IP in einem gleitenden Fenster."""

    def __init__(
        self,
        max_attempts: int = AUTH_MAX_ATTEMPTS,
        window_seconds: float = AUTH_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def is_blocked(self, source_ip: str) -> bool:
        """True, wenn die Adresse ihr Kontingent verbraucht hat. Räumt abgelaufene Einträge dabei weg."""
        window_start = self._clock() - self.window_seconds
        recent = [t for t in self._failures.get(source_ip, []) if t >= window_start]
        if recent:
            self._failures[source_ip] = recent
        else:
            self._failures.pop(source_ip, None)
        return len(recent) >= self.max_attempts

    def record_failure(self, source_ip: str) -> None:
        self._failures.setdefault(source_ip, []).append(self._clock())

    def clear(self, source_ip: str) -> None:
        """Nach einer gelungenen Anmeldung: frühere Tippfehler zählen nicht weiter."""
        self._failures.pop(source_ip, None)

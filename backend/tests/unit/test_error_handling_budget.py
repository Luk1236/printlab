"""Sperre gegen stille Fehler: ``except Exception: pass`` darf nicht weiter wachsen.

Breite Handler sind im Netzwerk- und Hardware-Teil oft Absicht (ein kaputter Sensor darf die Meldung
nicht verhindern), aber ``pass`` ohne Protokoll macht Fehlersuche unmöglich. Dieser Test friert den
Stand ein: neue stille Handler fallen auf, und beim Aufräumen wird die Zahl kleiner. Ziel ist nicht
„alle ersetzen“, sondern jeder neue Handler protokolliert mindestens auf ``debug``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "backend" / "app"

# Stand 30.10.2026. Nur senken.
BUDGET = 43

SILENT = re.compile(r"except\s+(?:Exception|BaseException)\s*(?:as\s+\w+)?:\s*\n\s*(?:pass|\.\.\.)\s*(?:\n|$)")


def _count(path: Path) -> int:
    return len(SILENT.findall(path.read_text(encoding="utf-8", errors="ignore")))


def test_silent_handlers_do_not_grow():
    offenders = {str(path.relative_to(ROOT)): _count(path) for path in APP.rglob("*.py") if _count(path)}
    total = sum(offenders.values())
    assert total <= BUDGET, (
        f"{total} stille Handler (Grenze {BUDGET}). Bitte im Handler protokollieren "
        f"(logger.debug(..., exc_info=True)) statt `pass`. Verteilung: {offenders}"
    )


def test_the_pattern_matches_what_it_should():
    """Der Zähler darf nicht versehentlich alles oder nichts finden."""
    assert SILENT.search("try:\n    x()\nexcept Exception:\n    pass\n")
    assert SILENT.search("try:\n    x()\nexcept BaseException as exc:\n    ...\n")
    assert not SILENT.search("try:\n    x()\nexcept Exception:\n    logger.debug('x')\n")
    assert not SILENT.search("except ValueError:\n    pass\n")

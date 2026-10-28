"""Vorgeschriebene Anmeldung (``PRINTLAB_REQUIRE_AUTH=1``).

Ohne diese Einstellung gilt das Verhalten von Bambuddy: bis jemand die Anmeldung einschaltet, ist PrintLab im Netz offen.
Mit ihr (der Pi-Installer setzt sie) ist die Schnittstelle gesperrt, solange keine Anmeldung eingerichtet ist; nur die
Einrichtung selbst und die Versionsabfrage bleiben erreichbar, und die Einrichtung lässt sich nicht ohne Administrator
und Passwort abschließen.
"""

from __future__ import annotations

import os

SETUP_HINT = "Die Anmeldung muss zuerst eingerichtet werden (Seite /setup)."


def is_required() -> bool:
    return os.environ.get("PRINTLAB_REQUIRE_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}

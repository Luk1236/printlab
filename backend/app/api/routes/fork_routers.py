"""Registry der eigenen Router des Forks.

``main.py`` liegt am Zeilenbudget (``test_file_size_budget.py``); jedes neue
Router-Modul kommt hierher statt dorthin. ``register_fork_routers(app, prefix)``
bindet alle Router einmalig in der bisherigen Reihenfolge ein — die Endpunkte
ändern sich dadurch nicht (gleiche Pfade, gleiche Rechteprüfung).
"""

from fastapi import FastAPI

from backend.app.api.routes import (
    assistant,
    auto_requeue,
    auto_setup,
    customer_portal_route,
    customers,
    error_help,
    failure_images,
    first_layer_inspector,
    fleet,
    ha_discovery_route,
    hardware,
    maintenance_wear,
    monthly_report,
    plate_calibration,
    plate_tuning,
    plate_wizard,
    push,
    quote,
    quote_queue,
    quote_share,
    reorder,
    search,
    selftest,
    spaghetti_check,
    timelapse_export,
    webhooks_outbound,
)


def register_fork_routers(app: FastAPI, prefix: str) -> None:
    """Bindet alle Fork-Router mit dem API-Präfix ein (Reihenfolge wie bisher)."""
    # Kamera-Einmessung (Monitor-Port P1): vier Plattenecken -> Plattenaufsicht.
    app.include_router(plate_calibration.router, prefix=prefix)
    # Spaghetti-/Abbruch-Erkennung (nur Warnung, nach Druckmitte).
    app.include_router(spaghetti_check.router, prefix=prefix)
    app.include_router(first_layer_inspector.router, prefix=prefix)
    app.include_router(hardware.router, prefix=prefix)
    app.include_router(plate_tuning.router, prefix=prefix)
    app.include_router(assistant.router, prefix=prefix)
    app.include_router(selftest.router, prefix=prefix)
    # Auto-Einrichtung: erledigt bei der Inbetriebnahme selbst, was ohne Zugangsdaten geht.
    app.include_router(auto_setup.router, prefix=prefix)
    app.include_router(failure_images.router, prefix=prefix)
    # Angebotskalkulator (Gewerbliches): Stundenlohn, Aufschlag, Energie.
    app.include_router(quote.router, prefix=prefix)
    # Monats-Report: Umsatz/Fertigung/Gewinn als Zahlenwerk und PDF.
    app.include_router(monthly_report.router, prefix=prefix)
    # Angebot → Warteschlange: verknüpfte Druckjobs eines Angebots neu einreihen.
    app.include_router(quote_queue.router, prefix=prefix)
    # Kunden-Stamm: Adressbuch für Angebote und Rechnungen.
    app.include_router(customers.router, prefix=prefix)
    # Fehlerhilfe: Fehlerbild-Bibliothek und optionale Gegenmaßnahmen.
    app.include_router(error_help.router, prefix=prefix)
    # Zeitraffer: aufbewahrte Schichtbilder als MP4 rendern.
    app.include_router(timelapse_export.router, prefix=prefix)
    # Automatische Umverteilung eines gescheiterten Auftrags (einmal, anderes Gerät).
    app.include_router(auto_requeue.router, prefix=prefix)
    # Nachbestellvorschlag aus Verbrauchsprognose, Lieferant und Preis.
    app.include_router(reorder.router, prefix=prefix)
    # Öffentlicher Angebots-Link mit Zusage/Ablehnung (Seite ohne Anmeldung).
    app.include_router(quote_share.router, prefix=prefix)
    # Einmess-Assistent für den Plattenwechsel (Messwerte, Sperre, Protokoll).
    app.include_router(plate_wizard.router, prefix=prefix)
    # Globale Suche für die Befehlspalette (Strg+K): Drucker, Bibliothek, Archiv, Warteschlange.
    app.include_router(search.router, prefix=prefix)
    # Browser-Meldungen: VAPID-Schlüssel, Abo, Testversand.
    app.include_router(push.router, prefix=prefix)

    # PrintLab v2.0 Enterprise & Infrastructure Erweiterungen
    app.include_router(fleet.router, prefix=prefix)
    app.include_router(maintenance_wear.router, prefix=prefix)
    app.include_router(ha_discovery_route.router, prefix=prefix)
    app.include_router(customer_portal_route.router, prefix=prefix)
    app.include_router(webhooks_outbound.router, prefix=prefix)

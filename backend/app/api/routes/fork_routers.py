"""Registry der eigenen Router des Forks.

``main.py`` liegt am Zeilenbudget (``test_file_size_budget.py``); jedes neue
Router-Modul kommt hierher statt dorthin. ``register_fork_routers(app, prefix)``
bindet alle Router einmalig in der bisherigen Reihenfolge ein — die Endpunkte
ändern sich dadurch nicht (gleiche Pfade, gleiche Rechteprüfung).
"""

from fastapi import FastAPI

from backend.app.api.routes import (
    assistant,
    failure_images,
    first_layer_inspector,
    hardware,
    monthly_report,
    plate_calibration,
    plate_tuning,
    quote,
    selftest,
    spaghetti_check,
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
    app.include_router(failure_images.router, prefix=prefix)
    # Angebotskalkulator (Gewerbliches): Stundenlohn, Aufschlag, Energie.
    app.include_router(quote.router, prefix=prefix)
    # Monats-Report: Umsatz/Fertigung/Gewinn als Zahlenwerk und PDF.
    app.include_router(monthly_report.router, prefix=prefix)

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class PortalQuote(Base):
    """Serverregistrierte Sofortkalkulation des Kundenportals.

    Ein Checkout darf ausschließlich Kalkulationen abrechnen, die dieser Server
    selbst erzeugt und gespeichert hat — so kann der Zahlbetrag nie aus dem
    Request kommen. Die Registry liegt in der SQLite-Hauptdatenbank, damit ein
    neu gestartetes Backend ein laufendes Stripe-Checkout-angebot erneut auflösen
    kann (die Stripe-Session lebt 60 Minuten, das Angebot ebenso).
    """

    __tablename__ = "portal_quotes"

    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

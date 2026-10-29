from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class Customer(Base):
    """Kunden-Stamm (leichtgewichtig): Adresse und Kontakt für Angebote und Rechnungen.

    Angebote und Rechnungen speichern Kunde und Anschrift als Kopie — die Tabelle
    ist das Adressbuch dahinter, keine Beziehung; ein gelöschter Kunde verändert
    frühere Belege nicht.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(240), default="")
    email: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

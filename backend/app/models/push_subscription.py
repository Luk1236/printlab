"""Browser-Push-Abos (Web Push).

Ein Abo gehört zu einem Browser/Gerät, nicht zu einem Benutzerkonto: derselbe Benutzer kann auf Handy und Rechner
angemeldet sein. ``user_id`` hält nur fest, wer das Abo angelegt hat (für das Testen und zum Aufräumen); der Versand
geht an alle Abos, weil die Meldungen von PrintLab ohnehin betriebsweit sind.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Vom Push-Dienst des Browsers vergeben; eindeutig, damit erneutes Abonnieren desselben Geräts kein Duplikat anlegt.
    endpoint: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aufeinanderfolgende Fehlschläge; ab einer Grenze wird das Abo verworfen (Browser gelöscht, Gerät weg).
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

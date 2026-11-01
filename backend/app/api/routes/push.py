"""Browser-Meldungen: Schlüssel, Abo und Testversand.

Angemeldete Benutzer abonnieren ihr Gerät; die Meldungen selbst sind betriebsweit (wie die vorhandenen
Meldungswege). Alle Routen verlangen dieselbe Anmeldung wie die übrigen Einstellungen (``require_auth_if_enabled``);
der veröffentlichte VAPID-Schlüssel selbst ist kein Geheimnis.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import require_auth_if_enabled
from backend.app.core.database import get_db
from backend.app.models.push_subscription import PushSubscription
from backend.app.models.settings import Settings
from backend.app.services import web_push

router = APIRouter(prefix="/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


class SubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=500)
    keys: SubscriptionKeys


class UnsubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=500)


def _decode_key(value: str, length: int) -> None:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:
        raise HTTPException(400, "Ungültiger Abo-Schlüssel.") from None
    if len(raw) != length:
        raise HTTPException(400, "Ungültiger Abo-Schlüssel.")


@router.get("/key")
async def push_key(db: AsyncSession = Depends(get_db), _current_user=Depends(require_auth_if_enabled)):
    """Öffentlicher VAPID-Schlüssel für ``pushManager.subscribe``.

    Der Schlüssel selbst ist kein Geheimnis, die Route hängt aber wie alle anderen an der Anmeldung — die
    Einrichtung passiert ohnehin in den Einstellungen.
    """
    _, public = await web_push.ensure_keys(db)
    return {"public_key": public}


@router.post("/subscribe")
async def subscribe(
    payload: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """Abo anlegen oder auffrischen (der Browser liefert beim erneuten Abonnieren denselben Endpunkt)."""
    _decode_key(payload.keys.p256dh, 65)
    _decode_key(payload.keys.auth, 16)

    existing = (
        await db.execute(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    ).scalar_one_or_none()
    if existing is None:
        existing = PushSubscription(endpoint=payload.endpoint, p256dh=payload.keys.p256dh, auth=payload.keys.auth)
        db.add(existing)
    else:
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        existing.failure_count = 0
        existing.last_error = None
    if current_user is not None:
        existing.user_id = current_user.id
    await db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(
    payload: UnsubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """Abo entfernen. Ohne Anmeldung (auth aus) darf jedes Gerät sein Abo abmelden."""
    conditions = [PushSubscription.endpoint == payload.endpoint]
    if current_user is not None and not current_user.is_admin:
        conditions.append(PushSubscription.user_id == current_user.id)
    await db.execute(delete(PushSubscription).where(*conditions))
    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_push(current_user=Depends(require_auth_if_enabled)):
    """Testmeldung an die eigenen Abos; ohne Anmeldung an alle."""
    sent, failed = await web_push.test_delivery(current_user.id if current_user is not None else None)
    return {"sent": sent, "failed": failed}


@router.get("/status")
async def push_status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """Wie viele Abos dieses Benutzerkonto hat (für die Karte in den Einstellungen)."""
    query = select(PushSubscription)
    if current_user is not None:
        query = query.where(PushSubscription.user_id == current_user.id)
    subscriptions = list((await db.execute(query)).scalars().all())
    configured = (
        await db.execute(select(Settings).where(Settings.key == web_push.PRIVATE_KEY_SETTING))
    ).scalar_one_or_none() is not None
    return {
        "subscriptions": len(subscriptions),
        "last_success_at": max((sub.last_success_at for sub in subscriptions if sub.last_success_at), default=None),
        "configured": configured,
    }

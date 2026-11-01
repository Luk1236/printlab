"""Browser-Meldungen ohne Zusatzpaket: VAPID, Verschlüsselung und Versand.

Die Meldung geht verschlüsselt an den Push-Dienst des Browsers (RFC 8291, ``aes128gcm``). Dafür braucht es nur
``cryptography`` und ``httpx``, die PrintLab ohnehin benutzt — kein ``pywebpush`` auf dem Pi. Die VAPID-Schlüssel
liegen in der Einstellungstabelle (``web_push_vapid_*``), damit sie mit der Datenbank gesichert und beim
Werkseinstellungen-Reset mit entfernt werden; Abos ohne passenden Schlüssel wären ohnehin wertlos.

Der Versand läuft als eigene Aufgabe (``broadcast``), weil der Meldepfad eines Drucks nicht auf einen fremden
Push-Dienst warten darf. Fehlgeschlagene Zustellungen werden gezählt; nach ``MAX_FAILURES`` fliegt das Abo raus.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select

from backend.app.core import database
from backend.app.models.push_subscription import PushSubscription
from backend.app.models.settings import Settings

logger = logging.getLogger(__name__)

PRIVATE_KEY_SETTING = "web_push_vapid_private"
PUBLIC_KEY_SETTING = "web_push_vapid_public"
VAPID_SUBJECT = "mailto:printlab@localhost"
MAX_FAILURES = 5
# Ein Abo, das fünfmal hintereinander nicht erreichbar war, ist praktisch immer gelöscht/neu installiert.
RECORD_SIZE = 4096
_running: set[asyncio.Task] = set()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


async def ensure_keys(db) -> tuple[str, str]:
    """VAPID-Schlüssel lesen oder einmalig erzeugen; gibt ``(private, public)`` base64url zurück."""
    rows = await db.execute(select(Settings).where(Settings.key.in_([PRIVATE_KEY_SETTING, PUBLIC_KEY_SETTING])))
    stored = {row.key: row.value for row in rows.scalars().all()}
    private = stored.get(PRIVATE_KEY_SETTING)
    public = stored.get(PUBLIC_KEY_SETTING)
    if private and public:
        return private, public

    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    if PRIVATE_KEY_SETTING not in stored:
        db.add(Settings(key=PRIVATE_KEY_SETTING, value=private))
    if PUBLIC_KEY_SETTING not in stored:
        db.add(Settings(key=PUBLIC_KEY_SETTING, value=public))
    await db.commit()
    return private, public


def vapid_headers(endpoint: str, private_b64: str, public_b64: str) -> dict[str, str]:
    """``Authorization``-Kopf nach RFC 8292: ES256-JWT über die Herkunft des Push-Dienstes."""
    parts = urlsplit(endpoint)
    origin = f"{parts.scheme}://{parts.netloc}"
    header = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = _b64(
        json.dumps(
            {"aud": origin, "exp": int(time.time()) + 12 * 3600, "sub": VAPID_SUBJECT},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode()
    key = ec.derive_private_key(int.from_bytes(_unb64(private_b64), "big"), ec.SECP256R1())
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    signature = _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return {
        "Authorization": f"vapid t={header}.{claims}.{signature},k={public_b64}",
        "TTL": "3600",
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
    }


def encrypt_payload(payload: bytes, p256dh: str, auth: str) -> bytes:
    """Verschlüsselt eine Meldung für ein Abo (RFC 8291, ein Datensatz).

    Aufbau des Körpers: Salt(16) | Datensatzgröße(4) | Länge des Ephemeral-Schlüssels(1) | Ephemeral-Schlüssel(65) |
    AES-GCM-Chiffrat. Der letzte Datensatz trägt das Füllzeichen ``0x02``.
    """
    ua_public = _unb64(p256dh)
    auth_secret = _unb64(auth)
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    as_public = ephemeral.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    shared = ephemeral.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))

    # Erster Schritt: gemeinsames Geheimnis mit dem Anmeldegeheimnis des Abos strecken.
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public + as_public,
    ).derive(shared)

    salt = os.urandom(16)
    prk = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    cek = HKDFExpand(algorithm=hashes.SHA256(), length=16, info=b"Content-Encoding: aes128gcm\x00\x01").derive(prk)
    nonce = HKDFExpand(algorithm=hashes.SHA256(), length=12, info=b"Content-Encoding: aes128gcm\x00\x02").derive(prk)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">I", RECORD_SIZE) + bytes([len(as_public)]) + as_public + ciphertext


async def send(subscription: PushSubscription, title: str, body: str, url: str = "/") -> bool:
    """Eine Meldung zustellen; aktualisiert Erfolg/Fehlschlag am Abo (ohne Commit)."""
    message = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False).encode()
    async with database.async_session() as db:
        private, public = await ensure_keys(db)
    try:
        encrypted = encrypt_payload(message, subscription.p256dh, subscription.auth)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                subscription.endpoint,
                content=encrypted,
                headers=vapid_headers(subscription.endpoint, private, public),
            )
    except Exception as exc:  # Netzfehler, kaputtes Abo, ungültiger Schlüssel
        subscription.failure_count += 1
        subscription.last_error = str(exc)[:500]
        logger.warning("Web-Push an %s fehlgeschlagen: %s", subscription.endpoint[:80], exc)
        return False

    if response.status_code in (404, 410):
        # Der Browser hat das Abo verworfen — beim nächsten Lauf entfernen.
        subscription.failure_count = MAX_FAILURES
        subscription.last_error = f"HTTP {response.status_code}"
        return False
    if response.status_code >= 400:
        subscription.failure_count += 1
        subscription.last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        logger.warning("Web-Push an %s: HTTP %s", subscription.endpoint[:80], response.status_code)
        return False

    subscription.failure_count = 0
    subscription.last_error = None
    subscription.last_success_at = datetime.now(UTC).replace(tzinfo=None)
    return True


async def deliver(subscriptions: list[PushSubscription], title: str, body: str, url: str = "/") -> tuple[int, int]:
    """An eine Liste zustellen und verworfene Abos löschen; gibt ``(zugestellt, fehlgeschlagen)`` zurück."""
    sent = failed = 0
    async with database.async_session() as db:
        for subscription in subscriptions:
            if await send(subscription, title, body, url):
                sent += 1
            else:
                failed += 1
            if subscription.failure_count >= MAX_FAILURES:
                await db.delete(await db.merge(subscription))
            else:
                await db.merge(subscription)
        await db.commit()
    return sent, failed


async def _broadcast(title: str, body: str, url: str) -> None:
    try:
        async with database.async_session() as db:
            rows = await db.execute(select(PushSubscription))
            subscriptions = list(rows.scalars().all())
        if subscriptions:
            await deliver(subscriptions, title, body, url)
    except Exception:
        # Ein kaputter Push-Dienst darf weder den Druck noch den Hintergrund-Loop stören.
        logger.exception("Web-Push-Verteilung fehlgeschlagen")


def schedule(title: str, body: str, url: str = "/") -> None:
    """Meldung im Hintergrund zustellen — der Meldepfad des Drucks wartet nicht auf den Push-Dienst."""
    task = asyncio.create_task(_broadcast(title, body, url))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def test_delivery(user_id: int | None) -> tuple[int, int]:
    """Testmeldung an die Abos eines Benutzers (oder an alle, wenn keine Anmeldung aktiv ist)."""
    async with database.async_session() as db:
        query = select(PushSubscription)
        if user_id is not None:
            query = query.where(PushSubscription.user_id == user_id)
        subscriptions = list((await db.execute(query)).scalars().all())
    return await deliver(subscriptions, "PrintLab", "Browser-Meldungen sind eingerichtet.", "/")

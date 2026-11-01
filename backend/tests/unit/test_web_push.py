"""Web Push: Verschlüsselung, VAPID und Schlüsselablage.

Der Rundlauf ist der eigentliche Beweis: Was ``encrypt_payload`` erzeugt, muss sich mit dem privaten Schlüssel des
Abos (den nur der Browser hat) wieder entschlüsseln lassen. Dafür wird hier genau der Ablauf aus RFC 8291
nachgebaut — unabhängig vom Produktionscode, damit ein gemeinsamer Denkfehler auffällt.
"""

from __future__ import annotations

import base64
import json
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.app.services import web_push


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _subscription_keys() -> tuple[ec.EllipticCurvePrivateKey, str, str]:
    private = ec.generate_private_key(ec.SECP256R1())
    p256dh = _b64(private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    auth = _b64(b"0123456789abcdef")
    return private, p256dh, auth


def _decrypt(body: bytes, private: ec.EllipticCurvePrivateKey, p256dh: str, auth: str) -> bytes:
    salt, record_size, key_length = body[:16], struct.unpack(">I", body[16:20])[0], body[20]
    assert record_size == 4096
    as_public = body[21 : 21 + key_length]
    ciphertext = body[21 + key_length :]
    ua_public = _unb64(p256dh)

    shared = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_unb64(auth),
        info=b"WebPush: info\x00" + ua_public + as_public,
    ).derive(shared)
    prk = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    cek = HKDFExpand(algorithm=hashes.SHA256(), length=16, info=b"Content-Encoding: aes128gcm\x00\x01").derive(prk)
    nonce = HKDFExpand(algorithm=hashes.SHA256(), length=12, info=b"Content-Encoding: aes128gcm\x00\x02").derive(prk)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_roundtrip_returns_original_json():
    private, p256dh, auth = _subscription_keys()
    payload = json.dumps({"title": "Fertig", "body": "Benchy ist gedruckt", "url": "/archives"}).encode()

    body = web_push.encrypt_payload(payload, p256dh, auth)

    assert _decrypt(body, private, p256dh, auth) == payload


def test_two_messages_use_different_salts():
    _, p256dh, auth = _subscription_keys()
    first = web_push.encrypt_payload(b"eins", p256dh, auth)
    second = web_push.encrypt_payload(b"eins", p256dh, auth)
    assert first != second
    assert first[:16] != second[:16]


def test_vapid_header_carries_a_verifiable_es256_jwt():
    private = ec.generate_private_key(ec.SECP256R1())
    private_b64 = _b64(private.private_numbers().private_value.to_bytes(32, "big"))
    public_b64 = _b64(private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))

    headers = web_push.vapid_headers("https://push.example.com/abc", private_b64, public_b64)

    token = headers["Authorization"].split("t=")[1].split(",")[0]
    header_b64, claims_b64, signature_b64 = token.split(".")
    claims = json.loads(_unb64(claims_b64))
    assert claims["aud"] == "https://push.example.com"
    assert claims["exp"] > 0
    assert headers["TTL"] == "3600"
    assert headers["Content-Encoding"] == "aes128gcm"

    signature = _unb64(signature_b64)
    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    private.public_key().verify(der, f"{header_b64}.{claims_b64}".encode(), ec.ECDSA(hashes.SHA256()))


async def test_ensure_keys_creates_once_and_stays_stable(db_session):
    first_private, first_public = await web_push.ensure_keys(db_session)
    second_private, second_public = await web_push.ensure_keys(db_session)

    assert (first_private, first_public) == (second_private, second_public)
    assert len(_unb64(first_private)) == 32
    assert len(_unb64(first_public)) == 65

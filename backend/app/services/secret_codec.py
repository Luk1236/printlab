"""Symmetrische Verschlüsselung für Dienst-Geheimnisse auf der Festplatte.

Einige Dienste müssen Geheimnisse persistent halten (z. B. HMAC-Kennwörter
ausgehender Webhooks). Im Klartext neben der Datenbank sind sie mit Datei-
Zugriff lesbar; dieses Modul verschlüsselt sie mit Fernet (AES-128-CBC +
HMAC-SHA256, aus dem ohnehin vorhandenen cryptography-Paket).

Schlüsselverwaltung: der Schlüssel liegt in ``service_secrets.key`` im
Datenordner und wird beim ersten Nutzen erzeugt. POSIX rechte: 0600. Geht die
Schlüsseldatei verloren, sind die damit verschlüsselten Geheimnisse unlesbar —
es gibt bewusst keine Wiederherstellung: Betroffene Webhooks müssen neu
registriert werden, und die Zustellung meldet den Grund ehrlich (Streak-Regel
der Webhook-Engine stellt den Hook danach still).

Format verschlüsselter Werte: ``enc:<fernet-token (base64url)>``. Werte ohne
Präfix werden als Bestandsklartext unverändert zurückgegeben — alte Datendateien
funktionieren weiter; neue Einträge sind immer verschlüsselt.
"""

from __future__ import annotations

import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

KEY_FILE = settings.base_dir / "service_secrets.key"
PREFIX = "enc:"

_lock = threading.Lock()
_cipher: Fernet | None = None


def _load_cipher() -> Fernet:
    """Lädt den Schlüssel (erstes Nutzen: erzeugen) und hält die Fernet-Instanz."""
    global _cipher
    with _lock:
        if _cipher is not None:
            return _cipher

        if KEY_FILE.is_file():
            key = KEY_FILE.read_text(encoding="utf-8").strip()
            if not key:
                raise ValueError(f"Schlüsseldatei {KEY_FILE} ist leer.")
        else:
            key = Fernet.generate_key().decode("ascii")
            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = KEY_FILE.with_name(KEY_FILE.name + ".tmp")
            tmp.write_text(key + "\n", encoding="utf-8")
            tmp.replace(KEY_FILE)
            _restrict_file_permissions(KEY_FILE)
            logger.info("Neuer Dienst-Schlüssel erzeugt: %s", KEY_FILE.name)

        _cipher = Fernet(key.encode("ascii"))
        return _cipher


def _restrict_file_permissions(path) -> None:
    """Schränkt Dateirechte auf den Besitzer ein (POSIX 0600; Windows erbt Profil-ACL)."""
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
        else:
            # Windows: Dateien im Benutzerprofil erben die ACL des Profils;
            # eine gezielte Härte via icacls wäre an Systemrichtlinien geknüpft
            # und gehört in die Installationsroutine, nicht in einen Dienstpfad.
            pass
    except OSError as exc:
        logger.warning("Dateirechte für %s konnten nicht eingeschränkt werden: %s", path, exc)


def encrypt_secret(plain: str) -> str:
    """Verschlüsselt ein Geheimnis für die Persistence; leer bleibt leer."""
    if not plain:
        return ""
    return PREFIX + _load_cipher().encrypt(plain.encode("utf-8")).decode("ascii")


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(PREFIX)


def decrypt_secret(stored: str) -> str:
    """Liefert das Klartext-Geheimnis zurück.

    Klartext-Einträge aus Bestandsdateien werden unverändert durchgereicht
    (Upgrade-on-write macht die Migration in den Zustellpfad). Ein Wert mit
    ``enc:``-Präfix, der nicht mehr entschlüsselt werden kann, wirft ValueError —
    der Aufrufer muss über den verlorenen Schlüssel informieren, statt stille
    unsignierte Zustellungen zu erzeugen.
    """
    if not is_encrypted(stored):
        return stored
    try:
        return _load_cipher().decrypt(stored[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError(
            f"Geheimnis mit Präfix '{PREFIX}' ist nicht lesbar — Schlüsseldatei "
            f"{KEY_FILE.name} fehlt oder wurde ersetzt. Betroffene Hooks neu registrieren."
        ) from exc


def reset_cached_cipher() -> None:
    """Trennt die zwischengespeicherte Schlüsselinstanz (Test-/Umgebungsschnittstelle)."""
    global _cipher
    with _lock:
        _cipher = None

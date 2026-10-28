"""Meldewege für Ausfälle (Telegram, ntfy): Einstellung aus der Oberfläche, gemeinsam genutzt von Überwachung und
Sicherung nach außen.

Die Zugangsdaten stehen in ``alert_channels.json`` im Datenordner (nur für den Besitzer lesbar). Die Oberfläche bekommt
sie **nie** zurück, nur ob sie gesetzt sind. Die Umgebungsvariablen ``PRINTLAB_ALERT_*`` (aus ``~/.config/printlab.env``)
bleiben möglich und haben Vorrang, falls beides gesetzt ist.

Nur Standardbibliothek: ``werkzeuge/ueberwachung.py`` und ``sicherung_extern.py`` laufen ohne die App.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

FILE_NAME = "alert_channels.json"
TELEGRAM_TOKEN_RX = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,60}")
TELEGRAM_CHAT_RX = re.compile(r"-?\d{1,20}|@[A-Za-z0-9_]{4,40}")
ENV_KEYS = {
    "telegram_token": "PRINTLAB_ALERT_TELEGRAM_TOKEN",
    "telegram_chat": "PRINTLAB_ALERT_TELEGRAM_CHAT",
    "ntfy_url": "PRINTLAB_ALERT_NTFY_URL",
}
SECRET_KEYS = ("telegram_token", "ntfy_url")  # ntfy-Themen sind wie ein Passwort: wer die Adresse kennt, kann mitlesen


class AlertConfigError(ValueError):
    """Ungültige Eingabe; die Meldung darf der Benutzer lesen."""


def _path(data_dir: Path | str) -> Path:
    return Path(data_dir).joinpath(FILE_NAME)  # SEC-PATH-OK: feste Namenskonstante


def read_file(data_dir: Path | str) -> dict[str, str]:
    try:
        raw = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if k in ENV_KEYS and isinstance(v, str) and v.strip()}


def effective(data_dir: Path | str | None, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Wirksame Einstellung: Datei als Grundlage, nicht leere Umgebungsvariablen haben Vorrang."""
    env = os.environ if environ is None else environ
    config = read_file(data_dir) if data_dir else {}
    for key, env_name in ENV_KEYS.items():
        value = str(env.get(env_name, "")).strip()
        if value:
            config[key] = value
    return config


def status(data_dir: Path | str, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Für die Oberfläche: was ist eingerichtet (ohne Geheimnisse)."""
    config = effective(data_dir, environ)
    ntfy = config.get("ntfy_url", "")
    host = urllib.parse.urlparse(ntfy).hostname if ntfy else None
    return {
        "telegram": bool(config.get("telegram_token") and config.get("telegram_chat")),
        "telegram_chat": config.get("telegram_chat", ""),
        "ntfy": bool(ntfy),
        "ntfy_host": host or "",
    }


def _check_ntfy(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AlertConfigError("Die ntfy-Adresse muss mit http:// oder https:// beginnen.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if parsed.hostname.lower() in ("localhost", "metadata.google.internal") or (
        address and (address.is_loopback or address.is_link_local or address.is_unspecified)
    ):
        raise AlertConfigError("Diese ntfy-Adresse ist nicht erlaubt (lokal oder Link-Local).")
    return url


def write(data_dir: Path | str, update: dict[str, Any]) -> dict[str, Any]:
    """Meldewege speichern. Ein leerer Wert löscht die Einstellung, ein fehlender Schlüssel lässt sie unverändert."""
    config = read_file(data_dir)
    for key in ENV_KEYS:
        if key not in update:
            continue
        value = str(update[key] or "").strip()
        if not value:
            config.pop(key, None)
            continue
        if key == "telegram_token" and not TELEGRAM_TOKEN_RX.fullmatch(value):
            raise AlertConfigError("Der Telegram-Token hat nicht die Form 123456789:ABC… (von @BotFather).")
        if key == "telegram_chat" and not TELEGRAM_CHAT_RX.fullmatch(value):
            raise AlertConfigError("Die Telegram-Chat-Nummer ist ungültig (Zahl oder @Kanalname).")
        if key == "ntfy_url":
            _check_ntfy(value)
        config[key] = value
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)  # enthält Zugangsdaten
    except OSError:
        pass
    tmp.replace(path)
    return status(data_dir, {})


def _post(url: str, data: bytes, timeout: float = 10.0) -> None:
    request = urllib.request.Request(url, data=data, method="POST")  # noqa: S310 - Adresse aus der eigenen Konfiguration
    urllib.request.urlopen(request, timeout=timeout).close()  # noqa: S310


def send(config: dict[str, str], text: str) -> dict[str, list[str]]:
    """Meldung an alle eingerichteten Wege. Rückgabe: ``sent`` und ``errors`` (nur Fehlerart, nie die Adresse/der Token)."""
    sent: list[str] = []
    errors: list[str] = []
    token, chat = config.get("telegram_token", ""), config.get("telegram_chat", "")
    if token and chat:
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
            _post(f"https://api.telegram.org/bot{token}/sendMessage", data)
            sent.append("telegram")
        except (OSError, ValueError) as exc:
            errors.append(f"telegram: {_reason(exc)}")
    ntfy = config.get("ntfy_url", "")
    if ntfy:
        try:
            _check_ntfy(ntfy)
            _post(ntfy, text.encode("utf-8"))
            sent.append("ntfy")
        except (OSError, ValueError) as exc:
            errors.append(f"ntfy: {_reason(exc)}")
    return {"sent": sent, "errors": errors}


def _reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return type(exc).__name__

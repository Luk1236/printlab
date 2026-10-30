"""Einstellungen des lokalen KI-Assistenten (Datei ``assistant.json`` im Datenordner).

PrintLab bringt kein Modell mit: Es spricht mit einem lokalen Modell-Server, der die OpenAI-kompatible Schnittstelle
anbietet (Ollama, llama.cpp, LM Studio …). Standard ist Ollama auf demselben Gerät. Die Adresse darf lokal oder im
Heimnetz liegen; Link-Local-Adressen (Cloud-Metadaten) werden abgelehnt.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.parse
from pathlib import Path
from typing import Any

FILE_NAME = "assistant.json"
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "base_url": "http://127.0.0.1:11434",
    "model": "qwen2.5:3b",
    "timeout_seconds": 180,
    "max_tokens": 500,
    # KI-Fehlererkennung (Fehlerhilfe): eigenes Bildmodell, Freigabe und
    # Mindest-Sicherheit. Leerer Modellname nutzt das Assistenten-Modell.
    "vision_model": "",
    "error_scan_enabled": False,
    "error_scan_min_confidence": 60,
}
TIMEOUT_RANGE = (10, 900)
TOKENS_RANGE = (50, 4000)


class AssistantConfigError(ValueError):
    pass


def _path(data_dir: Path | str) -> Path:
    return Path(data_dir).joinpath(FILE_NAME)  # SEC-PATH-OK: feste Namenskonstante


def _same_type(value: Any, default: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


def read(data_dir: Path | str) -> dict[str, Any]:
    """Gespeicherte Einstellungen, ergänzt um die Standardwerte (kaputte Dateien zählen als leer)."""
    try:
        raw = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    config = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key, default in DEFAULTS.items():
            if _same_type(raw.get(key), default):
                config[key] = raw[key]
    return config


def check_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AssistantConfigError("Die Adresse muss mit http:// oder https:// beginnen.")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if host == "metadata.google.internal" or (address and (address.is_link_local or address.is_unspecified)):
        raise AssistantConfigError("Diese Adresse ist nicht erlaubt (Link-Local).")
    return url.strip().rstrip("/")


def write(data_dir: Path | str, update: dict[str, Any]) -> dict[str, Any]:
    """Einstellungen speichern; fehlende Schlüssel bleiben unverändert, ungültige Werte werden abgelehnt."""
    config = read(data_dir)
    if "enabled" in update:
        if not isinstance(update["enabled"], bool):
            raise AssistantConfigError("„enabled“ muss wahr oder falsch sein.")
        config["enabled"] = update["enabled"]
    if "base_url" in update:
        config["base_url"] = check_url(str(update["base_url"] or ""))
    if "model" in update:
        model = str(update["model"] or "").strip()
        if not model or len(model) > 100:
            raise AssistantConfigError("Der Modellname fehlt oder ist zu lang.")
        config["model"] = model
    if "vision_model" in update:
        vision_model = str(update["vision_model"] or "").strip()
        if len(vision_model) > 100:
            raise AssistantConfigError("Der Name des Bildmodells ist zu lang.")
        config["vision_model"] = vision_model
    if "error_scan_enabled" in update:
        if not isinstance(update["error_scan_enabled"], bool):
            raise AssistantConfigError("„error_scan_enabled“ muss wahr oder falsch sein.")
        config["error_scan_enabled"] = update["error_scan_enabled"]
    if "error_scan_min_confidence" in update:
        value = update["error_scan_min_confidence"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise AssistantConfigError("Die Mindest-Sicherheit muss zwischen 0 und 100 liegen.")
        config["error_scan_min_confidence"] = value
    for key, (low, high), message in (
        ("timeout_seconds", TIMEOUT_RANGE, "Die Zeitgrenze muss zwischen 10 und 900 Sekunden liegen."),
        ("max_tokens", TOKENS_RANGE, "Die Antwortlänge muss zwischen 50 und 4000 Wörtern (Tokens) liegen."),
    ):
        if key in update:
            value = update[key]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise AssistantConfigError(message)
            config[key] = value
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    tmp.replace(path)
    return config

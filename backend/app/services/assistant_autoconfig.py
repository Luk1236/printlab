"""Automatische Einrichtung des lokalen KI-Assistenten (Ollama & Co.).

Ziel: Der Assistent ist nach dem Start ohne Handgriff nutzbar, sobald auf dem Gerät (oder unter der eingetragenen
Adresse) ein Modell-Server läuft.

- ``pick_model``: wählt aus den installierten Modellen ein passendes Chat-Modell (bevorzugt kleine, schnelle Modelle,
  Embedding-Modelle werden nie gewählt). Ein bereits eingetragenes, vorhandenes Modell bleibt.
- ``pick_vision_model``: ein Bildmodell für die KI-Fehlererkennung, falls eines installiert ist.
- ``autoconfigure``: sucht den Server (eingetragene Adresse zuerst, dann ``127.0.0.1:11434``), trägt Adresse und
  Modell ein und schaltet den Assistenten ein.
- ``ensure_on_startup``: dasselbe beim Start, aber nur, wenn der Benutzer den Assistenten nicht ausdrücklich
  ausgeschaltet hat (Datei fehlt) oder das eingetragene Modell fehlt. Danach wird das Modell vorgeladen.
- ``warmup``: lädt das Modell in den Speicher (Ollama ``/api/generate`` mit ``keep_alive``), damit die erste Antwort
  nicht erst nach dem Laden kommt.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from backend.app.services import assistant_config, assistant_llm

logger = logging.getLogger(__name__)

CANDIDATE_URLS = ("http://127.0.0.1:11434", "http://localhost:11434")

# Reihenfolge = Vorliebe: klein und schnell genug für einen Raspberry Pi 5, gut auf Deutsch.
PREFERRED_MODELS = (
    "qwen3.5:4b",
    "qwen3:4b",
    "qwen2.5:3b",
    "qwen3.5:2b",
    "qwen3:1.7b",
    "llama3.2:3b",
    "gemma3:4b",
    "phi4-mini",
    "qwen2.5:7b",
    "qwen3:8b",
    "llama3.1:8b",
    "gemma4:12b",
)
_FAMILIES = ("qwen", "llama", "gemma", "phi", "mistral", "granite", "deepseek")
_NOT_CHAT = ("embed", "bge", "minilm", "rerank", "nomic", "snowflake", "whisper")
_VISION_HINTS = ("vl", "llava", "vision", "gemma3", "gemma4", "minicpm-v", "moondream")
KEEP_ALIVE = "30m"

StatusFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _size_billion(name: str) -> float:
    """Parametergröße aus dem Namen (``qwen2.5:3b`` → 3.0); unbekannt = 99 (wird hinten einsortiert)."""
    match = re.search(r"[:\-_](\d+(?:\.\d+)?)b\b", name.lower())
    return float(match.group(1)) if match else 99.0


def _is_chat(name: str) -> bool:
    lowered = name.lower()
    return not any(word in lowered for word in _NOT_CHAT)


def pick_model(models: list[str], current: str | None = None) -> str | None:
    """Passendes Chat-Modell aus der Liste oder None, wenn keines brauchbar ist."""
    usable = [m for m in models if isinstance(m, str) and m and _is_chat(m)]
    if not usable:
        return None
    if current and current in usable:
        return current
    for preferred in PREFERRED_MODELS:
        if preferred in usable:
            return preferred
    known = [m for m in usable if m.lower().startswith(_FAMILIES)]
    pool = known or usable
    # Kleinstes Modell ab 1 Mrd. Parametern zuerst: auf dem Pi zählt die Antwortzeit.
    sized = sorted(pool, key=lambda m: (_size_billion(m) < 1.0, _size_billion(m)))
    return sized[0]


def pick_vision_model(models: list[str]) -> str:
    """Erstes installiertes Bildmodell (für die KI-Fehlererkennung) oder ``""``."""
    for name in models:
        if isinstance(name, str) and _is_chat(name) and any(hint in name.lower() for hint in _VISION_HINTS):
            return name
    return ""


def _candidate_urls(config: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for url in (config.get("base_url"), *CANDIDATE_URLS):
        if isinstance(url, str) and url and url.rstrip("/") not in urls:
            urls.append(url.rstrip("/"))
    return urls


async def autoconfigure(
    data_dir: Path | str,
    status_fn: StatusFn | None = None,
    *,
    enable: bool = True,
) -> dict[str, Any]:
    """Server suchen, Modell wählen, eintragen. Liefert ``state``: ``ready`` | ``no_model`` | ``no_server``."""
    status_fn = status_fn or assistant_llm.status
    config = assistant_config.read(data_dir)
    tried: list[str] = []
    for url in _candidate_urls(config):
        tried.append(url)
        status = await status_fn({**config, "base_url": url})
        if not status.get("reachable"):
            continue
        models = [str(m) for m in status.get("models") or []]
        model = pick_model(models, config.get("model"))
        if model is None:
            return {"state": "no_model", "base_url": url, "models": models, "config": config, "changed": False}
        update: dict[str, Any] = {"base_url": url, "model": model}
        if enable:
            update["enabled"] = True
        if not config.get("vision_model"):
            vision = pick_vision_model(models)
            if vision:
                update["vision_model"] = vision
        saved = assistant_config.write(data_dir, update)
        return {
            "state": "ready",
            "base_url": url,
            "model": model,
            "models": models,
            "config": saved,
            "changed": saved != config,
        }
    return {"state": "no_server", "tried": tried, "models": [], "config": config, "changed": False}


async def warmup(config: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Modell vorladen (Ollama-Schnittstelle). Wirft nie; False, wenn es nicht ging (z. B. kein Ollama)."""
    try:
        async with httpx.AsyncClient(timeout=float(config.get("timeout_seconds", 180)), transport=transport) as client:
            response = await client.post(
                f"{config['base_url']}/api/generate",
                json={"model": config["model"], "prompt": "", "keep_alive": KEEP_ALIVE, "stream": False},
            )
        return response.status_code == 200
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.debug("Assistent-Vorladen übersprungen: %s", exc)
        return False


def _needs_startup_setup(data_dir: Path | str) -> bool:
    """Beim Start nur eingreifen, wenn der Benutzer noch nichts entschieden hat oder das Modell fehlen könnte."""
    if not Path(data_dir).joinpath(assistant_config.FILE_NAME).is_file():  # SEC-PATH-OK: feste Namenskonstante
        return True
    return bool(assistant_config.read(data_dir).get("enabled"))


async def ensure_on_startup(data_dir: Path | str, status_fn: StatusFn | None = None) -> dict[str, Any]:
    """Beim Start: Assistent einrichten (falls nicht ausdrücklich aus) und Modell vorladen. Wirft nie."""
    try:
        if not _needs_startup_setup(data_dir):
            return {"state": "skipped"}
        result = await autoconfigure(data_dir, status_fn)
        if result["state"] == "ready":
            logger.info("[PrintLab] KI-Assistent bereit: %s unter %s", result["model"], result["base_url"])
            await warmup(result["config"])
        else:
            logger.info("[PrintLab] KI-Assistent nicht eingerichtet (%s)", result["state"])
        return result
    except Exception as exc:  # noqa: BLE001 - darf den Start nie verhindern
        logger.debug("[PrintLab] KI-Auto-Einrichtung übersprungen: %s", exc)
        return {"state": "failed"}

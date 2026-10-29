"""Verbindung zum lokalen Modell-Server (OpenAI-kompatible Schnittstelle, z. B. Ollama).

Nur ``POST /v1/chat/completions`` und ``GET /v1/models``. Fehler werden in verständliche Meldungen übersetzt, damit
die Oberfläche sagen kann, was zu tun ist (Server starten, Modell laden, mehr Zeit geben).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AssistantError(RuntimeError):
    """Der Modell-Server ist nicht erreichbar oder hat nicht brauchbar geantwortet."""


def _client(timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False)


async def status(config: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Erreichbarkeit und vorhandene Modelle des Servers."""
    result: dict[str, Any] = {"reachable": False, "models": [], "model_present": False, "error": ""}
    try:
        async with _client(8.0, transport) as client:
            response = await client.get(f"{config['base_url']}/v1/models")
        if response.status_code != 200:
            result["error"] = f"Der Modell-Server hat mit Fehler {response.status_code} geantwortet."
            return result
        data = response.json().get("data", [])
        names = [str(m.get("id", "")) for m in data if isinstance(m, dict) and m.get("id")]
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("assistant status failed: %s", exc)
        result["error"] = f"Kein Modell-Server unter {config['base_url']} erreichbar. Läuft Ollama?"
        return result
    result.update(reachable=True, models=names[:50], model_present=config["model"] in names)
    return result


async def chat(
    config: dict[str, Any], messages: list[dict[str, str]], transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Eine Antwort des Modells (ohne Streaming)."""
    body = {
        "model": config["model"],
        "messages": messages,
        "max_tokens": config["max_tokens"],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        async with _client(float(config["timeout_seconds"]), transport) as client:
            response = await client.post(f"{config['base_url']}/v1/chat/completions", json=body)
    except httpx.TimeoutException as exc:
        raise AssistantError(
            f"Das Modell hat nicht rechtzeitig geantwortet (nach {config['timeout_seconds']} Sekunden)."
        ) from exc
    except httpx.HTTPError as exc:
        raise AssistantError(f"Kein Modell-Server unter {config['base_url']} erreichbar. Läuft Ollama?") from exc
    if response.status_code == 404:
        raise AssistantError(f"Modell „{config['model']}“ nicht gefunden. Auf dem Pi: ollama pull {config['model']}")
    if response.status_code != 200:
        raise AssistantError(f"Der Modell-Server hat mit Fehler {response.status_code} geantwortet.")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AssistantError("Die Antwort des Modells war leer oder unlesbar.") from exc
    if not isinstance(content, str) or not content.strip():
        raise AssistantError("Die Antwort des Modells war leer oder unlesbar.")
    return content.strip()

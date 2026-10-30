"""KI-Fehlererkennung mit dem lokalen Bildmodell (Ollama o. ä.).

Nimmt ein Kamerabild auf, fragt das lokale Modell nach dem passenden
Fehlerbild aus ``services/error_patterns.py`` und legt Treffer in
``data/ai_error_findings.jsonl`` ab. Die Fehlerhilfe zeigt daraus „wie oft
erkannt“ und die letzten Begründungen.

Bewusst zurückhaltend: Die Erkennung ist ein Hinweis, keine Diagnose. Sie ist
standardmäßig aus, läuft nur mit freigegebenem Bildmodell und speichert nur
Treffer ab der eingestellten Mindest-Sicherheit. Die Rohbilder kommen aus der
Fehlerbild-Sammlung oder aus einem manuellen Upload.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.app.core.config import settings
from backend.app.services import assistant_config, error_patterns
from backend.app.utils import failure_images

logger = logging.getLogger(__name__)

FINDINGS_PATH = settings.base_dir / "ai_error_findings.jsonl"
FEEDBACK_PATH = settings.base_dir / "ai_error_feedback.jsonl"
MAX_FINDINGS = 2000
MAX_IMAGE_BYTES = 15 * 1024 * 1024
_ALLOWED_IDS = {pattern["id"] for pattern in error_patterns.PATTERNS}
_lock = threading.Lock()
_write_lock = threading.Lock()
_auto_semaphore = asyncio.Semaphore(1)
_batch_lock = threading.Lock()
_batch: dict[str, Any] = {"running": False, "done": 0, "total": 0, "matched": 0, "errors": 0, "started": None}


class AiScanError(RuntimeError):
    """Modell nicht erreichbar, ohne Bildunterstützung oder Antwort unbrauchbar."""


def _prepare_image(image_bytes: bytes) -> str:
    """Bild verkleinern (max. 768 px) und als base64-JPEG zurückgeben."""
    if not image_bytes:
        raise AiScanError("Das Bild ist leer.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise AiScanError("Das Bild ist größer als 15 MB.")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((768, 768))
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=82)
            return base64.b64encode(buffer.getvalue()).decode()
    except AiScanError:
        raise
    except Exception as exc:  # noqa: BLE001 - jede Bildbibliothek meldet anders
        raise AiScanError("Das Bild konnte nicht gelesen werden (JPEG, PNG oder WebP erwartet).") from exc


def _prompt() -> str:
    lines = []
    for pattern in error_patterns.PATTERNS:
        lines.append(f"- {pattern['id']}: {pattern['title']} — {pattern['summary']}")
    allowed = "\n".join(lines)
    return (
        "Du prüfst ein Kamerabild eines FDM-3D-Drucks. Ordne den sichtbaren Fehler genau einem der folgenden "
        'Fehlerbilder zu. Wenn kein Fehler klar erkennbar ist, antworte mit "none". Antworte ausschließlich mit '
        'JSON in der Form {"pattern_id": "<id oder none>", "confidence": 0.0 bis 1.0, "reason": "kurze Begründung auf Deutsch"}.\n\n'
        f"Erlaubte Fehlerbilder:\n{allowed}"
    )


def _parse_reply(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AiScanError("Das Modell hat kein verwertbares JSON geliefert.")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise AiScanError("Das Modell hat kein verwertbares JSON geliefert.") from exc
    pattern_id = data.get("pattern_id")
    if pattern_id in (None, "", "none", "null", "unauffällig"):
        pattern_id = None
    elif pattern_id not in _ALLOWED_IDS:
        raise AiScanError(f"Das Modell nannte ein unbekanntes Fehlerbild: {pattern_id!r}.")
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence > 1:
        confidence = confidence / 100
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "").strip()[:300]
    return {"pattern_id": pattern_id, "confidence": confidence, "reason": reason}


async def _ollama_vision(base_url: str, model: str, image_b64: str, timeout: float) -> str:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _prompt(), "images": [image_b64]}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 220},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}/api/chat", json=body)
    if response.status_code == 404:
        raise AiScanError(f"Bildmodell „{model}“ nicht gefunden. Auf dem Gerät: ollama pull {model}")
    if response.status_code != 200:
        raise AiScanError(f"Der Modell-Server hat mit Fehler {response.status_code} geantwortet.")
    try:
        content = response.json()["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AiScanError("Die Antwort des Modells war leer oder unlesbar.") from exc
    if not isinstance(content, str) or not content.strip():
        raise AiScanError("Die Antwort des Modells war leer oder unlesbar.")
    return content


async def _openai_vision(base_url: str, model: str, image_b64: str, timeout: float) -> str:
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt()},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
        "max_tokens": 220,
        "temperature": 0,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}/v1/chat/completions", json=body)
    if response.status_code == 404:
        raise AiScanError(f"Bildmodell „{model}“ nicht gefunden. Auf dem Gerät: ollama pull {model}")
    if response.status_code != 200:
        raise AiScanError(f"Der Modell-Server hat mit Fehler {response.status_code} geantwortet.")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiScanError("Die Antwort des Modells war leer oder unlesbar.") from exc
    if not isinstance(content, str) or not content.strip():
        raise AiScanError(
            "Das Modell hat nur intern gedacht und keine Antwort geliefert. "
            "Ein Ollama-Bildmodell ohne Denkmodus (z. B. qwen2.5vl oder llava) hilft hier."
        )
    return content


async def _is_ollama(base_url: str, timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url}/api/tags")
        return response.status_code == 200 and isinstance(response.json().get("models"), list)
    except (httpx.HTTPError, ValueError):
        return False


async def classify(image_bytes: bytes, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ein Bild klassifizieren; Ergebnis ohne Speicherung."""
    config = config or assistant_config.read(settings.base_dir)
    model = str(config.get("vision_model") or config.get("model") or "").strip()
    if not model:
        raise AiScanError("Es ist kein Bildmodell eingestellt.")
    base_url = str(config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    timeout = float(max(60, min(600, int(config.get("timeout_seconds") or 180))))
    image_b64 = _prepare_image(image_bytes)
    started = time.monotonic()
    if await _is_ollama(base_url, timeout=min(timeout, 5.0)):
        content = await _ollama_vision(base_url, model, image_b64, timeout)
    else:
        content = await _openai_vision(base_url, model, image_b64, timeout)
    result = _parse_reply(content)
    result["model"] = model
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def record(
    result: dict[str, Any],
    *,
    source: str,
    printer_id: int | None = None,
    image_name: str | None = None,
) -> dict[str, Any] | None:
    """Treffer ablegen; ohne erkanntes Fehlerbild wird nichts gespeichert."""
    if not result.get("pattern_id"):
        return None
    entry = {
        "id": uuid.uuid4().hex[:16],
        "ts": datetime.now(timezone.utc).isoformat(),
        "pattern_id": result["pattern_id"],
        "confidence": round(float(result.get("confidence", 0)), 3),
        "reason": str(result.get("reason") or "")[:300],
        "model": result.get("model"),
        "duration_ms": result.get("duration_ms"),
        "source": source,
        "printer_id": printer_id,
        "image_name": image_name,
    }
    with _write_lock:
        FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FINDINGS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim()
    return entry


def _trim() -> None:
    try:
        lines = FINDINGS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_FINDINGS:
        return
    keep = lines[-MAX_FINDINGS:]
    tmp = FINDINGS_PATH.with_suffix(".tmp")
    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    tmp.replace(FINDINGS_PATH)


def _all() -> list[dict[str, Any]]:
    try:
        lines = FINDINGS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("pattern_id"):
            out.append(entry)
    return out


def _feedback_lines() -> list[dict[str, Any]]:
    try:
        lines = FEEDBACK_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("finding_id"):
            out.append(entry)
    return out


def _feedback_map() -> dict[str, str]:
    """Letzte Bewertung je Treffer."""
    latest: dict[str, str] = {}
    for entry in _feedback_lines():
        finding_id = str(entry.get("finding_id") or "")
        verdict = str(entry.get("verdict") or "")
        if finding_id and verdict in ("correct", "wrong"):
            latest[finding_id] = verdict
    return latest


def record_feedback(finding_id: str, verdict: str) -> dict[str, Any]:
    """Einen Treffer als richtig oder falsch bewerten (letzte Bewertung zählt)."""
    if verdict not in ("correct", "wrong"):
        raise ValueError("verdict muss 'correct' oder 'wrong' sein")
    finding = find_finding(finding_id)
    if finding is None:
        raise KeyError(finding_id)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "finding_id": finding_id,
        "verdict": verdict,
        "pattern_id": finding.get("pattern_id"),
    }
    with _write_lock:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def feedback_summary() -> dict[str, int]:
    counts_ = {"correct": 0, "wrong": 0}
    for verdict in _feedback_map().values():
        counts_[verdict] += 1
    return counts_


def find_finding(finding_id: str) -> dict[str, Any] | None:
    if not finding_id:
        return None
    with _lock:
        for entry in _all():
            if entry.get("id") == finding_id:
                return entry
    return None


def list_findings(limit: int = 50, pattern_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        entries = _all()
        verdicts = _feedback_map()
    if pattern_id:
        entries = [entry for entry in entries if entry.get("pattern_id") == pattern_id]
    for entry in entries:
        entry["verdict"] = verdicts.get(str(entry.get("id") or ""))
    return entries[: max(1, min(limit, MAX_FINDINGS))]


def counts() -> dict[str, int]:
    out: dict[str, int] = {}
    with _lock:
        for entry in _all():
            pattern_id = str(entry.get("pattern_id"))
            out[pattern_id] = out.get(pattern_id, 0) + 1
    return out


def batch_status() -> dict[str, Any]:
    with _batch_lock:
        return dict(_batch)


def start_batch(limit: int = 10) -> dict[str, Any]:
    """Gesammelte Fehlerbilder der Reihe nach prüfen (Hintergrund).

    Bereits geprüfte Bilder (gleicher Dateiname in den Treffern) werden
    übersprungen, damit ein zweiter Lauf nicht dieselbe Arbeit macht.
    """
    config = assistant_config.read(settings.base_dir)
    if not str(config.get("vision_model") or config.get("model") or "").strip():
        raise AiScanError("Es ist kein Bildmodell eingestellt.")
    capped = max(1, min(50, int(limit)))
    with _batch_lock:
        if _batch["running"]:
            return dict(_batch)
        images = failure_images.list_failure_images()[:capped]
        seen = {entry.get("image_name") for entry in _all() if entry.get("image_name")}
        todo = [image["name"] for image in images if image["name"] not in seen]
        _batch.update(
            {
                "running": True,
                "done": 0,
                "total": len(todo),
                "matched": 0,
                "errors": 0,
                "started": datetime.now(timezone.utc).isoformat(),
            }
        )
        if not todo:
            _batch["running"] = False
            return dict(_batch)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        with _batch_lock:
            _batch["running"] = False
        raise AiScanError("Keine Ereignisschleife für die Stapelprüfung.") from exc
    loop.create_task(_run_batch(todo, config))
    return batch_status()


async def _run_batch(names: list[str], config: dict[str, Any]) -> None:
    try:
        for name in names:
            path = failure_images.find_failure_image(name)
            if path is None:
                with _batch_lock:
                    _batch["done"] += 1
                continue
            try:
                image = await asyncio.to_thread(path.read_bytes)
                async with _auto_semaphore:
                    result = await scan_and_record(image, source="failure_image", image_name=name, config=config)
                with _batch_lock:
                    _batch["done"] += 1
                    if result.get("pattern_id"):
                        _batch["matched"] += 1
            except Exception:  # noqa: BLE001 - ein kaputtes Bild stoppt den Rest nicht
                logger.warning("AI batch scan failed for %s", name, exc_info=True)
                with _batch_lock:
                    _batch["done"] += 1
                    _batch["errors"] += 1
    finally:
        with _batch_lock:
            _batch["running"] = False


async def scan_and_record(
    image_bytes: bytes,
    *,
    source: str,
    printer_id: int | None = None,
    image_name: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Klassifizieren und (ab Mindest-Sicherheit) ablegen."""
    config = config or assistant_config.read(settings.base_dir)
    result = await classify(image_bytes, config)
    threshold = int(config.get("error_scan_min_confidence", 60))
    if result.get("pattern_id") and float(result.get("confidence", 0)) * 100 >= threshold:
        record(result, source=source, printer_id=printer_id, image_name=image_name)
    return result


def schedule_failure_scan(image_bytes: bytes, printer_id: int | None, source: str) -> bool:
    """Automatische Prüfung eines Fehlerbilds anstoßen, wenn freigegeben."""
    try:
        config = assistant_config.read(settings.base_dir)
    except Exception:  # noqa: BLE001 - nie die Meldung stören
        return False
    if not config.get("error_scan_enabled"):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    async def _run() -> None:
        async with _auto_semaphore:
            try:
                await scan_and_record(image_bytes, source=source, printer_id=printer_id, config=config)
            except Exception:  # noqa: BLE001 - Hintergrundprüfung darf nichts abbrechen
                logger.warning("AI error scan failed", exc_info=True)

    loop.create_task(_run())
    return True

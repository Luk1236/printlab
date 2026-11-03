"""Outbound Webhooks Engine für PrintLab.

Ermöglicht das automatische Senden von Echtzeit-Ereignissen an externe Systeme
(Discord, Slack, Make, Zapier, Home Assistant, ERP-Systeme):
- print.started
- print.completed
- print.failed
- plate.swap_required
- plate.swap_done
- safety.emergency_stop
- maintenance.wear_alert

Mit kryptografischer HMAC-SHA256-Signaturprüfung (Header 'X-PrintLab-Signature')
und SSRF-Schutz vor unberechtigtem Zugriff auf interne Netze und Metadatendienste.

Zweistufiger SSRF-Schutz:
- Bei der Registrierung werden IP-Literale, numerische/hexadezimale Host-Kodierungen
  (SSRF-Klassiker wie ``http://2130706433/`` oder ``http://0x7f000001/``), Cloud-
  Metadaten-Hostnamen und privat Netzwerkadressen abgelehnt. DNS-Auflösung liegt
  bewusst NICHT in diesem Pfad: Registrierung soll auch ohne Netz funktionieren
  (Inbetriebnahme, CI) und nicht in den Request-Pfad blockender Auflösung laufen.
- Vor jeder Zustellung wird die URL erneut geprüft und der Hostname explizit per
  ``socket.getaddrinfo`` aufgelöst; jede resultierende Adresse wird gegen die
  Schutztregeln validiert. Damit werden Domains blockiert, die erst zur
  Zustellungszeit auf private Adressen oder Metadatendienste auflösen
  (DNS-Rebinding/Lookup-Spoofing). Die verbleibende TOCTOU-Lücke zwischen
  Auflösung und Connect ist eng (direkt aneinanderfolgend) und dokumentiert.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

WEBHOOKS_FILE = settings.base_dir / "outbound_webhooks.json"
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="PrintLabWebhookWorker")
# Begrenzt gleichzeitige Zustellungen: ein Ziel-Backlog (langsame Empfänger) stoppt
# die Verteilung nicht, aber ein Endloswachstum ausstehender Requests wird verhindert.
_MAX_CONCURRENT_DELIVERIES = 32
_inflight = threading.Semaphore(_MAX_CONCURRENT_DELIVERIES)
# Obergrenze registrierbarer Webhooks — begrenzt Persistenzgröße und Fan-out.
MAX_WEBHOOKS = 200

# Retry mit exponentiellem Backoff für transiente Fehler (Netzwerk, 5xx, 429).
# Verfolgt die Zustellhistorie im Hook-Record (failure_streak, last_delivery_*)
# und schreibt persistent fehlende Ziele nach _DISABLE_AFTER_FAILURES Fehlern in
# Folge still (Dead-Letter): dead_lettered=True, enabled=False. Der Betreiber
# sieht das in der Webhook-Verwaltung und kann den Hook reaktivieren.
_RETRY_DELAYS = (1.0, 4.0)  # Sekunden zwischen Versuchen; Versuche = 1 + len()
_DISABLE_AFTER_FAILURES = 5

ALL_EVENTS = (
    "print.started",
    "print.completed",
    "print.failed",
    "plate.swap_required",
    "plate.swap_done",
    "safety.emergency_stop",
    "maintenance.wear_alert",
)

# Cloud-Metadatendienste (AWS, GCP, Azure, OpenStack) — auch nicht als Domain
# umgehbar, weil zusätzlich jede aufgelöste Adresse geprüft wird.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "instance-data",
        "fd00:ec2::254",
    }
)

# Hostnamen ohne einen einzigen Buchstaben (z. B. "2130706433", "127.0.0.1",
# "0x7f.1", "127.1") sind Resolver-Spielzeug für SSRF-Kodierungen und werden
# als IP-Literal behandelt; was sich nicht sauber als IP dekodieren lässt,
# wird abgelehnt, statt auf dem Resolver-Roulette weiterzuleben.
_NUMERIC_HOST_RE = re.compile(r"^[0-9a-fA-F.:]+$")


def _check_ip(ip: ipaddress.IPAddress, allow_local: bool) -> str | None:
    """Liefert einen Verbotsgrund für die Adresse oder ``None``, wenn zulässig.

    IPv6-Mapping wird berücksichtigt: ``::ffff:127.0.0.1`` ist loopback, auch
    wenn die IPv6-Flags es von sich aus nicht sagen.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _check_ip(ip.ipv4_mapped, allow_local)

    if ip.is_loopback:
        return "Loopback-Adressen (127.0.0.1 / ::1) sind für ausgehende Webhooks gesperrt."
    if not allow_local and ip.is_private:
        return f"Private IP-Adressen ({ip}) sind für Webhooks im Produktivmodus gesperrt."
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or getattr(ip, "is_unspecified", False):
        return f"Spezielle IP-Adressbereiche ({ip}) sind nicht zulässig."
    return None


def _ip_from_hostname(hostname: str) -> ipaddress.IPAddress | None:
    """Dekodiert einen Hostnamen als IP-Literal — inklusive Zahlenkodierungen.

    Reine Ziffern- bzw. Hex-Kodierungen (``2130706433``, ``0x7f000001``) sind
    gültige IPv4-Darstellungen vieler Resolver, die ``ipaddress`` aber verwirft.
    Sie werden hier explizit dekodiert, damit sie dieselbe Prüfung durchlaufen.
    Rückgabe ``None`` = kein (sinnvoll interpretierbares) IP-Literal.
    """
    if _NUMERIC_HOST_RE.fullmatch(hostname) and re.search(r"[.:]", hostname) is None and hostname.isdigit():
        try:
            return ipaddress.ip_address(int(hostname, 10))
        except ValueError:
            pass
    if hostname.startswith("0x") and re.fullmatch(r"0x[0-9a-fA-F]{1,16}", hostname):
        try:
            return ipaddress.ip_address(int(hostname, 16))
        except ValueError:
            return None
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def is_safe_webhook_url(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """Prüft eine Ziel-URL gegen SSRF-Angriffe (Metadatendienste und unbefugte Netze).

    Registrierungszeit-Prüfung ohne DNS: IP-Literale, Zahlenkodierungen und
    Metadaten-Hostnamen werden abgelehnt. Domains werden hier nicht aufgelöst —
    die Zustellungsprüfung (``_validate_resolved_host``) deckt deren Auflösung ab.

    Returns:
        (is_safe, reason)
    """
    clean_url = (url or "").strip()
    if not clean_url:
        return False, "URL darf nicht leer sein."

    try:
        parsed = urllib.parse.urlparse(clean_url)
    except Exception:
        return False, "Ungültiges URL-Format."

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Ungültiges Protokoll '{parsed.scheme}'. Es sind nur HTTP und HTTPS zulässig."

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "Kein gültiger Hostname angegeben."

    if hostname in _BLOCKED_HOSTNAMES:
        return False, f"Zugriff auf Cloud-Instanz-Metadaten ({hostname}) ist strikt gesperrt."

    allow_local = allow_private or bool(os.environ.get("PRINTLAB_ALLOW_LOCAL_WEBHOOKS"))

    # 1. IP-Literal (auch Zahlenkodierungen) direkt bewerten.
    ip = _ip_from_hostname(hostname)
    if ip is not None:
        reason = _check_ip(ip, allow_local)
        if reason:
            return False, reason
        return True, "URL ist zulässig."

    # 2. Nicht-IP-Hostnamen, die trotzdem nur aus Ziffern und Punkten bestehen
    #    (z. B. "127.1" — von Resolvern als 127.0.0.1 gedeutet): ablehnen.
    if _NUMERIC_HOST_RE.fullmatch(hostname) and re.search(r"[a-zA-Z]", hostname) is None:
        return False, f"Host '{hostname}' ist nicht eindeutig als IP dekodierbar und daher unzulässig."

    # 3. Echte Domainnamen: an dieser Stelle zulässig; die Auflösung zur
    #    Zustellungszeit wird separat validiert (DNS-Rebinding-Schutz).
    return True, "URL ist zulässig."


def _validate_resolved_host(hostname: str, allow_local: bool) -> str | None:
    """Löst einen Hostnamen auf und validiert jede resultierende Adresse.

    Läuft zur Zustellungszeit im Worker-Thread. Rückgabe ist ein Verbotsgrund
    oder ``None``, wenn jede aufgelöste Adresse zulässig ist.
    """
    ip_literal = _ip_from_hostname(hostname)
    if ip_literal is not None:
        # IP-Literal: kein DNS beteiligt; bereits durch is_safe_webhook_url geprüft.
        return None
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        return f"Host '{hostname}' kann nicht aufgelöst werden: {exc}"

    for info in infos:
        addr = info[4][0] if info and info[4] else ""
        # IPv6-Zonen-Index ("fe80::1%eth0") ablegen — die Zone ändert die Adresse nicht.
        bare = addr.split("%", 1)[0] if isinstance(addr, str) else ""
        if not bare:
            continue
        try:
            ip = ipaddress.ip_address(bare)
        except ValueError:
            return f"Unaufgelösbare Zieladresse '{bare}' für '{hostname}'."
        reason = _check_ip(ip, allow_local)
        if reason:
            return reason
    return None


def mask_secret(secret: str) -> str:
    """Maskiert ein HMAC-Geheimnis für API-Antworten."""
    return "***" if (secret or "").strip() else ""


def mask_webhook(hook: dict[str, Any]) -> dict[str, Any]:
    """Liefert eine Kopie des Webhooks ohne das Klartext-Geheimnis."""
    masked = {k: v for k, v in (hook or {}).items() if k != "secret"}
    masked["secret"] = mask_secret((hook or {}).get("secret", ""))
    masked["secret_configured"] = bool((hook or {}).get("secret", "").strip())
    return masked


def _load_webhooks() -> list[dict[str, Any]]:
    if not WEBHOOKS_FILE.is_file():
        return []
    try:
        data = json.loads(WEBHOOKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Konnte outbound_webhooks.json nicht lesen: %s", exc)
        return []


def _save_webhooks(webhooks: list[dict[str, Any]]) -> bool:
    """Schreibt den Webhook-Speicher atomar (tmp + replace). Erfolg als bool."""
    try:
        WEBHOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = WEBHOOKS_FILE.with_name(WEBHOOKS_FILE.name + ".tmp")
        tmp.write_text(json.dumps(webhooks, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(WEBHOOKS_FILE)
        return True
    except Exception as exc:
        logger.error("Fehler beim Speichern von outbound_webhooks.json: %s", exc)
        return False


def _validate_event_list(events: list[str] | None, allow: frozenset[str]) -> list[str]:
    """Prüft die Event-Abos ("*" oder bekannte Ereignisse) und normalisiert sie.

    Ein Tippfehler ("print.complted") würde sonst einen Webhook schaffen, der
    still niemals feuert — lieber gleich mit klarer Meldung ablehnen.
    """
    if events is None:
        return ["*"]
    if not isinstance(events, list):
        raise ValueError("'events' muss eine Liste von Ereignisnamen sein.")
    cleaned: list[str] = []
    for event in events:
        name = str(event).strip()
        if not name:
            continue
        if name != "*" and name not in allow:
            raise ValueError(f"Unbekanntes Ereignis '{name}'. Gültig sind: '*', {', '.join(ALL_EVENTS)}")
        if name not in cleaned:
            cleaned.append(name)
    return cleaned or ["*"]


def register_webhook(
    url: str,
    secret: str = "",
    events: list[str] | None = None,
    format_type: str = "generic",
    description: str = "",
    allow_private: bool = False,
) -> dict[str, Any]:
    """Registriert einen neuen ausgehenden Webhook nach vorheriger SSRF-Prüfung."""
    safe, reason = is_safe_webhook_url(url, allow_private=allow_private)
    if not safe:
        raise ValueError(reason)

    with _lock:
        webhooks = _load_webhooks()
        if len(webhooks) >= MAX_WEBHOOKS:
            raise ValueError(
                f"Maximal {MAX_WEBHOOKS} Webhooks können registriert werden. Nicht mehr benötigte bitte löschen."
            )
        hook = {
            "id": f"wh_{uuid.uuid4().hex[:12]}",
            "url": url.strip(),
            "secret": secret.strip(),
            "events": _validate_event_list(events, allow=frozenset(ALL_EVENTS)),
            "format": format_type if format_type in ("generic", "discord", "slack") else "generic",
            "description": description.strip(),
            "enabled": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        webhooks.append(hook)
        if not _save_webhooks(webhooks):
            raise RuntimeError(
                "Webhook-Registrierung konnte nicht persistiert werden "
                f"(Schreibzugriff auf {WEBHOOKS_FILE.name} fehlgeschlagen)."
            )
        return hook


def list_webhooks(include_secret: bool = False) -> list[dict[str, Any]]:
    """Gibt registrierte Webhooks zurück — im Standard mit maskiertem Geheimnis.

    ``include_secret=True`` ist für interne Maschinenpfade (Zustellung) gedacht;
    API-Antworten nutzen die maskierte Variante, damit das HMAC-Geheimnis das
    Backend nie im Klartext verlässt.
    """
    with _lock:
        webhooks = _load_webhooks()
    if include_secret:
        return webhooks
    return [mask_webhook(hook) for hook in webhooks]


def delete_webhook(webhook_id: str) -> bool:
    """Entfernt einen registrierten Webhook anhand seiner ID."""
    with _lock:
        webhooks = _load_webhooks()
        orig_len = len(webhooks)
        webhooks = [w for w in webhooks if w.get("id") != webhook_id]
        if len(webhooks) < orig_len:
            return _save_webhooks(webhooks)
        return False


def build_signature(secret: str, body_bytes: bytes) -> str:
    """Berechnet die HMAC-SHA256 Signatur für den Webhook-Payload."""
    if not secret:
        return ""
    mac = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _event_matches(hook: dict[str, Any], event: str) -> bool:
    """Enthält das Abonnement des Hooks das Ereignis ("*" gilt als Alles)?"""
    events = hook.get("events")
    if not isinstance(events, list):
        return False
    return "*" in events or event in events


def format_payload(format_type: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Formatiert den Ereignis-Payload für das jeweilige Zielsystem (Generic, Discord oder Slack)."""
    title = f"PrintLab: {event}"
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    if format_type == "discord":
        color = (
            0x00AE42
            if "completed" in event or "done" in event
            else (0xEF4444 if "emergency" in event or "failed" in event else 0x3B82F6)
        )
        fields = [{"name": str(k), "value": str(v), "inline": True} for k, v in list(data.items())[:6]]
        return {
            "content": f"🚨 **PrintLab Ereignis: `{event}`**",
            "embeds": [
                {
                    "title": title,
                    "description": f"Zeitpunkt: {ts}",
                    "color": color,
                    "fields": fields,
                    "footer": {"text": "PrintLab v2.0 Outbound Engine"},
                }
            ],
        }

    elif format_type == "slack":
        return {
            "text": f"*{title}* ({ts})\n```\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```",
        }

    else:  # Generic JSON
        return {
            "event": event,
            "timestamp": ts,
            "data": data,
            "source": "PrintLab v2.0",
        }


def _record_delivery_outcome(hook: dict[str, Any], ok: bool, detail: str) -> None:
    """Schreibt das Dauerergebnis einer Zustellung in den persistenten Hook-Record.

    Führt ``failure_streak``, ``last_delivery_*`` und die Dead-Letter-Regel
    (``_DISABLE_AFTER_FAILURES``). Hooks, die nicht in der Persistenz stehen
    (z. B. kurzlebige Test-Dicts), werden ignoriert — es entsteht keine Datei.
    """
    hook_id = hook.get("id")
    if not hook_id or not str(hook_id).strip():
        return
    if not WEBHOOKS_FILE.is_file():
        return

    updated = False
    dead_letter_now = False
    now_stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _lock:
        webhooks = _load_webhooks()
        for stored in webhooks:
            if stored.get("id") != hook_id:
                continue
            if ok:
                streak = 0
            else:
                streak = int(stored.get("failure_streak", 0)) + 1
            stored["failure_streak"] = streak
            stored["last_delivery_status"] = "delivered" if ok else "failed"
            stored["last_delivery_detail"] = detail
            stored["last_delivery_at"] = now_stamp
            if not ok and streak >= _DISABLE_AFTER_FAILURES and stored.get("enabled", True):
                stored["enabled"] = False
                stored["dead_lettered"] = True
                dead_letter_now = True
            updated = True
            break
        if updated:
            _save_webhooks(webhooks)
    if dead_letter_now:
        logger.warning(
            "Webhook %s nach %d Fehlschlägen in Folge deaktiviert (Dead-Letter). Letzter Grund: %s",
            hook_id,
            _DISABLE_AFTER_FAILURES,
            detail,
        )


def deliver_webhook_sync(hook: dict[str, Any], event: str, data: dict[str, Any]) -> bool:
    """Sendet den Webhook synchron mit Timeout, SSRF-Prüfung und Backoff-Retry.

    Läuft im Worker-Thread; blockiert den Event-Loop nicht. Vor den Versuchen
    wird der Hostname aufgelöst und jede Zieladresse erneut gegen die SSRF-Regeln
    geprüft — eine Registierungszeit-Prüfung allein lässt Domainnamen zu, die
    erst später auf interne Adressen auflösen. Transiente Fehler (Netzwerk, 5xx,
    429) werden mit ``_RETRY_DELAYS``-Backoff wiederholt; dauerhafte Fehlschläge
    landen in der Zustellhistorie des Hooks und führen bei Bestand zur
    Dead-Letter-Deaktivierung.
    """
    url = hook.get("url")
    if not url or not hook.get("enabled", True):
        return False

    if not _event_matches(hook, event):
        return False

    allow_local = bool(os.environ.get("PRINTLAB_ALLOW_LOCAL_WEBHOOKS"))
    safe, reason = is_safe_webhook_url(url, allow_private=allow_local)
    if not safe:
        logger.warning("Zustellung abgelehnt (Hook %s, Event %s): %s", hook.get("id", "?"), event, reason)
        _record_delivery_outcome(hook, False, f"SSRF-Block: {reason}")
        return False

    hostname = (urllib.parse.urlparse(url).hostname or "").strip().lower()
    violation = _validate_resolved_host(hostname, allow_local)
    if violation:
        logger.warning(
            "DNS-SSRF-Block bei Zustellung (Hook %s, Event %s): %s",
            hook.get("id", "?"),
            event,
            violation,
        )
        _record_delivery_outcome(hook, False, f"SSRF-Block: {violation}")
        return False

    if not _inflight.acquire(blocking=False):
        # Backpressure: Zielbacklog begrenzt, statt unbegrenzt aufzustauen.
        logger.warning("Webhook-Zustellungsverlauf voll (>=%d), Event %s verworfen", _MAX_CONCURRENT_DELIVERIES, event)
        # Kein Streak: Backpressure ist ein Systemzustand, kein Empfängerfehler.
        return False

    try:
        formatted = format_payload(hook.get("format", "generic"), event, data)
        body = json.dumps(formatted, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PrintLab-Webhooks/2.0.1",
            "X-PrintLab-Event": event,
            "X-PrintLab-Delivery": uuid.uuid4().hex,
        }

        secret = hook.get("secret", "")
        if secret:
            headers["X-PrintLab-Signature"] = build_signature(secret, body)

        # follow_redirects=False: Zustellungen dürfen vom Empfänger nicht ohne
        # erneute SSRF-Prüfung umgeleitet werden.
        total_attempts = 1 + len(_RETRY_DELAYS)
        delivered = False
        detail = ""
        for attempt in range(total_attempts):
            if attempt > 0:
                time.sleep(_RETRY_DELAYS[attempt - 1] if attempt - 1 < len(_RETRY_DELAYS) else 0.0)
            try:
                with httpx.Client(timeout=4.0, follow_redirects=False) as client:
                    resp = client.post(url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    delivered = True
                    detail = f"HTTP {resp.status_code}"
                    break
                detail = f"HTTP {resp.status_code}"
                # 4xx (außer 429) = dauerhaft falsch konfiguriert → kein weiterer Versuch.
                retryable = resp.status_code >= 500 or resp.status_code == 429
                if not retryable:
                    break
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"

        if delivered:
            logger.info(
                "Webhook %s an %s gesendet (%s, Versuch %d/%d)", event, url, detail, attempt + 1, total_attempts
            )
        else:
            logger.warning("Webhook-Zustellung fehlgeschlagen für %s nach %d Versuch(en): %s", url, attempt + 1, detail)
        _record_delivery_outcome(hook, delivered, detail)
        return delivered
    except Exception as exc:  # defensive: Buildfehler des Payloads o. Ä. zählen als Fehlschlag
        detail = f"{type(exc).__name__}: {exc}"
        logger.warning("Webhook-Zustellungsfehler für %s: %s", url, detail)
        _record_delivery_outcome(hook, False, detail)
        return False
    finally:
        _inflight.release()


def dispatch_event(event: str, data: dict[str, Any]) -> int:
    """Verteilt ein Ereignis über den gebundenen ThreadPoolExecutor an alle passenden Webhooks.

    Rückgabe ist die Anzahl tatsächlich passender Hooks (abonniertes Ereignis
    vorhanden, aktiv), nicht eine pauschale Zählung aller Registrierungen.
    """
    hooks = _load_webhooks()
    matching = [h for h in hooks if h.get("enabled", True) and _event_matches(h, event)]
    for hook in matching:
        _executor.submit(deliver_webhook_sync, hook, event, data)
    if matching:
        logger.info("Event '%s' an %d Webhook(s) ausgeliefert.", event, len(matching))
    return len(matching)

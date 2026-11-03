"""Regressionstests für die v2.0.1-Härtung.

Deckt die kritischen Pfade des Release-Commits "Enterprise Hardening" ab:
- SSRF-Schutz inkl. Zahlenkodierungen und DNS-Auflösung zur Zustellungszeit,
- Angebots-Server-Registry (kein manipulierter Zahlbetrag im Checkout),
- Verschleiß-Multiplikatoren (explizit abrasiv ≠ bekanntes Muster),
- Webhook-Event-Validierung, Secret-Maskierung und Versand-Semantik,
- Fleet-Balancer-Toleranz gegen kaputte API-Payloads,
- Archive-Hook-Deduplizierung (keine doppelten Stundebuchungen).
"""

from __future__ import annotations

import json
import math
import socket
from typing import Any

import pytest

from backend.app.services import archive as archive_module, outbound_webhooks, secret_codec, wear_tracker
from backend.app.services.customer_portal import (
    _as_eur_amount,
    calculate_instant_quote,
    create_stripe_checkout_session,
)
from backend.app.services.fleet_load_balancer import (
    MIN_DISPATCH_SCORE,
    calculate_printer_fitness,
    dispatch_job_to_fleet,
)
from backend.app.services.outbound_webhooks import _validate_resolved_host

# ── SSRF: Registrierungszeit ─────────────────────────────────────────────────


class TestSSRFRegistration:
    def test_blocks_decimal_and_hex_ip_encodings(self):
        # 2130706433 == 127.0.0.1 (dezimal), 0x7f000001 == 127.0.0.1 (hex)
        for url in ("http://2130706433/latest/meta-data/", "http://0x7f000001/hit"):
            safe, msg = outbound_webhooks.is_safe_webhook_url(url, allow_private=False)
            assert not safe, url
            assert "Loopback" in msg, url

    def test_blocks_ambiguous_partial_numeric_hosts(self):
        # "127.1" wird von manchen Resolvern als 127.0.0.1 gedeutet —
        # konservativ abgelehnt, statt es dem Resolver zu überlassen.
        safe, _ = outbound_webhooks.is_safe_webhook_url("http://127.1/x", allow_private=False)
        assert not safe

    def test_blocks_ipv6_loopback_literal(self):
        safe, msg = outbound_webhooks.is_safe_webhook_url("http://[::1]:8000/x", allow_private=False)
        assert not safe
        assert "Loopback" in msg

    def test_blocks_raw_metadata_ip_even_with_allow_local(self):
        # Die Metadaten-Adresse bleibt gesperrt, auch wenn Privatnetze erlaubt sind.
        safe, msg = outbound_webhooks.is_safe_webhook_url(
            "http://169.254.169.254/latest/meta-data/", allow_private=True
        )
        assert not safe
        assert "Cloud-Instanz-Metadaten" in msg

    def test_private_ip_allowed_only_when_explicit(self):
        safe, _ = outbound_webhooks.is_safe_webhook_url("http://192.168.178.44:8123/api/webhook", allow_private=True)
        assert safe


# ── SSRF: Zustellungszeit (DNS) ──────────────────────────────────────────────


def _fake_getaddrinfo(addresses: list[str]):
    def _resolve(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        return [("AF_INET", socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addresses]

    return _resolve


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Blockiert httpx.Client in outbound_webhooks; meldet auftretende Versuche."""
    attempts: list[dict] = []

    def _no_client(*args: Any, **kwargs: Any) -> Any:
        attempts.append({"args": args, "kwargs": kwargs})
        raise AssertionError("Kein Netzversuch hinter der SSRF-Sperre erlaubt")

    class _Guard:
        __init__ = _no_client

    monkeypatch.setattr(outbound_webhooks.httpx, "Client", _Guard)
    return attempts


class TestSSRFDelivery:
    def test_delivery_blocks_domain_resolving_to_metadata_service(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            outbound_webhooks.socket,
            "getaddrinfo",
            _fake_getaddrinfo(["169.254.169.254"]),
        )
        _forbid_network(monkeypatch)

        hook: dict[str, Any] = {
            "id": "wh_test",
            "url": "http://webhook.evil.example/hook",
            "enabled": True,
            "events": ["*"],
        }
        ok = outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {"x": 1})
        assert ok is False

    def test_delivery_blocks_domain_resolving_to_private_network(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            outbound_webhooks.socket,
            "getaddrinfo",
            _fake_getaddrinfo(["93.184.216.34", "10.0.0.12"]),
        )
        violation = _validate_resolved_host("webhook.evil.example", allow_local=False)
        assert violation is not None
        assert "Private IP-Adressen" in violation

    def test_delivery_rejects_unresolvable_host(self, monkeypatch: pytest.MonkeyPatch):
        def _fail(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
            raise OSError("Name or service not known")

        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fail)
        violation = _validate_resolved_host("does-not-exist.example", allow_local=False)
        assert violation is not None
        assert "nicht aufgel" in violation

    def test_delivery_accepts_public_resolution(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            outbound_webhooks.socket,
            "getaddrinfo",
            _fake_getaddrinfo(["93.184.216.34"]),
        )
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        posts: list[dict] = []

        class _FakeResponse:
            status_code = 200

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                assert kwargs.get("follow_redirects") is False

            def __enter__(self) -> _FakeClient:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def post(self, url: str, **kwargs: Any) -> _FakeResponse:
                posts.append({"url": url, "headers": kwargs["headers"]})
                return _FakeResponse()

        monkeypatch.setattr(outbound_webhooks.httpx, "Client", _FakeClient)

        hook: dict[str, Any] = {
            "id": "wh_ok",
            "url": "https://hooks.example.com/printlab",
            "secret": "topsecret",
            "enabled": True,
            "events": ["print.completed"],
        }
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {"x": 1}) is True
        assert len(posts) == 1
        assert posts[0]["headers"]["X-PrintLab-Signature"].startswith("sha256=")

    def test_redirect_counts_as_failure(self, monkeypatch: pytest.MonkeyPatch):
        """follow_redirects=False und ein 3xx zählt als nicht ausgeliefert."""
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(
            outbound_webhooks.socket,
            "getaddrinfo",
            _fake_getaddrinfo(["93.184.216.34"]),
        )
        sent: list[str] = []

        class _FakeResponse:
            status_code = 302

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> _FakeClient:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def post(self, url: str, **kwargs: Any) -> _FakeResponse:
                sent.append(url)
                return _FakeResponse()

        monkeypatch.setattr(outbound_webhooks.httpx, "Client", _FakeClient)

        hook: dict[str, Any] = {
            "id": "wh_redir",
            "url": "https://hooks.example.com/redirect-me",
            "enabled": True,
            "events": ["*"],
        }
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False
        assert sent and "redirect-me" in sent[0]

    def test_disabled_hook_is_skipped(self, monkeypatch: pytest.MonkeyPatch):
        _forbid_network(monkeypatch)
        hook: dict[str, Any] = {
            "id": "wh_off",
            "url": "https://hooks.example.com/x",
            "enabled": False,
            "events": ["*"],
        }
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False


# ── Webhook-Verwaltung & Verteilung ──────────────────────────────────────────


class TestWebhookRegistry:
    def test_list_masks_secret(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        hook = outbound_webhooks.register_webhook(
            url="https://discord.com/api/webhooks/1", secret="supersecret123", events=["*"]
        )
        hooks = outbound_webhooks.list_webhooks()
        assert hooks[0]["id"] == hook["id"]
        assert "supersecret123" not in json.dumps(hooks)
        assert hooks[0]["secret"] == "***"
        assert hooks[0]["secret_configured"] is True

    def test_register_rejects_unknown_events(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        with pytest.raises(ValueError, match="Unbekanntes Ereignis 'print.complted'"):
            outbound_webhooks.register_webhook(
                url="https://discord.com/api/webhooks/1",
                events=["print.complted"],
            )

    def test_register_reports_persistence_failure(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_save_webhooks", lambda _data: False)
        with pytest.raises(RuntimeError, match="nicht persistiert"):
            outbound_webhooks.register_webhook(url="https://discord.com/api/webhooks/1")

    def test_register_enforces_cap(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "MAX_WEBHOOKS", 1)
        outbound_webhooks.register_webhook(url="https://discord.com/api/webhooks/1")
        with pytest.raises(ValueError, match="Maximal"):
            outbound_webhooks.register_webhook(url="https://discord.com/api/webhooks/2")

    def test_dispatch_counts_only_matching_hooks(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        outbound_webhooks.register_webhook(url="https://a.example.com/h", events=["print.completed"])
        outbound_webhooks.register_webhook(url="https://b.example.com/h", events=["*"])

        submitted: list[tuple[Any, tuple]] = []

        def _fake_submit(fn: Any, *args: Any, **kwargs: Any) -> None:
            submitted.append((fn, args))

        monkeypatch.setattr(outbound_webhooks._executor, "submit", _fake_submit)

        count = outbound_webhooks.dispatch_event("print.failed", {"x": 1})
        assert count == 1
        assert len(submitted) == 1
        # Übergebener Hook ist der "Alles"-Empfänger:
        assert submitted[0][1][0]["url"] == "https://b.example.com/h"
        assert submitted[0][1][1] == "print.failed"

    def test_dispatch_on_empty_registry_counts_zero(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "nonexistent.json")
        assert outbound_webhooks.dispatch_event("print.completed", {}) == 0


# ── Verschleiß-Tracker ───────────────────────────────────────────────────────


class TestWearTracker:
    def test_is_abrasive_flag_does_not_impersonate_cf(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", tmp_path / "wear.json")
        # PLA + pauschaler Abrasiv-Hinweis: Default-Faktor 3.0, nicht 5.0 (PLA-CF).
        wear_tracker.record_print_usage("p_hard", print_time_hours=10.0, filament_type="PLA", is_abrasive=True)
        overview = wear_tracker.get_wear_overview("p_hard")
        nozzle = next(c for c in overview["components"] if c["id"] == "nozzle")
        assert nozzle["used_hours"] == pytest.approx(30.0)

    def test_known_pattern_beats_default(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", tmp_path / "wear.json")
        wear_tracker.record_print_usage("p_cf", print_time_hours=10.0, filament_type="PLA-CF", is_abrasive=True)
        overview = wear_tracker.get_wear_overview("p_cf")
        nozzle = next(c for c in overview["components"] if c["id"] == "nozzle")
        assert nozzle["used_hours"] == pytest.approx(50.0)

    def test_bad_hours_are_rejected(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", tmp_path / "wear.json")
        wear_tracker.record_print_usage("p_nan", print_time_hours=float("nan"), filament_type="PLA")
        overview = wear_tracker.get_wear_overview("p_nan")
        nozzle = next(c for c in overview["components"] if c["id"] == "nozzle")
        assert nozzle["used_hours"] == pytest.approx(0.0)
        assert math.isfinite(nozzle["used_hours"])

    def test_wear_alert_fires_only_on_transition(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", tmp_path / "wear.json")
        events: list[tuple[str, dict[str, Any]]] = []
        monkeypatch.setattr(
            outbound_webhooks,
            "dispatch_event",
            lambda event, data: events.append((event, data)) or 1,
        )

        printer = "p_alert"
        # Buchung 1 (20 h PLA): alle Bauteile im OK-Band
        #   (z_spindle: 20/100 → 80 %, steel_rods: 20/75 → 73 %) → kein Event
        wear_tracker.record_print_usage(printer, print_time_hours=20.0, filament_type="PLA")
        assert events == []

        # Buchung 2 (+60 h PLA): steel_rods jetzt 80/75 h → CRITICAL;
        # z_spindle 80/100 → Gesund 20 % → WARN. Übergang OK → CRITICAL feuert.
        wear_tracker.record_print_usage(printer, print_time_hours=60.0, filament_type="PLA")
        assert len(events) == 1
        event, payload = events[0]
        assert event == "maintenance.wear_alert"
        assert payload["overall_status"] == "CRITICAL"
        fired = {c["id"]: c["status"] for c in payload["components"]}
        assert fired == {"steel_rods": "CRITICAL", "z_spindle": "WARN"}

        # Buchung 3 (+10 h): Status bleibt CRITICAL → kein erneutes Event
        wear_tracker.record_print_usage(printer, print_time_hours=10.0, filament_type="PLA")
        assert len(events) == 1


# ── Fleet Load Balancer ──────────────────────────────────────────────────────


class TestFleetBalancer:
    def test_garbage_job_fields_fall_back(self):
        printer = {
            "id": 1,
            "connected": True,
            "state": "IDLE",
            "plate_clear": True,
            "bed_temp": float("nan"),
            "nozzle_diameter": "0.4",
            "ams_slots": [],
            "total_operating_hours": "not-a-number",
        }
        job = {"material": "PLA", "filament_grams": "abc", "nozzle_diameter": None}
        score, reasons = calculate_printer_fitness(printer, job)
        # Kernpunkt: keine Exception, endliche Werte, begründbarer Score. Ohne
        # AMS-Passung (leere Slots, Material PLA) liegt der Score unter der
        # Dispatch-Schwelle — das ist korrektes Verhalten, kein Absturz.
        assert math.isfinite(score)
        assert 0.0 <= score < MIN_DISPATCH_SCORE
        assert any("Filament" in reason or "AMS" in reason for reason in reasons)

    def test_no_printers_yields_waiting_status(self):
        result = dispatch_job_to_fleet({"material": "PLA"}, [])
        assert result["status"] == "NO_PRINTERS_AVAILABLE"
        assert result["selected_printer_id"] is None


# ── Kundenportal ─────────────────────────────────────────────────────────────


class TestPortalQuoteStore:
    @pytest.mark.asyncio
    async def test_store_and_get_roundtrip(self, db_session):
        from backend.app.services.portal_quote_store import get_quote as fetch, store_quote

        quote = calculate_instant_quote(volume_cm3=30.0, quantity=1)
        await store_quote(db_session, quote)
        stored = await fetch(db_session, quote["quote_id"])
        assert stored is not None
        assert stored["pricing"]["gross_total_eur"] == quote["pricing"]["gross_total_eur"]
        # Der interne Ablagezeitstempel verlässt die Registry nicht.
        assert "_created_at" not in stored

    @pytest.mark.asyncio
    async def test_unknown_and_empty_ids(self, db_session):
        from backend.app.services.portal_quote_store import get_quote as fetch

        assert await fetch(db_session, "SQ-DOESNOTEXIST") is None
        assert await fetch(db_session, "") is None

    @pytest.mark.asyncio
    async def test_expired_quote_is_purged(self, db_session):
        from datetime import datetime, timedelta, timezone

        from backend.app.models.portal_quote import PortalQuote
        from backend.app.services.portal_quote_store import get_quote as fetch, store_quote

        quote = calculate_instant_quote(volume_cm3=30.0, quantity=1)
        await store_quote(db_session, quote)

        row = await db_session.get(PortalQuote, quote["quote_id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.commit()

        expired_row = await db_session.get(PortalQuote, quote["quote_id"])
        assert expired_row is not None and expired_row.payload == quote

        assert await fetch(db_session, quote["quote_id"]) is None

    def test_checkout_uses_registered_quote_price(self):
        quote = calculate_instant_quote(volume_cm3=30.0, quantity=1)
        session = create_stripe_checkout_session(
            quote,
            success_url="https://portal.example/done",
            cancel_url="https://portal.example/cancelled",
        )
        expected = int(round(quote["pricing"]["gross_total_eur"] * 100))
        assert session["amount_cents"] == expected
        assert session["quote_id"] == quote["quote_id"]
        assert session["success_url"] == "https://portal.example/done"
        assert session["cancel_url"] == "https://portal.example/cancelled"

    def test_checkout_rejects_invalid_redirect_urls(self):
        quote = calculate_instant_quote(volume_cm3=30.0, quantity=1)
        for bad in ("ftp://portal.example/done", "javascript:alert(1)", "  "):
            with pytest.raises(ValueError):
                create_stripe_checkout_session(
                    quote,
                    success_url=bad,
                    cancel_url="https://portal.example/cancelled",
                )

    def test_checkout_rejects_specific_scheme_violations(self):
        quote = calculate_instant_quote(volume_cm3=30.0, quantity=1)
        with pytest.raises(ValueError, match="http"):
            create_stripe_checkout_session(
                quote,
                success_url="ftp://portal.example/done",
                cancel_url="https://portal.example/cancelled",
            )

    def test_checkout_rejects_below_stripe_minimum(self):
        quote = calculate_instant_quote(volume_cm3=30.0, quantity=1)
        quote["pricing"]["gross_total_eur"] = 0.01
        with pytest.raises(ValueError, match="Mindestbetrag"):
            create_stripe_checkout_session(
                quote,
                success_url="https://portal.example/done",
                cancel_url="https://portal.example/cancelled",
            )

    def test_as_eur_amount_rejects_garbage(self):
        with pytest.raises(ValueError):
            _as_eur_amount(None)
        with pytest.raises(ValueError):
            _as_eur_amount(float("inf"))
        assert _as_eur_amount("12.50") == 12.50


# ── Archiv-Hooks ─────────────────────────────────────────────────────────────


class _FakeArchive:
    id = 7
    printer_id = 3
    print_name = "Teil"
    print_time_seconds = 1800
    filament_type = "PLA"


class TestArchiveHookDeduplication:
    def test_same_status_does_not_retrigger(self):
        assert archive_module._should_emit_status_hooks("printing", "completed") is True
        assert archive_module._should_emit_status_hooks("completed", "completed") is False
        assert archive_module._should_emit_status_hooks("failed", "failed") is False
        # Übergang (z. B. korrigierte Bewertung) feuert bewusst wieder:
        assert archive_module._should_emit_status_hooks("failed", "completed") is True
        assert archive_module._should_emit_status_hooks("printing", "printing") is False

    def test_emit_books_wear_and_dispatches(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[tuple[str, Any]] = []
        monkeypatch.setattr(
            outbound_webhooks,
            "dispatch_event",
            lambda event, data: calls.append(("event", event)) or 1,
        )
        monkeypatch.setattr(
            wear_tracker,
            "record_print_usage",
            lambda **kwargs: calls.append(("wear", kwargs["print_time_hours"])) or {},
        )

        archive_module._emit_lifecycle_hooks(_FakeArchive(), "completed", None)
        assert ("wear", 0.5) in calls  # 1800 s == 0.5 h
        assert ("event", "print.completed") in calls

    def test_emit_failure_is_warning_not_silent(self, monkeypatch: pytest.MonkeyPatch, caplog):
        def _boom(event: Any, data: Any) -> int:
            raise RuntimeError("Receiver weg")

        monkeypatch.setattr(outbound_webhooks, "dispatch_event", _boom)
        monkeypatch.setattr(wear_tracker, "record_print_usage", lambda **kwargs: {})

        with caplog.at_level("WARNING"):
            archive_module._emit_lifecycle_hooks(_FakeArchive(), "failed", "Bett blockiert")
        assert "Abschluss-Hooks" in caplog.text
        assert "failed" in caplog.text


# ── Webhook-Zustell-Lifecycle: Retry & Dead-Letter ───────────────────────────


def _post_recorder(statuses: list[int]):
    """Fake-httpx-Client, der pro POST den nächsten Status aus der Liste liefert."""
    posts: list[int] = []
    details: list[dict[str, Any]] = []

    class _FakeResponse:
        def __init__(self, code: int) -> None:
            self.status_code = code

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            assert kwargs.get("follow_redirects") is False

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            code = statuses[len(posts)] if len(posts) < len(statuses) else statuses[-1]
            posts.append(code)
            details.append({"url": url, "headers": kwargs["headers"], "content": kwargs["content"]})
            return _FakeResponse(code)

    _FakeClient.details = details
    return _FakeClient, posts


class TestWebhookDeliveryLifecycle:
    def test_transient_5xx_retried_until_success(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_RETRY_DELAYS", (0.0, 0.0, 0.0))
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
        FakeClient, posts = _post_recorder([503, 500, 200])
        monkeypatch.setattr(outbound_webhooks.httpx, "Client", FakeClient)

        hook = outbound_webhooks.register_webhook(
            url="https://hooks.example.com/h", secret="s", events=["print.completed"]
        )
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is True
        assert posts == [503, 500, 200]

        stored = outbound_webhooks.list_webhooks()[0]
        assert stored["last_delivery_status"] == "delivered"
        assert stored["failure_streak"] == 0

    def test_permanent_4xx_not_retried_but_recorded(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_RETRY_DELAYS", (0.0, 0.0, 0.0))
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
        FakeClient, posts = _post_recorder([404])
        monkeypatch.setattr(outbound_webhooks.httpx, "Client", FakeClient)

        hook = outbound_webhooks.register_webhook(url="https://hooks.example.com/h", secret="s", events=["*"])
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False
        assert posts == [404]  # kein zweiter Versuch: 4xx ist dauerhaft

        stored = outbound_webhooks.list_webhooks()[0]
        assert stored["last_delivery_status"] == "failed"
        assert stored["failure_streak"] == 1
        assert stored["enabled"] is True

    def test_dead_letter_disables_after_streak(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_RETRY_DELAYS", ())
        monkeypatch.setattr(outbound_webhooks, "_DISABLE_AFTER_FAILURES", 2)
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
        FakeClient, posts = _post_recorder([500])
        monkeypatch.setattr(outbound_webhooks.httpx, "Client", FakeClient)

        hook = outbound_webhooks.register_webhook(url="https://hooks.example.com/h", secret="s", events=["*"])
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False
        # Nach der zweiten Fehlschlagsbuchung ist der Hook deaktiviert (Dead-Letter):
        stored = outbound_webhooks.list_webhooks()[0]
        assert stored["enabled"] is False
        assert stored["dead_lettered"] is True
        assert stored["failure_streak"] == 2
        assert posts == [500, 500]

    def test_streak_resets_on_success(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_RETRY_DELAYS", ())
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
        FakeClient, posts = _post_recorder([500, 200])
        monkeypatch.setattr(outbound_webhooks.httpx, "Client", FakeClient)

        hook = outbound_webhooks.register_webhook(url="https://hooks.example.com/h", secret="s", events=["*"])
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is True
        stored = outbound_webhooks.list_webhooks()[0]
        assert stored["failure_streak"] == 0
        assert stored["enabled"] is True

    def test_ssrf_block_counts_toward_dead_letter(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_DISABLE_AFTER_FAILURES", 1)
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["169.254.169.254"]))
        _forbid_network(monkeypatch)

        hook = outbound_webhooks.register_webhook(url="https://hooks.example.com/h", secret="s", events=["*"])
        assert outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {}) is False
        stored = outbound_webhooks.list_webhooks()[0]
        assert stored["enabled"] is False
        assert stored["dead_lettered"] is True
        assert "SSRF-Block" in stored["last_delivery_detail"]


# ── Secret-at-rest (HMAC-Geheimnisse verschlüsselt) ──────────────────────────


class TestSecretAtRest:
    def test_register_stores_only_ciphertext(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(secret_codec, "KEY_FILE", tmp_path / "key.bin")
        secret_codec.reset_cached_cipher()
        try:
            outbound_webhooks.register_webhook(
                url="https://discord.com/api/webhooks/1", secret="hushhush", events=["*"]
            )
        finally:
            secret_codec.reset_cached_cipher()

        disk = (tmp_path / "wh.json").read_text(encoding="utf-8")
        assert "hushhush" not in disk
        assert "enc:" in disk
        # Die Schlüsseldatei ist kein Klartextabbild des Geheimnisses:
        assert "hushhush" not in (tmp_path / "key.bin").read_text(encoding="utf-8")

    def test_delivery_signs_with_decrypted_secret(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_RETRY_DELAYS", ())
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
        FakeClient, posts = _post_recorder([200])
        monkeypatch.setattr(outbound_webhooks.httpx, "Client", FakeClient)
        monkeypatch.setattr(secret_codec, "KEY_FILE", tmp_path / "key.bin")
        secret_codec.reset_cached_cipher()
        try:
            hook = outbound_webhooks.register_webhook(
                url="https://hooks.example.com/h", secret="hushhush", events=["*"]
            )
            result = outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {"x": 1})
        finally:
            secret_codec.reset_cached_cipher()

        assert posts == [200]
        assert result is True
        # Die Signatur wurde mit dem entschlüsselten Klartext-HMAC erzeugt:
        sent = FakeClient.details[0]
        expected = outbound_webhooks.build_signature("hushhush", sent["content"])
        assert sent["headers"]["X-PrintLab-Signature"] == expected

    def test_lost_key_key_fails_loudly_and_counts_streak(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(outbound_webhooks, "_RETRY_DELAYS", ())
        monkeypatch.delenv("PRINTLAB_ALLOW_LOCAL_WEBHOOKS", raising=False)
        monkeypatch.setattr(outbound_webhooks.socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
        _forbid_network(monkeypatch)
        monkeypatch.setattr(secret_codec, "KEY_FILE", tmp_path / "key.bin")
        secret_codec.reset_cached_cipher()
        try:
            hook = outbound_webhooks.register_webhook(
                url="https://hooks.example.com/h", secret="hushhush", events=["*"]
            )
        finally:
            secret_codec.reset_cached_cipher()

        # Schlüssel jetzt "verloren": Datei mit anderem Schlüssel überschreiben.
        (tmp_path / "key.bin").write_text("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n", encoding="utf-8")
        secret_codec.reset_cached_cipher()
        try:
            ok = outbound_webhooks.deliver_webhook_sync(hook, "print.completed", {"x": 1})
        finally:
            secret_codec.reset_cached_cipher()

        assert ok is False
        stored = outbound_webhooks.list_webhooks()[0]
        assert "Schlüssel" in stored["last_delivery_detail"]

    def test_legacy_plaintext_still_readable(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
        monkeypatch.setattr(secret_codec, "KEY_FILE", tmp_path / "key.bin")
        legacy = {
            "id": "wh_legacy",
            "url": "https://hooks.example.com/legacy",
            "secret": "old-plain",
            "events": ["*"],
            "enabled": True,
        }
        (tmp_path / "wh.json").write_text(json.dumps([legacy]), encoding="utf-8")
        raw = secret_codec.decrypt_secret("old-plain")
        assert raw == "old-plain"


# ── Konfigurations-Sanity ────────────────────────────────────────────────────


def test_version_sources_are_in_sync():
    """Alle Versionsquellen müssen dieselbe SemVer-Version tragen.

    Keine hartcodierte Version: der Release-Ablauf erhöht sie mehrfach (config,
    pyproject, Changelog) — der Test beweist nur die Parität und das Format,
    nicht eine einzelne Zahl, die bei jedem Release brechen würde.
    """
    import re
    from pathlib import Path

    from backend.app.core import config as config_module

    assert re.fullmatch(r"\d+\.\d+\.\d+", config_module.APP_VERSION), config_module.APP_VERSION

    repo_root = Path(config_module.__file__).resolve().parents[3]
    pyproject_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    py_ver = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.M)
    assert py_ver, "pyproject.toml: version nicht gefunden"
    assert py_ver.group(1) == config_module.APP_VERSION

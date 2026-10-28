"""Überwachung von außen (werkzeuge/ueberwachung.py): Neustart, Meldungen, Speicherplatz, Meldewege."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "ueberwachung.py"
if not SCRIPT.exists():  # das Docker-Test-Image enthält den Ordner werkzeuge/ nicht
    pytest.skip("werkzeuge/ fehlt in dieser Umgebung", allow_module_level=True)

spec = importlib.util.spec_from_file_location("ueberwachung", SCRIPT)
ue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ue)


class Recorder:
    def __init__(self, healthy=True, restart_ok=True):
        self.healthy = healthy
        self.restart_ok = restart_ok
        self.messages = []
        self.restarts = 0

    def probe(self):
        return self.healthy

    def restart(self):
        self.restarts += 1
        return self.restart_ok

    def notify(self, message):
        self.messages.append(message)


def step(state, rec, now=1000.0, **kw):
    return ue.run_check(state, probe=rec.probe, restart=rec.restart, notify=rec.notify, now=now, **kw)


def test_healthy_run_is_silent():
    rec = Recorder()
    state = step({}, rec)
    assert state["fails"] == 0 and rec.messages == [] and rec.restarts == 0


def test_short_hiccups_do_not_alert():
    rec = Recorder(healthy=False)
    state = {}
    for _ in range(2):
        state = step(state, rec)
    rec.healthy = True
    state = step(state, rec)
    assert rec.messages == [] and rec.restarts == 0 and state["fails"] == 0


def test_outage_restarts_once_and_alerts_once_then_reports_recovery():
    rec = Recorder(healthy=False)
    state = {}
    for _ in range(5):
        state = step(state, rec)
    assert rec.restarts == 1
    assert len(rec.messages) == 1 and "Neustart wurde ausgelöst" in rec.messages[0]
    rec.healthy = True
    state = step(state, rec)
    assert rec.messages[-1] == "PrintLab läuft wieder."
    step(state, rec)
    assert len(rec.messages) == 2  # nach der Entwarnung kommt nichts mehr


def test_failed_restart_is_reported_honestly():
    rec = Recorder(healthy=False, restart_ok=False)
    state = {}
    for _ in range(3):
        state = step(state, rec)
    assert "nicht möglich" in rec.messages[0]


def test_no_second_restart_within_ten_minutes():
    rec = Recorder(healthy=False)
    state = {"last_restart": 900.0}
    for _ in range(3):
        state = step(state, rec, now=1000.0)
    assert rec.restarts == 0 and len(rec.messages) == 1


def test_long_outage_sends_a_reminder():
    rec = Recorder(healthy=False)
    state = {}
    for _ in range(ue.REMINDER_EVERY_FAILS):
        state = step(state, rec)
    assert len(rec.messages) == 2 and "weiterhin nicht" in rec.messages[1]


def test_low_disk_space_is_reported_once_a_day():
    rec = Recorder()
    state = step({}, rec, now=10_000.0, free_bytes=500_000_000)
    assert len(rec.messages) == 1 and "0.5 GB" in rec.messages[0]
    state = step(state, rec, now=10_100.0, free_bytes=500_000_000)
    assert len(rec.messages) == 1
    step(state, rec, now=10_000.0 + ue.DISK_REMINDER_SECONDS + 1, free_bytes=500_000_000)
    assert len(rec.messages) == 2


def test_enough_disk_space_is_silent():
    rec = Recorder()
    step({}, rec, free_bytes=50_000_000_000)
    assert rec.messages == []


def test_notifier_sends_to_telegram_and_ntfy_without_leaking_the_token(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(ue, "_post", lambda url, data: sent.append((url, data)))
    notify = ue.make_notifier(
        {
            "PRINTLAB_ALERT_TELEGRAM_TOKEN": "123:abc",
            "PRINTLAB_ALERT_TELEGRAM_CHAT": "42",
            "PRINTLAB_ALERT_NTFY_URL": "https://ntfy.sh/meins",
        }
    )
    notify("Test")
    urls = [u for u, _ in sent]
    assert urls == ["https://api.telegram.org/bot123:abc/sendMessage", "https://ntfy.sh/meins"]
    assert b"chat_id=42" in sent[0][1]
    assert "123:abc" not in capsys.readouterr().out


def test_notifier_without_channels_only_prints(monkeypatch, capsys):
    monkeypatch.setattr(ue, "_post", lambda *a: pytest.fail("darf nichts senden"))
    ue.make_notifier({})("Hallo")
    assert "Hallo" in capsys.readouterr().out


def test_post_failure_never_prints_the_url(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("kaputt")

    monkeypatch.setattr(ue.urllib.request, "urlopen", boom)
    ue._post("https://api.telegram.org/bot123:abc/sendMessage", b"x")
    err = capsys.readouterr().err
    assert "OSError" in err and "123:abc" not in err


def test_state_roundtrip_and_broken_file(tmp_path):
    path = tmp_path / "s.json"
    ue.save_state(path, {"fails": 2})
    assert ue.load_state(path) == {"fails": 2}
    path.write_text("kein json")
    assert ue.load_state(path) == {}
    assert ue.load_state(tmp_path / "fehlt.json") == {}


def test_probe_false_when_nothing_listens():
    assert ue.http_probe("http://127.0.0.1:9/", timeout=1) is False

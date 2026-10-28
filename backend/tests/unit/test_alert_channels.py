"""Meldewege für Ausfälle (alert_channels): Speichern, Prüfen, Senden, keine Geheimnisse nach außen."""

import json
import os
import urllib.error

import pytest

from backend.app.services import alert_channels as ac

TOKEN = "123456789:" + "A" * 35


class TestWrite:
    def test_saves_and_reports_status_without_secrets(self, tmp_path):
        status = ac.write(
            tmp_path, {"telegram_token": TOKEN, "telegram_chat": "42", "ntfy_url": "https://ntfy.sh/geheim"}
        )
        assert status == {"telegram": True, "telegram_chat": "42", "ntfy": True, "ntfy_host": "ntfy.sh"}
        assert TOKEN not in json.dumps(status) and "geheim" not in json.dumps(status)

    @pytest.mark.skipif(os.name == "nt", reason="Dateirechte nur unter POSIX")
    def test_file_is_private(self, tmp_path):
        ac.write(tmp_path, {"ntfy_url": "https://ntfy.sh/x"})
        assert (tmp_path / ac.FILE_NAME).stat().st_mode & 0o077 == 0

    def test_missing_key_keeps_the_value_and_empty_value_deletes_it(self, tmp_path):
        ac.write(tmp_path, {"telegram_token": TOKEN, "telegram_chat": "42"})
        ac.write(tmp_path, {"ntfy_url": "https://ntfy.sh/x"})
        assert ac.status(tmp_path, {})["telegram"] is True
        ac.write(tmp_path, {"telegram_token": ""})
        assert ac.status(tmp_path, {})["telegram"] is False
        assert ac.status(tmp_path, {})["ntfy"] is True

    @pytest.mark.parametrize(
        "update",
        [
            {"telegram_token": "kein-token"},
            {"telegram_token": "123:abc"},
            {"telegram_chat": "abc def"},
            {"telegram_chat": "1" * 40},
            {"ntfy_url": "ftp://x/y"},
            {"ntfy_url": "ntfy.sh/ohne-schema"},
            {"ntfy_url": "http://localhost:8080/x"},
            {"ntfy_url": "http://127.0.0.1/x"},
            {"ntfy_url": "http://169.254.169.254/latest/meta-data"},
            {"ntfy_url": "file:///etc/passwd"},
        ],
    )
    def test_invalid_or_dangerous_values_are_refused(self, tmp_path, update):
        with pytest.raises(ac.AlertConfigError):
            ac.write(tmp_path, update)
        assert ac.read_file(tmp_path) == {}

    def test_lan_ntfy_servers_are_allowed(self, tmp_path):
        assert ac.write(tmp_path, {"ntfy_url": "http://192.168.1.20:8080/printlab"})["ntfy"] is True

    def test_telegram_channel_names_are_accepted(self, tmp_path):
        assert ac.write(tmp_path, {"telegram_token": TOKEN, "telegram_chat": "@printlab_meldungen"})["telegram"] is True


class TestEffective:
    def test_environment_wins_over_the_file(self, tmp_path):
        ac.write(tmp_path, {"ntfy_url": "https://ntfy.sh/datei"})
        merged = ac.effective(tmp_path, {"PRINTLAB_ALERT_NTFY_URL": "https://ntfy.sh/umgebung"})
        assert merged["ntfy_url"] == "https://ntfy.sh/umgebung"

    def test_blank_environment_values_do_not_override(self, tmp_path):
        ac.write(tmp_path, {"ntfy_url": "https://ntfy.sh/datei"})
        assert ac.effective(tmp_path, {"PRINTLAB_ALERT_NTFY_URL": "  "})["ntfy_url"] == "https://ntfy.sh/datei"

    def test_without_a_data_folder_only_the_environment_counts(self):
        assert ac.effective(None, {"PRINTLAB_ALERT_NTFY_URL": "https://x/y"}) == {"ntfy_url": "https://x/y"}

    def test_broken_file_is_ignored(self, tmp_path):
        (tmp_path / ac.FILE_NAME).write_text("{kaputt")
        assert ac.read_file(tmp_path) == {}


class TestSend:
    def test_sends_to_both_channels(self, monkeypatch):
        sent = []
        monkeypatch.setattr(ac, "_post", lambda url, data, timeout=10.0: sent.append((url, data)))
        result = ac.send({"telegram_token": TOKEN, "telegram_chat": "42", "ntfy_url": "https://ntfy.sh/x"}, "Hallo")
        assert result == {"sent": ["telegram", "ntfy"], "errors": []}
        assert sent[0][0].endswith("/sendMessage") and b"chat_id=42" in sent[0][1]
        assert sent[1] == ("https://ntfy.sh/x", b"Hallo")

    def test_nothing_configured_sends_nothing(self, monkeypatch):
        monkeypatch.setattr(ac, "_post", lambda *a, **k: pytest.fail("darf nichts senden"))
        assert ac.send({}, "x") == {"sent": [], "errors": []}
        assert ac.send({"telegram_token": TOKEN}, "x") == {"sent": [], "errors": []}  # ohne Chat

    def test_errors_name_the_reason_but_never_the_secret(self, monkeypatch):
        def boom(url, data, timeout=10.0):
            if "telegram" in url:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)
            raise OSError("kaputt")

        monkeypatch.setattr(ac, "_post", boom)
        result = ac.send({"telegram_token": TOKEN, "telegram_chat": "42", "ntfy_url": "https://ntfy.sh/geheim"}, "x")
        assert result["sent"] == []
        assert result["errors"] == ["telegram: HTTP 401", "ntfy: OSError"]
        assert TOKEN not in json.dumps(result) and "geheim" not in json.dumps(result)

    def test_a_dangerous_saved_ntfy_address_is_never_called(self, monkeypatch):
        monkeypatch.setattr(ac, "_post", lambda *a, **k: pytest.fail("darf nichts senden"))
        result = ac.send({"ntfy_url": "http://169.254.169.254/x"}, "x")
        assert result["sent"] == [] and len(result["errors"]) == 1

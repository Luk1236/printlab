"""Lokaler KI-Assistent: Einstellungen, Modell-Verbindung und Prüfung der Aktionsvorschläge."""

import json

import httpx
import pytest

from backend.app.services import assistant_actions as actions, assistant_config as cfg, assistant_llm as llm

CONFIG = {**cfg.DEFAULTS, "enabled": True}


class TestConfig:
    def test_defaults_and_a_missing_or_broken_file(self, tmp_path):
        assert cfg.read(tmp_path) == cfg.DEFAULTS and cfg.DEFAULTS["enabled"] is False
        (tmp_path / cfg.FILE_NAME).write_text("kaputt{", encoding="utf-8")
        assert cfg.read(tmp_path) == cfg.DEFAULTS
        (tmp_path / cfg.FILE_NAME).write_text("[1, 2]", encoding="utf-8")
        assert cfg.read(tmp_path) == cfg.DEFAULTS

    def test_values_of_the_wrong_type_fall_back_to_defaults(self, tmp_path):
        (tmp_path / cfg.FILE_NAME).write_text(
            json.dumps({"enabled": "ja", "timeout_seconds": True, "model": 5}), encoding="utf-8"
        )
        assert cfg.read(tmp_path) == cfg.DEFAULTS

    def test_write_keeps_unmentioned_values_and_persists(self, tmp_path):
        cfg.write(tmp_path, {"enabled": True, "model": "llama3.2:3b"})
        saved = cfg.write(tmp_path, {"timeout_seconds": 60})
        assert saved["enabled"] is True and saved["model"] == "llama3.2:3b" and saved["timeout_seconds"] == 60
        assert cfg.read(tmp_path) == saved

    @pytest.mark.parametrize(
        "update",
        [
            {"base_url": "ftp://x"},
            {"base_url": "kein-link"},
            {"base_url": "http://169.254.169.254/latest"},
            {"base_url": "http://metadata.google.internal"},
            {"base_url": "http://0.0.0.0:11434"},
            {"model": ""},
            {"model": "x" * 101},
            {"timeout_seconds": 5},
            {"timeout_seconds": 901},
            {"timeout_seconds": True},
            {"timeout_seconds": "60"},
            {"max_tokens": 10},
            {"enabled": "yes"},
        ],
    )
    def test_invalid_updates_are_rejected_and_change_nothing(self, tmp_path, update):
        before = cfg.write(tmp_path, {"enabled": True})
        with pytest.raises(cfg.AssistantConfigError):
            cfg.write(tmp_path, update)
        assert cfg.read(tmp_path) == before

    def test_local_and_lan_addresses_are_fine_and_a_trailing_slash_goes(self, tmp_path):
        for url in (
            "http://127.0.0.1:11434",
            "http://localhost:11434",
            "http://192.168.178.34:11434/",
            "https://llm.heim:8443",
        ):
            assert not cfg.write(tmp_path, {"base_url": url})["base_url"].endswith("/")


def transport(handler):
    return httpx.MockTransport(handler)


class TestLlm:
    @pytest.mark.asyncio
    async def test_status_lists_models_and_knows_the_chosen_one(self):
        def handler(request):
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": [{"id": "qwen2.5:3b"}, {"id": "llama3.2:3b"}]})

        result = await llm.status(CONFIG, transport(handler))
        assert result == {
            "reachable": True,
            "models": ["qwen2.5:3b", "llama3.2:3b"],
            "model_present": True,
            "error": "",
        }
        result = await llm.status({**CONFIG, "model": "fehlt"}, transport(handler))
        assert result["reachable"] is True and result["model_present"] is False

    @pytest.mark.asyncio
    async def test_status_without_a_server_or_with_an_error(self):
        def down(request):
            raise httpx.ConnectError("refused")

        result = await llm.status(CONFIG, transport(down))
        assert result["reachable"] is False and "Läuft Ollama?" in result["error"]
        result = await llm.status(CONFIG, transport(lambda r: httpx.Response(500)))
        assert result["reachable"] is False and "500" in result["error"]
        result = await llm.status(CONFIG, transport(lambda r: httpx.Response(200, text="kein json")))
        assert result["reachable"] is False

    @pytest.mark.asyncio
    async def test_chat_sends_the_request_and_returns_the_text(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content), path=request.url.path)
            return httpx.Response(200, json={"choices": [{"message": {"content": "  Hallo!  "}}]})

        assert await llm.chat(CONFIG, [{"role": "user", "content": "Hi"}], transport(handler)) == "Hallo!"
        assert seen["path"] == "/v1/chat/completions" and seen["model"] == CONFIG["model"]
        assert seen["stream"] is False and seen["max_tokens"] == CONFIG["max_tokens"] and seen["temperature"] <= 0.3

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler", "fragment"),
        [
            (lambda r: httpx.Response(404, json={}), "ollama pull"),
            (lambda r: httpx.Response(500), "Fehler 500"),
            (lambda r: httpx.Response(200, json={"choices": []}), "leer oder unlesbar"),
            (lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}), "leer oder unlesbar"),
            (lambda r: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}), "leer oder unlesbar"),
            (lambda r: httpx.Response(200, text="<html>"), "leer oder unlesbar"),
        ],
    )
    async def test_chat_turns_server_problems_into_clear_messages(self, handler, fragment):
        with pytest.raises(llm.AssistantError, match=fragment):
            await llm.chat(CONFIG, [{"role": "user", "content": "x"}], transport(handler))

    @pytest.mark.asyncio
    async def test_chat_timeout_and_connection_errors(self):
        def slow(request):
            raise httpx.ReadTimeout("zu langsam")

        def down(request):
            raise httpx.ConnectError("refused")

        with pytest.raises(llm.AssistantError, match="nicht rechtzeitig"):
            await llm.chat(CONFIG, [], transport(slow))
        with pytest.raises(llm.AssistantError, match="Läuft Ollama"):
            await llm.chat(CONFIG, [], transport(down))


ITEMS = {12: "Gehäuse", 13: "Deckel {x}"}


class TestActions:
    def test_split_reply_removes_the_marker_line(self):
        text, raw = actions.split_reply('Mache ich.\nACTIONS: [{"type":"set_priority"}]')
        assert text == "Mache ich." and raw == '[{"type":"set_priority"}]'
        assert actions.split_reply("Nur Text.") == ("Nur Text.", None)
        assert actions.split_reply("actions: []\n")[0] == ""

    def test_valid_priority_and_due_actions_get_our_own_labels(self):
        raw = '[{"type":"set_priority","item_id":12,"priority":"urgent"},{"type":"set_due_date","item_id":13,"due_at":"2026-11-05T09:30:00Z"}]'
        accepted, rejected = actions.validate(raw, ITEMS, "de")
        assert rejected == 0 and len(accepted) == 2
        assert accepted[0] == {
            "type": "set_priority",
            "item_id": 12,
            "priority": 2,
            "label": "Priorität von Auftrag 12 (Gehäuse) auf „Eilig“ setzen",
        }
        assert accepted[1]["due_at"].startswith("2026-11-05T09:30") and "Deckel {x}" in accepted[1]["label"]

    def test_english_labels_and_clearing_a_due_date(self):
        accepted, _ = actions.validate('[{"type":"set_due_date","item_id":12,"due_at":null}]', ITEMS, "en")
        assert accepted == [
            {"type": "set_due_date", "item_id": 12, "due_at": None, "label": "Remove the due date of item 12 (Gehäuse)"}
        ]
        accepted, _ = actions.validate('[{"type":"set_priority","item_id":12,"priority":"low"}]', ITEMS, "en")
        assert accepted[0]["label"] == "Set the priority of item 12 (Gehäuse) to “Low”"

    @pytest.mark.parametrize(
        "entry",
        [
            {"type": "set_priority", "item_id": 99, "priority": "urgent"},
            {"type": "set_priority", "item_id": "12", "priority": "urgent"},
            {"type": "set_priority", "item_id": True, "priority": "urgent"},
            {"type": "set_priority", "item_id": 12, "priority": "sofort"},
            {"type": "set_priority", "item_id": 12, "priority": 2},
            {"type": "set_due_date", "item_id": 12, "due_at": "gestern"},
            {"type": "set_due_date", "item_id": 12, "due_at": 5},
            {"type": "set_due_date", "item_id": 12, "due_at": "1999-01-01T00:00:00Z"},
            {"type": "set_due_date", "item_id": 12, "due_at": "2300-01-01T00:00:00Z"},
            {"type": "cancel_item", "item_id": 12},
            {"type": "delete_everything"},
            {"item_id": 12},
            "kein Objekt",
            None,
        ],
    )
    def test_invalid_or_unknown_proposals_are_rejected(self, entry):
        assert actions.validate(json.dumps([entry]), ITEMS) == ([], 1)

    def test_unparsable_input_and_non_lists(self):
        for raw in (None, "", "kaputt", "[1, 2", '{"type": "set_priority"}', "[]"):
            assert actions.validate(raw, ITEMS)[0] == []

    def test_at_most_five_actions_and_no_duplicates(self):
        entry = {"type": "set_priority", "item_id": 12, "priority": "low"}
        accepted, _ = actions.validate(json.dumps([entry, entry]), ITEMS)
        assert len(accepted) == 1
        many = [{"type": "set_due_date", "item_id": 12, "due_at": f"2026-11-0{i}T10:00:00Z"} for i in range(1, 9)]
        accepted, rejected = actions.validate(json.dumps(many), ITEMS)
        assert len(accepted) == actions.MAX_ACTIONS and rejected == 3

    def test_text_around_the_json_list_is_tolerated(self):
        raw = 'bitte: [{"type":"set_priority","item_id":13,"priority":"normal"}] danke'
        assert len(actions.validate(raw, ITEMS)[0]) == 1

"""Tests für die Agentic Tool-Calling Engine des KI-Assistenten."""

from backend.app.services import assistant_tools


class TestAssistantTools:
    def test_get_tool_definitions_structure(self):
        tools = assistant_tools.get_tool_definitions()
        assert len(tools) >= 6

        names = [t["function"]["name"] for t in tools]
        assert "get_printer_status" in names
        assert "emergency_stop" in names
        assert "set_temperatures" in names
        assert "search_hms_knowledge" in names
        assert "get_wear_status" in names
        assert "calculate_quick_quote" in names

        # Prüfe OpenAI/Ollama Schema-Konformität
        for t in tools:
            assert t["type"] == "function"
            fn = t["function"]
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"

    def test_get_printer_status_does_not_invent_values(self):
        res = assistant_tools.execute_tool("get_printer_status", {})
        assert res["status"] == "unavailable"
        assert "data" not in res

    def test_emergency_stop_hits_registered_instance(self, monkeypatch):
        from backend.app.services import hardware_extension as hwmod

        calls = []

        class FakeHw:
            def emergency_stop(self):
                calls.append(1)
                return True, "gestoppt"

        monkeypatch.setattr(hwmod, "_per_printer", {1: FakeHw()})
        monkeypatch.setattr(hwmod, "_hardware", None)
        res = assistant_tools.execute_tool("emergency_stop", {"reason": "Kollisionsalarm"})
        assert calls == [1]
        assert res["status"] == "success"
        assert "Kollisionsalarm" in res["message"]

    def test_emergency_stop_reports_failure_honestly(self, monkeypatch):
        from backend.app.services import hardware_extension as hwmod

        class BrokenHw:
            def emergency_stop(self):
                raise OSError("GPIO weg")

        monkeypatch.setattr(hwmod, "_per_printer", {1: BrokenHw()})
        monkeypatch.setattr(hwmod, "_hardware", None)
        res = assistant_tools.execute_tool("emergency_stop", {"reason": "Test"})
        assert res["status"] == "error"
        assert "NICHT" in res["message"]

    def test_set_temperatures_is_not_faked(self):
        res = assistant_tools.execute_tool("set_temperatures", {"bed_temp": 65.0})
        assert res["status"] == "unavailable"

    def test_execute_search_hms_knowledge(self):
        res = assistant_tools.execute_tool("search_hms_knowledge", {"query": "0300-0100"})
        assert res["status"] == "success"
        assert res["matches_found"] >= 1
        first_match = res["results"][0]
        assert "0300-0100" in first_match["code"]

    def test_execute_get_wear_status(self):
        res = assistant_tools.execute_tool("get_wear_status", {})
        assert res["status"] == "success"
        assert "wear_overview" in res
        overview = res["wear_overview"]
        assert "components" in overview

    def test_execute_calculate_quick_quote(self):
        res = assistant_tools.execute_tool(
            "calculate_quick_quote",
            {"print_time_hours": 3.0, "filament_grams": 100.0, "material": "PETG"},
        )
        assert res["status"] == "success"
        calc = res["calculation"]
        assert calc["print_time_hours"] == 3.0
        assert calc["filament_grams"] == 100.0
        assert calc["material_cost"] == 2.50
        assert calc["net_total_eur"] > 0
        assert calc["gross_total_eur"] > calc["net_total_eur"]

    def test_execute_unknown_tool(self):
        res = assistant_tools.execute_tool("non_existent_tool", {})
        assert res["status"] == "error"
        assert "Unbekanntes Werkzeug" in res["message"]

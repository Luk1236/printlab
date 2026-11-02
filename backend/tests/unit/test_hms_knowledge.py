"""Tests für die RAG-Wissensbasis über Bambu Lab HMS-Fehlercodes und Wartung."""

from backend.app.services import hms_knowledge


class TestHMSKnowledge:
    def test_search_by_exact_error_code(self):
        results = hms_knowledge.search_knowledge("0300-0100", limit=2)
        assert len(results) >= 1
        top = results[0]
        assert top["code"] == "0300-0100"
        assert "Nozzle" in top["title"] or "Düse" in top["title"]
        assert len(top["steps"]) >= 3
        assert "Inbusschlüssel" in " ".join(top["tools_needed"])

    def test_search_by_maintenance_keyword(self):
        results = hms_knowledge.search_knowledge("Z-Achse schmieren", limit=2)
        assert len(results) >= 1
        found = any("Z-Gewindespindeln" in r["title"] or "MAINT-Z" in r["code"] for r in results)
        assert found

    def test_search_by_symptom_ams(self):
        results = hms_knowledge.search_knowledge("AMS Filament staut sich", limit=2)
        assert len(results) >= 1
        top = results[0]
        assert "AMS" in top["title"] or "0500-0300" in top["code"]

    def test_empty_query_returns_top_entries(self):
        results = hms_knowledge.search_knowledge("", limit=3)
        assert len(results) == 3

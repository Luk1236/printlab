"""Test für den Export der OpenAPI-Spezifikation und der Postman-Collection."""

from __future__ import annotations

import json
from pathlib import Path

from werkzeuge import export_api_docs

ROOT = Path(__file__).resolve().parents[3]


def test_build_postman_collection():
    dummy_openapi = {
        "info": {"title": "Test API", "version": "1.0.0", "description": "Test Desc"},
        "paths": {
            "/api/v1/printers": {
                "get": {"summary": "List Printers", "tags": ["printers"]},
                "post": {"summary": "Create Printer", "tags": ["printers"]},
            },
            "/api/v1/slicer/status": {
                "get": {"summary": "Slicer Status", "tags": ["slicer"]},
            },
        },
    }

    collection = export_api_docs.build_postman_collection(dummy_openapi)
    assert collection["info"]["name"] == "Test API v1.0.0"
    assert len(collection["variable"]) >= 1

    folders = {item["name"]: item["item"] for item in collection["item"]}
    assert "Printers" in folders
    assert "Slicer" in folders
    assert len(folders["Printers"]) == 2
    assert len(folders["Slicer"]) == 1


def test_export_all_creates_valid_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(export_api_docs, "ROOT", tmp_path)
    export_api_docs.export_all()

    docs_openapi = tmp_path / "docs" / "openapi.json"
    schema_openapi = tmp_path / "postman" / "schemas" / "printlab.openapi.json"
    collection_file = tmp_path / "postman" / "PrintLab.postman_collection.json"
    resources_yaml = tmp_path / ".postman" / "resources.yaml"

    assert docs_openapi.is_file()
    assert schema_openapi.is_file()
    assert collection_file.is_file()
    assert resources_yaml.is_file()

    spec = json.loads(docs_openapi.read_text(encoding="utf-8"))
    assert "paths" in spec
    assert len(spec["paths"]) > 10

    coll = json.loads(collection_file.read_text(encoding="utf-8"))
    assert len(coll.get("item", [])) > 5

"""Exportiert die vollständige OpenAPI-Spezifikation und generiert eine Postman-Collection für PrintLab.

Erzeugt:
- docs/openapi.json
- postman/schemas/printlab.openapi.json
- postman/PrintLab.postman_collection.json
- .postman/resources.yaml
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_postman_collection(openapi: dict[str, Any]) -> dict[str, Any]:
    """Wandelt die OpenAPI-Spezifikation in eine strukturierte Postman Collection v2.1.0 um."""
    title = openapi.get("info", {}).get("title", "PrintLab API")
    version = openapi.get("info", {}).get("version", "1.26.0")

    collection: dict[str, Any] = {
        "info": {
            "name": f"{title} v{version}",
            "description": openapi.get(
                "info",
                {},
            ).get(
                "description",
                "PrintLab 3D-Drucker-Verwaltung, Slicer & Abrechnung",
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "version": version,
        },
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000", "type": "string"},
            {"key": "token", "value": "", "type": "string"},
        ],
        "item": [],
    }

    # Gruppierung nach Tags
    tag_folders: dict[str, list[dict[str, Any]]] = {}

    for path, methods in openapi.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue

            tags = op.get("tags") or ["Allgemein"]
            tag = tags[0].capitalize()

            # URL aufteilen
            url_path = [p for p in path.strip("/").split("/") if p]
            url_obj = {
                "raw": "{{base_url}}" + path,
                "host": ["{{base_url}}"],
                "path": url_path,
                "variable": [],
            }

            for p in url_path:
                if p.startswith("{") and p.endswith("}"):
                    var_name = p[1:-1]
                    url_obj["variable"].append(
                        {
                            "key": var_name,
                            "value": "1",
                            "description": f"Parameter {var_name}",
                        }
                    )

            request_obj: dict[str, Any] = {
                "name": op.get("summary") or f"{method.upper()} {path}",
                "request": {
                    "method": method.upper(),
                    "header": [
                        {
                            "key": "Accept",
                            "value": "application/json",
                            "type": "text",
                        }
                    ],
                    "url": url_obj,
                    "description": op.get("description", ""),
                },
                "response": [],
            }

            if method.lower() in ("post", "put", "patch"):
                request_obj["request"]["header"].append(
                    {
                        "key": "Content-Type",
                        "value": "application/json",
                        "type": "text",
                    }
                )
                request_obj["request"]["body"] = {
                    "mode": "raw",
                    "raw": "{}",
                    "options": {"raw": {"language": "json"}},
                }

            tag_folders.setdefault(tag, []).append(request_obj)

    # Ordner sortieren
    for tag_name in sorted(tag_folders.keys()):
        collection["item"].append(
            {
                "name": tag_name,
                "item": sorted(tag_folders[tag_name], key=lambda x: str(x["name"])),
            }
        )

    return collection


def export_all() -> None:
    from backend.app.core.config import PRINTLAB_VERSION
    from backend.app.main import app

    openapi = app.openapi()
    openapi["info"]["title"] = "PrintLab API"
    openapi["info"]["version"] = PRINTLAB_VERSION
    openapi["info"]["description"] = (
        "Autonome 3D-Drucker-Verwaltung, integrierter Slicer, lokale KI und Abrechnung (Bambu Lab P2S)."
    )

    # 1. docs/openapi.json
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    docs_openapi = docs_dir / "openapi.json"
    docs_openapi.write_text(json.dumps(openapi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {docs_openapi.relative_to(ROOT)} exportiert ({len(openapi.get('paths', {}))} Pfade)")

    # 2. postman/schemas/printlab.openapi.json
    postman_schemas = ROOT / "postman" / "schemas"
    postman_schemas.mkdir(parents=True, exist_ok=True)
    schema_file = postman_schemas / "printlab.openapi.json"
    schema_file.write_text(json.dumps(openapi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {schema_file.relative_to(ROOT)} geschrieben")

    # 3. postman/PrintLab.postman_collection.json
    collection = build_postman_collection(openapi)
    collection_file = ROOT / "postman" / "PrintLab.postman_collection.json"
    collection_file.write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")
    folder_count = len(collection.get("item", []))
    item_count = sum(len(f.get("item", [])) for f in collection.get("item", []))
    print(f"[OK] {collection_file.relative_to(ROOT)} erstellt ({folder_count} Ordner, {item_count} Anfragen)")

    # 4. .postman/resources.yaml
    dot_postman = ROOT / ".postman"
    dot_postman.mkdir(parents=True, exist_ok=True)
    resources_yaml = dot_postman / "resources.yaml"
    resources_content = (
        "formatVersion: '1.0'\n"
        "localResources:\n"
        "  collections:\n"
        "    - name: PrintLab API\n"
        "      path: postman/PrintLab.postman_collection.json\n"
        "  specs:\n"
        "    - name: PrintLab OpenAPI\n"
        "      path: postman/schemas/printlab.openapi.json\n"
    )
    resources_yaml.write_text(resources_content, encoding="utf-8")
    print(f"[OK] {resources_yaml.relative_to(ROOT)} geschrieben")


if __name__ == "__main__":
    export_all()

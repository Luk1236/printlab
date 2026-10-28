"""Grenze für die Dateigröße: die großen Dateien dürfen nicht weiter wachsen, neue bleiben klein.

Sehr große Dateien (``main.py`` mit über 11 000 Zeilen) machen jede Änderung riskant und Zusammenführungen mit dem
Upstream mühsam. Dieser Test ist eine Sperre nach oben: Für jede große Datei steht hier ihre Höchstgröße. Wer in einer
solchen Datei etwas hinzufügt, verschiebt gleich viel Code in ein eigenes Modul oder senkt die Grenze beim Verkleinern.
Alle anderen Dateien müssen unter ``DEFAULT_LIMIT`` Zeilen bleiben. Die Grenzen nur senken, nie anheben.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIMIT = 2600

# Höchstzahl der Zeilen je Datei (Stand 28.10.2026, aufgerundet auf 25). Beim Verkleinern hier senken.
LIMITS = {
    "backend/app/main.py": 11075,
    "backend/app/services/print_scheduler.py": 8750,
    "backend/app/services/bambu_mqtt.py": 8500,
    "backend/app/core/database.py": 6350,
    "backend/app/api/routes/library.py": 6100,
    "backend/app/api/routes/archives.py": 5550,
    "backend/app/api/routes/printers.py": 4850,
    "backend/app/api/routes/inventory.py": 3200,
    "backend/app/services/notification_service.py": 3000,
    "frontend/src/pages/PrintersPage.tsx": 10150,
    "frontend/src/api/client.ts": 9700,
    "frontend/src/pages/SettingsPage.tsx": 7850,
    "frontend/src/pages/ArchivesPage.tsx": 4925,
    "frontend/src/pages/FileManagerPage.tsx": 4050,
    "frontend/src/pages/QueuePage.tsx": 3325,
    "frontend/src/pages/InventoryPage.tsx": 3275,
    "frontend/src/pages/ProfilesPage.tsx": 3075,
}


def _sources():
    for base, patterns in (("backend/app", ("*.py",)), ("frontend/src", ("*.ts", "*.tsx"))):
        folder = ROOT / base
        if not folder.is_dir():
            continue
        for pattern in patterns:
            for path in folder.rglob(pattern):
                parts = path.parts
                if "locales" in parts or "__tests__" in parts or "node_modules" in parts:
                    continue
                yield path


def _lines(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


@pytest.mark.skipif(not (ROOT / "backend" / "app").is_dir(), reason="Quellordner fehlt in dieser Umgebung")
def test_no_file_outgrows_its_limit():
    too_big = []
    for path in _sources():
        key = path.relative_to(ROOT).as_posix()
        limit = LIMITS.get(key, DEFAULT_LIMIT)
        count = _lines(path)
        if count > limit:
            too_big.append(f"{key}: {count} Zeilen, Grenze {limit}")
    assert not too_big, (
        "Datei zu groß geworden: neuen Code in ein eigenes Modul legen (siehe tests/unit/test_file_size_budget.py):\n"
        + "\n".join(too_big)
    )


def test_limits_point_at_existing_files_and_are_not_too_generous():
    """Ein Eintrag für eine gelöschte oder stark geschrumpfte Datei ist Ballast: Grenze mitsenken."""
    if not (ROOT / "backend" / "app").is_dir():
        pytest.skip("Quellordner fehlt in dieser Umgebung")
    stale = []
    for key, limit in LIMITS.items():
        if not (ROOT / key.split("/")[0]).is_dir():
            continue  # dieser Teil des Projekts fehlt in dieser Umgebung (zum Beispiel frontend/ im Docker-Image)
        path = ROOT / key
        if not path.is_file():
            stale.append(f"{key}: Datei gibt es nicht mehr")
        elif _lines(path) < limit - 400:
            stale.append(f"{key}: nur {_lines(path)} Zeilen, Grenze {limit} jetzt senken")
    assert not stale, "\n".join(stale)

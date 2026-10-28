#!/usr/bin/env python3
"""Release-Prüfung: Version, Changelog und die gebaute Oberfläche (static/) passen zum Tag.

Aufruf (im Projektordner):
  python werkzeuge/release_pruefen.py v1.6.4            prüft Tag gegen Version, Changelog und static/
  python werkzeuge/release_pruefen.py v1.6.4 --notes    gibt den Changelog-Abschnitt als Release-Text aus
  python werkzeuge/release_pruefen.py --write-static-hash   schreibt static/BUILD_SOURCE_SHA (macht der Bau-Workflow)
Rückgabecode 0 = in Ordnung, 1 = Mangel (mit Erklärung).

Warum static/: Der Pi liefert die fertig gebaute Oberfläche aus dem Ordner static/ aus und hat kein Node. Ändert sich
frontend/, muss static/ neu gebaut sein, bevor ein Tag gesetzt wird; sonst bekommt der Pi eine veraltete Oberfläche.
Der Hash der Quellen (Inhalt der Dateien laut Git, unabhängig von Zeilenenden) steht in static/BUILD_SOURCE_SHA.
"""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HASH_FILE = "static/BUILD_SOURCE_SHA"
# Alles, was die gebaute Oberfläche beeinflusst (Tests und Hilfsskripte nicht)
SOURCE_PATHS = [
    "frontend/src",
    "frontend/public",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/vite.config.ts",
    "frontend/postcss.config.js",
    "frontend/tsconfig.json",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.node.json",
]
EXCLUDED = ("frontend/src/__tests__/",)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
        ["git", *args],  # noqa: S607
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def static_source_hash(root: Path = ROOT) -> str:
    """Hash über die Git-Blob-Kennungen der Quelldateien (gleich unter Windows und Linux)."""
    listing = _git(root, "ls-files", "-s", "--", *SOURCE_PATHS)
    lines = []
    for line in sorted(listing.splitlines()):
        meta, _, path = line.partition("\t")
        if path.startswith(EXCLUDED):
            continue
        lines.append(f"{meta.split()[1]} {path}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def write_static_hash(root: Path = ROOT) -> str:
    value = static_source_hash(root)
    (root / HASH_FILE).write_text(value + "\n", encoding="utf-8")
    return value


def current_version(root: Path = ROOT) -> str | None:
    text = (root / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    match = re.search(r'^PRINTLAB_VERSION\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else None


def changelog_section(root: Path, version: str) -> str | None:
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(rf"^## v{re.escape(version)}\b[^\n]*\n(.*?)(?=^## v|\Z)", text, re.M | re.S)
    return match.group(0).strip() + "\n" if match else None


def check(tag: str, root: Path = ROOT) -> list[str]:
    """Liste der Mängel; leer, wenn der Tag veröffentlicht werden kann."""
    problems: list[str] = []
    if not re.fullmatch(r"v\d+\.\d+\.\d+(b\d+|rc\d+)?", tag):
        return [f"Tag-Name {tag!r} hat nicht die Form vX.Y.Z"]
    version = tag[1:]
    if current_version(root) != version:
        problems.append(
            f"PRINTLAB_VERSION ist {current_version(root)!r}, der Tag verlangt {version!r} (config.py ändern)"
        )
    if changelog_section(root, version) is None:
        problems.append(f"CHANGELOG.md hat keinen Abschnitt '## v{version}'")
    hash_path = root / HASH_FILE
    if not hash_path.is_file():
        problems.append("static/BUILD_SOURCE_SHA fehlt: Workflow 'Build static frontend' laufen lassen")
    elif hash_path.read_text(encoding="utf-8").strip() != static_source_hash(root):
        problems.append(
            "static/ ist nicht aktuell (frontend/ wurde seit dem letzten Bau geändert): "
            "Workflow 'Build static frontend' laufen lassen, Ergebnis holen, erst dann taggen"
        )
    return problems


def main(argv: list[str]) -> int:
    if "--write-static-hash" in argv:
        print(write_static_hash())
        return 0
    tags = [a for a in argv if not a.startswith("--")]
    if not tags:
        print(__doc__)
        return 1
    tag = tags[0]
    if "--notes" in argv:
        section = changelog_section(ROOT, tag.lstrip("v"))
        if section is None:
            print(f"Kein Changelog-Abschnitt für {tag}", file=sys.stderr)
            return 1
        print(section)
        return 0
    problems = check(tag)
    for problem in problems:
        print(f"MANGEL: {problem}")
    if not problems:
        print(f"{tag}: Version, Changelog und static/ passen zusammen.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

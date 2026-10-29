#!/usr/bin/env python3
"""Release anlegen — prüfen, signiert taggen, pushen.

Der Tag-Push startet das öffentliche Release samt Docker-Image. Genau hier ist
am 29.10.2026 ein Tag entstanden, dessen Version noch nicht erhöht war: der
Release-Gate-Build scheiterte, der Tag blieb ohne Release zurück. Dieses
Skript dreht die Reihenfolge um — erst prüfen (Version, Changelog, static/),
dann signiert taggen, dann pushen.

Aufruf (im Projektordner):
  python werkzeuge/release.py v1.13.0            prüft, taggt und pusht
  python werkzeuge/release.py v1.13.0 --check-only   nur prüfen (kein Tag)
  python werkzeuge/release.py v1.13.0 --no-push      Tag lokal anlegen
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import release_pruefen as gate

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
        ["git", *args],  # noqa: S607
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"git {' '.join(args)} fehlgeschlagen")
    return result.stdout


def release_title(tag: str) -> str:
    """Erste Zeile des Changelog-Abschnitts als Tag-Nachricht."""
    section = gate.changelog_section(ROOT, tag.lstrip("v")) or ""
    for line in section.splitlines():
        if line.startswith("## "):
            # "## v1.13.0 (29.10.2026) — Fehlerhilfe" -> "Fehlerhilfe"
            return line.split("—", 1)[-1].strip() or tag
    return tag


def tag_exists(tag: str) -> bool:
    try:
        _git("rev-parse", "--verify", f"refs/tags/{tag}")
    except SystemExit:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PrintLab-Release prüfen, taggen und pushen")
    parser.add_argument("tag", help="Ziel-Tag, z. B. v1.13.0")
    parser.add_argument("--check-only", action="store_true", help="nur prüfen, nichts anlegen")
    parser.add_argument("--no-push", action="store_true", help="Tag nur lokal anlegen")
    parser.add_argument("--force", action="store_true", help="vorhandenen Tag ersetzen (nur bewusst)")
    args = parser.parse_args(argv)

    problems = gate.check(args.tag, ROOT)
    if problems:
        print(f"{args.tag} kann nicht veröffentlicht werden:", file=sys.stderr)
        for problem in problems:
            print(f"  MANGEL: {problem}", file=sys.stderr)
        return 1
    print(f"{args.tag}: Version, Changelog und static/ passen zusammen.")
    if args.check_only:
        return 0

    dirty = _git("status", "--porcelain").strip()
    if dirty:
        print("Der Arbeitsbaum ist nicht sauber. Erst committen, dann veröffentlichen:", file=sys.stderr)
        print(dirty, file=sys.stderr)
        return 1
    if tag_exists(args.tag):
        if not args.force:
            print(f"Tag {args.tag} existiert bereits — nichts geändert.", file=sys.stderr)
            return 1
        _git("tag", "-d", args.tag)
        print(f"Alter Tag {args.tag} lokal gelöscht (--force).")

    message = f"PrintLab {args.tag} — {release_title(args.tag)}"
    _git("tag", args.tag, "-s", "-m", message)
    print(f"Tag {args.tag} signiert angelegt: {message}")
    if args.no_push:
        print("Nicht gepusht (--no-push).")
        return 0

    _git("push", "origin", "HEAD", args.tag)
    print(f"Branch und {args.tag} gepusht. Der Release-Gate-Workflow legt das Release an.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

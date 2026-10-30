#!/usr/bin/env python3
"""Alles prüfen, was die CI prüft, in einem Aufruf (Windows, Linux, macOS).

Aufruf im Projektordner:
  .venv\\Scripts\\python.exe werkzeuge\\lokal_pruefen.py            alles (Backend, Frontend, Release-Hinweis)
  ... lokal_pruefen.py --schnell                                   nur Format, Lint und Unit-Tests
  ... lokal_pruefen.py --audit                                     zusätzlich pip-audit und npm audit
Rückgabecode 0 = alles grün (Übersprungenes zählt nicht als Fehler, wird aber genannt), 1 = etwas ist rot.

Bekannte Eigenheiten, die das Skript abfängt:
- Parallel laufende Tests (pytest-xdist) können unter Windows einzelne Arbeitsprozesse abstürzen lassen
  (test_support_helpers). Fehlgeschlagene Dateien werden deshalb einmal nacheinander wiederholt; nur was auch dann
  fehlschlägt, zählt.
- Blockiert Windows die Tailwind-Binärdatei ("Anwendungssteuerungsrichtlinie"), laufen Frontend-Bau und zwei
  CSS-abhängige Testdateien hier nicht. Das wird als ÜBERSPRUNGEN gemeldet; der Bau läuft dann in GitHub
  (Workflow "Build static frontend"). Die Richtlinie wird nicht umgangen.
- pip-audit scheitert hinter einer Firmen- oder Sicherheitssoftware mit eigenem Zertifikat an der Prüfung des
  Servers. Dann das Zertifikat des Unternehmens in REQUESTS_CA_BUNDLE eintragen; die Prüfung wird nie abgeschaltet.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Die Testausgabe enthält Zeichen wie „❯“. Wird die Ausgabe in eine Datei
# umgeleitet (Windows-Konsole, cp1252), stirbt das Skript sonst mitten in der
# Ergebniszeile und der eigentliche Befund geht verloren.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except AttributeError:  # pragma: no cover - nur sehr alte Python-Versionen
    pass

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
BLOCKED_MARKERS = ("Anwendungssteuerungsrichtlinie", "application control policy", "Cannot find native binding")

OK, FAIL, SKIP = "OK", "FEHLER", "ÜBERSPRUNGEN"
results: list[tuple[str, str, str]] = []


def run(cmd: list[str], cwd: Path = ROOT, env: dict | None = None) -> tuple[int, str]:
    merged = {**os.environ, "PYTHONUTF8": "1", **(env or {})}
    try:
        proc = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged,
            check=False,
        )
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def record(name: str, level: str, detail: str = "") -> None:
    results.append((name, level, detail))
    print(f"[{level:<12}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def tail(text: str, lines: int = 8) -> str:
    return " | ".join(line.strip() for line in text.strip().splitlines()[-lines:] if line.strip())


def npx(*args: str) -> list[str]:
    return [shutil.which("npx") or "npx", *args]


def backend(quick: bool, audit: bool) -> None:
    py = sys.executable
    code, out = run([py, "-m", "ruff", "format", "--check", "backend/"])
    record("Backend: ruff format", OK if code == 0 else FAIL, "" if code == 0 else "ruff format backend ausführen")
    code, out = run([py, "-m", "ruff", "check", "backend/"])
    record("Backend: ruff check", OK if code == 0 else FAIL, "" if code == 0 else tail(out))

    target = ["backend/tests/unit"] if quick else ["backend/tests"]
    have_xdist = run([py, "-c", "import xdist"])[0] == 0
    base = [py, "-m", "pytest", *target, "-q", "-p", "no:cacheprovider"]
    code, out = run(base + (["-n", "4"] if have_xdist else []))
    if code != 0:
        failed = sorted(
            set(
                re.findall(r"FAILED (backend[\\/][^\s:]+\.py)", out)
                + re.findall(r"ERROR (backend[\\/][^\s:]+\.py)", out)
            )
        )
        crashed = sorted(set(re.findall(r"crashed while running '([^:']+\.py)", out)))
        files = sorted({f.replace("\\", "/") for f in failed + [f"backend/tests/{c}" for c in crashed]})
        if files and have_xdist:
            print(
                f"  {len(files)} Datei(en) einmal nacheinander wiederholen (xdist-Eigenheit unter Windows) ...",
                flush=True,
            )
            code, out = run([py, "-m", "pytest", *files, "-q", "-p", "no:cacheprovider"])
    summary = tail(out, 3)
    record("Backend: Tests" + (" (nur Unit)" if quick else ""), OK if code == 0 else FAIL, summary)

    if audit:
        code, out = run([py, "-m", "pip_audit", "-r", "requirements.txt", "--progress-spinner", "off"])
        if code == 0:
            record("Backend: pip-audit", OK)
        elif "CERTIFICATE_VERIFY_FAILED" in out:
            record(
                "Backend: pip-audit",
                SKIP,
                "Zertifikatsprüfung scheitert: REQUESTS_CA_BUNDLE auf das Firmenzertifikat setzen",
            )
        else:
            record("Backend: pip-audit", FAIL, tail(out))


def frontend(quick: bool, audit: bool) -> None:
    if not (FRONTEND / "node_modules").is_dir():
        record("Frontend", SKIP, "node_modules fehlt (npm ci im Ordner frontend)")
        return
    code, out = run([shutil.which("npm") or "npm", "run", "typecheck"], FRONTEND)  # wie in der CI (tsc -b)
    record("Frontend: TypeScript", OK if code == 0 else FAIL, "" if code == 0 else tail(out))
    code, out = run(["node", "scripts/check-i18n-parity.mjs"], FRONTEND)
    record("Frontend: Übersetzungen (15 Sprachen)", OK if code == 0 else FAIL, "" if code == 0 else tail(out))
    if quick:
        return
    code, out = run(npx("eslint", ".", "--concurrency", "auto"), FRONTEND)
    record("Frontend: ESLint", OK if code == 0 else FAIL, "" if code == 0 else tail(out))
    code, out = run(npx("vitest", "run"), FRONTEND)
    blocked = any(marker in out for marker in BLOCKED_MARKERS)
    failed_tests = re.search(r"Tests\s+(\d+) failed", out)
    if code == 0:
        record("Frontend: Tests", OK, tail(out, 2))
    elif blocked and not failed_tests:
        record(
            "Frontend: Tests",
            SKIP,
            "einzelne Dateien laufen hier nicht (Windows blockiert die Tailwind-Binärdatei); alle anderen bestanden",
        )
    else:
        record("Frontend: Tests", FAIL, tail(out))
    if audit:
        code, out = run(["npm", "audit", "--omit=dev"], FRONTEND)
        record("Frontend: npm audit (Produktion)", OK if code == 0 else FAIL, "" if code == 0 else tail(out, 4))


def release_hint() -> None:
    text = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    match = re.search(r'^PRINTLAB_VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        record("Release: Version", SKIP, "PRINTLAB_VERSION nicht gefunden")
        return
    version = match.group(1)
    code, out = run([sys.executable, "werkzeuge/release_pruefen.py", f"v{version}"])
    name = f"Release v{version}: Version, Changelog, static/"
    if code == 0:
        record(name, OK)
    else:
        record(name, SKIP, tail(out, 3) + " (nur vor dem Taggen wichtig)")


def main(argv: list[str]) -> int:
    quick = "--schnell" in argv
    audit = "--audit" in argv
    backend(quick, audit)
    frontend(quick, audit)
    if not quick:
        release_hint()
    failed = [name for name, level, _ in results if level == FAIL]
    skipped = [name for name, level, _ in results if level == SKIP]
    print(
        f"\n{sum(1 for _, level, _ in results if level == OK)} bestanden, {len(skipped)} übersprungen, {len(failed)} fehlgeschlagen."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

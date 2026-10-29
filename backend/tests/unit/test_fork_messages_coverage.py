"""Jede deutsche Fehlermeldung der Erweiterungs-Endpunkte braucht eine englische Übersetzung.

Die Erweiterungen (Hardware, Wartung, Kamera-Prüfungen, Angebote, Fernzugriff) schreiben ihre Meldungen auf Deutsch; die
Middleware ``ForkI18nMiddleware`` übersetzt sie nach Regeln in ``i18n/fork_messages.py``, wenn die Oberfläche nicht auf
Deutsch steht. Vergisst jemand die Regel für eine neue Meldung, sähe ein englischer Nutzer deutschen Text. Dieser Test
liest die Routen per AST, sammelt deutsche Texte in ``HTTPException(...)`` und verlangt für jeden eine Regel.
"""

import ast
import re
from pathlib import Path

import pytest

from backend.app.i18n import fork_messages

ROUTES = Path(__file__).resolve().parents[2] / "app" / "api" / "routes"
FORK_ROUTE_FILES = [
    "hardware.py",
    "quote.py",
    "remote_access.py",
    "maintenance_programs.py",
    "maintenance_print.py",
    "layer_alerts.py",
    "part_watcher.py",
    "first_layer_inspector.py",
    "spaghetti_check.py",
    "plate_calibration.py",
    "assistant.py",
    "selftest.py",
]

GERMAN_HINT = re.compile(
    r"[äöüßÄÖÜ]|\b(nicht|fehlt|ist|sind|wird|werden|kein|keine|nur|bitte|ungültig|zuerst|oder|und|mit|für|dem|den|der|die|das)\b",
    re.I,
)
ENGLISH_ONLY_HINT = re.compile(r"^[\x20-\x7e]+$")


def _literals(node: ast.AST):
    """Konstante Textteile eines Arguments (bei f-Strings nur die festen Anfangsteile)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        first = next((v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)), "")
        if first:
            yield first
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        yield from _literals(node.left)
    elif isinstance(node, ast.Tuple):
        for item in node.elts:
            yield from _literals(item)


def _messages(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "HTTPException":
            args = list(node.args[1:2]) + [kw.value for kw in node.keywords if kw.arg == "detail"]
            for arg in args:
                for text in _literals(arg):
                    yield node.lineno, text


def _is_german(text: str) -> bool:
    text = text.strip()
    if len(text) < 6 or not GERMAN_HINT.search(text):
        return False
    # Nur-ASCII-Text ohne deutsche Signalwörter ist Englisch; "und", "oder" allein reichen nicht, wenn es sonst englisch aussieht
    return not (
        ENGLISH_ONLY_HINT.match(text)
        and not re.search(r"[äöüß]|\b(nicht|fehlt|ungültig|kein|keine|bitte|zuerst)\b", text, re.I)
    )


def _cases():
    for name in FORK_ROUTE_FILES:
        path = ROUTES / name
        if not path.is_file():
            continue
        for line, text in _messages(path):
            if _is_german(text):
                yield pytest.param(name, line, text, id=f"{name}:{line}")


@pytest.mark.parametrize(("file", "line", "text"), list(_cases()))
def test_german_message_has_an_english_rule(file, line, text):
    translated = fork_messages.translate(text)
    assert translated != text, f"{file}:{line} hat keine englische Übersetzung in i18n/fork_messages.py: {text!r}"


def test_the_scan_finds_the_messages_it_should():
    """Schutz gegen einen stillen Leerlauf (zum Beispiel falsche Dateinamen oder Pfade)."""
    assert len(list(_cases())) >= 10, "zu wenige deutsche Meldungen gefunden: Dateiliste in diesem Test prüfen"


UPDATE_MESSAGES = [
    "Der aktuelle Git-Stand ist nicht lesbar.",
    "Sicherung nicht möglich: Platte voll",
    "Die Sicherung von printlab.db ist nicht in Ordnung.",
    "Ungültiger Name der Sicherung.",
    "Diese Sicherung gibt es nicht mehr.",
    "Die Sicherung enthält keine Datenbank.",
    "Die Sicherung ist beschädigt (printlab.db) und wird nicht eingespielt.",
    "Wiederherstellen nur mit eingeschalteter Anmeldung.",
    "Wiederherstellen geht nur mit dem Update-Schutz im Dienst (Installer erneut ausführen).",
    "Ungültiger Tag-Name.",
    "Der Release-Name ist ungültig.",
    "Die Datei mit den erlaubten Schlüsseln enthält keinen gültigen Schlüssel.",
    "ssh-keygen fehlt (Paket openssh-client); die Signatur kann nicht geprüft werden.",
    "Die Signaturprüfung hat zu lange gedauert.",
    "Der Tag v1.2.3 ist nicht gültig signiert (keine Signatur).",
]


@pytest.mark.parametrize("text", UPDATE_MESSAGES)
def test_update_guard_and_signature_messages_are_translated(text):
    english = fork_messages.translate(text)
    assert english != text
    assert not re.search(r"[äöüß]", english), f"noch deutsche Reste: {english!r}"


def test_update_endpoints_are_in_the_translated_scope():
    assert fork_messages.PATH_RX.match("/api/v1/updates/status")
    assert fork_messages.PATH_RX.match("/api/v1/updates/backups/20260101-120000/restore")


def test_alert_channel_messages_are_translated_correctly():
    assert (
        fork_messages.translate("Meldewege nur mit eingeschalteter Anmeldung ändern.")
        == "Alert channels can only be changed with authentication enabled."
    )
    assert (
        fork_messages.translate("Meldewege nur mit eingeschalteter Anmeldung testen.")
        == "Alert channels can only be tested with authentication enabled."
    )

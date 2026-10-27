r"""Aktiviert die Bambuddy-Anmeldung und setzt ein Admin-Passwort.

Aufruf im Projektordner:

    .venv\Scripts\python.exe werkzeuge\admin_passwort_setzen.py

Das Passwort wird mit getpass abgefragt (keine Anzeige, nicht im Verlauf) und
nur als PBKDF2-Hash in ``bambuddy.db`` gespeichert. Es erfüllt Bambuddys
Komplexitätsregel (Groß-/Kleinbuchstaben, Ziffer, Sonderzeichen, mind. 8 Zeichen).

Notfall (Anmeldung wieder aus):
    .venv\Scripts\python.exe werkzeuge\admin_passwort_setzen.py --deaktivieren
"""
from __future__ import annotations

import argparse
import getpass
import sqlite3
import string
from pathlib import Path

from passlib.context import CryptContext

PROJEKT = Path(__file__).resolve().parent.parent
DB = PROJEKT / "bambuddy.db"

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def pruefe_passwort(pw: str) -> None:
    if len(pw) < 8:
        raise ValueError("mindestens 8 Zeichen")
    if not any(c.isupper() for c in pw):
        raise ValueError("mindestens ein Großbuchstabe")
    if not any(c.islower() for c in pw):
        raise ValueError("mindestens ein Kleinbuchstabe")
    if not any(c.isdigit() for c in pw):
        raise ValueError("mindestens eine Ziffer")
    if not any(c in string.punctuation for c in pw):
        raise ValueError("mindestens ein Sonderzeichen")



def deaktivieren() -> None:
    with sqlite3.connect(DB) as con:
        con.execute("UPDATE settings SET value='false', updated_at=CURRENT_TIMESTAMP WHERE key='auth_enabled'")
    print("Anmeldung deaktiviert. Server neu starten.")


def setzen(benutzer: str) -> None:
    pw = getpass.getpass("Neues Admin-Passwort: ")
    wieder = getpass.getpass("Passwort wiederholen: ")
    if pw != wieder:
        raise SystemExit("Die Passwörter stimmen nicht überein.")
    try:
        pruefe_passwort(pw)
    except ValueError as exc:
        raise SystemExit(f"Passwort zu schwach: {exc}") from exc

    pw_hash = pwd_context.hash(pw)
    with sqlite3.connect(DB) as con:
        row = con.execute("SELECT id FROM users WHERE username=?", (benutzer,)).fetchone()
        if row:
            uid = row[0]
            con.execute(
                "UPDATE users SET password_hash=?, role='admin', is_active=1, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (pw_hash, uid),
            )
            print(f"Passwort für '{benutzer}' aktualisiert.")
        else:
            cur = con.execute(
                "INSERT INTO users (username, role, auth_source, is_active, created_at, updated_at, password_hash) "
                "VALUES (?, 'admin', 'local', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)",
                (benutzer, pw_hash),
            )
            uid = cur.lastrowid
            print(f"Admin '{benutzer}' angelegt.")
        group = con.execute("SELECT id FROM groups WHERE name='Administrators'").fetchone()
        if group:
            con.execute("INSERT OR IGNORE INTO user_groups (user_id, group_id) VALUES (?, ?)", (uid, group[0]))
        con.execute("UPDATE settings SET value='true', updated_at=CURRENT_TIMESTAMP WHERE key='auth_enabled'")
        con.execute("UPDATE settings SET value='true', updated_at=CURRENT_TIMESTAMP WHERE key='setup_completed'")
    print("Anmeldung aktiviert. Server neu starten und mit diesem Benutzer/Passwort anmelden.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bambuddy-Adminpasswort setzen oder Anmeldung deaktivieren.")
    parser.add_argument("--benutzer", default="lukas", help="Benutzername (Standard: lukas)")
    parser.add_argument("--deaktivieren", action="store_true", help="Anmeldung wieder ausschalten")
    args = parser.parse_args()
    if not DB.is_file():
        raise SystemExit(f"Datenbank nicht gefunden: {DB}")
    if args.deaktivieren:
        deaktivieren()
    else:
        setzen(args.benutzer.strip() or "lukas")


if __name__ == "__main__":
    main()

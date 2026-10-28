"""Signaturprüfung für Updates: nur Tags, die mit einem bekannten Schlüssel signiert sind, werden eingespielt.

Der Updater holt einen Release-Tag von GitHub und setzt den Programmordner darauf. Ohne Prüfung genügt die Übernahme des
GitHub-Kontos, um Code auf dem Pi auszuführen. Mit dieser Prüfung muss ein Tag zusätzlich mit einem SSH-Schlüssel
signiert sein, dessen öffentlicher Teil in der Datei ``update_allowed_signers`` **auf dem Pi** steht (Format von
``ssh-keygen``: ``name namespaces="git" ssh-ed25519 AAAA...``). Die Datei liegt bewusst nicht im Repo und nicht bei
GitHub: ein Angreifer mit GitHub-Zugang kann dort eigene Schlüssel eintragen und „Verified" bekommen, aber nicht diese
Datei ändern.

Ist die Datei da, wird erzwungen (kein Tag ohne gültige Signatur, auch kein Branch). Fehlt sie, bleibt das Verhalten wie
bisher; die Oberfläche weist darauf hin. Geprüft wird lokal mit ``git verify-tag`` und ``ssh-keygen``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path

SIGNERS_NAME = "update_allowed_signers"
ENV_SIGNERS = "PRINTLAB_UPDATE_SIGNERS"
TAG_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,100}")
KEY_LINE_RX = re.compile(
    r"^\S+(\s+\S+=\S+)*\s+(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+|sk-ssh-ed25519@openssh\.com)\s+\S+"
)


def is_safe_ref_name(ref: str) -> bool:
    """Ein Tag-Name, der git nie als Option oder Pfad lesen kann (gilt auch ohne Signaturprüfung)."""
    return bool(TAG_RX.fullmatch(ref)) and ".." not in ref and not ref.endswith((".", "/", ".lock"))


def signers_file(data_dir: Path | str) -> Path | None:
    """Pfad der Datei mit den erlaubten Schlüsseln, wenn eine eingerichtet ist (Umgebungsvariable hat Vorrang)."""
    override = os.environ.get(ENV_SIGNERS, "").strip()
    path = Path(override) if override else Path(data_dir).joinpath(SIGNERS_NAME)  # SEC-PATH-OK: feste Konstante
    return path if path.is_file() else None


def has_valid_key(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    return any(KEY_LINE_RX.match(line.strip()) for line in lines if line.strip() and not line.lstrip().startswith("#"))


def policy(data_dir: Path | str) -> dict:
    """Zustand für Update-Prüfung und Oberfläche: ``enforced`` und ``reason`` (nur wenn nicht nutzbar)."""
    path = signers_file(data_dir)
    if path is None:
        return {"enforced": False, "reason": None}
    if not has_valid_key(path):
        return {"enforced": True, "reason": "Die Datei mit den erlaubten Schlüsseln enthält keinen gültigen Schlüssel."}
    return {"enforced": True, "reason": None}


async def verify_tag(git_path: str, app_dir: Path, tag: str, signers: Path) -> tuple[bool, str]:
    """True, wenn ``tag`` ein Tag mit gültiger Signatur eines erlaubten Schlüssels ist. Schlägt immer zu (fail-closed)."""
    if not is_safe_ref_name(tag):
        return False, "Ungültiger Tag-Name."
    if not has_valid_key(signers):
        return False, "Die Datei mit den erlaubten Schlüsseln enthält keinen gültigen Schlüssel."
    if shutil.which("ssh-keygen") is None:
        return False, "ssh-keygen fehlt (Paket openssh-client); die Signatur kann nicht geprüft werden."
    process = await asyncio.create_subprocess_exec(
        git_path,
        "-c",
        f"safe.directory={app_dir}",
        "-c",
        "gpg.format=ssh",
        "-c",
        f"gpg.ssh.allowedSignersFile={signers}",
        "verify-tag",
        f"refs/tags/{tag}",
        cwd=str(app_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        return False, "Die Signaturprüfung hat zu lange gedauert."
    if process.returncode != 0:
        detail = (stderr or b"").decode(errors="replace").strip().splitlines()
        return False, f"Der Tag {tag} ist nicht gültig signiert ({detail[-1][:160] if detail else 'keine Signatur'})."
    return True, ""

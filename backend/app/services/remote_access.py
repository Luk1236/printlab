"""Fernzugriff auf PrintLab über Tailscale, ohne Root-Rechte (Userspace-Modus).

PrintLab lädt bei Bedarf die offiziellen Tailscale-Programme (``tailscale``, ``tailscaled``) in den Datenordner,
startet den Dienst im Userspace-Netzwerkmodus (kein TUN-Gerät, kein ``sudo``), meldet den Rechner im privaten
Tailnet des Benutzers an und gibt den PrintLab-Port nur innerhalb dieses Tailnets frei (``tailscale serve``).
Nichts wird ins öffentliche Internet geöffnet. Ist schon ein systemweites Tailscale installiert und läuft es,
wird dieses benutzt und nicht verändert.

Sicherheit: Der Download kommt nur von ``pkgs.tailscale.com`` und wird gegen die dort veröffentlichte
SHA-256-Summe geprüft; aus dem Archiv werden ausschließlich die zwei Programme entpackt. Alle Befehle laufen
als Argumentliste ohne Shell mit minimaler Umgebung. Die Routen lassen Änderungen nur mit eingeschalteter
Anmeldung zu.

Nicht gegen ein echtes Tailnet getestet (Stand der Entwicklung): die Tests prüfen Parsen, Prüfsumme, Entpacken
und die Befehlszeilen mit einem Ersatz für das Programm.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

STATE_DIR = settings.base_dir / "tailscale"
BIN_DIR = STATE_DIR / "bin"
SOCKET = STATE_DIR / "tailscaled.sock"
STATE_FILE = STATE_DIR / "tailscaled.state"
CONFIG_PATH = STATE_DIR / "remote_access.json"

PKGS = "https://pkgs.tailscale.com/stable"
MAX_DOWNLOAD = 120 * 1024 * 1024
ARCH = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64", "armv7l": "arm", "armv6l": "arm"}
LOGIN_URL_RX = re.compile(r"https://login\.tailscale\.com/a/[A-Za-z0-9]+")
_ENV = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR"}}

_daemon: subprocess.Popen | None = None


class RemoteAccessError(Exception):
    """Fehler mit einer Meldung, die der Benutzer lesen darf."""


def supported() -> bool:
    return sys.platform.startswith("linux")


def _read_config() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_config(update: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = {**_read_config(), **update}
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def _local_binaries() -> tuple[Path, Path] | None:
    cli, daemon = BIN_DIR / "tailscale", BIN_DIR / "tailscaled"
    return (cli, daemon) if cli.is_file() and daemon.is_file() else None


def _system_cli() -> str | None:
    return shutil.which("tailscale")


async def _exec(args: list[str], timeout: float = 30.0) -> tuple[int | None, str]:
    """Programm ohne Shell ausführen; liefert (Rückgabecode, Ausgabe aus stdout + stderr)."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=_ENV
        )
    except OSError as exc:
        raise RemoteAccessError(f"Programm nicht startbar: {exc}") from exc
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RemoteAccessError("Zeitüberschreitung beim Aufruf von tailscale.") from None
    return process.returncode, out.decode("utf-8", "replace")


def _cli_prefix() -> list[str]:
    """Befehlsanfang: eigenes Programm mit eigenem Socket, sonst ein systemweites Tailscale."""
    local = _local_binaries()
    if local:
        return [str(local[0]), "--socket", str(SOCKET)]
    system = _system_cli()
    if system:
        return [system]
    raise RemoteAccessError("Tailscale ist nicht installiert.")


async def _ts(*args: str, timeout: float = 30.0) -> tuple[int | None, str]:
    return await _exec([*_cli_prefix(), *args], timeout=timeout)


def _daemon_running() -> bool:
    return _daemon is not None and _daemon.poll() is None


async def status() -> dict[str, Any]:
    """Zustand des Fernzugriffs; wirft nie."""
    info: dict[str, Any] = {
        "supported": supported(),
        "installed": bool(_local_binaries() or _system_cli()),
        "managed": bool(_local_binaries()),
        "daemon_running": _daemon_running(),
        "state": "off",
        "login_url": None,
        "ips": [],
        "dns_name": "",
        "serving": False,
        "enabled": bool(_read_config().get("enabled")),
        "error": None,
    }
    if not info["supported"] or not info["installed"]:
        return info
    if info["managed"] and not info["daemon_running"]:
        info["state"] = "stopped"
        return info
    try:
        code, out = await _ts("status", "--json", timeout=15)
        if code not in (0, 1):  # 1 = abgemeldet/gestoppt, trotzdem gültiges JSON
            info["error"] = out.strip()[:300]
            return info
        data = json.loads(out)
    except (RemoteAccessError, ValueError) as exc:
        info["error"] = str(exc)[:300]
        return info
    backend = str(data.get("BackendState", ""))
    me = data.get("Self") or {}
    info["ips"] = [str(ip) for ip in (me.get("TailscaleIPs") or data.get("TailscaleIPs") or [])]
    info["dns_name"] = str(me.get("DNSName", "")).rstrip(".")
    info["login_url"] = data.get("AuthURL") or None
    info["state"] = {"Running": "connected", "NeedsLogin": "login", "Starting": "login", "Stopped": "stopped"}.get(
        backend, "off"
    )
    if info["state"] == "connected":
        try:
            _, served = await _ts("serve", "status", timeout=15)
            info["serving"] = "tcp://" in served or "TCP" in served or "|--" in served
        except RemoteAccessError:
            pass
    return info


# --- Installation ----------------------------------------------------------------------------------------


async def install() -> str:
    """Offizielle Tailscale-Programme laden, prüfen und entpacken. Gibt die Version zurück."""
    if not supported():
        raise RemoteAccessError("Fernzugriff gibt es nur unter Linux.")
    arch = ARCH.get(platform.machine().lower())
    if not arch:
        raise RemoteAccessError(f"Unbekannte Prozessorarchitektur: {platform.machine()}")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        listing = await client.get(f"{PKGS}/?mode=json")
        listing.raise_for_status()
        name = (listing.json().get("Tarballs") or {}).get(arch)
        if not name or not re.fullmatch(r"tailscale_[0-9.]+_[a-z0-9]+\.tgz", name):
            raise RemoteAccessError("Kein passendes Tailscale-Paket gefunden.")
        sum_resp = await client.get(f"{PKGS}/{name}.sha256")
        sum_resp.raise_for_status()
        expected = sum_resp.text.split()[0].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RemoteAccessError("Prüfsumme von Tailscale nicht lesbar.")
        body = io.BytesIO()
        digest = hashlib.sha256()
        async with client.stream("GET", f"{PKGS}/{name}") as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                body.write(chunk)
                digest.update(chunk)
                if body.tell() > MAX_DOWNLOAD:
                    raise RemoteAccessError("Tailscale-Download ist unerwartet groß.")
    if digest.hexdigest() != expected:
        raise RemoteAccessError("Prüfsumme des Tailscale-Downloads stimmt nicht — abgebrochen.")
    _extract(body.getvalue())
    return name.split("_")[1]


def _extract(data: bytes) -> None:
    """Nur die Programme ``tailscale`` und ``tailscaled`` aus dem Archiv übernehmen (kein Pfad aus dem Archiv)."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    found = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            base = member.name.rsplit("/", 1)[-1]
            if not member.isfile() or base not in ("tailscale", "tailscaled"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            target = BIN_DIR / base
            tmp = target.with_name(base + ".part")
            tmp.write_bytes(handle.read())
            tmp.chmod(0o755)
            tmp.replace(target)
            found.add(base)
    if found != {"tailscale", "tailscaled"}:
        raise RemoteAccessError("Das Tailscale-Archiv enthält nicht die erwarteten Programme.")


# --- Dienst, Anmeldung, Freigabe -----------------------------------------------------------------------


async def start_daemon() -> None:
    """tailscaled im Userspace-Modus starten (nur für das eigene Programm; ein System-Tailscale bleibt unberührt)."""
    global _daemon
    local = _local_binaries()
    if not local or _daemon_running():
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _daemon = subprocess.Popen(  # noqa: S603 - feste Argumentliste, kein Shell-Aufruf
        [str(local[1]), "--tun=userspace-networking", f"--socket={SOCKET}", f"--state={STATE_FILE}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_ENV,
        start_new_session=True,
    )
    for _ in range(40):
        if SOCKET.exists():
            return
        if _daemon.poll() is not None:
            raise RemoteAccessError("tailscaled hat sich sofort beendet.")
        await asyncio.sleep(0.25)
    raise RemoteAccessError("tailscaled ist nicht rechtzeitig bereit geworden.")


def stop_daemon() -> None:
    global _daemon
    if _daemon_running():
        _daemon.terminate()
        try:
            _daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _daemon.kill()
    _daemon = None


async def login() -> str | None:
    """Anmeldung anstoßen; liefert den Anmelde-Link (oder ``None``, wenn schon angemeldet)."""
    code, out = await _ts("up", "--hostname=printlab", "--accept-dns=false", "--timeout=6s", timeout=40)
    match = LOGIN_URL_RX.search(out)
    if match:
        return match.group(0)
    current = await status()
    if current["state"] == "connected":
        return None
    if current["login_url"]:
        return str(current["login_url"])
    raise RemoteAccessError(f"Tailscale-Anmeldung nicht möglich: {out.strip()[:200] or code}")


async def share(port: int) -> None:
    """PrintLab-Port nur innerhalb des Tailnets erreichbar machen."""
    if not 1 <= int(port) <= 65535:
        raise RemoteAccessError("Ungültiger Port.")
    code, out = await _ts("serve", "--bg", f"--tcp={int(port)}", f"tcp://localhost:{int(port)}", timeout=30)
    if code != 0:
        raise RemoteAccessError(f"Freigabe fehlgeschlagen: {out.strip()[:200]}")
    _write_config({"enabled": True, "port": int(port)})


async def setup(port: int) -> dict[str, Any]:
    """Alles in einem Schritt: installieren (falls nötig), starten, Anmeldung anstoßen, ggf. freigeben."""
    if not (_local_binaries() or _system_cli()):
        await install()
    await start_daemon()
    url = await login()
    result = await status()
    if result["state"] == "connected":
        await share(port)
        result = await status()
    result["login_url"] = url or result["login_url"]
    _write_config({"enabled": True, "port": int(port)})
    return result


async def disable() -> dict[str, Any]:
    """Freigabe beenden, abmelden, Dienst stoppen."""
    try:
        await _ts("serve", "reset", timeout=20)
        await _ts("down", timeout=20)
    except RemoteAccessError:
        pass
    stop_daemon()
    _write_config({"enabled": False})
    return await status()


async def autostart() -> None:
    """Beim Start von PrintLab: war der Fernzugriff an, Dienst und Freigabe wieder herstellen."""
    config = _read_config()
    if not config.get("enabled") or not supported() or not _local_binaries():
        return
    try:
        await start_daemon()
        await asyncio.sleep(1)
        current = await status()
        if current["state"] == "connected":
            await share(int(config.get("port") or 8000))
    except RemoteAccessError as exc:
        logger.warning("[Fernzugriff] Autostart fehlgeschlagen: %s", exc)

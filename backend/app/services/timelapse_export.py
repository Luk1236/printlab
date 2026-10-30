"""Zeitraffer als MP4 aus den Schichtbildern.

Der Schicht-Zeitraffer (``services/layer_timelapse.py``) sammelt während des
Drucks ein Bild je Schicht und sticht am Ende automatisch ein Video. Dieses
Modul erweitert das um die Aufbewahrung: mit ``keep_frames`` bleiben die
Bilder nach dem Druck liegen, statt gelöscht zu werden. Aus ihnen lässt sich
jederzeit erneut ein MP4 rendern — mit anderer Bildrate, wenn das automatische
Stechen fehlschlug oder das Ergebnis zu schnell bzw. zu langsam ist.

Ablage:

* ``data/timelapse_kept/<archive_id>/<session_id>/layer_*.jpg`` — aufbewahrte Schichtbilder
* ``data/timelapse_exports/`` — gerenderte MP4s

Aufbewahrung: je Archiv höchstens ``max_kept_per_archive`` Sitzungen und
``retention_days`` Tage; je Archiv höchstens ``max_exports_per_archive``
Videos. Ältere werden beim nächsten Aufräumen gelöscht — die Aufbewahrung ist
eine Obergrenze, keine Zusage. Standardmäßig ist ``keep_frames`` **aus**:
Schichtbilder kosten auf dem Pi leicht einige hundert MB je Druck.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.utils.ffmpeg_output import NO_FFMPEG_OUTPUT, summarize_ffmpeg_stderr

CONFIG_PATH = settings.base_dir / "timelapse_export.json"
KEPT_ROOT = settings.base_dir / "timelapse_kept"
EXPORT_ROOT = settings.base_dir / "timelapse_exports"

DEFAULTS: dict[str, Any] = {
    "keep_frames": False,
    "retention_days": 14,
    "max_kept_per_archive": 3,
    "max_exports_per_archive": 3,
    "fps": 24,
}
MAX_RETENTION_DAYS = 365
MAX_KEPT = 20
MAX_EXPORTS = 20
MIN_FPS = 1
MAX_FPS = 60
STITCH_TIMEOUT_SECONDS = 300


def _as_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if minimum <= number <= maximum else fallback


def read_config() -> dict[str, Any]:
    """Aufbewahrungs-Einstellungen; fehlende oder ungültige Werte fallen auf die Vorgabe zurück."""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "keep_frames": bool(data.get("keep_frames", DEFAULTS["keep_frames"])),
        "retention_days": _as_int(data.get("retention_days"), 1, MAX_RETENTION_DAYS, DEFAULTS["retention_days"]),
        "max_kept_per_archive": _as_int(
            data.get("max_kept_per_archive"), 1, MAX_KEPT, DEFAULTS["max_kept_per_archive"]
        ),
        "max_exports_per_archive": _as_int(
            data.get("max_exports_per_archive"), 1, MAX_EXPORTS, DEFAULTS["max_exports_per_archive"]
        ),
        "fps": _as_int(data.get("fps"), MIN_FPS, MAX_FPS, DEFAULTS["fps"]),
    }


def write_config(update: dict[str, Any]) -> dict[str, Any]:
    """Nur bekannte Schlüssel übernehmen, ungültige Werte still auf die Vorgabe ziehen."""
    merged = {**read_config(), **{k: v for k, v in (update or {}).items() if k in DEFAULTS}}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return read_config()


def _safe_component(value: Any) -> str:
    """Nur Buchstaben, Ziffern, ``-`` und ``_`` — Sitzungsnamen kommen aus der Umgebung."""
    text = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")
    return text[:80]


def frame_files(folder: Path) -> list[Path]:
    """Schichtbilder einer Sitzung, nach Schichtnummer sortiert."""
    try:
        return sorted(p for p in folder.glob("layer_*.jpg") if p.is_file())
    except OSError:
        return []


def _session_dirs(archive_id: int) -> list[Path]:
    root = KEPT_ROOT / str(int(archive_id))
    try:
        return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    except OSError:
        return []


def keep_frames(archive_id: int | None, frames_dir: Path, session_id: str) -> Path | None:
    """Schichtbilder dauerhaft ablegen (statt löschen) und alte Aufbewahrungen aufräumen.

    Gibt den neuen Ordner zurück, oder ``None``, wenn es nichts zu behalten gab.
    Ein Fehler beim Verschieben ist kein Grund, den Druckabschluss scheitern zu
    lassen — der Aufrufer löscht dann wie bisher.
    """
    if not archive_id or not frame_files(frames_dir):
        return None
    target = KEPT_ROOT / str(int(archive_id)) / (_safe_component(session_id) or "session")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Zwei Abschlüsse mit derselben Sitzungskennung: nicht überschreiben.
        target = target.with_name(target.name + "_" + datetime.now(timezone.utc).strftime("%H%M%S"))
    shutil.move(str(frames_dir), str(target))
    prune_kept(archive_id)
    return target


def list_sources(archive_id: int) -> list[dict[str, Any]]:
    """Aufbewahrte Schichtbild-Sitzungen eines Archivs (neueste zuerst)."""
    cfg = read_config()
    sources: list[dict[str, Any]] = []
    for folder in _session_dirs(archive_id):
        files = frame_files(folder)
        if not files:
            continue
        try:
            newest = max(p.stat().st_mtime for p in files)
        except OSError:
            newest = 0.0
        sources.append(
            {
                "session": folder.name,
                "frames": len(files),
                "newest_frame": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat() if newest else None,
            }
        )
    return sources[: cfg["max_kept_per_archive"]]


def prune_kept(archive_id: int) -> int:
    """Aufbewahrung je Archiv begrenzen (Alter zuerst, dann Anzahl). Gibt die Zahl der Löschungen zurück."""
    cfg = read_config()
    cutoff = time.time() - cfg["retention_days"] * 86400
    removed = 0
    folders = _session_dirs(archive_id)
    for index, folder in enumerate(folders):
        files = frame_files(folder)
        try:
            newest = max((p.stat().st_mtime for p in files), default=0.0)
        except OSError:
            newest = 0.0
        too_old = newest and newest < cutoff
        too_many = index >= cfg["max_kept_per_archive"]
        if too_old or too_many:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    # Leere Archivordner bleiben sonst liegen.
    try:
        root = KEPT_ROOT / str(int(archive_id))
        if root.is_dir() and not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass
    return removed


def build_concat_text(files: list[Path], fps: int) -> str:
    """Inhalt der ffmpeg-concat-Liste: jede Schicht steht ``1/fps`` Sekunden, das letzte Bild länger.

    Der concat-Demuxer verlangt, dass die letzte Datei ein zweites Mal genannt
    wird, sonst fehlt ihr die Dauer und das Video endet zu früh.
    """
    if not files:
        return ""
    duration = 1.0 / max(1, int(fps))
    lines: list[str] = []
    for path in files:
        escaped = str(path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        lines.append(f"duration {duration:.6f}")
    escaped_last = str(files[-1]).replace("'", "'\\''")
    lines.append(f"file '{escaped_last}'")
    return "\n".join(lines) + "\n"


def _ffmpeg_command(ffmpeg: str, concat_path: Path, output_path: Path, fps: int) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-r",
        str(int(fps)),
        "-i",
        str(concat_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


async def render(archive_id: int, session_id: str | None = None, fps: int | None = None) -> dict[str, Any]:
    """MP4 aus einer aufbewahrten Sitzung rendern (Standard: neueste).

    Rückgabe: ``{"name", "path", "frames", "fps", "bytes"}``. Fehler als
    ``ValueError`` mit lesbarer deutscher Meldung — die Route macht daraus 4xx.
    """
    cfg = read_config()
    rate = _as_int(fps if fps is not None else cfg["fps"], MIN_FPS, MAX_FPS, cfg["fps"])
    sources = list_sources(archive_id)
    if not sources:
        raise ValueError(
            "Keine aufbewahrten Schichtbilder für dieses Archiv. Aufbewahrung unter Zeitraffer einschalten — "
            "sie gilt ab dem nächsten Druck."
        )
    chosen = None
    if session_id:
        wanted = _safe_component(session_id)
        chosen = next((s for s in sources if s["session"] == wanted), None)
        if chosen is None:
            raise ValueError("Diese Schichtbild-Sitzung gibt es für das Archiv nicht (mehr).")
    else:
        chosen = sources[0]

    folder = KEPT_ROOT / str(int(archive_id)) / chosen["session"]
    files = frame_files(folder)
    if not files:
        raise ValueError("Die Sitzung enthält keine Schichtbilder mehr.")

    from backend.app.services.camera import get_ffmpeg_path

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg wurde nicht gefunden — ohne FFmpeg lässt sich kein MP4 rendern.")

    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"archiv_{int(archive_id)}_{chosen['session']}_{rate}fps_{stamp}.mp4"
    output_path = EXPORT_ROOT / name
    concat_path = EXPORT_ROOT / f".{name}.txt"
    concat_path.write_text(build_concat_text(files, rate), encoding="utf-8")

    try:
        process = await asyncio.create_subprocess_exec(
            *_ffmpeg_command(ffmpeg, concat_path, output_path, rate),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=STITCH_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            raise RuntimeError("Das Rendern hat zu lange gedauert (über 5 Minuten).") from None
        if process.returncode != 0:
            detail = summarize_ffmpeg_stderr(stderr) or NO_FFMPEG_OUTPUT
            raise RuntimeError(f"FFmpeg konnte das Video nicht erzeugen: {detail}")
    finally:
        concat_path.unlink(missing_ok=True)

    prune_exports(archive_id)
    try:
        size = output_path.stat().st_size
    except OSError:
        size = 0
    return {
        "name": name,
        "path": str(output_path),
        "frames": len(files),
        "fps": rate,
        "bytes": size,
        "source": chosen["session"],
    }


def list_exports(archive_id: int) -> list[dict[str, Any]]:
    """Gerenderte MP4s eines Archivs (neueste zuerst)."""
    prefix = f"archiv_{int(archive_id)}_"
    try:
        files = [p for p in EXPORT_ROOT.glob(f"{prefix}*.mp4") if p.is_file()]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append(
            {
                "name": path.name,
                "bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return result


def prune_exports(archive_id: int) -> int:
    """Nur die letzten ``max_exports_per_archive`` Videos je Archiv behalten."""
    cfg = read_config()
    removed = 0
    for entry in list_exports(archive_id)[cfg["max_exports_per_archive"] :]:
        try:
            (EXPORT_ROOT / entry["name"]).unlink()
            removed += 1
        except OSError:
            pass
    return removed


def resolve_export(archive_id: int, name: str) -> Path | None:
    """Dateiname prüfen und den Pfad nur innerhalb des Export-Ordners auflösen."""
    clean = _safe_component(Path(str(name)).stem)
    if not clean or clean != Path(str(name)).stem or not str(name).endswith(".mp4"):
        return None
    # Nur ein reiner Dateiname — kein Verzeichnisanteil, keine Laufwerksangabe.
    if Path(str(name)).name != str(name):
        return None
    if not clean.startswith(f"archiv_{int(archive_id)}_"):
        return None
    path = EXPORT_ROOT / f"{clean}.mp4"
    try:
        resolved = path.resolve()
        if EXPORT_ROOT.resolve() not in resolved.parents:
            return None
    except OSError:
        return None
    return path if path.is_file() else None

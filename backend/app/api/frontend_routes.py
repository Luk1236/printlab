"""Auslieferung der gebauten Oberfläche: React-Build, PWA-Dateien und der Router-Catch-all.

Eigenes Modul, weil ``main.py`` an seiner Zeilengrenze steht: Die Reihenfolge der Registrierung bleibt gleich
(``register_frontend(app)`` wird an derselben Stelle aufgerufen, an der die Routen vorher standen), damit der
Catch-all weiterhin zuletzt greift.

Cache: Vite schreibt den Inhalts-Hash in jeden Dateinamen (``client-CDk7AWno.js``). Ändert sich der Inhalt, ändert
sich der Name — deshalb darf der Browser diese Dateien dauerhaft behalten, ohne je nachzufragen. Das spart bei jedem
Seitenaufruf über Tailscale die Rückfragen (``304``) für jeden Baustein. ``index.html`` bleibt davon ausgenommen:
Sie ist die einzige Datei, die weiß, welcher Hash gerade gilt (siehe ``_HTML_CACHE_HEADERS``).
"""

import gzip
import mimetypes
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import settings as app_settings

# index.html must always be revalidated — Vite emits content-hashed JS/CSS
# bundles (e.g. `index-JRaF_JhW.js`), so the JS itself is safe to cache
# forever, but the HTML wrapping it is the only file that knows which hash
# is current. Without explicit cache-control headers Chromium decides
# heuristically (typically 10% of the time since Last-Modified) and on
# long-running kiosks happily serves stale HTML across browser restarts.
# That stale HTML references an old bundle hash, the old bundle is also
# in the disk cache, and the user ends up running pre-update JS forever
# without ever knowing why. ``no-cache`` (revalidate every time, but a
# 304 is cheap) is the correct setting for an SPA's entry HTML.
_HTML_CACHE_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}

# Ein Jahr, unveränderlich: der Name enthält den Hash, ein anderer Inhalt bekommt einen anderen Namen.
_ASSET_CACHE = "public, max-age=31536000, immutable"
# Bilder, Symbole und Schriften tragen keinen Hash im Namen. Ein Tag ist der Kompromiss: Nach einem Update
# sieht man neue Symbole spätestens am nächsten Tag, ohne dass jeder Aufruf eine Rückfrage kostet.
_MEDIA_CACHE = "public, max-age=86400"

# Kompression: Nur textartige Dateien, ab 1 KB und bis 8 MB. WASM-, Bild- und Videodateien sind schon gepackt
# oder lohnen die Arbeit nicht. Gepackt wird einmal je Dateistand und dann im Arbeitsspeicher gehalten — bei 25 MB
# Oberfläche bleibt das überschaubar, und der Cache wird bei Änderungen (mtime/Größe) von selbst ungültig.
_COMPRESSIBLE_TYPES = ("text/", "application/javascript", "application/json", "application/xml", "image/svg+xml")
_GZIP_MIN_BYTES = 1024
_GZIP_MAX_BYTES = 8 * 1024 * 1024
_GZIP_CACHE_LIMIT = 96 * 1024 * 1024
_gzip_cache: dict[tuple[str, int, int], bytes] = {}


def _wants_gzip(scope: dict[str, Any]) -> bool:
    for key, value in scope.get("headers", []):
        if key.lower() == b"accept-encoding":
            return b"gzip" in value.lower()
    return False


def _is_compressible(path: str, size: int) -> bool:
    if size < _GZIP_MIN_BYTES or size > _GZIP_MAX_BYTES:
        return False
    media_type = mimetypes.guess_type(path)[0] or ""
    return media_type.startswith(_COMPRESSIBLE_TYPES)


def _gzip_body(path: str, stat_result: os.stat_result) -> bytes:
    global _gzip_cache
    key = (path, stat_result.st_mtime_ns, stat_result.st_size)
    cached = _gzip_cache.get(key)
    if cached is not None:
        return cached
    with open(path, "rb") as handle:  # noqa: PTH123 - Pfad kommt von StaticFiles
        raw = handle.read()
    # mtime=0: gleicher Inhalt ergibt gleiche Bytes, unabhängig vom Dateidatum.
    body = gzip.compress(raw, compresslevel=6, mtime=0)
    if sum(len(value) for value in _gzip_cache.values()) + len(body) > _GZIP_CACHE_LIMIT:
        _gzip_cache = {}
    _gzip_cache[key] = body
    return body


class CachedStaticFiles(StaticFiles):
    """``StaticFiles`` mit Cache-Anweisung und gzip für textartige Dateien."""

    def __init__(self, *args: Any, cache_control: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        path = args[0] if args else kwargs.get("path")
        stat_result = args[1] if len(args) > 1 else kwargs.get("stat_result")
        scope = args[2] if len(args) > 2 else kwargs.get("scope", {})
        status_code = args[3] if len(args) > 3 else kwargs.get("status_code", 200)

        if (
            status_code == 200
            and path
            and stat_result
            and _wants_gzip(scope)
            and _is_compressible(path, stat_result.st_size)
        ):
            headers = {
                "Cache-Control": self.cache_control,
                "Content-Encoding": "gzip",
                "Vary": "Accept-Encoding",
            }
            media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            return Response(_gzip_body(path, stat_result), media_type=media_type, headers=headers)

        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = self.cache_control
        return response


def register_frontend(app: FastAPI) -> None:
    """Montiert ``static/`` und registriert die Routen der Oberfläche.

    Muss nach allen API-Routern aufgerufen werden: Der Catch-all ``/{full_path:path}`` fängt jeden Pfad ab, der
    vorher nicht belegt wurde.
    """
    static_dir = app_settings.static_dir

    # Serve static files (React build)
    if static_dir.exists() and any(static_dir.iterdir()):
        app.mount(
            "/assets",
            CachedStaticFiles(directory=static_dir / "assets", cache_control=_ASSET_CACHE),
            name="assets",
        )
        if (static_dir / "img").exists():
            app.mount(
                "/img",
                CachedStaticFiles(directory=static_dir / "img", cache_control=_MEDIA_CACHE),
                name="img",
            )
        if (static_dir / "icons").exists():
            app.mount(
                "/icons",
                CachedStaticFiles(directory=static_dir / "icons", cache_control=_MEDIA_CACHE),
                name="icons",
            )
        # Self-hosted Inter woff2 files (#1460). Without this mount /fonts/*.woff2
        # falls through to the SPA catch-all and returns index.html, which the
        # browser's font sanitizer rejects ("downloadable font: rejected by
        # sanitizer").
        if (static_dir / "fonts").exists():
            app.mount(
                "/fonts",
                CachedStaticFiles(directory=static_dir / "fonts", cache_control=_MEDIA_CACHE),
                name="fonts",
            )

    @app.get("/")
    async def serve_frontend():
        """Serve the React frontend."""
        # Bewusst über ``app_settings`` und nicht über den oben gemerkten Ordner: Tests und ein späterer
        # Wechsel des Datenordners ändern ``settings.static_dir`` zur Laufzeit.
        index_file = app_settings.static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file, headers=_HTML_CACHE_HEADERS)
        return {
            "message": "PrintLab API",
            "docs": "/docs",
            "frontend": "Build and place React app in /static directory",
        }

    # GET + HEAD on the three PWA bootstrap routes (#1460). Scanners and a plain
    # `curl -I` use HEAD; FastAPI's @app.get only registers GET, so HEAD answers
    # with 405 Method Not Allowed and shows up as a "broken manifest" red herring
    # in deployment debugging.
    @app.api_route("/manifest.json", methods=["GET", "HEAD"])
    async def serve_manifest():
        """Serve PWA manifest."""
        manifest_file = app_settings.static_dir / "manifest.json"
        if manifest_file.exists():
            return FileResponse(manifest_file, media_type="application/manifest+json")
        return {"error": "Manifest not found"}

    @app.api_route("/sw.js", methods=["GET", "HEAD"])
    async def serve_service_worker():
        """Serve service worker."""
        sw_file = app_settings.static_dir / "sw.js"
        if sw_file.exists():
            return FileResponse(
                sw_file,
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        return {"error": "Service worker not found"}

    @app.api_route("/sw-register.js", methods=["GET", "HEAD"])
    async def serve_sw_register():
        """Serve the service-worker registration bootstrap script.

        Served as a real JS file so the strict `script-src 'self'` CSP covers it
        without needing 'unsafe-inline' or per-build hashes on the inline tag.
        """
        reg_file = app_settings.static_dir / "sw-register.js"
        if reg_file.exists():
            return FileResponse(reg_file, media_type="application/javascript")
        return {"error": "sw-register.js not found"}

    # ── GCode viewer static files ────────────────────────────────────────────

    # Catch-all route for React Router (must be last)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React app for client-side routing."""
        # Don't intercept API routes - raise proper 404 so FastAPI can handle redirects
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        index_file = app_settings.static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file, headers=_HTML_CACHE_HEADERS)

        return {"error": "Frontend not built"}

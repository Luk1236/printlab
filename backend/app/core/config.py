import logging
import os
import re as _re
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


# Ältere Installationen setzen noch die früheren BAMBUDDY_*-Variablen. Sie gelten weiter und werden auf die
# neuen PRINTLAB_*-Namen abgebildet (eine bereits gesetzte PRINTLAB_*-Variable hat Vorrang).
def mirror_legacy_env(environ) -> None:
    for key, value in list(environ.items()):
        if key.startswith("BAMBUDDY_"):
            environ.setdefault("PRINTLAB_" + key[len("BAMBUDDY_") :], value)


mirror_legacy_env(os.environ)

# Eigene Version von PrintLab (Git-Tags vX.Y.Z). Einzige Versionsquelle: Oberfläche, Backups, Support-Infos
# und die Update-Prüfung gegen das eigene Repo benutzen sie. Bei jedem Release erhöhen (docs/VERSIONING.md).
PRINTLAB_VERSION = "1.17.1"
APP_VERSION = PRINTLAB_VERSION
# Fork: Updates kommen aus dem eigenen Repo, nie aus dem Upstream (PRINTLAB_GITHUB_REPO überschreibt).
GITHUB_REPO = os.environ.get("PRINTLAB_GITHUB_REPO", "Luk1236/printlab")
# Fork: kein Fehlerbericht-Relay beim Upstream; leer = Fehlerberichte aus, BUG_REPORT_RELAY_URL setzt eines.
BUG_REPORT_RELAY_URL = os.environ.get("BUG_REPORT_RELAY_URL", "")

# App directory - where the application is installed (for static files)
_app_dir = Path(__file__).resolve().parent.parent.parent.parent

# Data directory - for persistent data (database, archives)
# Use DATA_DIR env var if set (Docker), otherwise use project root (local dev)
_data_dir_env = os.environ.get("DATA_DIR")
_data_dir = Path(_data_dir_env) if _data_dir_env else _app_dir

# Plate calibration directory - special handling to maintain backwards compatibility
# Docker: DATA_DIR/plate_calibration (e.g., /data/plate_calibration)
# Local dev: project_root/data/plate_calibration (original location)
_plate_cal_dir = Path(_data_dir_env) / "plate_calibration" if _data_dir_env else _app_dir / "data" / "plate_calibration"

# Log directory - use LOG_DIR env var if set, otherwise use app_dir/logs
_log_dir_env = os.environ.get("LOG_DIR")
_log_dir = Path(_log_dir_env) if _log_dir_env else _app_dir / "logs"


def _migrate_database() -> Path:
    """Datenbank auf den aktuellen Dateinamen ``printlab.db`` umziehen (aus ``bambuddy.db`` / ``bambutrack.db``)."""
    new_db = _data_dir / "printlab.db"
    if new_db.exists():
        return new_db
    for old_name in ("bambuddy.db", "bambutrack.db"):
        old_db = _data_dir / old_name
        if not old_db.exists():
            continue
        try:
            old_db.rename(new_db)
            for suffix in ("-wal", "-shm"):  # SQLite-Begleitdateien gehören dazu
                sidecar = _data_dir / (old_name + suffix)
                if sidecar.exists():
                    sidecar.rename(_data_dir / ("printlab.db" + suffix))
            logging.info("Migrated database: %s -> %s", old_db, new_db)
            return new_db
        except Exception as e:
            logging.warning("Could not migrate database: %s. Using old location.", e)
            return old_db
    return new_db


# External DATABASE_URL takes priority (PostgreSQL support)
_external_db_url = os.environ.get("DATABASE_URL")

# Determine database path (handles migration) — only used for SQLite
_db_path = _migrate_database() if not _external_db_url else None


class Settings(BaseSettings):
    app_name: str = "PrintLab"
    debug: bool = False  # Default to production mode

    # Paths
    base_dir: Path = _data_dir  # For backwards compatibility
    # `app_dir` is where the source code is checked out — distinct from `base_dir`
    # on native installs where DATA_DIR is set to a sibling like INSTALL_PATH/data.
    # Use this when you need the working tree (requirements.txt, frontend/, etc.)
    # rather than the data dir. On Docker / local dev where DATA_DIR is unset,
    # app_dir == base_dir.
    app_dir: Path = _app_dir
    archive_dir: Path = _data_dir / "archive"
    plate_calibration_dir: Path = _plate_cal_dir  # Plate detection references
    static_dir: Path = _app_dir / "static"  # Static files are part of app, not data
    log_dir: Path = _log_dir
    database_url: str = _external_db_url or f"sqlite+aiosqlite:///{_db_path}"

    # Database connection pool sizing. ``None`` = use the built-in, dialect-aware
    # default (PostgreSQL: pool_size 20 + max_overflow 60; SQLite: 20 + 200).
    # Large PostgreSQL printer farms can raise these via the DB_POOL_SIZE /
    # DB_MAX_OVERFLOW / DB_POOL_TIMEOUT / DB_POOL_RECYCLE env vars (issue #2572).
    # Make sure PostgreSQL ``max_connections`` comfortably exceeds
    # (pool_size + max_overflow) x number of app worker processes.
    db_pool_size: int | None = Field(default=None, gt=0)
    db_max_overflow: int | None = Field(default=None, ge=0)
    db_pool_timeout: int | None = Field(default=None, gt=0)
    db_pool_recycle: int | None = Field(default=None, gt=0)
    # LIFO checkout (PostgreSQL default on): reuse the most-recently-returned
    # connection so a bursty farm keeps a small hot set busy and lets the excess
    # overflow connections age out via pool_recycle instead of churning the whole
    # pool. Override with DB_POOL_USE_LIFO. No effect on SQLite. (#2572)
    db_pool_use_lifo: bool | None = Field(default=None)

    # Logging
    log_level: str = "INFO"  # Override with LOG_LEVEL env var or DEBUG=true
    log_to_file: bool = True  # Set to false to disable file logging
    # Rotation for printlab.log. Read by main.py (which owns the handler) and by
    # the support bundle (which harvests the backups as well as the live file);
    # they must agree on the backup count or the bundle silently skips history.
    # Bounded: RotatingFileHandler treats maxBytes=0 as "never rotate", so a
    # zero/negative override would grow the log without limit.
    log_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    log_backup_count: int = Field(default=3, ge=0)

    # API
    api_prefix: str = "/api/v1"

    # Slicer API sidecars. Defaults match the docker-compose.yml ports in the
    # orca-slicer-api fork (https://github.com/maziggy/orca-slicer-api):
    #   OrcaSlicer  → port 3003 (default profile)
    #   BambuStudio → port 3001 (built locally via Dockerfile.bambu-studio)
    # The slice route picks which one based on the user's preferred_slicer
    # setting.
    slicer_api_url: str = "http://localhost:3003"
    bambu_studio_api_url: str = "http://localhost:3001"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Don't reject unknown env vars — MFA_ENCRYPTION_KEY (#1219) and other
        # operational env vars are read directly by their owning modules and
        # never declared as Settings fields.
        extra = "ignore"


settings = Settings()

# S6: Warn on unknown MFA_*/PRINTLAB_* env vars so typos like MFA_ENCYPTION_KEY
# are not silently swallowed by ``extra = "ignore"``. The original Pydantic
# behaviour rejected them outright and broke startup (#1219); we now accept
# them but log every unrecognised one at INFO so operators can spot mistakes.
_INTENTIONAL_UNSETTINGS = {
    "MFA_ENCRYPTION_KEY",  # encryption.py reads this directly
    "DATA_DIR",  # paths.py / config.py
    "DATABASE_URL",  # config.py (above)
    "LOG_DIR",  # config.py (above)
    "LOG_LEVEL",  # main.py logging setup
    "BUG_REPORT_RELAY_URL",  # config.py (above)
    "ANNOUNCEMENTS_FEED_URL",  # services/announcements.py
    "PRINTLAB_GITHUB_REPO",  # config.py (above)
    # #1589 — api/routes/auth.py reads this on the login path. Unregistered it
    # logged "possible typo" at every boot, telling an operator who is locked
    # out and following the documented recovery that the variable is not real.
    "PRINTLAB_LOCAL_LOGIN",
    # #2593 — core/oidc_env.py reads these directly; they are not Settings
    # fields because they map to an OIDCProvider row, not to app config.
    "PRINTLAB_OIDC_NAME",
    "PRINTLAB_OIDC_ISSUER_URL",
    "PRINTLAB_OIDC_CLIENT_ID",
    "PRINTLAB_OIDC_CLIENT_SECRET",
    "PRINTLAB_OIDC_SCOPES",
    "PRINTLAB_OIDC_ENABLED",
    "PRINTLAB_OIDC_AUTO_CREATE_USERS",
    "PRINTLAB_OIDC_AUTO_LINK_EXISTING",
    "PRINTLAB_OIDC_EMAIL_CLAIM",
    "PRINTLAB_OIDC_REQUIRE_EMAIL_VERIFIED",
    "PRINTLAB_OIDC_GROUP_CLAIM",
    "PRINTLAB_OIDC_GROUP_MAPPING",
    "PRINTLAB_OIDC_ICON_URL",
    "PRINTLAB_OIDC_AUTOLOGIN",
    "PRINTLAB_OIDC_DEFAULT_GROUP",
}

_known_settings_fields = {f.upper() for f in settings.model_fields}

for _env_key in os.environ:
    if _re.match(r"^(MFA_|PRINTLAB_)", _env_key, _re.IGNORECASE):
        _norm = _env_key.upper()
        if _norm not in _known_settings_fields and _norm not in _INTENTIONAL_UNSETTINGS:
            logging.info(
                "Unknown env var %r — not a declared Settings field. Possible typo? Recognised operational vars: %s",
                _env_key,
                sorted(_INTENTIONAL_UNSETTINGS),
            )

# Ensure directories exist
settings.archive_dir.mkdir(parents=True, exist_ok=True)
settings.plate_calibration_dir.mkdir(parents=True, exist_ok=True)
settings.static_dir.mkdir(exist_ok=True)
if settings.log_to_file:
    settings.log_dir.mkdir(exist_ok=True)

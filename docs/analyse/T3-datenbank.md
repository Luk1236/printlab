# T3 Datenbank: Engine, Sitzungen, Migrationen, Indizes

Stand: 2026-11-10, Branch `bambu-monitor-port`. Vorgänger: [T2](T2-drucker-kommunikation.md). Übersicht: [README.md](README.md).

## 0. Abdeckung (ehrlich)

| Datei | Zeilen | Funktionen | Stufe | Was gelesen wurde |
|---|---:|---:|---|---|
| `core/database.py` Z. 1 bis 624 (Engine, Pool, `get_db`, `run_with_retry`, `init_db`, `check_pool_fits_server`) | 624 | 12 | **A** | vollständig |
| `core/database.py` Z. 624 bis 710 (`_safe_execute`, `_is_already_applied`) | 86 | 4 | **A** | vollständig |
| `core/database.py` `run_migrations` (Z. 1.813 bis 5.218) | 3.406 | 1 | **B+** | Anfang (130 Zeilen), `writable_schema`-Stellen, alle 29 `UPDATE`-Zeilen, Statistik per AST; **nicht** alle 453 Anweisungen einzeln |
| `core/database.py` übrige 34 Funktionen (Hilfs-Migrationen, Seeds) | ca. 2.500 | 34 | **B** | nur Inventar und Kennzahlen |
| `models/` (65 Dateien) | 4.980 | 36 | **B** | Schema der frischen Datenbank (94 Tabellen, 115 Fremdschlüssel) maschinell ausgewertet, nicht Datei für Datei gelesen |

Die zwei neuen Messwerte (Startzeit, Indexwirkung) und der Fehler T3-01 sind **nachgestellt** (Skripte im Scratchpad, eigene Test-Datenbank,
die echte `printlab.db` blieb unberührt).

## 1. High-Level-Überblick

- **Zweck:** Ein asynchroner SQLAlchemy-Engine (SQLite mit WAL oder PostgreSQL), Sitzungs-Fabrik, FastAPI-Abhängigkeit `get_db`,
  Start-Initialisierung `init_db` (Tabellen anlegen, Migrationen, Seeds).
- **Migrationsmodell:** **Kein** Versionszähler und kein Alembic. `Base.metadata.create_all` legt fehlende Tabellen an, danach läuft
  `run_migrations` bei **jedem** Start komplett durch. Jede Änderung ist ein idempotenter `ALTER TABLE … ADD COLUMN` (Fehler „existiert schon“
  wird verschluckt) oder eine geschützte Datenmigration.
- **Pool:** SQLite 20 plus 200 Überlauf, PostgreSQL 20 plus 60 mit `pool_pre_ping`; `PRAGMA journal_mode=WAL`, `busy_timeout=15000`, `synchronous=NORMAL`.

## 2. Funktionsaufbau (Kern)

| Funktion | Zweck | Rückgabe / Nebenwirkung |
|---|---|---|
| `_set_sqlite_pragmas(dbapi_conn, record)` | je neue Verbindung WAL, 15 s Wartezeit, `synchronous=NORMAL` | schreibt Pragmas |
| `_resolve_pool_kwargs()` / `_resolve_connect_args()` / `_create_engine()` | Pool- und Verbindungsparameter aus Einstellungen; entfernt Zeitzonen aus Parametern (asyncpg) | `AsyncEngine`; schreibt `_pool_config` |
| `get_pool_status()` | Pool-Zustand für die Systemansicht | `dict` |
| `run_with_retry(fn, max_attempts=3)` | SQLite „database is locked“ bis 3-mal mit 0,5/1,0 s; Postgres einmal | Ergebnis von `fn`; **eine frische Sitzung je Versuch** |
| `close_all_connections()` / `reinitialize_database()` | Sicherung/Wiederherstellung: Engine entsorgen bzw. **neuen** Engine und neue Fabrik zuweisen | schreibt Modul-Globals `engine`, `async_session` |
| `get_db()` | Sitzung je Anfrage, Commit am Ende; bei jedem Abbruch (auch `CancelledError`) Rückrollen unter `asyncio.shield` | `AsyncSession` (Generator) |
| `init_db()` | Modelle importieren, `create_all`, `run_migrations(conn)`, danach getrennt: Geheimnisse neu verschlüsseln, Vorlagen/Gruppen/Katalog säen, Pool-Prüfung | schreibt Schema und Daten |
| `check_pool_fits_server()` | warnt, wenn der Pool mehr Verbindungen erlaubt als PostgreSQL | nur Postgres; Fehler werden bewusst verschluckt |
| `_safe_execute(conn, sql)` | DDL im Sicherungspunkt; „schon angewendet“ (SQLSTATE oder Text) wird ignoriert, alles andere geloggt und **erneut ausgelöst** | `None` oder Ausnahme |
| `_is_already_applied(exc, sql)` | trennt Wiederholung von echtem Fehler; bei `RENAME COLUMN` auch „no such column“ | `bool` |
| `run_migrations(conn)` | 3.406 Zeilen, 453 Anweisungen, siehe 3 | |

**Datenfluss beim Start:** `init_db` öffnet **eine** Transaktion (`engine.begin()`), `create_all`, dann `run_migrations`. Fehlschlag in einer
Migration bricht den Start ab (gewollt, Docstring von `_safe_execute`). Seeds laufen in eigenen Sitzungen, damit der WAL-Schreiber nicht blockiert (Kommentar Z. 356 bis 360).

## 3. `run_migrations` in Zahlen (AST und Textmessung)

| Kennzahl | Wert |
|---|---:|
| Zeilen / Anweisungen auf oberster Ebene | 3.406 / 453 |
| Komplexität | 299 |
| `_safe_execute`-Aufrufe | 409 |
| davon `ALTER TABLE … ADD COLUMN` | 377 |
| `CREATE INDEX` | 29 |
| `UPDATE … SET` / `DELETE FROM` / `DROP` | 29 / 6 / 11 |
| `begin_nested()` (Sicherungspunkte) | 56 |
| Abfragen `is_sqlite()` | 67 |
| Aufrufe ausgelagerter `_migrate_*` | 21 |
| Kommentare „# Migration:“ | 225 |
| `except … : pass` | **39** (38-mal `(OperationalError, ProgrammingError)`) |
| Versionstabelle | **keine** |

**Gemessene Startkosten** (leere Test-Datenbank auf diesem PC, SQLite): erster Start 3,42 s, jeder weitere Start 1,58 s, davon
`run_migrations` allein **1,46 s**. Auf dem Raspberry Pi ist das langsamer (nicht gemessen). Jeder Start führt alle 409 `_safe_execute`-Anweisungen
aus, jede in einem eigenen Sicherungspunkt, und fast alle scheitern absichtlich mit „duplicate column“.

## 4. Befunde

Schweregrad: **H** hoch, **M** mittel, **N** niedrig, **I** Hinweis. Beleg: **nachgestellt**, **gemessen**, **gelesen**.

| Nr. | Grad | Befund | Beleg |
|---|:---:|---|---|
| T3-01 | **H** (behoben, ungepusht) | **Eine Einstellung wird bei jedem Neustart zurückgesetzt.** In `run_migrations` steht ohne Bedingung `UPDATE filament_sku_settings SET lead_time_days = 0 WHERE lead_time_days = 7` (Z. 4.216 für SQLite, Z. 4.371 für PostgreSQL). Wer die Lieferzeit für Nachbestellungen bewusst auf 7 Tage setzt, bekommt nach dem nächsten Start 0. Das Modell hat `default=0` (`models/filament_sku_settings.py:26`), die Migration ist ein Überbleibsel aus der Zeit, als der Standard 7 war. | **nachgestellt**: Zeile mit 7 eingefügt, `init_db()` ein zweites Mal ausgeführt, danach 0 |
| T3-02 | M | **`PRAGMA foreign_keys` wird nie eingeschaltet.** `_set_sqlite_pragmas` setzt nur WAL, `busy_timeout`, `synchronous` (Z. 15 bis 23). SQLite erzwingt Fremdschlüssel nur auf ausdrücklichen Befehl. Alle `ON DELETE CASCADE` / `SET NULL` aus Modellen und Migrationen (z. B. Z. 1.842 `ON DELETE SET NULL`) wirken unter SQLite **nicht**; verwaiste Zeilen sind möglich. Der Code weiß es teilweise (`models/oidc_provider.py:103`: „SQLite ignores it (no PRAGMA foreign_keys=ON)“; `core/auth.py:1280` verlässt sich auf `CASCADE`, behandelt aber den Ausfall). Unter PostgreSQL gelten die Regeln, das Verhalten beider Datenbanken weicht also ab. | gelesen |
| T3-03 | M | **70 von 115 Fremdschlüsseln haben keinen Index** (frische Datenbank, erster Spaltenplatz geprüft). Darunter die großen Tabellen: `print_archives` (`printer_id`, `project_id`, `created_by_id`, `cost_center_id`, `library_file_id`), `print_queue` (7 Fremdschlüssel), `spool_usage_history` (3), `library_files` (3), `notification_logs`. 25 Stellen im Code filtern auf `PrintArchive.printer_id ==`. Ein Vergleich mit 50.000 Archiven (reines `sqlite3`, Messung, keine Anwendungsabfrage): 2,68 ms ohne Index, 0,31 ms mit Index, also **8,7-fach**. Außerdem verlangsamt der fehlende Index jedes Löschen eines Elternobjekts (Drucker, Projekt, Benutzer), sobald Fremdschlüssel aktiv sind (T3-02). Bei kleinen Farmen kaum spürbar, bei großem Archiv schon. | gemessen |
| T3-04 | M | **Kein Migrationszähler: jeder Start wiederholt 409 DDL-Anweisungen** (1,46 s auf dem PC). Ein Absturz in der Mitte hinterlässt keinen Hinweis, welche Schritte liefen; neue Änderungen werden einfach angehängt (225 Kommentare „# Migration:“), das Nacharbeiten ist nur über Ticketnummern im Kommentar nachvollziehbar. | gemessen, gelesen |
| T3-05 | M | **38 handgeschriebene `try/except (OperationalError, ProgrammingError): pass` schlucken jeden Fehler**, nicht nur „existiert schon“. `_safe_execute` unterscheidet das sauber (`_is_already_applied`) und wirft alles andere weiter; die handgeschriebene Form (z. B. Z. 3.044 bis 3.050: `ALTER TABLE slot_preset_mappings ADD COLUMN …`, `pass  # Already applied`) tut es nicht. Eine gesperrte Datenbank, ein Tippfehler im SQL oder ein fehlender Tabellenname bleiben dann unbemerkt, die Spalte fehlt später beim ersten Zugriff. | AST, gelesen |
| T3-06 | N | **Mehrere Starts oder Prozesse gleichzeitig** (z. B. Windows-Dienst und Aufgabe) laufen beide durch `run_migrations`; ohne Sperre kollidieren sie auf SQLite mit `busy_timeout`, auf PostgreSQL mit zwei gleichzeitigen `ALTER TABLE`. Gegenmittel: Advisory-Lock bzw. Datei-Sperre. Praktisch bei einem einzigen Prozess nicht auffällig. | gelesen (vermutet) |
| T3-07 | N | **`reinitialize_database()` erzeugt einen zweiten Engine mit eigenem Pool**, der alte bleibt in den bereits importierten Referenzen (`async_session` wird in 42 Modulen per Name importiert; `check_pool_fits_server` erklärt das Problem selbst, Z. 392 bis 398). Nach einer Wiederherstellung leben zwei Pools nebeneinander; bei PostgreSQL verdoppelt das die mögliche Verbindungszahl. Auf SQLite folgenlos, solange die Datei dieselbe ist. | gelesen (vermutet) |
| T3-08 | N | **`get_db` committet am Ende jeder Anfrage**, auch bei reinen Lesezugriffen (Z. 263 bis 264). Auf SQLite ist das billig, aber es beendet die Lese-Transaktion erst am Ende der Antwort; in Streaming-Routen bleibt die Verbindung so lange belegt. Das Muster („Sitzung vor der Ein-/Ausgabe freigeben“) wird in `on_print_start` per Hand befolgt (T2). | gelesen |
| T3-09 | I | **`run_with_retry` lädt Meldungstexte**: `"database is locked" not in str(exc)` hängt an der englischen SQLite-Meldung (Z. 224). Stabil, aber ein Treiberwechsel bricht es lautlos; besser `exc.orig.sqlite_errorcode`. | gelesen |
| T3-10 | I | **`writable_schema`-Eingriffe** (Z. 3.024, 3.687) ändern `sqlite_master` direkt, um `NOT NULL` zu entfernen, mit Hochzählen von `schema_version`. Das ist das von der SQLite-Dokumentation beschriebene Verfahren und hier abgesichert (Prüfung auf den exakten Text, Fehlerprotokoll), bleibt aber eine heikle Stelle: bei einem Absturz zwischen den Schritten kann das Schema beschädigt sein. Vor solchen Schritten sollte eine Sicherungskopie liegen. | gelesen |

### 4.1 Geprüft, kein Befund

- **Rückrollen bei Abbruch:** `get_db` fängt `BaseException`, rollt unter `asyncio.shield` zurück und schließt die Sitzung ebenso; die geschachtelten `pass` sind hier gewollt (Kommentare Z. 266 bis 283).
- **Gesperrte Datenbank:** WAL plus 15-s-Wartezeit plus `run_with_retry` mit frischer Sitzung je Versuch.
- **Datenmigrationen mit Schutz:** `can_manage_library`, `can_manage_inventory` und folgende werden nur beim Anlegen der Spalte befüllt (`_api_keys_column_exists`, Z. 3.966 bis 3.980), User-Änderungen bleiben erhalten; `password_changed_at` nur für `NULL` (Z. 3.904); das Datei-Typ-Update ist idempotent (Z. 3.466 bis 3.474).
- **SQL-Einfügung:** die `f"… {_col} …"`-Stellen (Z. 2.486, 2.489) nehmen feste Spaltennamen aus einer Liste, mit `# nosec`-Hinweis.
- **Pool-Warnung:** nicht blockierend, Fehler beim Abfragen verhindern den Start nicht.

## 5. Refactoring-Vorschläge (nicht angewendet; Syntax geprüft)

### 5.1 Sofortmaßnahme für T3-01

Die Zeile hat seit dem Wechsel des Standards keinen Zweck mehr. Löschen (beide Stellen) **oder** nur in der Migration ausführen, die die Tabelle erstmals anlegt:

```python
    # Einmalig: Zeilen, die noch den alten Standardwert 7 tragen, auf den neuen Standard 0 setzen.
    # Nur wenn die Tabelle in diesem Start neu entstand oder die Spalte safety_margin_value fehlt (alter Stand).
    legacy_table = not await _table_has_column(conn, "filament_sku_settings", "safety_margin_value")
    if legacy_table:
        async with conn.begin_nested():
            await conn.execute(text("UPDATE filament_sku_settings SET lead_time_days = 0 WHERE lead_time_days = 7"))
```

Dazu ein Test: Zeile mit `lead_time_days=7` einfügen, `run_migrations` zweimal ausführen, Wert muss 7 bleiben (das Skript aus der Analyse ist dafür die Vorlage).
Betroffenen Nutzern lässt sich der Wert nicht automatisch zurückholen; der Hinweis im Änderungsprotokoll genügt.

### 5.2 Migrationszähler (löst T3-04, entschärft T3-05)

```python
from dataclasses import dataclass
from typing import Awaitable, Callable

Migration = Callable[[AsyncConnection], Awaitable[None]]


@dataclass(frozen=True)
class Step:
    id: str            # z. B. "0001_baseline", "0002_add_plate_id", aufsteigend und unveränderlich
    run: Migration


async def _ensure_version_table(conn) -> None:
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations (id VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
    ))


async def apply_pending(conn, steps: list[Step]) -> list[str]:
    """Führt nur noch nicht verbuchte Schritte aus, jeden in einem Sicherungspunkt, und verbucht sie danach."""
    await _ensure_version_table(conn)
    done = {row[0] for row in await conn.execute(text("SELECT id FROM schema_migrations"))}
    applied = []
    for step in steps:
        if step.id in done:
            continue
        async with conn.begin_nested():
            await step.run(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (id, applied_at) VALUES (:id, :now)"),
                {"id": step.id, "now": datetime.now(timezone.utc)},
            )
        applied.append(step.id)
    return applied
```

Einführung ohne Risiko: Der heutige Block `run_migrations` wird **unverändert** zum Schritt `0001_baseline` (läuft auf jeder bestehenden Installation
ein letztes Mal, ist idempotent) und danach nie wieder. Neue Änderungen kommen als weitere `Step`s. Erwarteter Effekt: Start ohne 409 Anweisungen
(statt 1,46 s nur noch das Lesen einer Tabelle), jeder Schritt ist einzeln testbar, und ein Schritt, der scheitert, bricht laut ab statt still zu scheitern.
Alembic wäre die Standardlösung; bei dieser Menge an SQLite-Sonderfällen (`writable_schema`, Tabellenumbau) ist ein eigener schlanker Zähler leichter zu übernehmen.

### 5.3 Einheitliche „schon angewendet“-Behandlung (löst T3-05)

```python
async def _add_column(conn, table: str, ddl: str) -> None:
    """ALTER TABLE … ADD COLUMN, nur 'Spalte existiert schon' wird ignoriert; alles andere bricht ab."""
    await _safe_execute(conn, f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

Die 38 handgeschriebenen `try/except … pass` werden mechanisch durch `_safe_execute` bzw. `_add_column` ersetzt. Ein Test (`ast`) verhindert Rückfälle:

```python
def test_no_bare_pass_in_migrations():
    tree = ast.parse(Path("backend/app/core/database.py").read_text(encoding="utf8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_migrations")
    swallowed = [h.lineno for h in ast.walk(fn)
                 if isinstance(h, ast.ExceptHandler) and len(h.body) == 1 and isinstance(h.body[0], ast.Pass)]
    assert swallowed == [], f"stilles except/pass in run_migrations: {swallowed}"
```

(Der Test würde heute 39 Stellen melden, so viele zählt die AST-Messung; ausgeführt habe ich ihn nicht. Er ist die Abnahme für die Umstellung.)

### 5.4 Indizes auf Fremdschlüssel (löst T3-03)

Zuerst die Spalten, die nachweislich gefiltert werden (aus der Liste in T3-03), als eigener Schritt:

```python
HOT_FK_INDEXES = [
    ("print_archives", "printer_id"), ("print_archives", "project_id"), ("print_archives", "created_by_id"),
    ("print_archives", "cost_center_id"), ("print_archives", "library_file_id"),
    ("print_queue", "printer_id"), ("print_queue", "archive_id"), ("print_queue", "library_file_id"),
    ("print_queue", "batch_id"), ("spool_usage_history", "spool_id"), ("spool_usage_history", "archive_id"),
    ("spool_assignment", "spool_id"), ("library_files", "folder_id"), ("notification_logs", "provider_id"),
]


async def add_fk_indexes(conn) -> None:
    for table, col in HOT_FK_INDEXES:
        await _safe_execute(conn, f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
```

In den Modellen zugleich `index=True` an die Spalte setzen, damit frische und aktualisierte Installationen gleich aussehen (sonst fehlt der Index
auf neuen Datenbanken, denn `create_all` kennt ihn nicht). Vor der Umsetzung auf einer Kopie der echten Datenbank `EXPLAIN QUERY PLAN` für die
häufigsten Abfragen vergleichen; die übrigen 56 Fremdschlüssel nur bei nachgewiesenem Bedarf.

### 5.5 Fremdschlüssel erzwingen (löst T3-02), nur stufenweise

```python
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA busy_timeout = 15000")
    cursor.execute("PRAGMA synchronous = NORMAL")
    if settings.sqlite_foreign_keys:          # neue Einstellung, zunächst False
        cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()
```

Vorgehen: (1) auf einer Kopie der Produktivdatenbank `PRAGMA foreign_key_check` ausführen und die Verwaisten zählen; (2) Löschpfade prüfen, die auf
`CASCADE`/`SET NULL` gebaut sind **und** solche, die Kinder von Hand löschen (Reihenfolge); (3) erst nach grünem Testlauf den Standard auf `True`
stellen. Ohne diese Schritte kann das Einschalten bestehende Löschvorgänge mit `IntegrityError` abbrechen.

### 5.6 Kleinere Punkte

- **T3-06:** Beim Start `BEGIN IMMEDIATE` (SQLite) bzw. `pg_advisory_lock(<Konstante>)` (PostgreSQL) um `apply_pending` legen.
- **T3-09:** `isinstance(exc.orig, sqlite3.OperationalError) and exc.orig.sqlite_errorcode in (5, 6)` (BUSY, LOCKED) statt Textvergleich.
- **T3-10:** vor `writable_schema`-Schritten `VACUUM INTO 'backup.db'` bzw. Dateikopie.
- **`seed_default_groups`** (323 Zeilen, Komplexität 65): als Tabelle (Name, Rechte) statt Verzweigungen darstellen; gehört in T11.

## 6. Offene Punkte

1. Die übrigen 424 von 453 Anweisungen in `run_migrations` einzeln lesen, vor allem die 29 `UPDATE`, 6 `DELETE`, 11 `DROP` auf weitere unbedingte Datenänderungen wie T3-01 (alle 29 `UPDATE`-Zeilen sind aufgelistet und gesichtet, bei drei weiteren Zeilen bleibt unklar, ob eine Bedingung später greift: Z. 2.486, 2.517, 4.485).
2. Postgres-Pfad praktisch testen (nicht gemessen; Postgres ist laut Konfiguration nur optional).
3. Auf dem Raspberry Pi die Startzeit von `run_migrations` messen (PC: 1,46 s).
4. Alle Löschpfade auf Abhängigkeit von `ON DELETE` prüfen, bevor T3-02 umgesetzt wird.
5. `models/`: Datei für Datei lesen (Default-Werte, Zeitzonen, `nullable`-Abweichungen zur Migration), das Schema selbst wurde nur maschinell ausgewertet.

**T3-01 ist behoben** (Hilfsfunktion `_reset_legacy_sku_lead_time` in `core/database.py`, Test `backend/tests/unit/test_sku_lead_time_migration.py`; lokal, noch nicht gepusht). Die Vorschläge 5.2 bis 5.6 sind weiterhin nicht angewendet; über sie entscheidet der Auftraggeber.

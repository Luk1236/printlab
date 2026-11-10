# T2 Drucker-Kommunikation: MQTT, Statusfluss, Druckstart/-ende, FTP

Stand: 2026-11-10, Branch `bambu-monitor-port`. Vorgänger: [T1 Sicherheit](T1-sicherheit.md). Übersicht: [README.md](README.md).

## 0. Abdeckung (ehrlich)

Diese Tranche ist **überwiegend Stufe B**. Die vier Kernfunktionen haben jeweils über 1.400 Zeilen; eine Zeile-für-Zeile-Beschreibung
würde allein für sie über 5.000 Zeilen Code erfordern. Gelesen wurde dort, wo die Risiken liegen; der Rest ist über Inventar,
Gliederung und AST-Messung erfasst.

| Datei | Zeilen | Funktionen | Stufe | Was gelesen wurde |
|---|---:|---:|---|---|
| `services/bambu_mqtt.py` | 7.659 | 114 | B+ | `connect`, `_on_message`, `_handle_request_message`, Stale-/Reconnect-Pfad (Z. 1.000 bis 1.150), Anfang `_process_message`, `_update_state` Z. 3.475 bis 3.555 und 4.818 bis 5.037; Gliederung der ganzen Funktion per AST |
| `services/mqtt_status_flow.py` | 1.475 | 13 | B | nur Inventar und Kennzahlen |
| `services/mqtt_print_complete.py` | 1.622 | 13 | B | Gliederung per AST (Stufenfolge, innere Funktionen) |
| `services/print_start_flow.py` | 1.996 | 15 | B | Gliederung, Z. 649 bis 700 (Platten-Prüfung), Z. 1.316 bis 1.460 (FTP-Download), Pfad-Marker |
| `services/bambu_ftp.py` | 2.558 | 68 | B | TLS-Aufbau (Z. 426 bis 475), Zeitlimit-Logik als Überblick, Kennzahlen |
| `services/print_storage.py` | Auszug | 2 | A | `probe_filename_from_url`, `ftp_probe_paths` |

**Nicht** gelesen, daher nicht beurteilt: Inneres von `_handle_ams_data` (718 Zeilen), `_parse_xcam_data`, `start_print` (376 Zeilen),
`on_print_complete` und `on_print_start` Zeile für Zeile, `on_ams_change`, `on_printer_status_change`, FTP-Upload und -Download-Schleifen.
Das ist der Auftrag für T2b (Abschnitt 6).

## 1. High-Level-Überblick

- **Zweck:** Hält je Drucker eine MQTT-Verbindung (Port 8883, Benutzer `bblp`, Access Code als Passwort), wertet die Statusmeldungen
  aus, erkennt Druckstart und -ende, startet Drucke, und lädt 3MF-Dateien und Zeitraffer über FTPS (Port 990).
- **Muster:** `BambuMQTTClient` (paho im eigenen Netzwerk-Thread) schreibt in ein veränderliches `PrinterState`-Objekt und ruft
  Rückruffunktionen (`on_state_change`, `on_print_start`, `on_print_complete`, …). `PrinterManager` übersetzt sie über
  `asyncio.run_coroutine_threadsafe` in Aufgaben der Ereignisschleife (`printer_manager.py:706`, mit Fehlerabfang im Rückruf).
  `mqtt_status_flow`, `print_start_flow`, `mqtt_print_complete` sind die ausgelagerten Ereignis-Handler; sie erreichen die Fassade
  `backend.app.main` über `_rt()`.
- **Abhängigkeiten:** paho-mqtt 2.x (`CallbackAPIVersion.VERSION2`, MQTT 3.1.1), `ftplib.FTP_TLS` (Unterklasse `ImplicitFTP_TLS`), asyncio.

## 2. Datenfluss

```
Drucker ──MQTT 8883──► paho-Thread: _on_message ──► _process_message ──► _update_state(print_data)
                                                                              │ schreibt PrinterState (ohne Lock)
                                                                              ├─► on_state_change ─► WebSocket-Broadcast
                                                                              ├─► on_print_start  ─► print_start_flow.on_print_start (async, über run_coroutine_threadsafe)
                                                                              └─► on_print_complete ─► mqtt_print_complete.on_print_complete
on_print_start: Archiv anlegen, 3MF per FTPS holen (mehrere Pfade, Wiederholungen, Cool-off), Benachrichtigung
on_print_complete: Archiv abschließen, Energie, Verbrauch, Foto, Zeitraffer, Wartung, Warteschlange, Benachrichtigungen (8 Hintergrundaufgaben)
```

Staleness: `check_staleness()` (aus API-Abfragen) schließt bei 60 s Stille die Verbindung (Abkühlzeit 30 s). Aus dem Ereignisschleifen-Kontext
wird der Client **neu gebaut** (frische `client_id`, damit paho keine alten QoS-1-Befehle wiederholt, #1136); aus dem paho-Thread heraus
wird nur der Socket geschlossen (`_reset_client_for_reconnect`, Z. 1.089).

## 3. Funktionsprofil (gemessen)

| Datei | Funktionen | breite `except` | stille `pass` | Komplexität über 15 | ohne Docstring |
|---|---:|---:|---:|---:|---:|
| `bambu_mqtt.py` | 114 | 10 | 9 | 9 | 9 |
| `mqtt_status_flow.py` | 13 | 19 | 2 | 3 | 0 |
| `mqtt_print_complete.py` | 13 | 52 | 8 | 4 | 4 |
| `print_start_flow.py` | 15 | 29 | 6 | 4 | 2 |
| `bambu_ftp.py` | 68 | 8 | 15 | 8 | 20 |
| **Summe** | **223** | **118** | **40** | **28** | **35** |

Die größten Funktionen:

| Funktion | Zeilen | Komplexität | Hinweis |
|---|---:|---:|---|
| `BambuMQTTClient._update_state` | 1.569 | **391** | 93 Anweisungen auf oberster Ebene (68 `if`), Verschachtelung bis Tiefe 10 |
| `on_print_complete` | 1.568 | 322 | 86 Anweisungen, 8 innere Funktionen, 26-mal `async_session()` |
| `on_print_start` | 1.440 | 251 | **ein** `async with async_session()` über 1.348 Zeilen |
| `BambuMQTTClient._handle_ams_data` | 718 | 143 | |
| `on_ams_change` | 592 | 117 | |
| `on_printer_status_change` | 468 | 102 | |
| `BambuMQTTClient.start_print` | 376 | 42 | |
| `BambuMQTTClient._process_message` | 323 | 74 | |
| `download_file_async` | 217 | 27 | |

## 4. Befunde

Schweregrad: **M** mittel, **N** niedrig, **I** Hinweis. Beleg: **gelesen**, **AST** (maschinell gemessen) oder **vermutet** (logisch begründet, nicht nachgestellt).

| Nr. | Grad | Befund | Beleg |
|---|:---:|---|---|
| T2-01 | M | **17 ungeschützte Zahlenumwandlungen in `_update_state`.** `float(data["mc_percent"])` (Z. 3.505), `int(data["mc_remaining_time"])` (3.516), `int(data["mc_print_sub_stage"])` (3.518) sowie 14 Temperaturfelder (3.818 bis 3.910) stehen in keinem `try`. Für `total_layer_num` und `layer_num` schützt der Code selbst, und sein Kommentar (Z. 3.536 bis 3.541) nennt den Grund: `_on_message` fängt nur `JSONDecodeError`, paho steht auf `suppress_exceptions = False`, die Ausnahme wird im Netzwerk-Thread erneut ausgelöst und „nimmt die Druckerverbindung herunter“. Ein einziges `null` oder ein Text wie `"--"` in einem dieser Felder reicht. Wiederherstellung erst über die Staleness-Erkennung nach 60 s. Ob echte Firmware solche Werte sendet, ist offen (latenter Fehler). | gelesen, AST |
| T2-02 | N | **Kein globales Sicherheitsnetz in `_on_message`.** Außer `JSONDecodeError` (Z. 1.431) wird nichts gefangen; jede unerwartete Ausnahme in den 4.000 Zeilen darunter hat dieselbe Wirkung wie T2-01. Ein `except Exception` um `_process_message` mit Logging würde die ganze Klasse von Fehlern entschärfen. | gelesen |
| T2-03 | N | **Keine Zertifikatsprüfung und kein Pinning.** Sowohl MQTT (`bambu_mqtt.py:5278-5287`) als auch FTPS (`bambu_ftp.py:442-454`) nutzen `check_hostname=False`, `CERT_NONE`. Das ist wegen selbstsignierter Druckerzertifikate üblich, aber der Access Code geht bei jedem Verbindungsaufbau an wen auch immer antwortet. Im LAN schwer auszunutzen, im WLAN oder bei fremder Infrastruktur möglich. Besser: Fingerabdruck beim ersten Kontakt merken und danach prüfen. | gelesen |
| T2-04 | N | **Gemeinsamer Zustand ohne Sperre.** `bambu_mqtt.py` enthält kein einziges `Lock`. Der paho-Thread schreibt `PrinterState` (viele Felder nacheinander), die Ereignisschleife liest es bei API-Abfragen. Verbindend ist nur die GIL; ein Leser kann einen halb aktualisierten Zustand sehen, z. B. `state` schon `FINISH`, `progress` noch alt. Listen werden an einigen Stellen ersetzt, an anderen verändert (`tray_change_log.clear()`, Z. 4.861). Eine Wettlauf-Ausnahme ist denkbar, aber nicht nachgestellt. | gelesen (Struktur), vermutet (Wirkung) |
| T2-05 | M (Wartbarkeit) | **Vier Funktionen über 1.400 Zeilen mit Komplexität über 250.** Eine Änderung an einem Feld (z. B. neue Firmware) erfordert das Verstehen von bis zu 1.569 Zeilen mit Verschachtelung bis Tiefe 10; `_update_state` mischt Parsen, Zustandsänderung, Erkennung von Druckstart/-ende und Rückrufe. Die zahlreichen Kommentare mit Ticketnummern (#2547, #2702, #1771, …) zeigen, dass jede Regression einzeln nachgetragen wurde. | AST, gelesen |
| T2-06 | N | **118 breite `except` und 40 stille `pass`** in diesen fünf Dateien, davon 52 allein in `mqtt_print_complete.py`. In Hintergrundaufgaben (Energie, Foto, Wartung, Benachrichtigung) ist Ausfallsicherheit gewollt, aber ohne einheitliche Meldung („welcher Schritt ist gescheitert?“) sieht der Betreiber Fehler nur im Log. | AST |
| T2-07 | N | **`on_print_start` hält eine einzige `async with`-Sitzung über 1.348 Zeilen** (Z. 649 bis 1.997), mit 8 `commit()`-Aufrufen dazwischen. Die kritische Stelle (DB-Verbindung während 2,5-s-Warten und Kamera) ist **bereits entschärft** (Z. 663 bis 669, #2572); gefährlich bleibt, dass die Grenzen der Transaktionen nur an den `commit()`-Stellen erkennbar sind und bei jeder Änderung neu geprüft werden müssen. | gelesen |
| T2-08 | I | **`_completion_triggered` wird auch gesetzt, wenn keine Fertigmeldung ausgelöst wurde** (Z. 4.946 bis 4.957: „State is FINISH but completion NOT triggered“ markiert es als ausgelöst). Gewollt („Zustand für den nächsten Druck sauber“), bedeutet aber: Ein Abschluss, der wegen eines Zeitproblems (`_previous_gcode_state`) nicht erkannt wurde, wird nie mehr nachgeholt. Der Gegenmechanismus (Archiv-Wiederherstellung) liegt in `print_start_flow`. | gelesen |
| T2-09 | N | **`with_ftp_retry` und Cool-off** verhindern Dauerschleifen, aber mehrere Pfad-Proben je Druckstart (`ftp_probe_paths`, bis ca. 110 Pfade bei der Sweep-Variante laut Kommentar) belasten ein Gerät, das FTPS nur eingeschränkt bedient. Die Begrenzung (nur bei vorhandener externer Speicherkarte, ein Dateiname statt Sweep) ist umgesetzt, #2780/#2856. Kein Fehler, nur Beobachtungspunkt. | gelesen |

### 4.1 Geprüft, kein Befund

- **DB-Verbindung während Ein-/Ausgabe** (Verdacht bei `on_print_start`): bewusst freigegeben (`await db.commit()` vor der Kamera-Arbeit, Z. 663 bis 669); Pool 20 plus 200 Überlauf bei SQLite, `busy_timeout=15000`, WAL (`core/database.py:19-21`, `50-52`).
- **Lokale Dateinamen aus Druckerdaten:** `probe_filename_from_url` verweigert statt zu bereinigen (Trenner, `..`, Steuerzeichen, Länge, nur `.3mf`; `print_storage.py:164-198`). Die übrigen Pfade tragen `# SEC-PATH-OK:`-Marker mit Begründung (`print_start_flow.py:416`, `1.400`, `1.508`).
- **Nachrichtenprotokoll** `_message_log` ist begrenzt (`deque(maxlen=100)`, Z. 783).
- **Thread-Brücke:** `PrinterManager` plant Coroutines per `run_coroutine_threadsafe` und protokolliert Ausnahmen aus dem Ergebnis (`printer_manager.py:706-715`).
- **Wiederverbindung:** Rücksetzen mit neuer `client_id` verhindert Wiederholung alter QoS-1-Befehle (`bambu_mqtt.py:1061-1087`); Abklingzeit gegen schnelle Folge (`STALE_RECONNECT_COOLDOWN = 30`); `reconnect_delay_set(1, 30)`.
- **Client-ID:** enthält Prozess-ID und laufende Nummer, kollidiert nicht zwischen Neustarts (Z. 5.257).

## 5. Refactoring-Vorschläge (nicht angewendet; Syntax geprüft)

### 5.1 Sichere Umwandlung und Sicherheitsnetz (löst T2-01, T2-02)

```python
def _num(data: dict, key: str, cast=float, default=None):
    """Liest ein Zahlenfeld aus einer Druckermeldung. Unbrauchbare Werte (null, Text, Liste) ergeben `default`."""
    value = data.get(key)
    if value is None or isinstance(value, (list, dict, bool)):
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default
```

Verwendung statt der 17 ungeschützten Stellen:

```python
        progress = _num(data, "mc_percent", float)
        if progress is not None:
            previous_progress = self.state.progress
            if progress > 0:
                self._last_valid_progress = progress
            self.state.progress = progress
            if progress > previous_progress and self._was_running and self.on_print_progress:
                self.on_print_progress(int(progress))
        remaining = _num(data, "mc_remaining_time", int)
        if remaining is not None:
            self.state.remaining_time = remaining
```

Zusätzlich das Netz in `_on_message`, damit **keine** Ausnahme den paho-Thread erreicht:

```python
    def _on_message(self, client, userdata, msg):
        try:
            self._handle_message(msg)
        except Exception:  # Sicherheitsnetz: eine kaputte Meldung darf die Verbindung nicht beenden
            logger.exception("[%s] Meldung auf %s konnte nicht verarbeitet werden", self.serial_number, msg.topic)
```

(`_handle_message` ist der bisherige Rumpf von `_on_message`.) Mehrwert: Ein unbrauchbares Feld kostet höchstens diese Meldung, nicht die Verbindung.

### 5.2 `_update_state` in Abschnitte zerlegen (löst T2-05)

Der Umbau ist rein mechanisch und lässt sich Stück für Stück absichern, weil jede Gruppe ein klares Eingabeschlüssel-Muster hat:

```python
    def _update_state(self, data: dict) -> None:
        """Nimmt eine Statusmeldung an. Jede Gruppe liest nur ihre eigenen Schlüssel."""
        previous = self.state.state
        self._probe_end_of_print_safely(data)
        self._apply_job_fields(data)          # gcode_state, Dateien, subtask_*
        self._apply_progress(data)            # mc_percent, Restzeit, Schichten
        self._apply_temperatures(data)        # alle Temperaturfelder, nur über _num()
        self._apply_hms_and_errors(data)      # hms, print_error
        self._apply_devices_and_functions(data)
        transition = self._detect_transition(previous)  # liefert NEW_PRINT / FILE_CHANGE / COMPLETE / None
        if transition is not None:
            self._dispatch_transition(transition, data)
```

Vorgehen: erst die Temperaturen und den Fortschritt herausziehen (Z. 3.499 bis 3.560, 3.818 bis 3.910), jeweils mit einem Test, der dieselbe
Meldung vor und nach dem Umbau durchspielt und `PrinterState` vergleicht. `_detect_transition` kapselt die Bedingungen aus Z. 4.919 bis 4.942
und wird so als Tabelle testbar:

```python
@dataclass(frozen=True)
class CompletionCase:
    state: str
    previous: str | None
    was_running: bool
    expect_trigger: bool


def should_trigger_completion(state: str, previous: str | None, was_running: bool, already: bool) -> bool:
    """Reine Funktion der Bedingungen aus _update_state (Z. 4.919 bis 4.942)."""
    if already:
        return False
    if state in ("FINISH", "FAILED"):
        if previous == "RUNNING":
            return True
        if was_running and previous != state:
            return True
        return state == "FAILED" and previous in ("PREPARE", "SLICING")
    return state == "IDLE" and previous == "RUNNING"
```

### 5.3 Fingerabdruck-Pinning (löst T2-03)

```python
import hashlib
import ssl


def server_fingerprint(sock: ssl.SSLSocket) -> str:
    der = sock.getpeercert(binary_form=True)
    return hashlib.sha256(der).hexdigest()


def verify_or_pin(printer, observed: str) -> None:
    """Erster Kontakt merkt den Fingerabdruck, danach muss er gleich bleiben (Vertrauen beim ersten Mal)."""
    if not printer.tls_fingerprint:
        printer.tls_fingerprint = observed          # einmalig speichern, im UI sichtbar machen
        return
    if printer.tls_fingerprint != observed:
        raise ssl.SSLError("Zertifikat des Druckers hat sich geändert (möglicher Abhörversuch)")
```

Neue Spalte `printers.tls_fingerprint`; im UI ein Knopf „Zertifikat neu vertrauen“ nach Firmware-Update oder Gerätewechsel. Für paho
muss die Prüfung in `on_connect` bzw. über `ssl_context.wrap_socket` laufen; für FTPS in `ImplicitFTP_TLS.connect` nach dem
`wrap_socket`. Vor Umsetzung klären, ob Drucker nach Firmware-Updates das Zertifikat wechseln.

### 5.4 Ereignis-Handler als Stufenfolge (löst T2-05, T2-07 für Druckstart und -ende)

```python
async def on_print_start(printer_id: int, data: dict) -> None:
    ctx = StartContext(printer_id=printer_id, data=data)
    for step in (check_plate_empty, find_or_create_archive, fetch_3mf, attach_metadata, notify_started):
        outcome = await step(ctx)
        if outcome is StepOutcome.STOP:      # z. B. Platte nicht leer, Archiv bereits vorhanden
            break
```

Jede Stufe öffnet ihre **eigene** kurze Sitzung (`async with async_session()`), und Netzwerk-Arbeit (FTP, Kamera, Benachrichtigung) läuft ausdrücklich
außerhalb einer offenen Transaktion. Dasselbe Muster gilt für die acht Hintergrundaufgaben von `on_print_complete`: heute innere Funktionen mit
geteiltem Zustand, besser eigenständige Funktionen mit einem gemeinsamen `CompleteContext` und einer Hülle, die Fehler einheitlich meldet:

```python
async def run_step(name: str, coro) -> None:
    """Führt eine Hintergrundstufe aus und meldet Fehler einheitlich (statt 52 einzelner breiter except)."""
    try:
        await coro
    except Exception:
        logger.exception("Stufe '%s' nach Druckende fehlgeschlagen", name)
        record_step_failure(name)   # z. B. Zähler für die Systemprüfung
```

## 6. Offene Punkte (T2b)

1. `on_print_complete`, `on_print_start`, `on_ams_change`, `on_printer_status_change` Zeile für Zeile lesen (Stufe A), vor allem Archiv-Zuordnung, doppelte Abschlüsse und Warteschlangen-Übergänge.
2. T2-01 mit einer Testmeldung nachstellen (`mc_percent: null` an `_on_message`) und prüfen, ob der paho-Thread endet.
3. `bambu_ftp.py` vollständig lesen: Zeitlimits, `with_ftp_retry`, Parallelität (`_DOWNLOAD_GATE`), Sitzungswiederverwendung für A1.
4. `start_print` (376 Zeilen): welche Eingaben aus der API werden in MQTT-Befehle übernommen, gibt es Einschleusung in JSON-Felder?
5. Verhalten bei Neustart während eines Drucks (`_was_running`, Wiederherstellung) mit einem Test-Skript durchspielen.

Die Entscheidung über die Umsetzung von 5.1 bis 5.4 liegt beim Auftraggeber; nichts davon ist im Code angewendet.

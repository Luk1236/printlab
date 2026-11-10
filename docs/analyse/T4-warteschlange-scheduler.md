# T4 Warteschlange und Druckplaner

Stand: 2026-11-10, Branch `bambu-monitor-port`. Vorgänger: [T3](T3-datenbank.md). Übersicht: [README.md](README.md).

## 0. Abdeckung (ehrlich)

| Datei | Zeilen | Funktionen | Stufe | Was gelesen wurde |
|---|---:|---:|---|---|
| `services/print_scheduler.py` | 3.949 | 68 | **A (Kern), B (Rest)** | gelesen: Konstanten und Kopf (Z. 150 bis 329), `run`, Abgleich hängengebliebener Aufträge, Claim-Logik, Upload-Pool, `_dispatch_one`, Rückrollen (Z. 394 bis 962) und `_start_print` (Z. 3.018 bis 3.946). **Nicht gelesen:** Filament-Zuordnung (Z. 962 bis 2.090), Niedrigbestand und Bestandsprognose (Z. 2.100 bis 2.740), `_repoint_siblings_at_archive` (Z. 2.770) |
| `services/scheduler/queue_pass.py` | 582 | 14 | **A** | vollständig |
| `services/scheduler/selection.py` | 483 | 3 | **A** | vollständig |
| `services/scheduler/dispatch.py` | 208 | 4 | **A** | vollständig |
| `services/scheduler/upload.py` | 204 | 2 | **A** | vollständig |
| `services/scheduler/watchdog.py` | 362 | 3 | **A** | vollständig |
| `services/scheduler/availability.py` | 623 | 13 | **B** | nur `_power_on_and_wait` (Z. 472 bis 525) gelesen |
| `services/scheduler/{drying,preheat,filament,delivery,nozzles,chamber}.py` | 3.007 | 61 | **B** | nur Inventar und Kennzahlen |
| `api/routes/print_queue.py` | 2.478 | 33 | **A (Teile), B (Rest)** | gelesen: `add_to_queue` bis Z. 1.073, `delete`, `reorder`, `resume`, `cancel`, `stop`, `start` (Z. 2.072 bis 2.478). **Nicht gelesen:** Antwortaufbau `_enrich_response`, Stapel (`create_batch` bis `cancel_batch`), `update_queue_item`, `bulk_update` |
| `services/finance_budget.py`, `finance_billing.py` | | | **A (Teile)** | nur die Stellen, die die Reservierung betreffen (Befund T4-02) |

Die Reservierungs-Lücke (T4-02) und die fehlende Obergrenze der Stückzahl (T4-04) sind **nachgestellt** (Skript im Scratchpad, eigene
Test-Datenbank). Alle anderen Befunde sind **gelesen**, mit `Datei:Zeile`, aber nicht ausgeführt; das steht je Befund dabei.
Insgesamt 198 Funktionen in den T4-Dateien. In Tiefe gelesen sind rund 4.600 der 11.900 Zeilen (knapp 40 Prozent), der Rest ist Inventar (Stufe B).

## 1. High-Level-Überblick

- **Zweck:** Ein Hintergrunddienst (`PrintScheduler.run`) schaut alle 3 bis 30 Sekunden in die Warteschlange, wählt je freiem Drucker einen
  Auftrag, lädt die Datei per FTP hoch und sendet den Druckbefehl per MQTT. Die HTTP-Routen in `print_queue.py` legen Aufträge an, ändern,
  stoppen und starten sie.
- **Aufteilung:** `PrintScheduler` erbt vier Mixins (Verfügbarkeit, Vorheizen, Trocknen, Wächter); eine Runde ist ein eigenes Objekt `QueuePass`
  (Zustand der Runde als Attribute, nicht als Verschlüsse).
- **Besonderheit:** Alle Module greifen über `_rt()` (ein `importlib.import_module` auf das Fassadenmodul) auf Namen zu, damit Tests
  `print_scheduler.<name>` ersetzen können. Das funktioniert, ist aber Kopplung über Zeichenketten (siehe T4-11).

## 2. Kontroll- und Datenfluss

```
run() ── alle 3 s (nach Start einer Datei) oder 30 s ─────────────────────────────────────────────┐
  _sample_chamber_temps → _clear_stale_dispatch_claims → _close_stranded_printing_items → check_queue
check_queue → QueuePass.run
  _collect   : pending-Aufträge (ohne dispatching_at, ohne laufende Uploads), Einstellungen, Trocknungsläufe
  _select    : je Auftrag _select_item
                 geplant/manuell → Haltegrund
                 fester Drucker → _select_pinned   (belegt? Stecker? idle? Trocknung? Bedingung? AMS-Zuordnung? Defizit?)
                 nach Modell    → _select_for_model (Kandidaten, Kreuzmodell-Sperre, freier Drucker, Einschalten, Zuweisung)
  _finish    : Warmhalten, upload_limit lesen, COMMIT, _launch_uploads (höchstens limit gleichzeitig), Trocknen/Filament/Bestand
_launch_uploads → je Auftrag Hintergrundaufgabe _dispatch_one
_dispatch_one  : Claim per CAS (pending und dispatching_at IS NULL) → _start_print → finally: Rückrollen, Claim lösen
_start_print   : NOT-HALT → Budget prüfen und reservieren → Drucker/Quelle/Datei → Düsen-Sperre → Plattenprüfung → Vorheizen
                 → G-code einfügen → COMMIT → FTP → CAS pending→printing → Plan → start_print (MQTT) → Wächter + Meldungen
_watchdog_print_start : Phase A 90 s, Phase B 180 s; Zurückstellen, höchstens 3 Versuche, dann „failed"
```

Die Reihenfolge „erst `printing` schreiben, dann senden“ (Z. 3.611 bis 3.634) ist richtig begründet: lieber ein hängender Auftrag
als ein doppelter Druck nach einem Absturz. Die Folge ist, dass alles in Abschnitt 4 zu „Auftrag bleibt in `printing`“ eine echte
Aufräum-Verantwortung hat.

## 3. Funktionsaufbau (Kern)

| Funktion | Zweck | Rückgabe / Nebenwirkung |
|---|---|---|
| `PrintScheduler.run` | Hauptschleife, fängt alles | schläft 3 s nach produktiver Runde, sonst 30 s |
| `_close_stranded_printing_items` (Z. 421) | schließt Zeilen, die >300 s `printing` sind, während der Drucker verbunden und beendet ist | schreibt `completed`/`failed`/`cancelled`; **keine** Reservierungsfreigabe, keine Meldungen |
| `_clear_stale_dispatch_claims` (Z. 505) | löscht `dispatching_at`, wenn kein Upload läuft | `UPDATE` |
| `_launch_uploads` (Z. 556) | startet höchstens `limit - len(_inflight)` Hintergrundaufgaben | trägt in `_inflight` ein, synchron |
| `_dispatch_one` (Z. 621) | Claim, `_start_print`, sicheres Aufräumen im `finally` | siehe Abschnitt 2 |
| `_start_print` (Z. 3.018) | 929 Zeilen, Komplexität 106 | der ganze Weg von der Zeile bis zum Befehl |
| `QueuePass._collect / _select / _select_item / _finish` | eine Runde | `bool`: etwas abgesetzt oder läuft noch |
| `SelectionMixin._select_pinned / _select_for_model` | Entscheidung je Auftrag | schreiben `waiting_reason`, `printer_id`, `dispatch_ids` |
| `deliver_file` (upload.py) | Löschen, Toast, Upload mit/ohne Wiederholung | `UploadOutcome` (kein DB-Zugriff, gut) |
| `_watchdog_print_start` (watchdog.py) | zweiphasige Überwachung nach dem Senden | setzt zurück oder lässt fehlschlagen; `statisch`, benutzt globales `rt.scheduler` |
| `_effective_plate_id` (dispatch.py) | Platte auflösen, ohne zu raten | `int`; warnt, ändert aber nie die Platte |

## 4. Befunde

Schweregrad: **H** hoch, **M** mittel, **N** niedrig, **I** Hinweis. Beleg: **nachgestellt**, **gelesen**.

### T4-01 (M, gelesen) Einschalten für feste Drucker blockiert die ganze Runde, ohne Abkühlzeit und ohne Limit — **behoben, ungepusht**

`selection.py:94-122` ruft für jeden Auftrag mit festem Drucker, der offline ist und einen „Auto An“-Stecker hat,
`_power_on_and_wait` auf (`availability.py:472-525`). Das wartet zuerst starr 30 s und dann bis 180 s auf die Verbindung, **innerhalb der
laufenden Runde**. Das Gegenstück für „Beliebiger Drucker dieses Modells“ ist dagegen gedeckelt: ein Einschalten je Runde
(`power_on_attempted`, `selection.py:352-369`) und eine Abkühlzeit von 600 s nach Fehlschlag (`_wake_failures`, `availability.py:92-96, 196`).
Der feste Zweig kennt beides nicht (`_wake_failures` kommt im ganzen `selection.py` nicht vor).

**Folge:** Drei Aufträge, die an drei ausgeschaltete Drucker gebunden sind, deren Stecker zwar schaltet, die aber nie eine Verbindung aufbauen (defekt, kein WLAN), halten jede Runde bis zu 3 × 180 s fest. (Ist der Stecker selbst nicht erreichbar, kehrt die Funktion sofort zurück, Z. 482-484.)
In dieser Zeit wird kein anderer Drucker bedient, der Abgleich für hängengebliebene Aufträge läuft nicht, und die Runde beginnt danach
sofort wieder von vorn. Die Zähluhr `elapsed` zählt außerdem nur Schlafzeit, nicht die Dauer von `connect_printer` selbst; die echte Wartezeit kann länger sein.
Genau diese Fehlerklasse wurde für die Modellsuche schon behoben (#2786, Kommentar Z. 230 bis 246 in `print_scheduler.py`).

Vorschlag: 5.3.

### T4-02 (M, nachgestellt) Budget-Reservierungen bleiben aktiv, wenn ein Auftrag ohne Abrechnung endet — **behoben, ungepusht**

Eine Reservierung (`BudgetReservation`, Status `active`) zählt in `get_cost_center_reserved_map` (`finance_budget.py:130-148`) **unabhängig vom
Status des Auftrags** weiter. Freigegeben wird sie nur an diesen Stellen: Löschen und Abbrechen eines wartenden Auftrags
(`print_queue.py:2109, 2247`), im `finally` von `_dispatch_one` (solange der Befehl nicht bestätigt ist), im Wächter-Zweig „aufgegeben“
(`watchdog.py:249`) und in der Abrechnung `apply_print_charge_for_archive`. Diese Wege lassen sie stehen:

| Weg | Stelle | Wann |
|---|---|---|
| Wächter, Zweig „Befehl abgelehnt“ | `watchdog.py:209-222` | Drucker verweigert die Befehlsprüfung (HMS 0500-0500-0001-0007); Auftrag wird `failed`, **ohne** Freigabe (der Zweig „aufgegeben“ direkt darunter gibt frei) |
| Abgleich hängengebliebener Aufträge | `print_scheduler.py:482-496` | schließt als `completed`/`failed`/`cancelled`, bewusst ohne Nebenwirkungen, aber auch ohne Freigabe |
| Stoppen bei Offline-Drucker | `print_queue.py:2327-2347` | Auftrag `cancelled`, Archiv `cancelled`, die Abrechnung läuft hier nie, weil kein MQTT-Ereignis kommt |
| Frühe Ausstiege der Abrechnung | `finance_billing.py:147-171` | Archiv fehlt, `wallet_charge_skipped`, Status nicht abrechenbar, kein Ersteller, Grundkosten ≤ 0 |

**Nachgestellt** (`scratchpad/t4_budget_leak.py`, Kostenstelle mit Monatsbudget 100, Auftrag 40 reserviert): Nach dem Schließen des Auftrags ohne
Freigabe bleiben **40 reserviert**, ein neuer Auftrag über 70 wird mit „70.00 > 60.00“ abgelehnt. Nach der Freigabe sind es 0 und der
Auftrag über 70 geht durch. Es gibt keinen Aufräumer für verwaiste `active`-Reservierungen (`release_budget_reservation` wird nur an den
oben genannten Stellen aufgerufen). Wer Abrechnung und Budgets eingeschaltet hat, verliert so dauerhaft Budget, bis jemand die Tabelle von Hand korrigiert.

Vorschlag: 5.1 (ein Weg zum Beenden) und ein Aufräumer, der `active`-Reservierungen ohne offenen Auftrag freigibt.

### T4-03 (M, gelesen) Modell-Aufträge werden an einen Drucker „festgenagelt“, wenn der Upload-Pool voll ist — **behoben, ungepusht**

`_select_for_model` setzt `item.printer_id = printer_id` (`selection.py:438`) und `_finish` schreibt das fest (`queue_pass.py:456`), **bevor**
`_launch_uploads` prüft, ob noch Platz im Pool ist (`print_scheduler.py:589-608`; Standard `queue_max_concurrent_uploads` = 4,
`queue_pass.py:449`). Ist der Pool voll, wird der Auftrag mit der Meldung „deferring“ zurückgestellt, behält aber den zugewiesenen Drucker. In der
nächsten Runde ist er ein **Auftrag mit festem Drucker** (`selection.py:391-392`) und kann nicht mehr auf einen freien Schwesterdrucker ausweichen.
Auch die Zuweisungs-Benachrichtigung (`on_queue_job_assigned`, `selection.py:445`) ist schon raus. Betroffen ist jeder Fall mit mehr
gleichzeitig startbaren Aufträgen als Slots, also vor allem Batches und größere Farmen.

Vorschlag: 5.4. Mit einem Test, der fünf Modell-Aufträge, Limit 2 und zwei freie Drucker annimmt und prüft, dass die zurückgestellten wieder `printer_id = None` haben.

### T4-04 (M, nachgestellt) `quantity` hat keine Obergrenze — **behoben, ungepusht**

`PrintQueueItemCreate.quantity: int = 1` (`schemas/print_queue.py:118`) hat kein `le=`. Die Route nimmt `max(1, data.quantity)`
(`print_queue.py:957`) und legt in `for i in range(quantity)` (Z. 1.147) so viele ORM-Objekte in **einer** Anfrage an. Die Schema-Prüfung
akzeptiert `10**9` (nachgestellt). Der danebenstehende `PrintBatchPlateTarget.quantity_target` ist dagegen auf `le=999` begrenzt (Z. 398).
Wer `queue:create` hat, oder jeder im Netz, wenn die Anmeldung aus ist, kann damit den Speicher und die Datenbank füllen. Die Ausführung wurde bewusst nicht probiert.

Vorschlag: 5.2 (eine Zeile).

### T4-05 (N, plausibel, nicht nachgestellt) Der Abgleich kann einen nie gestarteten Auftrag als „completed“ schließen

`_TERMINAL_STATE_QUEUE_STATUS` bildet `FINISH` auf `completed` ab (`print_scheduler.py:179-183`), und `_close_stranded_printing_items` prüft nur
Zustand und Dauer, nicht, **ob dieser** Druck lief (`print_scheduler.py:467-496`). `FINISH` ist aber auch der Zustand des *vorigen* Drucks. Zusammen
mit dem Wächter, der still aussteigt, wenn der Drucker keinen Status mehr meldet (`watchdog.py:89-95`, „don't mess with the DB“), ergibt sich: Befehl
verloren, Verbindung weg, Wächter beendet, Drucker kommt im Zustand `FINISH` zurück, nach 300 s steht der Auftrag auf `completed`, obwohl nichts
gedruckt wurde. Die Abrechnung läuft dafür nicht (siehe T4-02), die Anzeige ist aber falsch. Selten, aber stille Fehlinformation.

Vorschlag: bei `FINISH` nur dann `completed`, wenn Dateiname oder `subtask_id` des Druckers zum Auftrag passen, sonst `failed` mit „Druck nie gestartet“.

### T4-06 (N, gelesen) `stop_queue_item` verwechselt „offline“ mit „Befehl nicht gesendet“

`stop_sent = printer_manager.stop_print(...)` ist auch `False`, wenn der Drucker verbunden ist, aber das Senden scheiterte (`print_queue.py:2307-2314`).
Dann wird der Auftrag `cancelled`, das Archiv „cancelled (printer was offline)“ (Z. 2340-2345) und der Nutzer bekommt „Queue item cancelled (printer
was offline)“, während der Drucker weiterdruckt. Der Zustand des Druckers sperrt die Folgeaufträge (`_is_printer_idle`), das Archiv und die Anzeige lügen aber.
Besser: nur bei `not printer_manager.is_connected(printer_id)` abschließen, sonst Fehler 502 und den Auftrag lassen, wie er ist.

### T4-07 (N, gelesen) Aufräumen nach Abbruch: übrig gebliebene Dateien

1. **Library-Datei „verbraucht“, Druck scheitert.** Mit `cleanup_library_after_dispatch` wird die Zeile gelöscht und **committet** (`print_scheduler.py:3265-3273`),
   die Dateien (3MF, Vorschau) aber erst nach dem erfolgreichen CAS gelöscht (Z. 3.680-3.695). Scheitert der Upload oder greift ein Abbruch dazwischen,
   kehrt die Funktion vorher zurück; die Liste `cleanup_disk_paths` ist eine lokale Variable und geht verloren. Folge: verwaiste Dateien auf der Platte (das Archiv hat eine eigene Kopie)
   und der Nutzer hat den Bibliothekseintrag für einen fehlgeschlagenen Druck verloren.
2. **Temporäre G-code-Datei.** `inject_gcode_into_3mf` legt eine Temp-Datei an, deren Löschung dem Aufrufer überlassen ist (`threemf_tools.py:1404`). Der Aufrufer löscht sie nach
   `deliver_file` (`print_scheduler.py:3527-3529`), nicht in einem `finally`; wirft `deliver_file` oder der `commit` davor, bleibt sie liegen.

### T4-08 (N, gelesen) Kurzer Verbindungsabriss lässt den Auftrag endgültig scheitern

`_start_print` setzt bei `not printer_manager.is_connected(...)` sofort `failed` (`print_scheduler.py:3096-3103`). Die Auswahl hat die Verbindung vor Sekunden noch
bejaht; zwischen Auswahl, Claim, Budgetprüfung und dieser Zeile kann ein MQTT-Wiederverbinden liegen. Der Nutzer muss neu einreihen. Alle anderen
„Drucker gerade nicht bereit“-Fälle (`busy`, Upload abgelehnt) stellen zurück.

### T4-09 (N, gelesen) Blockierende 3MF-Zugriffe im Ereignis-Loop

`add_to_queue` öffnet und liest die 3MF direkt in der `async`-Route (`print_queue.py:930, 1041, 1051`, in `_resolve_queue_variants` Z. 783, 787 ebenso); die Datei hat
`0` Treffer für `to_thread`/`run_in_executor`. Bei großen Dateien blockiert das alle anderen Anfragen und MQTT-Rückrufe für die Dauer des Entpackens.
`reorder_queue` fragt außerdem je Eintrag einzeln ab (Z. 2149-2153, N+1).

### T4-10 (N, gelesen) Fehler ohne Stacktrace, viele breite `except`

`print_scheduler.py` hat 35 breite `except` und 7 `except … pass`; `scheduler/` weitere 26 und 5. Die drei Rettungsanker der Hauptschleife protokollieren nur `str(e)`
(`run` Z. 414-415, Abgleich Z. 500-503, Claim-Sweep Z. 540-541), ohne `exc_info`. Ein wiederkehrender Fehler in `check_queue` steht dann als eine Zeile alle 30 s im Log, ohne
Ort. Das Muster ist an vielen Stellen bewusst („best effort“, mit Begründung im Kommentar), dort ist `debug` mit `exc_info=True` ein günstiger Gewinn.

### T4-11 (I) Struktur

- `_start_print`: 929 Zeilen, Komplexität 106, **13** fast gleiche Blöcke „Status `failed` setzen, `error_message`, `completed_at`, `commit`, Log, `_power_off_if_needed`“,
  dazu 6 Aufrufe von `on_queue_job_failed` samt Toast. Genau diese Wiederholung ist die Ursache von T4-02 (jeder neue Ausstieg muss an die Freigabe denken).
- Die `_rt()`-Fassade (4 Module) und `_watchdog_print_start` als `staticmethod` mit globalem `rt.scheduler` sind ein Kompromiss für die Tests; sauberer wäre ein Aufruf mit Abhängigkeiten.
- `queue_pass.py:358-361` endet mit einem Kommentar, der zu Code gehört, der nach der Auslagerung nach `_finish` gewandert ist.
- `print_scheduler.py` hat 3.949 Zeilen und steht im Zeilenbudget-Test; weiteres Wachstum nur in eigenen Modulen.

### Was gut gelöst ist

Der Claim per CAS (`pending` und `dispatching_at IS NULL`, Z. 906-920) mit Aufräumen im `finally` und Nachfegen im ruhigen Takt; die Rückgabe des Vorheizens in jedem Ausstieg; die Bestätigungs-Logik
der Budget-Reservierung (`_unconfirmed_budget_reservations`); der CAS `pending→printing` gegen Abbruch während des Uploads; die Trennung von `deliver_file` (liefert ein Ergebnis, kein DB-Zugriff);
begründeter Backoff bei abgelehnten Uploads (#3210); die Wiederholungsgrenze des Wächters.

## 5. Refactoring-Vorschläge

Der Code steht in `scratchpad/t4_proposals.py`, ist mit `py_compile` und `ruff check` geprüft und in seinem Verhalten (Freigabe, Lösen, Grenze) mit einer Test-Datenbank ausprobiert. Eingebaut ist nichts.

### 5.1 Ein Weg, einen Auftrag zu beenden (T4-02)

```python
async def close_queue_item(
    db: AsyncSession,
    item: PrintQueueItem,
    status: TerminalStatus,
    message: str | None = None,
    *,
    release_budget: bool = True,
) -> None:
    item.status = status
    item.error_message = message
    item.completed_at = datetime.now(timezone.utc)
    item.waiting_reason = None
    if release_budget:
        await release_budget_reservation(db, source_type="print_queue", source_id=item.id, status="released")
    await db.commit()
```

Wächter („Befehl abgelehnt“), Abgleich, Stoppen bei Offline und die 13 Blöcke in `_start_print` rufen diese Funktion auf. Die Freigabe ist idempotent (berührt nur `active`).
Ergebnis in der Probe: vorher 40 reserviert, nachher 0, Status `completed`. Dazu ein kleiner Aufräumer (einmal je Stunde): `active`-Reservierungen von `print_queue`, deren Auftrag nicht mehr `pending`/`printing` ist oder fehlt, freigeben.

### 5.2 Grenze für die Stückzahl (T4-04)

```python
MAX_QUEUE_QUANTITY = 999  # wie PrintBatchPlateTarget.quantity_target

class PrintQueueItemCreate(BaseModel):
    quantity: int = Field(default=1, ge=1, le=MAX_QUEUE_QUANTITY)
```

Die Probe lehnt `10**9` ab. `max(1, data.quantity)` in der Route kann dann entfallen. Das Frontend schickt heute nur kleine Zahlen (nicht geprüft; vor dem Einbau per Suche nach `quantity` in `frontend/src` bestätigen).

### 5.3 Einschalten für feste Drucker mit Abkühlzeit und Limit (T4-01)

```python
async def try_power_on_pinned(qp: QueuePass, printer_id: int, plug, db: AsyncSession) -> bool | None:
    scheduler = qp._s
    now = time.monotonic()
    cooloff_until = scheduler._wake_failures.get(printer_id)
    if cooloff_until is not None:
        if now < cooloff_until:
            return None
        del scheduler._wake_failures[printer_id]
    if qp.power_on_attempted:
        return None
    qp.power_on_attempted = True
    ok = await scheduler._power_on_and_wait(plug, printer_id, db)
    if not ok:
        scheduler._wake_failures[printer_id] = time.monotonic() + scheduler._wake_failure_cooloff
    return ok
```

`selection.py:102` ruft statt `_power_on_and_wait` diese Funktion auf; bei `None` bleibt der Auftrag mit Haltegrund „Offline, wartet auf Einschalten“ liegen und die Runde geht weiter.
Das ist dieselbe Regel wie bei der Modellsuche, nur gemeinsam genutzt (`power_on_attempted`, `_wake_failures`).

### 5.4 Zurückgestellte Modell-Aufträge wieder lösen (T4-03)

```python
def unpin_deferred_model_items(items, deferred_ids, model_assigned_ids) -> list[int]:
    released = []
    by_id = {it.id: it for it in items}
    for item_id in deferred_ids:
        item = by_id.get(item_id)
        if item is not None and item_id in model_assigned_ids:
            item.printer_id = None
            released.append(item_id)
    return released
```

`_select_for_model` trägt die Id in `self.model_assigned_ids` ein, wenn es `printer_id` setzt. `_launch_uploads` gibt die zurückgestellten Ids zurück, `_finish` ruft die Funktion
auf und committet. Aufträge, deren Drucker der Nutzer gewählt hat, bleiben unberührt. In der Probe: `[1]` gelöst, Auftrag 2 behält Drucker 9.

### 5.5 `_start_print` in Phasen zerlegen (T4-11)

Nach 5.1 bleibt der Ablauf in sechs benannten Schritten, jeder liefert `None` (weiter) oder beendet den Auftrag über `close_queue_item`:
`_preflight` (NOT-HALT, Budget, Drucker, Verbindung, `pending` prüfen), `_resolve_source` (Archiv/Bibliothek, Datei da, Düsen-Sperre), `_prepare` (Plattenprüfung, Vorheizen, G-code),
`_transfer` (commit, `deliver_file`, `finally` für die Temp-Datei), `_commit_start` (CAS, Plan, Abrechnungs-ID), `_send_and_watch` (`start_print`, Wächter, Meldungen).
Das ist reine Umordnung ohne neues Verhalten und gehört **nach** den Tests aus Abschnitt 6.

## 6. Tests, die vor einer Umsetzung geschrieben werden sollten

| Test | Sichert |
|---|---|
| Wächter-Zweig „Befehl abgelehnt“ lässt keine aktive Reservierung zurück | T4-02 |
| Abgleich schließt `printing` + `FINISH`: Reservierung frei | T4-02 |
| Stoppen bei Offline-Drucker: Reservierung frei | T4-02 |
| fünf Modell-Aufträge, Limit 2: zurückgestellte haben `printer_id = None` | T4-03 |
| `quantity=1000` und `0` werden mit 422 abgelehnt | T4-04 |
| zwei feste Aufträge auf zwei ausgeschalteten Druckern: höchstens ein Einschalten je Runde, Abkühlzeit gilt | T4-01 |
| `stop` bei verbundenem Drucker und gescheitertem Senden: Auftrag bleibt `printing`, Antwort 502 | T4-06 |

## 7. Empfohlene Reihenfolge

1. T4-04 (eine Zeile, kein Risiko) und T4-02 mit 5.1 (Geld, belegt).
2. T4-01 und T4-03 (Verfügbarkeit der Warteschlange).
3. T4-05, T4-06, T4-07, T4-08 (Richtigkeit der Anzeige, Plattenplatz).
4. T4-09, T4-10, dann 5.5 (Umbau).

## 8. Offen in dieser Tranche (Stufe B, nicht gelesen)

`print_scheduler.py` Z. 962 bis 2.740 (Filament-Zuordnung `_match_filaments_to_slots` k52, 203 Zeilen; Niedrigbestand; Bestandsprognose), `_repoint_siblings_at_archive`;
`drying.py` (`_check_auto_drying` 454 Zeilen, k80), `preheat.py` (`_preheat_and_soak` 361 Zeilen, k73), `availability.py` (`_find_idle_printer_for_model` k49), `delivery.py` (`prepare_start` k38);
in `print_queue.py` `update_queue_item`, `bulk_update_queue_items`, die Stapel-Routen und `_enrich_response` (k46). Eine zweite Sitzung „T4b“ kann diese lesen.

## 9. Umsetzung der mittleren Befunde (2026-11-10)

| Befund | Änderung | Test |
|---|---|---|
| T4-04 | `PrintQueueItemCreate.quantity` mit `ge=1, le=999` (`schemas/print_queue.py`) | `test_add_to_queue_rejects_unbounded_quantity_t4_04` |
| T4-02 | Freigabe im Wächter-Zweig „Befehl abgelehnt“, im Abgleich und beim Anhalten bei Offline-Drucker; zusätzlich Aufräumer `scheduler/reservations.py` (einmal je Stunde, Schonfrist 10 min), aufgerufen aus `QueuePass.run` | Wächter, Abgleich, `stop` offline/online, vier Fälle des Aufräumers |
| T4-01 | `scheduler/wake.py`: ein Einschalten je Runde, Abkühlzeit nach Fehlschlag, geteilt mit der Modellsuche; `selection.py` hält den Auftrag mit Haltegrund | vier Fälle in `test_t4_queue_fixes.py` |
| T4-03 | `QueuePass._unpin_deferred`: zurückgestellte Modell-Aufträge bekommen Drucker **und** AMS-Zuordnung von vor der Runde zurück | fünf Fälle in `test_t4_queue_fixes.py` |

Abweichungen vom Vorschlag in Abschnitt 5: kein gemeinsames `close_queue_item` (die 13 Blöcke in `_start_print` bleiben für T4-11), dafür der Aufräumer als Netz unter allen Stellen, die eine Freigabe vergessen könnten.
Beim Zurückstellen wird auch die AMS-Zuordnung zurückgesetzt, weil sie für den zuerst gewählten Drucker berechnet wurde und sonst auf einem anderen Drucker die falschen Fächer ansprechen könnte.
Der Abgleich gibt die Reservierung frei, auch wenn er einen Auftrag als `completed` schließt, für den nie abgerechnet wurde; das ist besser als dauerhaft gebundenes Budget, gleicht aber den Betrag nicht aus.
Geprüft: Ruff sauber, 1.674 Tests aus Planer, Queue, Finanzen und Zeilenbudget bestanden; vier der fünf neuen Fehlerfälle schlagen auf dem alten Stand fehl (der fünfte, „online stoppen behält die Reservierung“, sichert nur das bestehende Verhalten).

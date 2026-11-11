# T5 Archiv, Bibliothek, Dateien: Uploads, Pfade, 3MF/Zip

Stand: 2026-11-10, Branch `bambu-monitor-port`. Vorgänger: [T4](T4-warteschlange-scheduler.md). Übersicht: [README.md](README.md).

## 0. Abdeckung (ehrlich)

Der Bereich ist groß: 29 Dateien mit rund 23.800 Zeilen und etwa 520 Funktionen. Gelesen habe ich nach Risiko, nicht gleichmäßig.

| Datei | Zeilen | Funktionen | Stufe | Was gelesen wurde |
|---|---:|---:|---|---|
| `utils/safe_path.py`, `filename.py`, `library_paths.py`, `archive_paths.py` | 458 | 17 | **A** | vollständig |
| `api/routes/library.py` | 3.984 | 48 | **A (Teile), B (Rest)** | gelesen: externe Ordner (Z. 828 bis 970, Scan 1.170 bis 1.262), `upload_file` und `extract_zip_file` (Z. 1.560 bis 2.030). **Nicht gelesen:** Verschieben, Kombinieren, Löschen, Freigabe, Slicer-Token, Vorschau, Fotos (außer der Größenprüfung) |
| `api/routes/archives.py` | 5.523 | 92 | **A (Teile), B (Rest)** | gelesen: Foto-, F3D-, Zeitraffer- und alle Upload-Stellen (Z. 3.075 bis 3.345, 5.410 bis 5.450 und die Eingänge der übrigen Uploads). **Nicht gelesen:** Zeitraffer-Zuordnung, Neuberechnung, Vergleich, Neudruck, Umschnitt |
| `api/routes/customer_portal_route.py` | 270 | | **A (Teile)** | nur die beiden Upload-Routen und der Ratenbegrenzer (gehört fachlich zu T8) |
| `services/archive.py`, `utils/threemf_tools.py` | 3.970 | 90 | **B** | Inventar, alle `zf.read`-Stellen gezählt, der Parser gemessen; Funktionen nicht einzeln gelesen |
| `services/library_trash.py`, `archive_purge.py`, `slicer_*`, `slice_*`, `builtin_slicer.py` | ca. 5.000 | 100 | **B** | Inventar, nur Löschpfade gelesen |
| übrige (`library_slicing`, `library_variants`, `library_tags`, `pending_uploads`, …) | ca. 3.600 | 90 | **B** | nur Inventar |

Nachgestellt (Skripte im Scratchpad, eigene Test-Datenbank, die echte Datenbank blieb unberührt): T5-01 (Zip-Bombe), T5-03 (Speicher im öffentlichen
Portal), T5-04 (F3D-Schreibpfad), T5-05 (Blockierzeit). Alles andere ist **gelesen** mit `Datei:Zeile`.

## 1. High-Level-Überblick

- **Zweck:** Dateien kommen auf vier Wegen ins System: Bibliothek (`/library`, einzeln, als ZIP, aus externen Ordnern), Archiv (`/archives/upload`,
  `-bulk`, Quelle, F3D, Fotos, Zeitraffer), Slicer-Ausgaben und das öffentliche Kundenportal. Eine 3MF ist ein Zip, aus dem Metadaten, Vorschaubild und
  Filamentangaben gelesen werden.
- **Speicherort:** Bibliotheksdateien unter UUID-Namen (`<uuid><endung>`), Archive in einem eigenen Ordner je Archiv. Der Name des Nutzers landet nur in der
  Datenbank, nicht auf der Platte (das schließt die klassische Pfad-Einschleusung aus, siehe „Was gut gelöst ist“).
- **Besonderheit:** Zwei Pfadmodelle nebeneinander: relative Pfade (Standard) und absolute (externe Ordner, Altbestand). `to_absolute_path` nimmt absolute Pfade
  unverändert an; das ist nur sicher, weil kein Weg `file_path` von außen schreibt (`FileUpdate` hat das Feld nicht).

## 2. Kontroll- und Datenfluss (Einzel-Upload in die Bibliothek)

```
POST /library/files
  Anmeldung/Recht LIBRARY_UPLOAD → Dateiname prüfen (FAT-Zeichen) → Zielordner → _resolve_upload_destination
  content = await file.read()                  ← ganze Datei im Speicher, keine Grenze
  validate_print_file_upload(name, content)    ← nur „.3mf beginnt mit PK“, rohes .gcode abgelehnt
  open(...).write(content)                     ← zweite Kopie auf der Platte
  calculate_file_hash(path)                    ← Platte wird noch einmal gelesen (im Ereignis-Loop)
  ThreeMFParser(path).parse()                  ← entpackt Teile ohne Grenze, im Ereignis-Loop
  Vorschau: gcode / Bild / STL (trimesh) im Ereignis-Loop, PDF in einem Thread
  LibraryFile anlegen, commit
```

Die ZIP-Route macht dasselbe je Teil und liest die **ganze** Zip-Datei und danach jedes Teil vollständig (`zf.read`, Z. 1.787 und 1.896).

## 3. Funktionsaufbau (Kern)

| Funktion | Zweck | Rückgabe / Nebenwirkung |
|---|---|---|
| `safe_join_under(parent, *parts)` | Nutzerstrings unter einem Elternordner zusammensetzen | aufgelöster Pfad; wirft 400 bei `/`, `\`, NUL, `..`-Flucht, Symlink-Flucht |
| `assert_under(parent, candidate)` | Eindeutigkeitsprüfung für bereits gebaute Pfade | aufgelöster Pfad oder 400 |
| `validate_print_filename` | Dateinamen wie Bambu Studio prüfen | wirft `InvalidFilenameError` |
| `safe_path_component` | Anzeigenamen in *eine* Pfadkomponente verwandeln | ersetzt statt zu verwerfen, schneidet auf Bytes |
| `derive_remote_filename` | SD-Karten-Name aus dem Bibliotheksnamen | `…​.3mf`, Leerzeichen zu `_` |
| `archive_dir(archive)` | Ordner eines Archivs, kennt den Sonderfall ohne 3MF | `Path` |
| `_validate_external_path` | externen Ordner nur unter erlaubten Wurzeln, nie in Datenordnern | `Path` oder 400 |
| `upload_file`, `extract_zip_file` | Einzel- und ZIP-Upload | `LibraryFile`-Zeilen, Dateien, Vorschauen |
| `ThreeMFParser.parse` | Metadaten und Vorschaubild aus der 3MF | `dict`, `_thumbnail_data` als Bytes |

## 4. Befunde

Schweregrad: **H** hoch, **M** mittel, **N** niedrig, **I** Hinweis. Beleg: **nachgestellt**, **gelesen**.

### T5-01 (H, nachgestellt) Kein Schutz gegen Zip-Bomben: Teile werden ohne Grenze entpackt — **behoben, ungepusht**

Im ganzen Backend gibt es nur eine Entpack-Grenze (`MAX_PRINTER_ZIP_BYTES` in `printer_media.py:406`). Dagegen lesen 54 Stellen (`threemf_tools.py` 17,
`archives.py` 15, `library.py` 8, `archive.py` 7, `slicer_3mf_convert.py` 6, `plate_thumbnail.py` 1) ein Zip-Teil mit `zf.read(...)` komplett in den Speicher, ohne vorher
`ZipInfo.file_size` zu prüfen. Eine Zip-Datei kann mit gut komprimierbarem Inhalt tausendfach größer entpackt werden.

**Nachgestellt** (`t5_zipbomb.py`): eine 3MF mit einem Teil `Metadata/slice_info.config` aus Leerzeichen. Auf der Platte **199 KB**, entpackt 200 MB (Faktor 1.027:1).
`ThreeMFParser(...).parse()` liefert ein Ergebnis, die Speicherspitze liegt bei **438 MB** in 1,8 s. Eine 2-MB-Datei erreicht damit rund 2 GB; auf einem Raspberry Pi mit 1 bis 4 GB Arbeitsspeicher beendet das
den Prozess (OOM). Die ZIP-Route `extract_zip_file` hat zusätzlich keine Grenze für Teilzahl und Gesamtgröße und legt je Teil eine Zeile an.

Vorschlag: 5.1.

### T5-02 (H, gelesen) Uploads werden vollständig in den Speicher gelesen, fast nirgends mit Grenze — **behoben, ungepusht**

`await file.read()` ohne Größenangabe steht an **20** Stellen: `archives.py` (3.091 Zeitraffer, 3.221 Audio, 3.325 Foto, 4.132 Upload, 4.195 Sammel-Upload, 5.137 Quelle, 5.351 Quell-Upload,
5.446 F3D), `library.py` (1.606 Datei, 1.787 ZIP), `projects.py` (3), `customer_portal_route.py` (2), `settings.py`, `local_presets.py`, `error_help.py`, `layer_inspection.py`, `pc_slicer.py`.
Drei Stellen sind begrenzt: Bibliotheks-Foto 10 MB (Z. 3.553), Vorschaubild 2 MB (Z. 3.459) und der CSV-Import des Bestands (liest in Stücken). Dort ist das Muster schon da, es wurde nicht übernommen.
Bei `upload_file` liegt die Datei danach dreifach vor: im Speicher, auf der Platte, und der Hash liest sie noch einmal. Ein Sammel-Upload (`/upload-bulk`) liest eine Datei nach der anderen vollständig.
Es gibt keine Grenze in einer Zwischenschicht (kein `client_max_body_size` im Projekt, keine Body-Grenze in der Anwendung).

Vorschlag: 5.2.

### T5-03 (H, wenn das Portal von außen erreichbar ist; gelesen, Speicher nachgestellt) Öffentliche Modellanalyse: ohne Anmeldung, ohne Größengrenze, rechnet im Ereignis-Loop — **behoben, ungepusht**

`POST /api/v1/portal/analyze-model` und `/quote-from-model` sind bewusst ohne Anmeldung (`test_route_auth_coverage.py:116-117`). Sie lesen die Datei unbegrenzt
(`customer_portal_route.py:168, 193`) und rufen `analyze_mesh_data` synchron im Ereignis-Loop auf (Z. 170, 195; kein `to_thread`), das `trimesh.load` auf Nutzerdaten ausführt.
Der Ratenbegrenzer zählt Anfragen je IP (20 bis 30 je Minute), nicht Bytes, und greift erst, **nachdem** der Body angenommen wurde. Hinter einem Reverse-Proxy ist `request.client.host` die Adresse des Proxys (alle Kunden teilen einen Eimer).

**Nachgestellt** (`t5_portal_bomb.py`): 3MF mit einem 200 MB großen `3D/3dmodel.model` aus Leerzeichen, 200 KB Upload. `analyze_mesh_data` wirft nach 1,0 s einen `ValueError` („huge text node“),
aber erst **nachdem** das Teil entpackt war: Speicherspitze 438 MB, und der Loop stand die ganze Zeit. Ein Dritter ohne Zugang kann die ganze Anwendung (Druckplaner, MQTT, Oberfläche) lahmlegen oder den Prozess beenden.

Vorschlag: 5.2 und 5.3.

### T5-04 (M, nachgestellt) F3D-Upload bei Archiven ohne 3MF schreibt in den Ordner über dem Datenordner — **behoben, ungepusht**

`upload_f3d` (`archives.py:5431-5445`) leitet den Zielordner mit `(settings.base_dir / archive.file_path).parent` ab. Bei einem Archiv ohne 3MF ist `file_path == ""`,
`base_dir / ""` ist `base_dir`, und `.parent` ist der Ordner **darüber**. Genau dafür gibt es `archive_dir()` (#1820), diese Stelle benutzt es nicht.
**Nachgestellt** (temporärer Test mit den Test-Fixtures, danach gelöscht): Datenordner `…/data`, Archiv mit `file_path=""`, Upload von `design.f3d`. Die Datei landet in
`…/f3d/design.f3d`, also **außerhalb** des Datenordners; danach scheitert `relative_to(settings.base_dir)` mit `ValueError` (500), die Datei bleibt liegen und der Eintrag wird nicht gespeichert.
Der Name ist durch `_safe_filename` auf einen Basenamen begrenzt, ein beliebiger Zielort ist also nicht möglich. Es bleiben verwaiste Dateien an einem Ort, den Sicherung und Aufräumer nicht kennen.

Dieselbe Ableitung `settings.base_dir / archive.file_path` steht an 23 weiteren Stellen (17 in `archives.py`, dazu `print_scheduler.py:3182`, `usage_tracker.py:1388` u. a.). Dort ist die Folge milder: für `""`
ist der Pfad der Datenordner, `file_path.exists()` ist wahr, und der Planer versucht, einen **Ordner** hochzuladen (Fehlermeldung „Upload failed“ statt „Source file not found on disk“, `print_scheduler.py:3379`).
Das Einreihen prüft das nicht (`_assert_can_queue_archive` fragt nur nach Rechten).

Vorschlag: 5.4.

### T5-05 (M, nachgestellt) Schwere synchrone Arbeit im Ereignis-Loop bei Upload und Scan

`upload_file`, `extract_zip_file` und der Ordner-Scan rufen Hash (`calculate_file_hash`), `ThreeMFParser.parse`, Bild- und STL-Vorschau (trimesh) und `os.walk` direkt in `async def` auf
(`library.py:1618, 1633, 1685, 1699, 1906, 1916, 1974`, Scan 1.239); nur die PDF-Vorschau läuft in `asyncio.to_thread`. **Gemessen** mit der mitgelieferten 3-MB-Beispieldatei: Hash 24 ms, Parser 91 ms,
in dieser Zeit steht der Loop (größte Verzögerung einer parallelen Aufgabe 86 ms). Das Verhältnis wächst mit der Dateigröße und ist auf dem Pi ein Mehrfaches. Während eines Uploads großer Dateien
ruckeln Kamerastrom, MQTT-Verarbeitung und Oberfläche. Gleiche Familie wie T4-09.

### T5-06 (N, gelesen) Fehlertexte geben Interna preis

`detail=f"Upload failed: {str(e)}"` (`library.py:1735`), `"Failed to save ZIP file: …"` (1.791), `"ZIP extraction failed: …"` (2.021) und je Teil `errors.append(... error=str(e))` (2.006) geben die
Ausnahme im Wortlaut an den Aufrufer: Dateipfade, SQL-Fehler, Bibliothekstexte. Das Protokoll hat den Fehler ohnehin (`exc_info=True`); die Antwort braucht nur eine kurze Meldung und eine Kennung.

### T5-07 (N, gelesen) ZIP-Upload prüft Dateinamen nicht wie der Einzel-Upload

Der Einzel-Upload lehnt Namen mit `< > : " / \ | ? *`, Steuerzeichen und Endpunkt ab (`validate_print_filename`, #1540). `extract_zip_file` nimmt `os.path.basename(zip_path)`
ungeprüft (Z. 1.886). So landen Namen in der Bibliothek, die erst beim Einreihen scheitern („Filename contains invalid character“). Ordnernamen aus dem Zip (`part`, Z. 1.852) sind ungeprüft, aber nur Datenbankeinträge, kein Pfad.

### T5-08 (N, gelesen) Fotos, Zeitraffer und F3D werden nur an der Endung erkannt

`upload_photo` (`archives.py:3305`) und `upload_f3d` (5.420) prüfen nur das Namensende, nicht den Inhalt (Magic Bytes, Pillow). Ausgeliefert wird nach Endung. Ein als `.png` benannter Fremdinhalt ist harmlos
solange `nosniff` und eine passende Content-Security-Policy gesetzt sind (nicht geprüft); sauberer ist die Prüfung beim Speichern. `upload_f3d` prüft die Endung zudem nur klein geschrieben (`.F3D` wird abgelehnt).

### T5-09 (N, gelesen) Drei Stellen parsen unvertrauliches XML mit dem Standard-Parser

Rund 40 Stellen nutzen `defusedxml` (gut). Ausnahmen: `filament_requirements.py:56` (3MF-Inhalt, mit `# noqa: S314`), `virtual_printer/manager.py:1261` (3MF-Inhalt, `# nosec`) und
`external_links.py:332` (SVG-Prüfung vor dem Speichern). Externe Entitäten löst der Standard-Parser nicht auf, und das gebündelte expat (2.8.2 in der Python-Version dieses Projekts) hat Schutz gegen
Entitäts-Verstärkung; die Gefahr ist damit klein. Die Umstellung ist eine Zeile je Stelle und beseitigt die Ausnahmen für die Sicherheitsprüfungen (`noqa`/`nosec` sind dann überflüssig).

### T5-10 (I) Struktur

- `archives.py` (5.523 Zeilen, 92 Funktionen, 25 breite `except`, 25 davon mit `pass`) und `library.py` (3.984 Zeilen, 16 und 14) sind die größten Routen-Dateien; `archive.py` hat 19 `except … pass`, `threemf_tools.py` 14.
- `upload_file` und `extract_zip_file` wiederholen rund 100 Zeilen (Datei speichern, Typ bestimmen, Hash, Metadaten, Vorschau, Zeile anlegen). Die Hilfsfunktion `clean_metadata` ist dreimal wörtlich eingebettet (`library.py:1651, 1930` und im Scan).
  Eine gemeinsame Funktion `ingest_library_file()` würde T5-01, T5-02, T5-05 und T5-07 an **einer** Stelle beheben statt an dreien.
- Das Muster „Grenze bei Upload“ ist an drei Stellen vorhanden (Foto, Vorschau, CSV) und fehlt an 20; ein gemeinsames Hilfsmittel würde es zur Gewohnheit machen.

### Was gut gelöst ist

- `safe_join_under` und `assert_under` sind vollständig (absolute Teile, NUL, `..`, Symlinks) und werden an den Stellen mit Nutzernamen benutzt; Stellen mit sicheren Konstanten tragen eine `# SEC-PATH-OK`-Begründung, ein CI-Wächter prüft sie.
- Bibliotheksdateien liegen unter `<uuid><endung>`; der Name des Nutzers erreicht die Platte nicht. **Zip-Slip ist damit ausgeschlossen**, denn Zip-Teilnamen werden nie als Pfad benutzt.
- Externe Ordner: Positivliste (`PRINTLAB_EXTERNAL_ROOTS`, standardmäßig leer), PrintLab-eigene Ordner immer gesperrt, auch bei zu weiter Positivliste, Symlink-Prüfung beim Scan, erhöhtes Recht (`SETTINGS_UPDATE`).
- `FileUpdate` enthält `file_path` nicht; `to_absolute_path` bleibt dadurch sicher trotz der Altlast absoluter Pfade.
- Warteschlange: Zugriffs-Prüfung auf Archive und Bibliotheksdateien (IDOR) an einer Stelle gebündelt; 3MF-Magic-Byte-Prüfung; rohes `.gcode` abgelehnt.
- 40 Stellen mit `defusedxml`; `plate_thumbnail` liest große Netze als Strom mit `resolve_entities=False`, `no_network=True`, `load_dtd=False`.

## 5. Refactoring-Vorschläge

Der Code steht in `scratchpad/t5_proposals.py`, ist mit `py_compile` und `ruff check` geprüft und mit der Zip-Bombe aus T5-01 und Test-Uploads ausprobiert. Eingebaut ist nichts.

### 5.1 Entpack-Grenzen (T5-01)

```python
MAX_SMALL_MEMBER_BYTES = 32 * MB      # Metadaten, Konfiguration, Vorschaubild
MAX_MODEL_MEMBER_BYTES = 512 * MB     # Netze: 163 MB sind in Bambu-Dateien gesehen worden
MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_TOTAL_BYTES = 2048 * MB

class ZipLimitError(ValueError): ...

def check_zip(zf, *, max_members=MAX_ZIP_MEMBERS, max_total_bytes=MAX_ZIP_TOTAL_BYTES) -> None:
    infos = zf.infolist()
    if len(infos) > max_members:
        raise ZipLimitError(f"zip has {len(infos)} entries, limit is {max_members}")
    total = sum(i.file_size for i in infos)
    if total > max_total_bytes:
        raise ZipLimitError(f"zip unpacks to {total} bytes, limit is {max_total_bytes}")

def read_member(zf, name, *, max_bytes=MAX_SMALL_MEMBER_BYTES) -> bytes:
    declared = zf.getinfo(name).file_size
    if declared > max_bytes:
        raise ZipLimitError(f"{name!r} unpacks to {declared} bytes, limit is {max_bytes}")
    return zf.read(name)
```

`ZipInfo.file_size` ist eine verlässliche Obergrenze, weil `zipfile` nie mehr als diese Zahl liest. Ergebnis in der Probe: die 200-MB-Bombe wird **abgelehnt, bevor entpackt wird** (Speicherspitze 0,0 MB statt 438 MB), ein
kleines Teil und `plate_1.png` gehen durch. Einbau: `read_member` an den 54 Stellen (die Modelldatei mit `MAX_MODEL_MEMBER_BYTES`), `check_zip` am Anfang von `ThreeMFParser.parse` und `extract_zip_file`.

### 5.2 Upload mit Grenze, ohne alles in den Speicher zu laden (T5-02, T5-03)

```python
async def read_upload_limited(upload, max_bytes) -> bytes:        # klein: Bilder, Portal-Netze
    ...  # liest in 1-MB-Stücken, bei Überschreitung 413 ohne weiterzulesen

async def save_upload_limited(upload, dest, max_bytes) -> tuple[int, bytes]:   # groß: 3MF, ZIP
    ...  # schreibt in Stücken auf die Platte, liefert (Größe, erste 8 Byte), löscht bei 413 die Teildatei
```

Probe: 1.000 Bytes gehen durch, 3 MB bei Grenze 2 MB geben 413; ein 2-MB-Upload wird gespeichert (Kopf `PK\x03\x04`), ein 6-MB-Upload bei Grenze 5 MB gibt 413 und die Teildatei ist weg.
Die Prüfung `validate_print_file_upload(name, content)` braucht danach nur noch die ersten Bytes. Die Grenze gehört als Einstellung angelegt (Vorschlag: 1 GB für Bibliothek und Archiv, 25 MB für das Portal, 10 MB für Bilder).

### 5.3 Portal-Route (T5-03)

`analyze_model` und `create_quote_from_model`: `content = await read_upload_limited(file, 25 * MB)`, `check_zip` vor `trimesh.load` bei 3MF, und der Aufruf `await asyncio.to_thread(analyze_mesh_data, content, file.filename)`
mit `asyncio.wait_for(..., 30)`. Zusätzlich eine Grenze am Reverse-Proxy (z. B. nginx `client_max_body_size 30m` für `/api/v1/portal/`), denn die Anwendung sieht den Body erst, wenn er angenommen ist. Im Projekt (`deploy/`, `install/`) ist keine Proxy-Konfiguration mit Grenze mitgeliefert.

### 5.4 F3D-Ziel immer unter dem Datenordner (T5-04)

```python
def f3d_target(archive, filename) -> Path:
    target = safe_join_under(archive_dir(archive) / "f3d", filename)
    return assert_under(settings.base_dir, target)
```

Probe: Archiv mit `file_path=""` ergibt `<Datenordner>/archive/7/f3d/design.f3d`, Archiv mit 3MF `<Datenordner>/archives/1/f3d/design.f3d`; beide unter dem Datenordner. Dazu ein kleiner Wächtertest (AST), der in
`routes/` jede Ableitung `base_dir / archive.file_path` gefolgt von `.parent` verbietet, damit niemand den Fehler wiederholt, und eine Prüfung `if not archive.file_path` an den Stellen, die eine Datei **lesen** (Planer, Neudruck, Neuberechnung).

### 5.5 Eine Eingangsfunktion für Bibliotheksdateien (T5-10)

`ingest_library_file(db, source_path, filename, folder_id, user, ...)` mit Namensprüfung (`validate_print_filename`), Grenze, Hash in einem Thread, Parser in einem Thread, Vorschau, Zeile anlegen und einem
einzigen `clean_metadata`. `upload_file`, `extract_zip_file` und der Scan rufen sie auf. Reine Umordnung, dafür vorher die vorhandenen Upload-Tests als Netz.

## 6. Tests, die vor einer Umsetzung geschrieben werden sollten

| Test | Sichert |
|---|---|
| Zip-Bombe (200 KB, 200 MB entpackt) wird vom Parser mit `ZipLimitError` abgelehnt, Speicherspitze klein | T5-01 |
| `extract_zip_file` lehnt zu viele Teile und zu große Gesamtgröße ab | T5-01 |
| Upload über der Grenze gibt 413 und hinterlässt keine Datei (Bibliothek, Archiv, Portal) | T5-02 |
| Portal: 3MF-Bombe gibt 400/413 und blockiert den Loop nicht (parallele Aufgabe läuft weiter) | T5-03 |
| F3D-Upload bei Archiv ohne 3MF landet unter dem Datenordner (oder 400), nie darüber | T5-04 |
| Wächter: keine `base_dir / archive.file_path` + `.parent` in `routes/` | T5-04 |
| ZIP-Upload mit ungültigem Dateinamen meldet ihn je Teil als Fehler | T5-07 |

## 7. Empfohlene Reihenfolge

1. T5-01 und T5-03 zusammen (Zip-Grenzen, Portal-Route), weil sie von außen ohne Anmeldung nutzbar sind.
2. T5-02 (Upload-Grenze, Streaming) und T5-04 (F3D, eine Stelle, klein).
3. T5-05, T5-06, T5-07, T5-08, T5-09.
4. 5.5 (Eingangsfunktion) als Umbau.

## 8. Offen in dieser Tranche (Stufe B, nicht gelesen)

`library.py`: Verschieben, Kombinieren, Löschen, Bulk-Löschen, Freigabe, Slicer-Token, Fotos; `archives.py`: Zeitraffer-Zuordnung (über 600 Zeilen), Neuberechnung, Vergleich, Neudruck, Umschnitt;
`archive.py` (`archive_print` 327 Zeilen) und `threemf_tools.py` je Funktion; `library_slicing.py` (`_slice_one` 525 Zeilen), die Slicer-Anbindung (`slicer_cli.py`, Komplexität 93, startet Fremdprogramme: Argumentübergabe prüfen);
`pending_uploads.py`. Eine zweite Sitzung „T5b“ kann diese lesen; zuerst `slicer_cli.py` (Fremdprozess mit Nutzerdateien).

## 9. Umsetzung (2026-11-10)

| Befund | Änderung | Test |
|---|---|---|
| T5-01 | `utils/zip_limits.py`: `read_member` (Grenze nach Endung: 32 MB klein, 768 MB für `.model`/`.gcode`/`.stl`/…), `check_zip`, `extract_member_limited`. **82 Zip-Lesestellen** in 19 Dateien umgestellt, `ThreeMFParser.parse` ruft `check_zip` zuerst auf | Parser-Bombe (kleiner als 20 MB Spitze statt 438 MB), Grenzen je Endung, Strom-Entpacken räumt auf |
| T5-02 | `utils/upload_limits.py`: `read_upload_limited`, `save_upload_limited`. Einstellungen `max_upload_mb` (Standard 1024) und `max_portal_upload_mb` (25), Umgebung `MAX_UPLOAD_MB` / `MAX_PORTAL_UPLOAD_MB`. Bibliothek: Datei und ZIP werden **in Stücken auf die Platte** geschrieben; alle übrigen `await file.read()` (archives, projects, settings, local_presets, error_help, layer_inspection, pc_slicer) laufen über `read_upload_limited` mit 25 MB für Bilder, 100 MB Audio, 256 MB Entwurf, 50 MB für kleine Dateien, sonst `max_upload_mb` | Bibliothek 413 ohne Restdatei, ZIP 413, Foto 413, abgelehntes `.3mf` wird wieder gelöscht |
| T5-03 | Portal: `read_upload_limited(…, max_portal_upload_bytes())`, `analyze_mesh_data` im Thread mit 30 s Zeitgrenze, `mesh_analysis` prüft 3MF mit `check_zip` (150 MB entpackt, 2.000 Teile) vor `trimesh` | Portal 413, Bombe 400 mit „unpacks to“, defektes 3MF gibt `ValueError` |
| T5-04 | `archive_paths.f3d_target()` (über `archive_dir`, `safe_join_under`, `assert_under`); der Upload liest zuerst und löscht die alte Datei erst danach | F3D bei Archiv ohne 3MF landet unter dem Datenordner |

Abweichungen vom Vorschlag in Abschnitt 5:
- Die ZIP-Route der Bibliothek entpackt Teile **in Stücken auf die Platte** (`extract_member_limited`), nicht mehr mit `zf.read`. Ein zu großes Teil wird als Fehler dieses Teils gemeldet, die übrigen werden weiter entpackt.
- Die Archiv-Uploads (`/upload`, `/upload-bulk`, Quelle, Zeitraffer) lesen weiter in den Speicher, aber mit Grenze (`max_upload_mb`, Standard 1 GB). Streaming auf die Platte ist dort ein eigener Umbau, weil der Dienst den Inhalt als `bytes` erwartet; auf einem Pi mit 1 GB RAM sollte `MAX_UPLOAD_MB` niedriger gesetzt werden.
- Kopierschleifen, die alle Teile einer 3MF in eine neue schreiben (Umschnitt, G-code-Einfügen), nutzen `read_member_large`: die Grenze soll Bomben abwehren, keine Anhänge unbekannter Endung abweisen.
- Mit angepasst wurden zwei Fehlertexte, an denen ich ohnehin war (T5-06: ZIP-Fehler zeigen nur noch „Failed to save ZIP file“ / „ZIP extraction failed“, Einzelheiten stehen im Protokoll).
- Nicht gemacht: T5-05 (Ereignis-Loop in Upload und Scan, außer im Portal), T5-07 bis T5-10, und die Proxy-Grenze vor dem Portal (Betrieb, nicht Code).

- Der Foto-Upload für Archive liest jetzt zuerst und legt den Ordner erst danach an; ein abgelehnter Upload hinterlässt weder Datei noch Ordner.

### Nebenbefunde aus den Testläufen (behoben in `backend/tests/conftest.py`)

Beide Punkte haben dieselbe Ursache und sind mit einer Änderung erledigt: `conftest.py` setzt `DATA_DIR` vor dem ersten App-Import auf ein Wegwerf-Verzeichnis und bricht den Lauf ab, wenn `settings.base_dir` oder `settings.archive_dir` nicht darunter liegen. Gegenprobe über die ganze Suite (15.026 bestanden, 185 übersprungen, parallel mit vier Prozessen): Vorher-Nachher-Vergleich des Projektordners ergibt keine neue, keine gelöschte und keine geänderte Datei. Der einzige Fehlschlag, `test_abnahme.py::test_repo_hygiene_check_is_ok`, kam von zwei leeren `test_pipeline_*.3mf` im Projektstamm, Resten eines früheren Laufs; nach dem Löschen besteht er. Nicht angefasst: die Altlasten unter `archive/` (dort können auch echte lokale Daten liegen) und `gpio_hardware.py`, das `gpio_mechanik.json` weiterhin in den globalen Datenordner statt neben den übergebenen `config_path` schreibt.

- **Ein vorhandener Test überschreibt eine versionierte Kalibrierdatei.** `test_gpio_hardware.py::test_gpio_service_save_config_and_calibration` lenkt nur `gpio_hardware.json` in ein Temp-Verzeichnis um; `save_servo_calibration(15.5, 160.0)` schreibt zusätzlich in die echte `backend/data/gpio_mechanik.json` (Klappenwinkel 12/150 werden zu 15,5/160). Nach einem lokalen Testlauf steht die Datei als geändert im Arbeitsverzeichnis und könnte versehentlich committet werden. Ich habe sie auf den versionierten Stand zurückgesetzt.
- **Tests schreiben in den echten Datenordner.** Ohne `DATA_DIR` ist `settings.base_dir` der Projektordner; viele vorhandene Tests legen dadurch Dateien unter `archive/` ab (in zwei Tagen 248 Dateien, der Ordner ist per `.gitignore` ausgenommen und wächst unbemerkt). Die neuen T5-Tests lenken ihre Pfade in Temp-Verzeichnisse um; die Testdateien aus meinen ersten Läufen habe ich wieder entfernt.

Geprüft: Ruff sauber; 4.747 vorhandene Tests aus Bibliothek, Archiv, 3MF, Slicer, Portal, Projekten und Einstellungen bestanden; neun der zwölf neuen Tests schlagen auf dem alten Stand fehl (die übrigen drei sichern das bestehende Verhalten: kleiner Upload geht durch, defektes 3MF, abgelehnte Umbenennung).

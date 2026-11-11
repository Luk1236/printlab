# T6 Drucker-Routen, Kamera, virtueller Drucker

Stand: 2026-11-11, Branch `bambu-monitor-port`. Vorgänger: [T5](T5-archiv-bibliothek-dateien.md). Übersicht: [README.md](README.md).

## 0. Abdeckung (ehrlich)

21 Dateien mit rund 19.800 Zeilen und 433 Funktionen. Gelesen habe ich nach Risiko: zuerst alles, was von außen erreichbar ist (die Server des
virtuellen Druckers, Datei- und Steuer-Routen, Kamera-Abruf), die großen Fachfunktionen nur als Inventar.

| Datei | Zeilen | Funktionen | Stufe | Was gelesen wurde |
|---|---:|---:|---|---|
| `virtual_printer/ftp_server.py`, `mqtt_server.py`, `bind_server.py` | 2.538 | 66 | **A** | vollständig |
| `virtual_printer/tcp_proxy.py` | 1.870 | 37 | **A (Teile), B (Rest)** | gelesen: `TLSProxy` (Z. 107 bis 388), FTP-Datenproxy (Z. 1.097 bis 1.433). **Nicht gelesen:** `_rewrite_mqtt_ip`, FTP-Steuerkanal, `SlicerProxyManager` |
| `virtual_printer/manager.py` | 1.907 | 48 | **A (Teile), B (Rest)** | gelesen: Konstruktor, Datei- und Druckbefehl-Rückrufe, Archiv/Prüfung/Warteschlange (Z. 226 bis 465, 621 bis 1.285). **Nicht gelesen:** Start/Stopp, `sync_from_db`, `_restamp_recent_queue_item` |
| `virtual_printer/mqtt_bridge.py` | 814 | 19 | **B** | nur `is_active` und `forward_to_printer` gelesen |
| `virtual_printer/ssdp_server.py`, `certificate.py`, `diagnostic.py`, `tailscale.py`, `_debug.py` | 1.733 | 42 | **B** | Inventar; bei `certificate.py` nur die Dateirechte der Schlüssel geprüft |
| `api/routes/virtual_printers.py` | 596 | 10 | **A (Teile)** | Anlegen und Auflisten (Z. 1 bis 300). **Nicht gelesen:** Ändern, Löschen |
| `services/external_camera.py` | 1.339 | 24 | **A (Teile)** | Zielprüfung und Einzelbild-Abruf (Z. 30 bis 166, 540 bis 820). **Nicht gelesen:** die drei Stream-Generatoren |
| `api/routes/camera.py` | 2.047 | 41 | **A (Teile), B (Rest)** | Token, Stream, Stopp, Schnappschuss, Status (Z. 925 bis 1.365, 1.424 bis 1.487). **Nicht gelesen:** `generate_rtsp_mjpeg_stream`, Plattenerkennung, Aufräumdienst |
| `services/camera.py`, `camera_fanout.py`, `camera_diagnose.py`, `camera_profiles.py`, `camera_calibration.py` | 2.021 | 58 | **B** | nur Inventar |
| `api/routes/printers.py`, `printer_sensor_history.py` | 4.967 | 88 | **A (Teile), B (Rest)** | Dateirouten (Z. 1.582 bis 1.716, 1.959 bis 2.136), Steuerbefehle (Z. 3.700 bis 4.151). **Nicht gelesen:** Status, Titelbild, AMS-Konfiguration, Kalibrierung, Druckvorschub |
| `core/auth.py` (aus T1) | | | nachgelesen | `check_printer_access` und `require_printer_permission_if_auth_enabled` (Z. 1.772 bis 1.840) |

Nachgestellt (acht Tests im Scratchpad gegen den unveränderten Code, eigene Test-Datenbank): T6-01 bis T6-08. Alles andere ist **gelesen** mit `Datei:Zeile`.
Die Vorschläge aus Abschnitt 6 sind als Code geprüft (`py_compile`, Ruff, Selbsttests).

## 1. High-Level-Überblick

- **Drucker-Routen** (`/printers/...`, 86 Funktionen): Stammdaten, Status, Dateien auf dem Drucker (über FTP), Steuerbefehle (über MQTT), AMS, Kalibrierung.
- **Kamera:** je Drucker ein gemeinsamer Zulieferer (`MjpegBroadcaster`), an den sich alle Betrachter hängen, weil die meisten Drucker nur eine
  Kameraverbindung erlauben. Externe Kameras (MJPEG, RTSP, Einzelbild, USB) laufen daran vorbei über `external_camera.py`.
- **Virtueller Drucker (VP):** PrintLab gibt sich im Netz als Bambu-Drucker aus. Vier Betriebsarten: `archive` (Datei nur archivieren), `review`
  (zur Prüfung ablegen), `queue` (in die Warteschlange), `proxy` (alles an den echten Drucker durchreichen). In den ersten drei Arten laufen eigene
  Server: SSDP (Erkennung), Bind (Port 3000/3002), MQTT (8883), FTPS (990). Im Proxy-Betrieb terminiert PrintLab TLS auf beiden Seiten.
- **Wichtig für die Einordnung:** Hat ein VP einen Zieldrucker, übernimmt er dessen Zugangscode (`virtual_printers.py:219-221`). Der VP-Code ist dann
  der Code des echten Druckers. Ohne Zieldrucker hat der VP einen eigenen Code.

## 2. Kontroll- und Datenfluss

```
Slicer „Senden“ an einen VP (Betriebsart queue)
  SSDP/Bind: Slicer findet den VP (ohne Anmeldung, wie beim echten Drucker)
  MQTT 8883 (TLS): CONNECT bblp/<Code>            ← 5 Fehlversuche je 60 s und IP, dann gesperrt
  FTPS 990 (TLS): USER bblp, PASS <Code>          ← keine Bremse (T6-02)
     PASV → Datenport aus 10er-Bereich je VP      ← nimmt jede Gegenstelle an (T6-03)
     STOR datei.3mf → uploads/<vp>/datei.3mf      ← Name auf letzte Pfadkomponente gekürzt, Zip-Ende geprüft
  on_file_received → _add_to_print_queue
     wartet kurz auf MQTT project_file (Druckoptionen des Slicers)
     ArchiveService.archive_print → je Platte ein PrintQueueItem   ← Plattenzahl ohne Grenze (T6-10)
  MQTT: alles außer pushall/get_version/project_file geht 1:1 an den echten Drucker (bewusst, gleicher Code)

API-Aufruf mit Schlüssel, der auf Drucker A beschränkt ist
  /printers/B/files           → RequirePrinterPermissionIfAuthEnabled → 403
  /printers/B/print/stop      → RequirePermissionIfAuthEnabled        → wird ausgeführt (T6-01)
```

## 3. Funktionsaufbau (Kern)

| Funktion | Zweck | Rückgabe / Nebenwirkung |
|---|---|---|
| `FTPSession.handle` | Steuerverbindung: Zeile lesen, `cmd_<NAME>` aufrufen | läuft bis Trennung oder 5 Minuten Leerlauf |
| `FTPSession.cmd_STOR` | Upload in 64-KiB-Stücken auf die Platte, danach Zip-Prüfung | Datei unter `uploads/<vp>/`, Rückruf `on_file_received`; bei Fehler 426 und Datei weg |
| `SimpleMQTTServer._handle_client` | eigener kleiner MQTT-Server: CONNECT, SUBSCRIBE, PUBLISH, PINGREQ | registriert den Client für den 1-Hz-Status |
| `SimpleMQTTServer._handle_publish` | Befehle des Slicers: lokal beantworten oder an den Drucker weiterreichen | `on_print_command`, `MQTTBridge.forward_to_printer` |
| `VirtualPrinterInstance._add_to_print_queue` (432 Zeilen) | Datei archivieren, je Platte einen Warteschlangen-Eintrag anlegen | DB-Schreibzugriffe, löscht die Upload-Datei |
| `FTPTLSProxy._start_data_proxy_server` | Einmal-Server für eine FTP-Datenverbindung im Proxy-Betrieb | bindet Port auf `0.0.0.0`, Klartext zum Slicer |
| `_sanitize_camera_url`, `_blocked_host_reason` | Kamera-Adresse prüfen (Schema, kein Loopback, kein Link-Local) | bereinigte URL oder `None` |
| `capture_frame`, `_capture_snapshot`, `_capture_rtsp_frame` | ein Bild von der externen Kamera | JPEG-Bytes oder `None` |
| `camera_stream` | MJPEG-Strom an den Browser, geteilt über `MjpegBroadcaster` | `StreamingResponse`, Einträge in sechs Modul-Registern |
| `build_printer_file`, `build_printer_files_zip` | Druckerdateien über FTP auf die Platte holen, mit Größengrenze | Pfad einer Temp-Datei, einmaliger Download-Link |
| `bed_jog`, `xy_jog`, `extruder_jog`, `home_axes` | Bewegung als G-Code über MQTT | `client.send_gcode(...)` |
| `check_printer_access` | Drucker-Liste eines API-Schlüssels durchsetzen | 403, wenn der Drucker nicht in `printer_ids` steht |

## 4. Befunde

Stufen: **H** hoch, **M** mittel, **N** niedrig, **I** Hinweis. Die Tabelle beschreibt den Stand **vor** der Umsetzung; T6-01 bis T6-06 und T6-08
sind behoben, siehe Abschnitt 9.

| Nr. | St. | Befund | Beleg |
|---|---|---|---|
| T6-01 | H | **Die Drucker-Beschränkung von API-Schlüsseln gilt nur für 10 von 168 Routen.** Ein Schlüssel mit `printer_ids=[A]` (Feld „null = alle Drucker“, `models/api_key.py:60`) wird nur in den Dateirouten von `printers.py` (Z. 1.609 bis 2.123) und in `webhook.py:352` geprüft. Alle anderen Routen mit `{printer_id}` im Pfad nutzen `RequirePermissionIfAuthEnabled` ohne diese Prüfung: Stopp, Pause, Temperaturen, Bewegung, AMS, Kamera, Hardware, Wartung, Firmware, Löschen. Im Test hält, pausiert und bewegt ein auf Drucker A beschränkter Schlüssel den Drucker B (Antwort 200, Befehle beim Client angekommen), während `/files` korrekt 403 liefert. Routen, die den Drucker im Anfragekörper tragen (Warteschlange, `fleet/command`), sind ebenfalls ungeprüft. | nachgestellt |
| T6-02 | M | **FTP-Anmeldung am VP ohne Bremse gegen Durchprobieren.** `cmd_PASS` (`ftp_server.py:172-186`) zählt Fehlversuche nicht, wartet nicht und trennt nicht. MQTT desselben VP sperrt nach 5 Fehlversuchen je 60 s (`mqtt_server.py:29-37`), mit der Begründung, dass VPs über Tailscale oder Portweiterleitung erreichbar sein können. Über FTP läuft derselbe Code ungebremst: 20.000 falsche `PASS` auf einer Verbindung in 1,4 s (ohne Netz gemessen), danach gelingt die Anmeldung. Hat der VP einen Zieldrucker, ist das der Zugangscode des echten Druckers. Bei einem achtstelligen Ziffern-Code sind es 10^8 Möglichkeiten; die Rate über das Netz habe ich nicht gemessen. | nachgestellt |
| T6-03 | M | **FTP-Datenverbindung wird von jeder Adresse angenommen.** `_handle_data_connection` (`ftp_server.py:322-364`) vergleicht die Gegenstelle nicht mit der Steuerverbindung. Der Datenport liegt in einem Bereich von 10 Ports je VP. Wer im Netz schneller verbindet als der Slicer, liefert den Inhalt der Datei, die danach archiviert oder in die Warteschlange gestellt wird, ohne den Zugangscode zu kennen. Im Proxy-Betrieb ist es leichter: Der Einmal-Server (`tcp_proxy.py:1402-1408`) lauscht auf `0.0.0.0` statt auf der VP-Adresse, ohne TLS, auf dem vom Drucker genannten Port, und reicht den Inhalt an den echten Drucker weiter. | Servermodus nachgestellt, Proxy gelesen |
| T6-04 | M | **`nan` als Bewegungsweite wird als G-Code gesendet.** `abs(distance) > 200` und `distance == 0` sind für NaN beide falsch (`printers.py:4018`, `4050`, `4092`). `POST /printers/1/bed-jog?distance=nan` sendet `G91 / G1 Znan F600 / G90`, ebenso `Xnan` und `Enan`. `inf` wird abgewiesen. Was die Firmware mit `Znan` macht, weiß ich nicht. Dazu gelesen: Keine der Bewegungsrouten prüft, ob der Drucker gerade druckt; `send_gcode` (`bambu_mqtt.py:6657`) prüft nur die Verbindung. Der Docstring von `bed_jog` hält selbst fest, dass die Firmware Endschalter bei MQTT-G-Code nicht beachtet. | nachgestellt |
| T6-05 | M | **Druckerdateien werden ohne Grenze in den Speicher geladen.** `get_printer_file_gcode`, `get_printer_file_plates` und `get_printer_file_plate_thumbnail` (`printers.py:1696`, `1743`, `1970`) rufen `download_file_bytes_async` auf, das keine Größengrenze kennt (anders als `download_file_async` für den Weg über die Platte, `bambu_ftp.py:1615`). Die G-Code-Route prüft die Endung erst **nach** dem Download: `?path=/timelapse/video.mp4` lädt das ganze Video und antwortet dann mit „Unsupported file type“. Die Vorschaubild-Route lädt die komplette 3MF je Platte neu. Die Download-Route daneben macht es richtig (auf die Platte, mit Größengrenze). | nachgestellt |
| T6-06 | M | **Weiterleitungen umgehen die Zielprüfung der Kamera.** `_sanitize_camera_url` prüft nur die erste Adresse; `session.get(safe_url)` folgt Weiterleitungen (`external_camera.py:571`, `778`, `1020`). Eine Kamera-Adresse, die auf `http://127.0.0.1:…` oder `169.254.169.254` weiterleitet, wird abgerufen, und `_capture_snapshot` gibt nicht dekodierbare Antworten unverändert zurück (Z. 809 bis 818), die Schnappschuss-Route liefert sie als Bild aus. Dazu liest `_capture_snapshot` die Antwort ohne Größengrenze (`response.read()`, Z. 784); der MJPEG-Pfad daneben hat 5 MB. Wer statt der Einzelbild- eine Stream-Adresse einträgt, puffert bei jedem Abruf bis zum Zeitlimit. | nachgestellt (Weiterleitung) |
| T6-07 | N | **Der MQTT-Server liest große Pakete unvollständig.** `reader.read(remaining_length)` (`mqtt_server.py:586`) liefert höchstens so viel, wie gerade da ist. Ein PUBLISH, das in zwei Teilen ankommt (über etwa 16 KiB oder getrennte TLS-Datensätze), wird abgeschnitten, der Rest als neuer Paketkopf gedeutet. Im Test geht derselbe `project_file`-Befehl am Stück durch und in zwei Teilen verloren. Übliche Slicer-Befehle sind kleiner, deshalb niedrig. | nachgestellt |
| T6-08 | M | **Der FTP-Datenproxy reicht nur eine Richtung durch und schneidet bei kurzen Pausen ab.** `handle_data` (`tcp_proxy.py:1252-1400`) liest nur vom Slicer. Daten vom Drucker (LIST, RETR) kommen nie beim Slicer an; im Test wartet er vergeblich. Für Uploads gilt: 0,3 s ohne Daten nach dem ersten Stück gelten als „fertig“ (Z. 1.341 bis 1.353), die Druckerseite wird geschlossen und der Drucker bestätigt eine unvollständige Datei. Der Proxy-Betrieb ist gerade für entfernte Netze gedacht, wo solche Pausen vorkommen. Außerdem wächst `slicer_buffer` ohne Grenze, solange die Verbindung zum Drucker aufgebaut wird (bis 10 s). | Richtung nachgestellt, Abschneiden gelesen |
| T6-09 | N | **Proxy-Betrieb: jede eingehende Verbindung öffnet sofort eine zum Drucker.** `TLSProxy._handle_client` (`tcp_proxy.py:295-339`) verbindet vor jeder Anmeldung, ohne Obergrenze je IP oder insgesamt. Wer den Proxy erreicht, kann die wenigen Verbindungsplätze des Druckers belegen. | gelesen |
| T6-10 | N | **Warteschlangen-VP: Plattenzahl und Ablage ohne Grenze.** `_extract_plate_ids` (`manager.py:1240-1282`) übernimmt jede `<plate>`-Angabe, auch doppelte; je Angabe entsteht ein Eintrag (Z. 1.073). Im Prüf-Betrieb bleiben Uploads bis zur Entscheidung liegen (`_queue_file`), bis 4 GiB je Datei, ohne Kontingent. Beides setzt den Zugangscode voraus. | gelesen |
| T6-11 | N | **Upload-Verarbeitung im Ereignis-Loop.** `f.write(chunk)` in `cmd_STOR` (`ftp_server.py:444-452`), die Zip-Prüfung danach und `ThreeMFParser.parse()` in `_queue_file` laufen synchron (gleiches Muster wie T5-05). Zwei gleichzeitige Uploads mit demselben Namen schreiben in dieselbe Datei; der Docstring nennt das selbst („no concurrency guard“). | gelesen |
| T6-12 | N | **Buchführung externer Kamera-Streams zählt nicht.** `_active_external_streams` ist eine Menge (`camera.py:108`, `1011`, `1066`): Verlässt der erste von zwei Betrachtern, gilt der Stream als beendet. `_stream_start_times[printer_id]` wird von jedem Betrachter überschrieben (Z. 1.010), der eingebaute Pfad nutzt aus genau diesem Grund `setdefault` (Z. 1.103). Externe Kameras hängen nicht am gemeinsamen Zulieferer: jeder Betrachter öffnet eine eigene Verbindung, was bei USB-Kameras mit einem Leser scheitert. | gelesen |
| T6-13 | I | **Toter und veralteter Code.** `VirtualPrinterMQTTServer` (`mqtt_server.py:85-217`, amqtt) wird nirgends benutzt, bindet `0.0.0.0` und vergleicht den Code mit `==`. Der Kommentar über `MAX_UPLOAD_BYTES` (`ftp_server.py:29-35`) beschreibt noch das Puffern im Speicher. `_pending_files` (`manager.py:290`) dient nur noch als Zähler; die Kommentare über eine „same-name STOR guard“ (Z. 1.208) beschreiben eine Prüfung, die es nicht gibt. | gelesen |
| T6-14 | I | **Kleine Robustheitslücken.** `bind_ip` und `remote_interface_ip` werden nicht als IP-Adresse geprüft (`virtual_printers.py:44`, `59`; nur Einstellungs-Recht). Ein MQTT-Befehl, dessen `pushing`-Wert kein Objekt ist, wirft `AttributeError` und trennt die Verbindung (`mqtt_server.py:1385`). PUBLISH mit QoS 1 bekommt kein PUBACK; ein CONNECT mit Will-Feldern wird falsch zerlegt. | gelesen |
| T6-15 | I | **Sehr große Funktionen, nicht einzeln gelesen:** `configure_ams_slot` (525 Zeilen, Komplexität 87), `get_printer_file_plates` (236, 80), `generate_rtsp_mjpeg_stream` (376, 63), `_add_to_print_queue` (432, 59), `get_printer_status` (381, 58), `_produce_cover_image` (331, 52). Fehler darin sind möglich und hier nicht ausgeschlossen. | Inventar |

Zur Einordnung von T6-02 und der MQTT-Weiterleitung: Dass der VP jeden nicht selbst beantworteten Befehl an den echten Drucker reicht
(`mqtt_bridge.py:794-814`, auch Stopp oder `gcode_line`), ist kein eigener Befund, weil der Slicer dafür den Code des echten Druckers schon hat.
Es heißt aber: Wer den VP-Code errät, steuert den Drucker, nicht nur die Warteschlange.

Die fehlende Zertifikatsprüfung zum Drucker (`tcp_proxy.py:206-216`) ist derselbe Punkt wie T2-03 und dort beschrieben.

## 5. Was gut gelöst ist

- **Kamera-Zielprüfung** klassifiziert Adressen mit `ipaddress` statt mit Zeichenketten und kennt Oktal-, Dezimal- und IPv6-Schreibweisen
  (`external_camera.py:37-91`); ffmpeg bekommt eine Protokoll-Positivliste. Es fehlt nur die Weiterleitung (T6-06).
- **FTP-Upload** kürzt den Namen auf die letzte Pfadkomponente, schreibt in Stücken statt alles zu puffern, hat eine Obergrenze und prüft bei 3MF das
  Zip-Ende, bevor er Erfolg meldet. Fehlgeschlagene Uploads hinterlassen keine Datei.
- **MQTT** vergleicht den Code in konstanter Zeit und bremst Fehlversuche; hängende Clients werden nach 5 s Schreibstau entfernt.
- **Datenbank:** Stream- und Dateirouten laden den Drucker in einer kurzen Sitzung und geben die Verbindung vor dem langen Netzzugriff frei.
- **Datei-Download** läuft über die Platte mit Größen- und Platzprüfung und einem einmaligen, an Drucker und Zweck gebundenen Link.
- **Bewegung:** `home_axes` sendet immer das vollständige `G28`; die Bewegungsrouten fassen `M211` nicht mehr an. Die Docstrings erklären, warum.
- **Schlüsseldateien** des VP werden mit Rechten 0600 geschrieben.

## 6. Vorschläge

Der Code steht geprüft im Scratchpad (`t6_proposals.py`); hier die Kernstücke.

**V1 zu T6-01: eine Prüfung für alle Drucker-Routen statt je Route.** Als Router-Abhängigkeit, die nur greift, wenn ein API-Schlüssel und ein
`printer_id` im Pfad vorhanden sind. Benutzer-Sitzungen bleiben unverändert.

```python
async def enforce_api_key_printer_scope(
    request: Request, api_key: APIKey | None = Depends(current_api_key_if_present)
) -> None:
    raw = request.path_params.get("printer_id")
    if api_key is None or raw is None:
        return
    try:
        printer_id = int(raw)
    except (TypeError, ValueError):
        return  # die Route selbst antwortet mit 422
    check_printer_access(api_key, printer_id)

# einmal an der App (main.py bindet 67 Router einzeln ein, einen gemeinsamen API-Router gibt es nicht):
app = FastAPI(..., dependencies=[Depends(enforce_api_key_printer_scope)])
```

Zu beachten: `current_api_key_if_present` prüft dann bei jeder Anfrage einen mitgeschickten Schlüssel und antwortet bei ungültigem Schlüssel mit 401,
auch auf Routen ohne Anmeldung. Wer das nicht will, liest den Schlüssel in der Abhängigkeit erst, wenn `printer_id` im Pfad steht.

Dazu ein Wächter-Test nach dem Muster von `test_route_auth_coverage.py`, der je Route mit `{printer_id}` einen Aufruf mit beschränktem Schlüssel
gegen einen fremden Drucker macht und 403 erwartet. Offen bleibt danach der Drucker im Anfragekörper (Warteschlange, `fleet/command`); das braucht
eine eigene Prüfung an diesen wenigen Stellen.

**V2 zu T6-04: nur endliche Zahlen.**

```python
distance: float = Query(..., ge=-200, le=200, allow_inf_nan=False)
```

Optional zusätzlich: Bewegungsrouten mit 409 ablehnen, solange `gcode_state` `RUNNING` oder `PAUSE` ist, außer mit ausdrücklichem `force`.

**V3 zu T6-02 und T6-03: eine gemeinsame Bremse und eine Adressprüfung.** Die Zählung aus `mqtt_server.py` in eine kleine Klasse `AuthRateLimiter`
ziehen, die FTP und MQTT desselben VP teilen; bei FTP nach jedem Fehlversuch eine Sekunde warten und bei Sperre mit 421 trennen. In
`_handle_data_connection` und im Proxy-Einmal-Server Verbindungen ablehnen, deren Adresse nicht die der Steuerverbindung ist; den Proxy-Server an
`self.bind_address` statt `0.0.0.0` binden.

**V4 zu T6-05:** Endung vor dem Abruf prüfen und `max_bytes` übergeben (Vorschlag 256 MB); Vorschaubilder aus der schon geladenen Datei
zwischenspeichern statt je Platte neu zu laden.

**V5 zu T6-06:** `allow_redirects=False`, jeden Sprung erneut durch `_sanitize_camera_url` schicken (höchstens drei), Antwort in Stücken lesen
und bei 20 MB abbrechen.

**V6 zu T6-07:** `readexactly(remaining_length)` mit Zeitlimit und einer Obergrenze von 1 MB je Paket.

**V7 zu T6-08:** beide Richtungen gleichzeitig weiterreichen und enden, wenn eine Seite schließt. Die 0,3-Sekunden-Regel durch das Signal des
Steuerkanals ersetzen (der Slicer schickt nach dem Upload weiter Befehle) oder mindestens deutlich verlängern. Das muss mit einem echten Slicer
geprüft werden; der Kommentar im Code beschreibt ein beobachtetes Verhalten von Bambu Studio, das ich nicht nachstellen kann.

## 7. Kennzahlen

| Datei | Funktionen | über 100 Zeilen | Komplexität über 15 | breite `except` | `except: pass` |
|---|---:|---:|---:|---:|---:|
| `api/routes/printers.py` | 86 | 8 | 9 | 11 | 7 |
| `api/routes/camera.py` | 41 | 4 | 3 | 7 | 6 |
| `api/routes/virtual_printers.py` | 10 | 2 | 2 | 5 | 0 |
| `services/external_camera.py` | 24 | 4 | 4 | 7 | 1 |
| `virtual_printer/tcp_proxy.py` | 37 | 5 | 11 | 18 | 31 |
| `virtual_printer/manager.py` | 48 | 5 | 4 | 13 | 9 |
| `virtual_printer/mqtt_server.py` | 29 | 3 | 3 | 8 | 7 |
| `virtual_printer/mqtt_bridge.py` | 19 | 3 | 3 | 9 | 3 |
| `virtual_printer/ftp_server.py` | 30 | 1 | 1 | 5 | 7 |
| `virtual_printer/ssdp_server.py` | 19 | 1 | 2 | 4 | 15 |

## 8. Offen für die Vertiefung (T6b)

- `configure_ams_slot`, `_apply_pa_after_refresh`, `get_printer_status`, `_produce_cover_image` zeilenweise lesen.
- `generate_rtsp_mjpeg_stream` und der Aufräumdienst für ffmpeg-Prozesse (Lecks, Wiederverbindung).
- `SlicerProxyManager`, `_rewrite_mqtt_ip`, SSDP und `VirtualPrinterManager._sync_from_db_locked`.
- `hardware.py` (15 Drucker-Routen) gehört fachlich zu T10 und ist hier nur bei T6-01 mitgezählt.

## 9. Umsetzung (2026-11-11, ungepusht)

| Befund | Was geändert wurde | Wo |
|---|---|---|
| T6-01 | Eine Abhängigkeit an der App prüft bei jeder Anfrage mit API-Schlüssel, ob ein genannter Drucker erlaubt ist: `printer_id` im Pfad oder als Query-Parameter, `printer_id`, `target_printer_id` oder `printer_ids` auf der obersten Ebene eines JSON-Körpers. Sonst 403. Sitzungen ohne Schlüssel und unbeschränkte Schlüssel sind unberührt. | neu `core/printer_scope.py`, `main.py` |
| T6-02 | FTP zählt Fehlversuche je Quell-IP über alle Verbindungen eines VP: nach 5 in 60 s antwortet `PASS` mit 421 und die Verbindung wird getrennt. Ein richtiger Code löscht den Zähler. | neu `virtual_printer/auth_limiter.py`, `ftp_server.py` |
| T6-03 | Datenverbindungen werden nur von der Adresse der Steuerverbindung angenommen, im Servermodus und im Proxy. Eine fremde Verbindung wird geschlossen, ohne den Datenport zu verbrauchen. | `ftp_server.py`, `tcp_proxy.py` |
| T6-04 | `allow_inf_nan=False` an den Weiten von `bed-jog`, `xy-jog`, `extruder-jog` und an `k_value`: `nan` und `inf` ergeben 422. | `routes/printers.py` |
| T6-05 | Die drei Vorschau-Routen laden höchstens 256 MB (sonst 413); die G-Code-Route prüft die Endung vor dem Abruf. `download_file` und `download_file_bytes_async` haben dafür den Parameter `max_bytes` bekommen und brechen beim Überschreiten sofort ab. | `routes/printers.py`, `bambu_ftp.py` |
| T6-06 | Der Kamera-Abruf folgt Weiterleitungen nicht mehr selbst, sondern prüft jedes Ziel wie die erste Adresse (höchstens drei Sprünge). Einzelbilder über 20 MB werden verworfen. | `external_camera.py` |
| T6-08 | Der Datenproxy reicht jetzt auch die Richtung Drucker → Slicer durch (Listen und Downloads kommen an). Der Puffer vor dem Verbindungsaufbau ist auf 8 MB begrenzt. | `tcp_proxy.py` |

Bewusst **nicht** geändert:

- **T6-08, Abschneiden bei Pausen.** Die Regel „0,3 s ohne Daten gilt als Upload-Ende“ bleibt. Sie bildet ein im Code dokumentiertes Verhalten von Bambu
  Studio ab; eine Änderung lässt sich ohne echten Slicer nicht prüfen.
- **T6-03, Bindeadresse des Proxy-Datenports.** Er lauscht weiter auf `0.0.0.0`. Der Code begründet das mit iptables-Umleitungen; die Adressprüfung
  schließt die Lücke auch so.
- **T6-04, Bewegen während des Drucks.** Die Bewegungsrouten prüfen den Druckzustand weiterhin nicht.
- **T6-02, MQTT.** Der MQTT-Server behält seine eigene, gleich aufgebaute Zählung; FTP und MQTT zählen getrennt.

Grenzen der Korrektur zu T6-01: Listen ohne Druckerangabe (`GET /printers`) zeigen einem beschränkten Schlüssel weiter alle Drucker. Drucker, die tiefer
im Anfragekörper stehen (zum Beispiel in einer Liste von Einträgen), und Aufträge ohne festen Drucker („beliebiger Drucker dieses Modells“) werden nicht
geprüft. Die Prüfung sucht den Schlüssel über seinen Präfix und verzichtet auf die teure Hash-Prüfung; ob der Schlüssel gültig ist, entscheidet weiterhin
die Route.

Geprüft: 45 neue Tests (`tests/unit/test_t6_fixes.py`, `tests/integration/test_t6_printer_scope.py`), darunter ein Wächter-Test, der für jede Route mit
`{printer_id}` die App-weite Abhängigkeit verlangt. Zwei Test-Attrappen in `test_external_camera.py` an den neuen Aufruf angepasst.

# PrintLab — Hilfe

Kurzanleitungen zu den Meldungen, die PrintLab selbst anzeigt. Sie ersetzen die früheren Verweise auf ein
externes Wiki.

## Erste Schritte

1. PrintLab starten (`README.md`, Abschnitt „Schnellstart“) und die Einrichtung abschließen.
2. Am Drucker den **LAN-Modus** und den **Developer Mode** einschalten, IP-Adresse, Seriennummer und
   Zugangscode (Access Code) notieren und den Drucker unter „Drucker“ hinzufügen.
3. Im Drucker eine **SD-Karte oder einen USB-Stick** einlegen (siehe nächster Abschnitt).
4. Anmeldung einschalten, bevor die Mechanik (Tür, Plattenwechsler) im Befehlsmodus angeschlossen wird
   (`werkzeuge\admin_passwort_setzen.py`).

## Schritt 4 gesendete Dateien auf externem Speicher speichern

PrintLab liest die geslicte Datei (`.gcode.3mf`) per FTP von der Karte oder dem Stick des Druckers, um
Vorschaubild und Slicer-Daten ins Archiv zu übernehmen. Dafür muss im Slicer (Bambu Studio / OrcaSlicer,
Reiter „Gerät“) die Option **„Gesendete Dateien auf externem Speicher speichern“** eingeschaltet sein.
Ohne Karte oder Stick im Drucker gibt es keinen Ablageort.

## Archiv-Karte hat nur einen Namen

Bei den Modellen der H2-Serie, beim P2S und beim X2D legt die Schaltfläche **Drucken** in Bambu Studio die Datei
immer im **internen Speicher** des Druckers ab. Den kann PrintLab per FTP nicht lesen. Der Druck wird trotzdem
mit Name und Zeit archiviert, aber ohne Vorschaubild und Slicer-Daten.

Für ein vollständiges Archiv:

- den Druck **aus PrintLab starten**, oder
- in **OrcaSlicer** slicen, oder
- in Bambu Studio **Senden** mit Ziel **Extern** wählen und den Druck danach starten.

Alle Wege brauchen eine Karte oder einen Stick im Drucker.

## Druck am Drucker gestartet, kein Vorschaubild

Diese Drucke liefen aus der eigenen Bibliothek des Druckers (erneut drucken am Display, Start über die Handy-App,
früher gesendete Datei). PrintLab liest nur Karte oder Stick per FTP; die Bibliothek des Druckers liegt in einem
Bereich, den FTP nicht erreicht. Es gibt deshalb keine 3MF zum Lesen, und keine Slicer-Einstellung ändert das.
Der Druck wird mit Name und Zeit archiviert; unter „Archiv bearbeiten“ lässt sich das verbrauchte Filament von
Hand eintragen. Für ein vollständiges Archiv den Druck aus PrintLab oder aus dem Slicer starten.

## FTPS TLS Fehler

PrintLab hat den Dateiübertragungs-Port des Druckers (FTPS, Port 990) geöffnet, und der Drucker hat mit etwas
geantwortet, das kein TLS ist. Es konnte nichts gelesen werden. Das ist keine Slicer-Einstellung und nichts, was du
geändert hast; ein betroffener Drucker funktioniert meist später von selbst wieder. Nach einem solchen Fehler
pausiert PrintLab die Übertragungen zu diesem Drucker fünf Minuten und holt die Datei danach nach.

Hilft das nicht: auf der Seite „System“ das Debug-Protokoll einschalten und ein Support-Paket erstellen.

## FTP Uebertragung Zeitueberschreitung

Die Datei lag auf der Karte und der Drucker hat sie ausgeliefert, aber die Übertragung wurde in der erlaubten
Zeit nicht fertig. Beim Druckstart bedient der Drucker gleichzeitig Kamera, Statusmeldungen und den Auftrags-Upload;
große 3MF-Dateien schaffen das nicht immer. PrintLab versucht es in den folgenden zehn Minuten dreimal erneut.
Bleibt die Karte leer, die **Verbindungs-Zeitüberschreitung** unter Einstellungen → Netzwerk → FTP-Wiederholung erhöhen.

## Virtueller Drucker

Der virtuelle Drucker braucht zusätzliche Systemeinstellungen: Port-Weiterleitung, Firewall-Regeln und
plattformspezifische Einstellungen (unter Linux z. B. Host-Netzwerk beim Docker-Container). Der Container muss
mit `network_mode: host` laufen, damit Drucker-Erkennung und virtueller Drucker funktionieren. Danach den
Slicer auf den virtuellen Drucker senden; die Datei landet in der Warteschlange.

## Ankuendigungen

Ankündigungen sind Meldungen aus einem Feed, den du selbst einrichtest. Standardmäßig ist keiner eingetragen, es
werden also keine Daten abgerufen. Mit der Umgebungsvariable `ANNOUNCEMENTS_FEED_URL` lässt sich ein Feed
festlegen; in den Einstellungen kann die Anzeige jederzeit abgeschaltet werden.

## Fehlerbehebung allgemein

- **Drucker bleibt offline:** IP-Adresse, Seriennummer und Zugangscode prüfen (der Code ändert sich bei jedem
  Wechsel des Betriebsmodus), LAN-Modus und Developer Mode kontrollieren, nur **ein** Client darf gleichzeitig
  mit dem Drucker sprechen (ein weiterer Monitor oder Bambu Handy kann stören).
- **Kamera zeigt nichts:** RTSP-Port 322 des Druckers muss vom PrintLab-Rechner erreichbar sein; ffmpeg muss
  installiert sein.
- **Etwas anderes:** auf der Seite „System“ die Gesundheitsprüfung öffnen; sie wertet das Protokoll aus und nennt
  bekannte Ursachen.

## Update-Pruefung zeigt keine neue Version

Bei einem **privaten Repo** antwortet GitHub der Update-Pruefung ohne Token mit
„keine Releases“ (404), obwohl Releases existieren. Loesung: der Umgebungsvariable
`PRINTLAB_GITHUB_TOKEN` ein GitHub-Zugangstoken mitgeben, bevor PrintLab startet.
Mit `starte_printlab.bat` geschieht das automatisch aus der `gh`-Anmeldung; manuell:

```powershell
$env:PRINTLAB_GITHUB_TOKEN = (gh auth token)
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
```

Der Token wird nur an `api.github.com` geschickt und nicht protokolliert. Ein
authentifizierter Aufruf hat zudem ein hoeheres Limit (5000 statt 60 Anfragen je Stunde).
Nach einem PrintLab-Update muss die Instanz ohnehin neu gestartet werden, damit die neue
Versionsnummer angezeigt wird.

## Angebote mit Briefkopf und PDF

Im Angebotskalkulator: **Firmendaten** eintragen (Name, Anschrift, Bankverbindung, Umsatzsteuer, Gültigkeit, Präfix der
Angebotsnummer). Beim Speichern eines Angebots vergibt PrintLab eine fortlaufende Nummer (`A-2026-0001`); in
**Verlauf** erzeugt „PDF“ das Angebot mit dem Briefkopf (Sprache der Oberfläche: Deutsch oder Englisch). Bei 0 %
Umsatzsteuer steht der Hinweistext aus den Firmendaten im Angebot (zum Beispiel zur Kleinunternehmerregelung).

## Update ist schiefgegangen

PrintLab sichert vor jedem Update Datenbank und Einstellungen (Ordner `update-backups` im Datenordner) und baut
selbstständig zurück, wenn die neue Version nicht stabil startet; „Einstellungen → System“ zeigt dann einen Hinweis.
Von Hand zurück: die Dateien aus dem neuesten Ordner in `update-backups` in den Datenordner kopieren (PrintLab vorher
beenden) und im Programmordner `git reset --hard <alter Stand>` ausführen.

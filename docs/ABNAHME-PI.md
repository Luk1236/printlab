# Abnahme am Pi — Checkliste in Reihenfolge

Diese Liste arbeitet **eine Sitzung am Gerät** ab, in dieser Reihenfolge:

1. **Update** auf 1.22.0 — erst danach sind die neuen Funktionen da, auf die sich die übrigen Punkte beziehen.
2. **Slicer und Druckweg** — der Weg Modell → Slice → Druck, samt Meldung, wenn der Slicer fehlt.
3. **Angebots-Link** — reine Software, kein Risiko für Mechanik oder Druckbetrieb, geht auch vom Schreibtisch und Handy.
4. **Hardware** — vom Trockenlauf bis zur ersten echten Bewegung, aufsteigend im Risiko.

Richtwerte: Update 20 Minuten, Slicer 10 Minuten, Angebots-Link 20 Minuten, Hardware 60–90 Minuten. Was die Liste nicht
abdeckt (E-Rechnung, KI-Fehlerhilfe, Sicherung, HTTPS), steht in [`ABNAHME.md`](ABNAHME.md).

**Regeln für die ganze Sitzung**

- Am **Betriebs-Pi** nur tun, was sich zurücknehmen lässt. Die Sicherung läuft vor dem Update automatisch; bei Hardware
  gilt „Hand am Netzstecker“.
- Nach jedem Block: Ergebnis ins Protokoll am Ende eintragen. Ein „nicht geprüft“ ist ein Ergebnis, ein Häkchen ohne
  Beobachtung nicht.
- **Abbruchkriterien** stehen bei jedem Block. Wenn eines eintritt: anhalten, notieren, nicht „schnell noch mal“ probieren.

---

## 0. Vorbereitung (10 Minuten)

- [ ] Uhrzeit und Datum am Pi stimmen (`date`) — Signaturprüfung und Link-Ablauf hängen daran.
- [ ] Aktuelle Version notieren: **Einstellungen → Aktualisierungen** („Aktuelle Version“) oder
      `curl -s localhost:8000/api/v1/updates/version`.
- [ ] Zustand aufnehmen: Wartung → **System & Betrieb** → „Zustand des Geräts“ (Temperatur, Drosselung, freier Speicher, SD-Karte).
- [ ] Automatischen Check laufen lassen und Ausgabe aufheben:
      `cd ~/printlab && .venv/bin/python werkzeuge/abnahme.py`
      Erwartung: keine **FAIL**-Zeile. WARN-Zeilen sind erlaubt, aber notieren.
- [ ] Sicherung von heute vorhanden (Wartung → Zustand, oder `systemctl --user start printlab-backup.service`, dann Eintrag prüfen).
- [ ] Testmittel bereit: Handy **mit mobilen Daten** (nicht im Heim-WLAN) für den Angebots-Link, PC für den Gegentest.
- [ ] Für die Hardware: Kreuzschlitz, Kabelbinder, ein Stück Pappe als „Platte“ für den Trockenlauf, niemand sonst im Raum.

---

## 1. Update auf 1.22.0 (20 Minuten)

Ziel: der Pi läuft auf 1.22.0, und du weißt, dass der Weg zurück funktioniert, bevor irgendetwas anderes passiert.

- [ ] **Einstellungen → Aktualisierungen → „Jetzt prüfen“** drücken.
      Erwartung: „Update verfügbar: v1.22.0“ (oder neuer), darunter „Versionshinweise“.
- [ ] **„Update installieren“** drücken. Die Seite lädt nach dem Neustart selbst neu; falls nicht, von Hand neu laden.
- [ ] Version gegenprüfen: unter **Einstellungen → Aktualisierungen** steht bei „Aktuelle Version“ **1.22.0**
      (die Oberfläche zeigt die Version nur dort an).
- [ ] `journalctl --user -u printlab -n 40` — Erwartung: Start ohne Traceback, kein „Application startup failed“.
- [ ] Automatischen Check wiederholen (`werkzeuge/abnahme.py`): gleiche oder bessere Einstufung als in Schritt 0.
- [ ] Stichprobe der neuen Stellen: Wartung → **Hardware & Optik** zeigt „Einmess-Assistent Plattenwechsel“,
      „Automatische Umverteilung“, „Nachbestellvorschlag“ und „Zeitraffer-Aufbewahrung“; Finanzen → Verlauf zeigt je
      Angebot den Knopf **„Teilen“**.

**Abbruch:** Wird kein Update angeboten, obwohl 1.18.0 veröffentlicht ist → `data/update_allowed_signers` auf dem Pi prüfen
(siehe [`UPDATE-SIGNATUR.md`](UPDATE-SIGNATUR.md)); fehlt die Datei, wird nicht signiert geprüft, das ist kein Fehler, aber
dann bitte bewusst entscheiden. Schlägt der Start fehl: nach dem vierten erfolglosen Start greift der Rückbau auf den alten
Stand samt Datenbank — Dienst neu starten und Log sichern, nicht von Hand Dateien tauschen.

**Nicht Teil dieses Blocks:** ein Update, das absichtlich nicht startet, um den Rückbau zu provozieren. Das gehört auf eine
Testkopie, nicht auf den Betriebs-Pi.

---

## 1b. Slicer und Druckweg (10 Minuten)

Ziel: Der PC-Slicer ist vom Pi aus erreichbar, und nach dem Slicen führt ein Knopf direkt zum Druck — ohne den Umweg über
die Bibliothek. Das ruhigste Testmodell ist ein kleines Teil, das du notfalls wirklich drucken kannst.

**Voraussetzungen**

- [ ] Slicer-Sidecar läuft auf dem PC (Bambu Studio oder OrcaSlicer mit geöffnetem Port), PC und Pi im selben Netz oder über
      Tailscale erreichbar — **nicht** `localhost` als Adresse eintragen: das zeigt auf den Pi selbst.
- [ ] Unter **Einstellungen → Slicer** ist „Slicer-API verwenden“ an und die Adresse des PCs eingetragen, z. B.
      `http://192.168.1.50:3001`.
- [ ] In einem zweiten Browsertab die Oberfläche geöffnet, damit ein Neuladen nichts unterbricht.

**Ablauf**

- [ ] **Einstellungen → Slicer → „Verbindung prüfen“** drücken.
      Erwartung: „Sidecar erreichbar.“ mit Version, darunter die tatsächlich benutzte Adresse. Kommt stattdessen eine rote
      Meldung, steht dort die Adresse und der Grund (z. B. „All connection attempts failed“).
- [ ] **Gegenprobe:** Adresse absichtlich auf `http://localhost:3001` ändern, speichern, erneut prüfen.
      Erwartung: nicht erreichbar, und die Meldung nennt `localhost` — genau der Fehler, den die Prüfung sichtbar machen soll.
- [ ] Adresse zurückstellen und erneut prüfen. Jetzt muss die Kopfzeile ruhig bleiben: bei erreichbarem Sidecar erscheint
      **kein** gelber Hinweis. Bei nicht erreichbarem Sidecar steht auf jeder Seite „Der Slicer ist nicht erreichbar (…)“
      mit einem Link zu den Slicer-Einstellungen.
- [ ] Eine `.3mf`-Datei (noch **nicht** geslict) aus dem Dateimanager auf die Karte eines Druckers ziehen.
      Erwartung: Die Datei wird hochgeladen und der Slicedialog öffnet sich — nicht die Meldung „Nur .gcode …“.
- [ ] Presets prüfen (Drucker, Prozess, Filament), **„Slicen“** drücken, Dialog schließen.
      Erwartung: Fortschrittsmeldung unten rechts; nach dem Fertigstellen eine grüne Meldung mit dem Dateinamen und dem
      Knopf **„Jetzt drucken“**.
- [ ] **„Jetzt drucken“** drücken.
      Erwartung: Der normale Druckdialog öffnet sich mit dem geslicten `.gcode.3mf`, Druckerauswahl, AMS-Zuordnung und
      Zeitplan. Für die Abnahme reicht, den Dialog einmal zu prüfen und mit **Abbrechen** zu schließen (oder das kleine
      Teil wirklich zu drucken).
- [ ] **Push bei Fehlschlag:** In **Einstellungen → Benachrichtigungen** die Browser-Meldungen für diesen Browser
      einschalten und „Testmeldung“ bestätigen. Dann die Slicer-Adresse auf eine falsche IP stellen, slicen, Browser-Tab
      schließen.
      Erwartung: Kurz darauf kommt eine Browser-Meldung „Slicen fehlgeschlagen: Der Slicer ist nicht erreichbar (…)“;
      ein Klick öffnet die Einstellungen. Adresse danach zurückstellen.
- [ ] `journalctl --user -u printlab -n 40` — Erwartung: kein Traceback, kein „Unhandled exception“.

**Abbruch:** Der Slicedialog bietet „Slicen“ an, obwohl die Verbindungsprüfung rot ist → nicht slicen, Befund notieren.
Öffnet „Jetzt drucken“ einen Dialog ohne Datei oder mit falschem Drucker → nicht absenden, Datei im Dateimanager prüfen.
Eine Push-Meldung, die trotz falscher Adresse ausbleibt, ist ein Befund (dann Benachrichtigungsstatus im selben Dialog
prüfen), aber kein Grund, den restlichen Ablauf abzubrechen.

---

## 2. Angebots-Link mit Zusage (20 Minuten)

Ziel: ein Kunde kann ein Angebot ohne Anmeldung öffnen und einmalig zusagen — und du siehst die Antwort im Verlauf.

**Voraussetzungen**

- [ ] Firmendaten vollständig: Finanzen → Angebotskalkulator → Firmenprofil (Name, Anschrift, E-Mail, Steuernummer/USt-IdNr.,
      Umsatzsteuerhinweis). Ohne diese Angaben ist der Link zwar gültig, wirkt aber unfertig.
- [ ] Externe Adresse gesetzt: Einstellungen → **Netzwerk → Externe URL** (z. B. `https://printlab.…ts.net`). Fehlt sie,
      entsteht ein relativer Pfad, den das Handy nicht öffnen kann.
- [ ] Testangebot mit **zwei Positionen** anlegen und speichern (kein echtes Kundenangebot, sondern z. B. „Test Teil A/B“).

**Ablauf**

- [ ] Im Verlauf beim Testangebot **„Teilen“** drücken.
      Erwartung: Toast „Link erstellt und kopiert — 14 Tage gültig.“, daneben der Status **„offen“**, darunter der Link und
      „Link endet mit …“.
- [ ] Link am PC **in einem privaten Fenster ohne Anmeldung** öffnen.
      Erwartung: Seite mit Firmenname, Angebotsnummer, Datum, Gültigkeit, Kunde, Positionen, Gesamtpreis, Umsatzsteuerhinweis.
- [ ] Inhalt prüfen: **keine** internen Zahlen (Material, Energie, Arbeitszeit, Aufschlag) sichtbar; Mengen, Einzelpreise und
      Summen stimmen mit dem Angebot überein; Umlaute korrekt.
- [ ] Denselben Link auf dem **Handy über mobile Daten** öffnen.
      Erwartung: lesbar ohne Zoomen, Tabelle bricht nicht aus dem Bild, Formular „Passt das Angebot so für Sie?“ mit
      **Annehmen**/**Ablehnen** und Feld „Anmerkung (optional)“.
- [ ] **Annehmen** mit Anmerkung „Abnahmetest“ drücken.
      Erwartung: dieselbe Seite zeigt „Angenommen — <Datum Uhrzeit>“ und die Anmerkung; kein Formular mehr.
- [ ] Seite neu laden: die Antwort bleibt stehen (kein zweites Absenden, keine Umkehr).
- [ ] In PrintLab Verlauf neu laden: Status **„zugesagt“**, Tooltip mit dem Antwortdatum.
- [ ] **Zurückziehen testen:** zweites Testangebot teilen, „zurückziehen“ drücken, diesen Link öffnen.
      Erwartung: „Dieser Link wurde zurückgezogen.“
- [ ] **Ersetzen testen:** für dasselbe Angebot erneut „Teilen“ → der erste Link muss jetzt „zurückgezogen“ melden, der neue
      funktioniert.
- [ ] **Unbekannter Link:** eine Ziffer im Link ändern → „Dieser Link ist unbekannt.“

**Abbruch:** Zeigt die Seite interne Kalkulation, oder lässt sich eine Antwort zweimal abgeben bzw. nachträglich umdrehen →
sofort notieren und den Link zurückziehen; das ist ein Fehler, kein Bedienfehler. Den Ablauf nach 14 Tagen nicht am Gerät
abwarten; wenn du die Grenze prüfen willst, erzeuge den Link mit kurzer Gültigkeit über die Schnittstelle
(`POST /api/v1/quote/history/<id>/share` mit `{"days": 1}`) — die Oberfläche nutzt fest 14 Tage.

---

## 3. Hardware (60–90 Minuten)

**Nur weitergehen, wenn der vorige Schritt ohne Befund war.** Die Reihenfolge ist bewusst: erst Software im Trockenlauf,
dann Positionen, dann eine einzelne Bewegung, dann die Automatik.

### 3.1 Trockenlauf ohne Mechanik (15 Minuten)

- [ ] Wartung → **Hardware & Optik** → „Hardware & Magazin“: Drucker wählen, Modus auf **„Simulieren“** stellen und speichern.
- [ ] Magazin: Status je Fach durchklicken (bereit → benutzt → leer → belegt) und Etiketten setzen.
      Erwartung: Änderung bleibt nach Neuladen erhalten, keine Teilwirkung (entweder ganz oder gar nicht).
- [ ] „Tür öffnen“, „Tür schließen“ im Simulationsmodus.
      Erwartung: Erfolgsmeldung, Zustand wechselt, Eintrag im **Protokoll** darunter.
- [ ] **Not-Halt** drücken. Erwartung: „Not-Halt aktiv — Sperre aufheben, um fortzufahren.“, weitere Aktionen werden abgewiesen.
- [ ] **„Sperre aufheben“**. Erwartung: Aktionen wieder möglich, Protokolleintrag „Not-Halt aufgehoben“.
- [ ] Modus zurück auf **„Befehle“** stellen, sobald die echten Befehle eingetragen sind (nicht vorher).

### 3.2 Positionen einmessen (25 Minuten)

Am Gerät, Gestänge noch **abgekoppelt**, Hand am Netzstecker.

- [ ] Wartung → Hardware & Optik → **„Einmess-Assistent Plattenwechsel“**, Drucker wählen.
      Erwartung: „Fortschritt: 0/5 Pflichtschritte · noch nicht begonnen“.
- [ ] **Referenzpunkt**: Achsen von Hand auf den Referenzpunkt fahren, X/Y/Z eintragen, „Schritt speichern“.
- [ ] **Aufnahmeposition** und **Ablageposition** genauso aufnehmen und speichern.
- [ ] **Übergabe Magazin (optional)**: nur ausfüllen, wenn die Mechanik eine eigene Übergabeposition hat.
- [ ] **Tür und Endschalter**: Tür von Hand öffnen und schließen; Häkchen „Tür öffnet und schließt, Ablauf geprüft“ **und**
      „Endschalter meldet den Türzustand“ setzen, speichern.
- [ ] **Probelauf ohne Platte**: Ablauf einmal von Hand durchfahren, Häkchen setzen, speichern.
      Erwartung: Fortschritt 5/5, keine Positionswarnung. Kommt „… liegen auf derselben Position — bitte prüfen.“,
      sind zwei Punkte versehentlich gleich eingetragen.
- [ ] „Eingemessen von“ mit Namen füllen und **„Abschließen“** drücken.
      Erwartung: „abgeschlossen von <Name> am <Datum>“, Felder werden schreibgeschützt.

**Abbruch:** Lässt sich eine Position nicht sauber anfahren, oder meldet der Endschalter den Zustand nicht zuverlässig →
Assistent **nicht** abschließen. Ein begonnener Assistent sperrt den Plattenwechsel (siehe 3.3) — das ist gewollt und
verhindert, dass mit halben Werten gefahren wird. „Zurücksetzen“ verwirft die Eingaben.

### 3.3 Sperre prüfen (5 Minuten)

- [ ] Bei **begonnenem, nicht abgeschlossenem** Assistenten (z. B. vor dem Abschließen einmal testen): „Plattenwechsel“
      drücken. Erwartung: abgelehnt mit „Einmess-Assistent für den Plattenwechsel ist begonnen, aber nicht abgeschlossen.“
      Auch die Automatik darf in diesem Zustand nicht starten.
- [ ] Nach dem Abschließen: Sperre weg, Wechsel wieder anstoßbar (noch nicht ausführen, erst 3.4).
- [ ] „Wechsel geprüft“ erscheint nur, wenn ein Wechsel unvollständig ist; „Wechsel abbrechen“ ist während eines
      laufenden Wechsels und in der Wartezeit der Automatik nutzbar.

### 3.4 Erster einzelner Plattenwechsel (15 Minuten)

- [ ] Magazin mit einer **entbehrlichen** Platte bestücken, Status im Magazin auf „bereit“.
- [ ] Sicherheitslage: Not-Halt-Schalter in Reichweite und **vorher einmal betätigt** (er muss den Motorstrom trennen,
      unabhängig von der Software).
- [ ] Einmal **„Plattenwechsel“** von Hand auslösen und den Ablauf beobachten.
      Erwartung: Tür öffnet, Aufnahme fährt die eingemessenen Koordinaten an, Platte landet in der Ablage, Tür schließt,
      Protokolleintrag „Plattenwechsel“ mit Erfolg.
- [ ] Danach Magazinstand prüfen: benutzte Platte ist „benutzt“, die nächste „bereit“.
- [ ] Absichtlich einen Fehler provozieren (z. B. Tür von Hand festhalten oder Endschalter abdecken) und den Wechsel
      erneut starten. Erwartung: Abbruch mit klarer Meldung, **kein** „offen“ ohne Bestätigung des Schalters, Zustand
      „unvollständig“ mit „Wechsel geprüft“ zum Quittieren.

**Abbruch:** unerwartete Bewegung, Geräusch, Kollision → **Not-Halt**, Netzstecker, nichts wiederholen, bevor die Ursache
klar ist. Koordinaten dann im Assistenten korrigieren (Zurücksetzen und neu einmessen, nicht „grob nachziehen“).

### 3.5 Automatik (15 Minuten)

- [ ] Wartung → Hardware & Optik → „Wartungsprogramme“ → **„Automatik einschalten“** für diesen Drucker.
- [ ] Optional „nur bei wartendem Auftrag“ aktivieren — Standard ist aus; für den Test erst **aus** lassen.
- [ ] Einen kurzen Druck starten und bis zum Ende laufen lassen (oder einen Wartungsdruck nutzen).
      Erwartung nach Druckende: wartet auf Abkühlung, liest die Tür (mit hinterlegtem `door_status_command` frisch am
      Endschalter), wechselt die Platte, Meldung im Verlauf; bei knappem Magazin kommt vorher eine Warnung.
- [ ] Während der Wartezeit **„Wechsel abbrechen“** drücken. Erwartung: Automatik endet sauber, kein halber Wechsel,
      Protokolleintrag.
- [ ] Zum Schluss die Automatik wieder **ausschalten**, solange die Mechanik nicht im Alltag erprobt ist.
- [ ] `journalctl --user -u printlab -n 60` auf Warnungen zum Wechsel prüfen (Temperatur unbekannt, Tür ohne Endschalter).

**Abbruch:** Wechsel startet bei unbekannter Betttemperatur, oder die Automatik läuft trotz Abbruch weiter → sofort
Automatik aus, Not-Halt bereit halten, Befund notieren.

---

## 4. Nachbereitung (10 Minuten)

- [ ] Testangebote aus dem Verlauf löschen, offene Links zurückziehen.
- [ ] Automatik aus, Modus steht auf „Befehle“ (oder bewusst auf „Simulieren“, wenn noch nicht verdrahtet).
- [ ] Einmessung **nicht** zurücksetzen — sie ist der Beleg für 3.2 und die Grundlage der Bewegung.
- [ ] Ergebnis in [`TODO.md`](../TODO.md) abhaken und Auffälligkeiten in [`ABNAHME.md`](ABNAHME.md) ergänzen.
- [ ] Wenn alles grün ist: kurze Notiz im `CHANGELOG.md` unter der nächsten Version („am Gerät abgenommen am …“).

---

## 5. Protokoll

| Block | Datum | Wer | Ergebnis (ok / Befund) | Bemerkung |
|---|---|---|---|---|
| 0 Vorbereitung | | | | |
| 1 Update auf 1.22.0 | | | | |
| 1b Slicer und Druckweg | | | | |
| 2 Angebots-Link | | | | |
| 3.1 Trockenlauf | | | | |
| 3.2 Einmessen | | | | |
| 3.3 Sperre | | | | |
| 3.4 Einzelwechsel | | | | |
| 3.5 Automatik | | | | |

## 6. Wenn etwas schiefgeht

- **Bewegung unerwartet:** Not-Halt (Hardware), Netzstecker, danach in PrintLab „Not-Halt“ und „Sperre aufheben“, damit der
  Zustand wieder bekannt ist. Ursache notieren, bevor du neu startest.
- **Update startet nicht mehr:** Dienst neu starten (`systemctl --user restart printlab`); nach dem vierten Fehlstart greift
  der Rückbau. Log mit `journalctl --user -u printlab -n 200` sichern.
- **Link zeigt Interna:** Link sofort zurückziehen, Angebot prüfen, Befund melden — die Seite darf nur die Kundenansicht
  zeigen.
- **Zweifel an einer Einstellung:** lieber ausschalten und notieren. Alle neuen Funktionen sind standardmäßig aus; ein
  „aus“ ist kein Rückschritt.

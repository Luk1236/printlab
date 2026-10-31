# Lokale KI einrichten (Ollama)

PrintLab bringt kein Modell mit. Es spricht mit einem lokalen Modell-Server, der die
OpenAI-kompatible Schnittstelle anbietet — in der Regel **Ollama** auf demselben Gerät.
Zwei Rollen sind zu unterscheiden:

| Rolle | Modell | Kann Bilder? |
|---|---|---|
| **Assistent** (Fragen zur Werkstatt, Systemprüfung) | `qwen2.5:3b` | nein, nur Text |
| **KI-Fehlererkennung** (Fehlerhilfe) | `qwen2.5vl:3b` | **ja** |

> **Wichtig:** `qwen2.5:3b` ist ein Textmodell. Es kann Kamerabilder nicht ansehen. Für die
> Fehlerhilfe braucht es ein Vision-Modell, z. B. `qwen2.5vl:3b`.

## 1. Ollama installieren

**Raspberry Pi / Linux:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
```

**Windows:** Installer von https://ollama.com/download herunterladen.

Prüfen:

```bash
ollama --version
curl -s http://127.0.0.1:11434/api/tags
```

## 2. Modelle laden

```bash
# Assistent (Text)
ollama pull qwen2.5:3b

# Fehlererkennung (Bild/Video-Standbild) – das ist das Modell mit Sehen
ollama pull qwen2.5vl:3b
```

Alternativen für die Bildprüfung: `llava:7b`, `moondream`, `qwen3.5:4b`. Auf einem Pi 4/5
ist ein 3B-Vision-Modell die vernünftige Obergrenze; größere Modelle brauchen deutlich
länger pro Bild.

Prüfen, welche Modelle da sind:

```bash
ollama list
```

## 3. In PrintLab eintragen

**Assistent:** Wartung → Assistent

- Adresse: `http://127.0.0.1:11434` (Standard)
- Modell: `qwen2.5:3b`
- Assistent einschalten, speichern. Unter der Karte erscheint, ob Server und Modell
  gefunden wurden.

**Fehlererkennung:** Fehlerhilfe → KI-Fehlererkennung (lokal)

- **Bildmodell:** `qwen2.5vl:3b` (leer lassen würde das Assistenten-Modell nehmen — das
  kann aber keine Bilder)
- **Mindest-Sicherheit:** 60 % ist ein guter Anfang
- Erkennung einschalten (der Schalter gilt für die automatische Prüfung nach Warnungen)
- Speichern

## 4. Testen

1. Ein Bild eines Drucks hochladen (oder ein gesammeltes Fehlerbild auswählen).
2. **Analysieren** drücken. Das Modell antwortet mit Fehlerbild, Sicherheit und Begründung.
3. Über die Daumen an der Trefferzeile festhalten, ob die Erkennung stimmt. Die Summe
   steht oben in der Karte.

Ein Software-Screenshot ergibt korrekt „kein Fehlerbild“ — das ist ein guter erster
Funktionstest, ohne dass ein Druck laufen muss.

**Dauer:** Das erste Bild lädt das Modell in den Speicher und kann mehrere Minuten dauern.
Danach liegt die Prüfung je nach Gerät bei etwa 1–3 Minuten pro Bild. Der Fortschritt der
Stapelprüfung steht in der Karte; bereits geprüfte Bilder werden übersprungen.

## 5. Automatik

Standardmäßig ist die automatische Prüfung **aus**. Wenn du sie einschaltest, prüft
PrintLab nach AI- und „Platte nicht frei“-Warnungen das Kamerabild im Hintergrund. Die
Erkennung ist ein Hinweis, keine Diagnose — erst mit eigenen Bildern gegenprüfen, dann
einschalten. Die Systemprüfung (Wartung → System) meldet, ob Server und Bildmodell bereit
sind, und nennt die Dauer der letzten Prüfung.

## 6. Laufende Überwachung während des Drucks (lokal)

Damit brauchst du Obico nicht: PrintLab holt im eingestellten Abstand selbst ein
Kamerabild, prüft es mit dem lokalen Bildmodell und handelt erst, wenn **dasselbe
Fehlerbild mehrfach hintereinander** erkannt wurde. Einstellungen in der Fehlerhilfe
unter „Laufende Überwachung (lokal)“:

| Einstellung | Bedeutung |
|---|---|
| Überwachung einschalten | Standard aus |
| Abstand | Minuten zwischen zwei Bildern (mindestens 2) |
| Treffer in Folge | Wie oft dasselbe Fehlerbild bestätigt werden muss (Standard 2) |
| Bilder je Prüfung | Aufnahmen pro Runde (1–3, Standard 2); entschieden wird nach Mehrheit |
| Pause zwischen Meldungen | Ruhezeit nach einer Meldung (Standard 30 Minuten) |
| Aktion | „Nur melden“ oder „Pausieren und melden“ |
| Schwellen je Fehlerbild | Eigene Mindest-Sicherheit je Fehlerbild; leer = allgemeiner Wert |

Damit das Modell nicht bei jeder Runde neu geladen wird, hält PrintLab es bei Ollama
30 Minuten im Speicher (`keep_alive`). Der erste Aufruf nach einem Neustart dauert
trotzdem länger.

Ablauf bei einem Treffer: Bild wird in der Fehlerbild-Sammlung abgelegt, ein Treffer für
die Fehlerhilfe festgehalten (zählt in „N× erkannt“), eine Meldung über die Kanäle
geschickt und bei „Pausieren“ der Druck angehalten. „Jetzt prüfen“ macht eine Runde
sofort — das dauert je nach Gerät ein bis drei Minuten pro Drucker.

Grenzen: Das lokale Modell ist deutlich langsamer als Obicos ML-API; deshalb ist der
Abstand großzügig und die Bestätigung über mehrere Bilder Pflicht. Es startet nie einen
Druck und bricht keinen ab. Obico bleibt als separate, schnellere Option erhalten.

## Fehlersuche

| Meldung | Ursache / Abhilfe |
|---|---|
| „Kein Modell-Server … erreichbar“ | Ollama läuft nicht: `sudo systemctl start ollama`, Adresse prüfen |
| „Bildmodell … fehlt“ | `ollama pull <modell>`; Name exakt wie in `ollama list` |
| „nur intern gedacht und keine Antwort“ | Denkmodell ohne Bildantwort — ein Vision-Modell wie `qwen2.5vl:3b` nehmen |
| Antwort dauert sehr lange | Modell zu groß für das Gerät; kleineres Vision-Modell laden |
| Abbruch nach Minuten | Zeitgrenze des Assistenten erhöhen (Wartung → Assistent) |

## Datenschutz

Die Bilder verlassen das Gerät nicht: Ollama läuft lokal, PrintLab schickt das Bild nur an
den eingestellten Modell-Server. Treffer und Rückmeldungen liegen in
`data/ai_error_findings.jsonl` bzw. `data/ai_error_feedback.jsonl`; die Rohbilder in
`data/failure_images/` (90 Tage, höchstens 500).

# Übersetzungs-Glossar und Satzvorlagen

Für die Gegenleser der 13 Nebensprachen. Ziel ist nicht „wörtlich richtig", sondern **dieselbe
Bedeutung in derselben Kürze**: Die Texte stehen in Karten, Popovern und Tabellen, wo zwei
zusätzliche Wörter ein Layout umbrechen.

## Was übersetzt wird

| Ort | Inhalt | Quelle |
|---|---|---|
| `frontend/src/i18n/locales/<sprache>.ts` | Oberflächentexte, u. a. `errorHelp.*` | englische Referenz in `en.ts` |
| `backend/app/services/error_patterns.py` | 12 Fehlerbilder: `title`, `summary`, `causes`, `slicer`, `automation` | deutsche Fließtexte (maßgeblich), englische Kurzfassung als Hilfe |
| `backend/app/services/countermeasures.py` | Titel der beiden Bauraum-Regeln | `RULES` |

Die Fehlerbilder sind **zweisprachig hinterlegt** (deutsch und englisch). Eine weitere Sprache
braucht zuerst eine Entscheidung: entweder eigene Felder je Sprache oder eine Übersetzungstabelle
im Frontend. Bis dahin bleiben die deutschen Fließtexte stehen — die englischen Titel und
Kurzfassungen sind der Anhaltspunkt für Gegenleser.

## Glossar (verbindlich)

| Deutsch | Englisch | Hinweis für die Zielsprache |
|---|---|---|
| Bauraum | chamber | nicht „build room"; der umschlossene Raum um das Bett |
| Bauraumtemperatur | chamber temperature | |
| Düse | nozzle | |
| Düsenverstopfung | clog / clogging | |
| Heatbreak | heatbreak | Lehnwort, nicht übersetzen |
| Heat Creep | heat creep | Lehnwort, kleingeschrieben |
| Hotend | hotend | Lehnwort |
| Extruderzahnrad | extruder gear | |
| Vorschub | extrusion / feed | je nach Satz „extrusion" (Materialfluss) oder „feed" (Mechanik) |
| Unterextrusion | under-extrusion | |
| Überextrusion | over-extrusion | |
| Fluss | flow | |
| Rückzug | retraction | |
| Leerfahrt | travel move | |
| Deckschicht | top layer | |
| Wandbindung | wall adhesion | |
| Warping | warping | Lehnwort |
| Delamination | delamination | |
| Rissbildung | cracking | |
| Fadenziehen | stringing | |
| Schichthaftung | layer adhesion | |
| K-Faktor / Pressure Advance | pressure advance (K factor) | Zahl bleibt Zahl |
| Trockenlauf | dry run | „nur protokollieren" |
| Gegenmaßnahme | countermeasure | |
| Warteschlange | print queue | |
| Auftrag | job | nicht „order" (das ist ein Angebot) |
| Drucker | printer | |
| Betttemperatur | bed temperature | |
| Kammerlüfter | chamber fan | |
| Zusatzlüfter | auxiliary fan | |
| Abluft | exhaust | |
| Schicht | layer | |
| Endschalter | limit switch | |
| Plattenwechsel | plate change | |

## Satzvorlagen

Die zwölf Fehlerbilder folgen drei Mustern. Wer neu formuliert, bleibt bei ihnen:

1. **Titel:** Substantiv + optionaler Zusatz, keine Satzform.
   - `Heat Creep & Düsenverstopfung` → `Heat creep & clogging`
   - `Warping & Randablösung` → `Warping & edge lifting`
2. **Kurzfassung:** ein Satz, Ursache → Wirkung, höchstens 18 Wörter, kein „Sie".
   - Vorlage: *„<Ursache>; <was am Druck sichtbar wird>."*
   - Beispiel: *„Filament softens in the heatbreak before reaching the melt zone; extrusion stops mid-print."*
3. **Maßnahme:** Imperativ oder Nominalstil, ein Schritt je Zeile, Zahlen mit Einheit.
   - `Bauraumtemperatur überwachen; bei PLA über 38–40 °C Kammerlüfter auf 100 % schalten`
   - `Monitor chamber temperature; above 38–40 °C on PLA, run the chamber fan at 100 %`

Platzhalter in der Oberfläche sind `{{name}}` und müssen **unverändert** übernommen werden.
Zahlen, Einheiten und Gradzeichen bleiben wie in der Quelle (`38–40 °C`, nicht `38-40 C`).

## Ablauf für Gegenleser

1. Datei der Sprache öffnen, z. B. `frontend/src/i18n/locales/fr.ts`.
2. Nur Werte ändern, niemals Schlüssel. Kein Eintrag darf identisch mit `en.ts` bleiben —
   der Paritätstest lehnt das ab, außer es ist ein Marken- oder Fachbegriff.
3. Prüfen:
   ```bash
   cd frontend
   node scripts/check-i18n-parity.mjs     # Schlüssel, Platzhalter, Kürzung
   npm run typecheck
   ```
4. Die betroffene Seite bei 1280 px und 390 px Breite ansehen: Titel dürfen nicht abschneiden,
   Knöpfe nicht umbrechen.
5. Ergebnis als kurze Notiz an die Änderung hängen (Sprache, geprüfte Bildschirme, offene Fragen).

## Prüfliste je Sprache

- [ ] `errorHelp.*` gelesen (Fehlerhilfe, KI-Karte, Gegenmaßnahmen)
- [ ] Fehlerbild-Titel und Kurzfassungen gegengelesen
- [ ] Platzhalter unverändert, Paritätstest grün
- [ ] Zahlen, Einheiten, Gradzeichen geprüft
- [ ] Schmale Ansicht geprüft (390 px)
- [ ] Kommentar im Commit: Sprache und offene Punkte

## Bekannte Grenzen

- Die zwölf Fließtexte (Ursachen, Slicer-Hilfen, Automatik) liegen nur auf Deutsch vor.
  Eine Übersetzung braucht zuerst ein Datenmodell je Sprache — siehe `TODO.md`.
- Die beiden Bauraum-Regeln haben deutsche und englische Titel; weitere Sprachen zeigt die
  Oberfläche derzeit englisch an.
- Maschinenlesbare Prüfung deckt Schlüssel und Platzhalter ab, nicht die Qualität. Die
  Sichtprüfung bei schmaler Breite bleibt Handarbeit.

# Code-Analyse PrintLab (Tranchen)

Gestaffelte, belegte Analyse des Codes nach Risiko. Jede Tranche: Überblick, Funktionsaufbau, Kontroll- und Datenfluss,
Befunde mit `datei:zeile`, Refactoring-Vorschläge. Es wird nichts im Produktivcode geändert; Umsetzung ist ein eigener Schritt.

Abdeckungsstufen: **A** Datei vollständig gelesen und je Funktion beschrieben, **B** Inventar mit Kennzahlen, nur Auffälliges gelesen,
**C** nur automatische Kennzahlen.

| Tranche | Bereich | Stand | Befunde | Dokument |
|---|---|---|---:|---|
| T1 | Sicherheit | erledigt (Teile B, siehe Abschnitt 0 und 6) | 18 (5 mittel) | [T1-sicherheit.md](T1-sicherheit.md) |
| T2 | Drucker-Kommunikation (MQTT, FTP, Druckstart/-ende) | erledigt, überwiegend Stufe B; Vertiefung T2b offen | 9 (2 mittel) | [T2-drucker-kommunikation.md](T2-drucker-kommunikation.md) |
| T3 | Datenbank und Migrationen | erledigt, `run_migrations` Stufe B+ | 10 (1 hoch, 4 mittel) | [T3-datenbank.md](T3-datenbank.md) |
| T4 | Warteschlange und Scheduler | offen | | |
| T5 | Archiv, Bibliothek, Dateien | offen | | |
| T6 | Drucker-Routen, Kamera, virtueller Drucker | offen | | |
| T7 | Inventar und Verbrauch | offen | | |
| T8 | Integrationen und Betrieb | offen | | |
| T9 | Frontend | offen | | |
| T10 | Hardware (Plattenwechsler, GPIO) | offen | | |
| T11 | Querschnitt und Gesamtbericht | offen | | |

Vorgänger ohne Tiefe: [GESAMTAUDIT-2026-11-07.md](../GESAMTAUDIT-2026-11-07.md), [ANALYSE-2026-10-30.md](../ANALYSE-2026-10-30.md).

Ausgangsmessung (Ruff über `backend/`): 398 zu komplexe Funktionen, 764 breite `except`, 86 `except: pass`, 73 Funktionen über 200 Zeilen.

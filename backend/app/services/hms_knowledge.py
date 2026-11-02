"""RAG-Wissensbasis für Bambu Lab HMS-Fehlercodes und Wartungsanleitungen.

Ermöglicht dem KI-Assistenten und der Oberfläche das sofortige Abrufen
präziser, bebilderter Handlungsanweisungen bei Druckerfehlern und Wartungsaufgaben.
"""

from __future__ import annotations

import re
from typing import Any

# Kuratierte Wissensbasis über offizielle Bambu Lab P2S Fehler- und Wartungsverfahren
HMS_ENTRIES: list[dict[str, Any]] = [
    {
        "id": "HMS_0300_0100_0001_0001",
        "code": "0300-0100",
        "title": "Düsen-Temperaturanomalie (Nozzle Temperature Malfunction)",
        "category": "Extruder & Hotend",
        "keywords": ["düse", "nozzle", "temperatur", "heater", "thermistor", "hotend", "0300-0100"],
        "cause": "Der Temperatursensor (Thermistor) oder die Heizpatrone des Hotends hat einen Wackelkontakt oder liefert unplausible Werte.",
        "steps": [
            "1. Drucker ausschalten und Hotend abkühlen lassen.",
            "2. Frontabdeckung des Werkzeugkopfs vorsichtig nach vorne abziehen.",
            "3. Steckverbindungen des Thermistors und der Keramikheizung auf der Werkzeugkopfplatine (TH-Board) auf festen Sitz prüfen.",
            "4. Prüfen, ob Wärmeleitpaste zwischen Thermistor und Hotend-Kühlkörper noch intakt ist.",
            "5. Falls das Problem fortbesteht: Ersatz-Hotend einbauen (2× M2×14 Schrauben mit Inbusschlüssel 1,5 mm).",
        ],
        "tools_needed": ["Inbusschlüssel 1,5 mm", "Wärmeleitpaste"],
        "wiki_url": "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/0300-0100-0001-0001",
    },
    {
        "id": "HMS_0300_0200_0001_0002",
        "code": "0300-0200",
        "title": "Druckbett-Heizfehler (Heatbed Temperature Malfunction)",
        "category": "Druckbett",
        "keywords": ["bett", "heatbed", "bett-temperatur", "heizbett", "0300-0200"],
        "cause": "Das Heizbett erreicht die Solltemperatur nicht in der erwarteten Zeit oder die Übertemperatursicherung hat angesprochen.",
        "steps": [
            "1. Netzstecker des Druckers ziehen.",
            "2. Prüfen, ob das Heizbettkabel an der Rückseite der Z-Achse frei beweglich ist und nicht eingeklemmt wurde.",
            "3. Sicherstellen, dass die Netzspannung (115V / 230V Wahlschalter auf der Rückseite) korrekt eingestellt ist.",
            "4. Druckraumtür und Deckel geschlossen halten, wenn hohe Betttemperaturen (>80 °C) für ABS/ASA gefordert werden.",
        ],
        "tools_needed": ["Sichtprüfung"],
        "wiki_url": "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/0300-0200-0001-0002",
    },
    {
        "id": "HMS_0500_0300_0001_0002",
        "code": "0500-0300",
        "title": "AMS-Filament-Vorschubfehler (AMS Filament Assist Motor Overload)",
        "category": "AMS (Materialsystem)",
        "keywords": ["ams", "vorschub", "filament", "stau", "motor", "spule", "0500-0300", "verklemmt"],
        "cause": "Das Filament lässt sich nicht von der Spule abrollen oder klemmt im PTFE-Schlauch zum Werkzeugkopf.",
        "steps": [
            "1. Prüfen, ob die Spule im AMS sauber auf den Rollen liegt und sich frei drehen kann (Pappspulen können rutschen).",
            "2. Kontrollieren, ob das Filament auf der Spule überkreuzt oder verheddert ist.",
            "3. PTFE-Führungsschlauch am Werkzeugkopf und an der AMS-Rückseite auf enge Biegeradien oder Knicke prüfen.",
            "4. Filamenttrichter am AMS-Slot drücken und das Filament manuell 10 cm zurückziehen und wieder einschieben.",
        ],
        "tools_needed": ["Manuelle Entlastung"],
        "wiki_url": "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/0500-0300-0001-0002",
    },
    {
        "id": "HMS_0700_2000_0002_0001",
        "code": "0700-2000",
        "title": "Druckbett-Nivellierung fehlgeschlagen (Bed Leveling Sensor Failure)",
        "category": "Sensoren & Nivellierung",
        "keywords": ["nivellierung", "leveling", "bett", "abtastung", "pei", "0700-2000"],
        "cause": "Die Dehnungsmessstreifen (Piezo-Sensoren) unter dem Druckbett konnten den Kontakt der Düse nicht eindeutig registrieren.",
        "steps": [
            "1. Prüfen, ob Filamentreste oder Plastikklumpen an der Düsenspitze kleben; Düse mit Drahtbürste bei 200 °C reinigen.",
            "2. Sicherstellen, dass die PEI-Druckplatte sauber und plan auf dem Magnetbett aufliegt und nicht an den Rändern verkantet ist.",
            "3. Prüfen, ob unter der flexiblen Druckplatte Fremdkörper oder Filamentkrümel liegen.",
            "4. Druckbett-Kalibrierung im Menü des Druckers oder in PrintLab neu starten.",
        ],
        "tools_needed": ["Messing-Drahtbürste", "Isopropanol 99,9 %"],
        "wiki_url": "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/0700-2000-0002-0001",
    },
    {
        "id": "MAINT_LEADSCREW_LUBE",
        "code": "MAINT-Z",
        "title": "Schmierung der Z-Gewindespindeln (Lead Screw Lubrication)",
        "category": "Wartung",
        "keywords": ["schmieren", "fett", "spindel", "z-achse", "wartung", "quietscht", "superlube"],
        "cause": "Regelmäßige Wartung alle 100 Druckstunden oder bei Quietschgeräuschen der Z-Achse.",
        "steps": [
            "1. Druckbett ganz nach oben fahren (`G28 Z` oder über die Druckersteuerung).",
            "2. Alte Schmiermittel- und Staubablagerungen mit einem fusselfreien Tuch von allen drei Gewindespindeln abwischen.",
            "3. Eine dünne Spur PTFE-Schmierfett (z. B. Super Lube 21030 synthetisches Schmierfett) auf die Spindeln auftragen.",
            "4. Das Druckbett mehrmals von oben nach unten und zurück bewegen, um das Fett gleichmäßig zu verteilen.",
        ],
        "tools_needed": ["Fusselfreies Mikrofasertuch", "Synthetisches Schmierfett (Super Lube 21030 PTFE)"],
        "wiki_url": "https://wiki.bambulab.com/en/p1/maintenance/lead-screw-lubrication",
    },
    {
        "id": "MAINT_STEEL_RODS",
        "code": "MAINT-RODS",
        "title": "Reinigung und Schmierung der P2S-Stahlführungsstangen",
        "category": "Wartung",
        "keywords": ["führungsstange", "stange", "stangen", "öl", "schmieren", "p2s", "rods"],
        "cause": "Wartungsintervall alle 50 bis 100 Druckstunden für Leichtgängigkeit und Vermeidung von Schrittverlusten.",
        "steps": [
            "1. Die zylindrischen Stahlstangen der X- und Y-Achsen mit Isopropanol und einem sauberen Tuch gründlich entfetten.",
            "2. 2-3 Tropfen Feinmechaniköl (ISO VG 32 oder Nähmaschinenöl) auf die Stangen geben.",
            "3. Den Druckkopf manuell oder über Achsbefehle mehrfach über den gesamten Verfahrbereich bewegen.",
            "4. Überschüssiges Öl mit einem trockenen Tuch sanft abwischen (keine Tropfenbildung).",
        ],
        "tools_needed": ["Isopropanol (IPA 99,9 %)", "Mikrofasertuch", "Feinmechaniköl ISO VG 32"],
        "wiki_url": "https://wiki.bambulab.com/en/p1/maintenance/p1p-maintenance",
    },
]


def search_knowledge(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Durchsucht die Wissensbasis anhand von Begriffen oder Fehlercodes und liefert die relevantesten Einträge zurück."""
    clean_query = query.lower().strip()
    if not clean_query:
        return HMS_ENTRIES[:limit]

    # Tokenisierung der Suchanfrage
    tokens = [t for t in re.split(r"[\s\-_,.:;]+", clean_query) if len(t) >= 2]

    scored: list[tuple[float, dict[str, Any]]] = []

    for entry in HMS_ENTRIES:
        score = 0.0
        # Exakter Code-Treffer (z. B. "0300-0100")
        if entry["code"].lower() in clean_query or clean_query in entry["code"].lower():
            score += 15.0

        for kw in entry["keywords"]:
            if kw in clean_query:
                score += 5.0

        for token in tokens:
            if token in entry["title"].lower():
                score += 4.0
            if token in entry["cause"].lower():
                score += 2.0
            if any(token in step.lower() for step in entry["steps"]):
                score += 1.5

        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]

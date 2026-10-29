"""Fehlerbild-Bibliothek: Ursachen, Slicer-Hilfen und Gegenmaßnahmen beim FDM-Druck.

Inhaltlich eine gepflegte Sammlung aus der Werkstattpraxis (Stand 29.10.2026),
kein Herstellerdokument. Jeder Eintrag nennt Erklärung, typische Ursachen, was
im Slicer hilft und was PrintLab während des Drucks tun kann. Die Kennung
``actions`` verweist auf Einträge in ``MANUAL_ACTIONS`` und auf Regeln in
``services/countermeasures.py``; nur diese Verweise lösen Knöpfe in der
Oberfläche aus.

Die Texte sind deutsch; ``title_en``/``summary_en`` geben englischen Lesern
Titel und Kurzfassung. Die Details werden in ``TODO.md`` als Übersetzungsarbeit
geführt.
"""

from __future__ import annotations

CATEGORIES = [
    {
        "id": "extrusion",
        "title": "Extrusion & Materialfluss",
        "title_en": "Extrusion & material flow",
        "hint": "Zu wenig, zu viel oder gar kein Material — und was die Düse zwischen den Bauteilen hinterlässt.",
        "hint_en": "Too little, too much, or no material at all — and what the nozzle leaves between parts.",
    },
    {
        "id": "thermal",
        "title": "Thermisch & Haftung",
        "title_en": "Thermal & adhesion",
        "hint": "Schrumpfung, Verzug, Ablösen und Risse durch Temperaturführung.",
        "hint_en": "Shrinkage, warping, lifting and cracks caused by heat management.",
    },
    {
        "id": "mechanical",
        "title": "Mechanik & Kinematik",
        "title_en": "Mechanics & kinematics",
        "hint": "Versatz, Schwingungen und Streifen — der Drucker selbst als Fehlerquelle.",
        "hint_en": "Shifts, ringing and banding — the machine itself as the source.",
    },
    {
        "id": "slicer",
        "title": "Slicer & Geometrie",
        "title_en": "Slicer & geometry",
        "hint": "Fehler, die vor allem in Vorbereitung und Bauteilgeometrie entstehen.",
        "hint_en": "Problems rooted in preparation and part geometry.",
    },
]

PATTERNS = [
    {
        "id": "heat_creep",
        "category": "extrusion",
        "title": "Heat Creep & Düsenverstopfung",
        "title_en": "Heat creep & clogging",
        "summary": "Das Filament erweicht schon im Heatbreak oder zwischen den Extruderzahnrädern. Der Vorschub bricht "
        "mitten im Druck ab, die Düse fördert Luft statt Material.",
        "summary_en": "Filament softens in the heatbreak before reaching the melt zone; extrusion stops mid-print.",
        "causes": [
            "Bauraum zu warm für Material mit niedriger Glasübergangstemperatur (PLA ab etwa 60 °C)",
            "Hotend-Kühllüfter ausgefallen oder verschmutzt",
            "Sehr lange oder sehr häufige Rückzüge an derselben Stelle",
        ],
        "slicer": [
            "Abluft-/Kammerlüfter im Filament-Start-G-Code ab einer Betttemperatur einschalten",
            "Rückzugslänge auf 0,4–0,8 mm begrenzen und lange Leerfahrten vermeiden",
        ],
        "automation": [
            "Bauraumtemperatur überwachen; bei PLA über 38–40 °C Kammerlüfter auf 100 % und Zusatzlüfter zuschalten",
            "Heizbett dabei um 5 °C absenken, damit die Wärmeeintrag sinkt",
        ],
        "actions": ["chamber_fan_full", "aux_fan_70", "bed_minus_5"],
        "rules": ["chamber_hot"],
    },
    {
        "id": "under_extrusion",
        "category": "extrusion",
        "title": "Unterextrusion",
        "title_en": "Under-extrusion",
        "summary": "Es kommt zu wenig Material an: Lücken in der Deckschicht, schwache Wandbindung, brüchige Bauteile.",
        "summary_en": "Too little material: gaps in top layers, weak walls, brittle parts.",
        "causes": [
            "Reibung im PTFE-Schlauch oder verknotete Spule",
            "Verschmutztes oder verschlissenes Extruderzahnrad",
            "Geschwindigkeit über der maximalen Schmelzleistung des Hotends",
        ],
        "slicer": [
            "Maximalen Volumenfluss (mm³/s) im Filamentprofil als harte Obergrenze setzen",
            "Fluss pro Filament kalibrieren statt global zu raten",
        ],
        "automation": [
            "Fluss im laufenden Druck leicht anheben (M221 S105) und Düsentemperatur um 5–10 °C erhöhen",
            "Bei anhaltendem Problem Tempo auf Silent (50 %) drosseln, statt weiter zu heizen",
        ],
        "actions": ["flow_105", "nozzle_plus_10", "silent_speed"],
        "rules": [],
    },
    {
        "id": "over_extrusion",
        "category": "extrusion",
        "title": "Überextrusion",
        "title_en": "Over-extrusion",
        "summary": "Zu viel Material: die Düse pflügt durch überschüssigen Kunststoff, Maße und Oberfläche leiden.",
        "summary_en": "Too much material: the nozzle ploughs through plastic, hurting dimensions and surface.",
        "causes": [
            "Falsch kalibrierter Flusswert",
            "Schwankender Filamentdurchmesser",
            "Unkalibrierter Pressure Advance (K-Faktor)",
        ],
        "slicer": [
            "Fluss je Filament kalibrieren; K-Faktor im Start-G-Code hinterlegen (M900 K…)",
            "Deckschicht-Fluss separat leicht reduzieren, etwa auf 0,95",
        ],
        "automation": [
            "Fluss im laufenden Druck senken (M221 S98), wenn Kanten aufgeworfen wirken",
        ],
        "actions": ["flow_98"],
        "rules": [],
    },
    {
        "id": "stringing",
        "category": "extrusion",
        "title": "Stringing & Oozing",
        "title_en": "Stringing & oozing",
        "summary": "Feine Fäden zwischen Bauteilen oder Pickel an der Außenwand nach Leerfahrten.",
        "summary_en": "Fine threads between parts or blobs on outer walls after travel moves.",
        "causes": [
            "Feuchtes Filament — Wasserdampf drückt Material aus der Düse",
            "Düsentemperatur zu hoch",
            "Rückzug fehlt, ist zu kurz oder zu langsam",
        ],
        "slicer": [
            "„Wipe while retracting“ und Spiral-Z-Hop einschalten",
            "Düsentemperatur um 5–10 °C senken und Filament vorher trocknen",
        ],
        "automation": [
            "Bei erkanntem Fadenziehen Düsentemperatur um 5 °C senken, ohne den Druck zu unterbrechen",
        ],
        "actions": ["nozzle_minus_5"],
        "rules": [],
    },
    {
        "id": "warping",
        "category": "thermal",
        "title": "Warping (Ecken lösen sich)",
        "title_en": "Warping (corners lift)",
        "summary": "Thermische Schrumpfung zieht die oberen Schichten zusammen; die Ecken heben sich vom Bett.",
        "summary_en": "Thermal shrinkage pulls upper layers together and lifts the corners off the bed.",
        "causes": [
            "Zu schnelle Abkühlung oder Zugluft (besonders ABS/ASA)",
            "Betttemperatur zu niedrig oder Druckplatte verschmutzt",
            "Scharfe 90°-Ecken ohne Rand",
        ],
        "slicer": [
            "Bauteillüfter für die ersten 3–5 Schichten ausschalten",
            "Brim oder „Mäuseohren“ an den Ecken anlegen",
        ],
        "automation": [
            "Gehäuse vor dem Start auf Temperatur bringen und während des Drucks halten (nur bei Modellen mit Kammerheizung)",
            "Bei offener Tür oder fallender Kammertemperatur lüftende Lüfter drosseln",
        ],
        "actions": ["aux_fan_off", "chamber_fan_off"],
        "rules": ["chamber_cold"],
    },
    {
        "id": "curling",
        "category": "thermal",
        "title": "Curling (Kanten biegen hoch)",
        "title_en": "Curling (edges curl up)",
        "summary": "Überhänge und scharfe Kanten stellen sich auf; die Düse schlägt beim nächsten Layer dagegen.",
        "summary_en": "Overhangs and sharp edges curl upward and the nozzle catches them on the next layer.",
        "causes": [
            "Zu wenig Bauteilkühlung an Überhängen",
            "Kleine Schichten werden zu schnell gedruckt, das Material erstarrt nicht",
        ],
        "slicer": [
            "Mindestschichtzeit erhöhen, damit kleine Schichten langsamer laufen",
            "„Slow down for overhangs“ aktivieren und den Lüfter dort auf 100 % schalten",
        ],
        "automation": [
            "Bei sichtbarem Aufstellen der Kanten Part- und Zusatzlüfter voll aufdrehen",
        ],
        "actions": ["part_fan_full", "aux_fan_70"],
        "rules": [],
    },
    {
        "id": "elephants_foot",
        "category": "slicer",
        "title": "Elefantenfuß",
        "title_en": "Elephant's foot",
        "summary": "Die untersten Schichten werden nach außen gequetscht; am Boden entsteht eine Wulst.",
        "summary_en": "The first layers are squeezed outward, leaving a bulge at the bottom.",
        "causes": [
            "Düse im ersten Layer zu nah am Bett",
            "Betttemperatur dauerhaft über dem Erweichungspunkt des Materials",
        ],
        "slicer": [
            "Elefantenfuß-Kompensation auf 0,15–0,2 mm stellen",
            "Betttemperatur ab Schicht 2 um 5 °C absenken",
        ],
        "automation": [
            "Nach der ersten Schicht Bettziel um 5 °C senken (M140), wenn das Modell es zulässt",
        ],
        "actions": ["bed_minus_5"],
        "rules": [],
    },
    {
        "id": "delamination",
        "category": "thermal",
        "title": "Schichtablösung & Rissbildung",
        "title_en": "Layer delamination & cracking",
        "summary": "Schichten haften nicht aufeinander oder das Bauteil reißt während des Drucks horizontal auf.",
        "summary_en": "Layers do not bond or the part cracks horizontally during the print.",
        "causes": [
            "Zu viel Bauteilkühlung, besonders bei ABS, ASA und PC",
            "Düsen- oder Kammertemperatur zu niedrig",
        ],
        "slicer": [
            "Bauteillüfter bei ABS/ASA stark begrenzen",
            "Kammertemperatur im Filamentprofil als Ziel führen",
        ],
        "automation": [
            "Fällt die Kammertemperatur bei ABS/ASA, lüftende Lüfter sofort drosseln und Düsentemperatur leicht anheben",
        ],
        "actions": ["chamber_fan_off", "aux_fan_off", "nozzle_plus_10"],
        "rules": ["chamber_cold"],
    },
    {
        "id": "object_detached",
        "category": "thermal",
        "title": "Bauteil löst sich vom Bett",
        "title_en": "Part detaches from the bed",
        "summary": "Ein einzelnes Objekt verliert die Haftung. Die Düse schiebt es über die Platte und gefährdet die übrigen Teile.",
        "summary_en": "A single object loses adhesion; the nozzle drags it across the plate and endangers the other parts.",
        "causes": [
            "Erste Schicht zu dünn oder Platte verschmutzt",
            "Warping an den Ecken (siehe Warping)",
            "Düse stößt an hochgebogene Kanten und schiebt das Teil weg",
        ],
        "slicer": [
            "Brim oder Mäuseohren an kleinen Standflächen",
            "Z-Hop beim Rückzug, damit die Düse nicht über das Teil schleift",
        ],
        "automation": [
            "Fehlerhaftes Objekt im Druck überspringen (Druckerkarte → Objekte); der Rest der Platte läuft weiter",
            "Danach die Ursache an der ersten Schicht und der Betthaftung suchen",
        ],
        "actions": [],
        "rules": [],
    },
    {
        "id": "layer_shift",
        "category": "mechanical",
        "title": "Layer Shift (Schichtversatz)",
        "title_en": "Layer shift",
        "summary": "Ab einer Höhe ist der restliche Druck seitlich versetzt — meist nachdem die Düse irgendwo hängen blieb.",
        "summary_en": "The rest of the print is offset sideways, usually after the nozzle caught on something.",
        "causes": [
            "Schrittverlust durch hochgebogenes Material oder sich kreuzendes Infill",
            "Zu hohe Beschleunigung auf Leerfahrten",
            "Lockere Riemen oder Spiel in den Achsen",
        ],
        "slicer": [
            "Kreuzungsfreies Infill wie Gyroid oder Cross Hatch verwenden",
            "Z-Hop beim Rückzug und „Avoid crossing walls“ aktivieren",
        ],
        "automation": [
            "Leerfahrt-Beschleunigung senken (M204) und im Verdachtsfall das Tempo auf Silent drosseln",
        ],
        "actions": ["silent_speed"],
        "rules": [],
    },
    {
        "id": "ghosting",
        "category": "mechanical",
        "title": "Ghosting & Ringing",
        "title_en": "Ghosting & ringing",
        "summary": "Nach scharfen Kanten wiederholt sich die Kontur als wellenförmiges Echo auf glatten Flächen.",
        "summary_en": "After sharp corners the contour echoes as ripples across smooth surfaces.",
        "causes": [
            "Mechanische Resonanzen von Rahmen und Riemen",
            "Wackeliger Untergrund oder gelockerte Schrauben",
        ],
        "slicer": [
            "Input Shaping nach Umstellen oder Dämpferfüßen neu kalibrieren",
            "Beschleunigung der Außenwand auf 2 000–3 000 mm/s² begrenzen",
        ],
        "automation": [
            "Keine automatische Regelung — erst Mechanik und Kalibrierung prüfen",
        ],
        "actions": [],
        "rules": [],
    },
    {
        "id": "z_wobble",
        "category": "slicer",
        "title": "Z-Wobble & Z-Banding",
        "title_en": "Z-wobble & Z-banding",
        "summary": "Regelmäßige oder unregelmäßige horizontale Rillen an den Seitenwänden.",
        "summary_en": "Regular or irregular horizontal bands on side walls.",
        "causes": [
            "Schwankende Druckzeit je Schicht und damit unterschiedliche Schrumpfung",
            "Verschmutzte Z-Spindeln oder schwingende Bettregelung (PID)",
        ],
        "slicer": [
            "Außenwandgeschwindigkeit konstant halten („Don't slow down outer walls“)",
            "Vorschau auf Geschwindigkeit prüfen: gleichmäßige Schichtzeiten anstreben",
        ],
        "automation": [
            "Keine — Bett-PID prüfen und Mechanik warten",
        ],
        "actions": [],
        "rules": [],
    },
]

# Sofort-Eingriffe am laufenden Druck. Die Befehle sind Bambu-Lab-G-Code; auf
# anderen Druckern heißen Lüfter und Fluss ggf. anders. Immer erst im
# Trockenlauf/Log prüfen.
MANUAL_ACTIONS = [
    {
        "id": "chamber_fan_full",
        "title": "Kammerlüfter 100 %",
        "title_en": "Chamber fan 100 %",
        "command": "M106 P3 S255",
        "effect": "Führt Wärme aus dem Bauraum ab und senkt das Risiko von Heat Creep bei PLA/PETG.",
        "effect_en": "Moves heat out of the chamber, reducing heat creep risk for PLA/PETG.",
        "requires": "printing",
        "fan": {"index": 3, "speed": 100},
    },
    {
        "id": "chamber_fan_off",
        "title": "Kammerlüfter aus",
        "title_en": "Chamber fan off",
        "command": "M106 P3 S0",
        "effect": "Hält die Wärme im Gehäuse — für ABS/ASA gegen Warping und Schichtablösung.",
        "effect_en": "Keeps heat inside the enclosure, for ABS/ASA against warping and delamination.",
        "requires": "printing",
        "fan": {"index": 3, "speed": 0},
    },
    {
        "id": "aux_fan_70",
        "title": "Zusatzlüfter 70 %",
        "title_en": "Auxiliary fan 70 %",
        "command": "M106 P2 S178",
        "effect": "Verteilt Luft gleichmäßig und kühlt Überhänge, ohne die ganze Kammer auszukühlen.",
        "effect_en": "Spreads air evenly and cools overhangs without chilling the whole chamber.",
        "requires": "printing",
        "fan": {"index": 2, "speed": 70},
    },
    {
        "id": "aux_fan_off",
        "title": "Zusatzlüfter aus",
        "title_en": "Auxiliary fan off",
        "command": "M106 P2 S0",
        "effect": "Verhindert Zugluft an ABS/ASA-Bauteilen.",
        "effect_en": "Prevents draughts on ABS/ASA parts.",
        "requires": "printing",
        "fan": {"index": 2, "speed": 0},
    },
    {
        "id": "part_fan_full",
        "title": "Bauteillüfter 100 %",
        "title_en": "Part cooling fan 100 %",
        "command": "M106 P1 S255",
        "effect": "Lässt Überhänge und dünne Schichten sofort erstarren.",
        "effect_en": "Freezes overhangs and thin layers immediately.",
        "requires": "printing",
        "fan": {"index": 1, "speed": 100},
    },
    {
        "id": "bed_minus_5",
        "title": "Bett 5 °C kühler",
        "title_en": "Bed 5 °C cooler",
        "command": "M140 S{bed}",
        "effect": "Senkt den Wärmeeintrag von unten; verringert Elefantenfuß und Heat Creep.",
        "effect_en": "Reduces heat from below; mitigates elephant's foot and heat creep.",
        "requires": "printing",
        "bed_delta": -5,
    },
    {
        "id": "flow_105",
        "title": "Fluss +5 %",
        "title_en": "Flow +5 %",
        "command": "M221 S105",
        "effect": "Hilft bei leichter Unterextrusion, bis die Ursache (Vorschub, Düse) geklärt ist.",
        "effect_en": "Helps with mild under-extrusion until the root cause is fixed.",
        "requires": "printing",
    },
    {
        "id": "flow_98",
        "title": "Fluss −2 %",
        "title_en": "Flow −2 %",
        "command": "M221 S98",
        "effect": "Nimmt Überextrusion an Kanten und Deckschichten zurück.",
        "effect_en": "Reduces over-extrusion on edges and top surfaces.",
        "requires": "printing",
    },
    {
        "id": "nozzle_plus_10",
        "title": "Düse +10 °C",
        "title_en": "Nozzle +10 °C",
        "command": "M104 S{nozzle}",
        "effect": "Erhöht die Schmelzenergie bei Unterextrusion und schwacher Schichthaftung.",
        "effect_en": "Adds melt energy for under-extrusion and weak layer bonding.",
        "requires": "printing",
        "nozzle_delta": 10,
    },
    {
        "id": "nozzle_minus_5",
        "title": "Düse −5 °C",
        "title_en": "Nozzle −5 °C",
        "command": "M104 S{nozzle}",
        "effect": "Verringert Nachtropfen und Fäden bei etwas zu heißer Düse.",
        "effect_en": "Reduces oozing and stringing from a slightly too-hot nozzle.",
        "requires": "printing",
        "nozzle_delta": -5,
    },
    {
        "id": "silent_speed",
        "title": "Tempo Silent (50 %)",
        "title_en": "Silent speed (50 %)",
        "command": "M220 S50",
        "effect": "Halbiert das Tempo; verringert Hebelkräfte auf hohe Bauteile und Schrittverluste.",
        "effect_en": "Halves speed; reduces leverage on tall parts and skipped steps.",
        "requires": "printing",
    },
]


def catalog() -> dict:
    """Alles, was die Oberfläche zum Anzeigen braucht."""
    return {
        "categories": CATEGORIES,
        "patterns": PATTERNS,
        "manual_actions": MANUAL_ACTIONS,
    }


def pattern(pattern_id: str) -> dict | None:
    return next((entry for entry in PATTERNS if entry["id"] == pattern_id), None)


def manual_action(action_id: str) -> dict | None:
    return next((entry for entry in MANUAL_ACTIONS if entry["id"] == action_id), None)

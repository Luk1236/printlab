"""Meldungen der PrintLab-Erweiterungen auf Englisch (Quelle der Meldungen ist Deutsch).

Die Erweiterungen (Wartungsprogramme, Tür/Plattenwechsler, Automatik, Kamera-Prüfungen, Angebote) erzeugen ihre
Meldungen auf Deutsch. Die Oberfläche schickt die gewählte Sprache als ``Accept-Language`` mit. Für alle Sprachen
außer Deutsch ersetzt diese Schicht bekannte deutsche Meldungen in den JSON-Antworten dieser Endpunkte durch
englische (wie die Grundanwendung, deren serverseitige Texte ebenfalls nur Deutsch und Englisch kennen).
Unbekannte Texte bleiben unverändert (deutsch), es geht also nie eine Meldung verloren.
"""

from __future__ import annotations

import json
import re
from typing import Any

# (deutsches Muster, englische Ersetzung); längere/spezifischere Muster zuerst.
_RAW: list[tuple[str, str]] = [
    # --- Hardware: Tür und Plattenwechsler ---------------------------------------------------------
    (
        r"Not-Halt aktiv — Hardware-Konfiguration neu laden oder Magazin auffüllen, um fortzufahren\.",
        "Emergency stop active — reload the hardware configuration or refill the magazine to continue.",
    ),
    (
        r"Letzter Wechsel unvollständig \((?P<s>[^)]*)\) — Mechanik prüfen, dann den Wechsel als geprüft bestätigen\.",
        r"Last change incomplete (\g<s>) — check the mechanics, then confirm the change as checked.",
    ),
    (r"Es läuft bereits ein Hardware-Vorgang\.", "A hardware operation is already running."),
    (
        r"Hardware-Vorgang läuft bereits — kein automatischer Wechsel\.",
        "Hardware operation already running — no automatic change.",
    ),
    (r"Tür geöffnet \(Simulation\)\.", "Door opened (simulation)."),
    (r"Tür geschlossen \(Simulation\)\.", "Door closed (simulation)."),
    (r"Tür geöffnet\.", "Door opened."),
    (r"Tür geschlossen\.", "Door closed."),
    (r"Tür-Endschalter meldet UNKNOWN\.", "Door limit switch reports UNKNOWN."),
    (r"Tür ist nach dem Öffnen noch geschlossen\.", "Door is still closed after opening."),
    (r"Tür ist nach dem Schließen noch offen\.", "Door is still open after closing."),
    (
        r"Tür ist offen bzw\. unbestätigt — Plattenwechsel nicht angetreten\.",
        "Door is open or unconfirmed — plate change not started.",
    ),
    (r"Keine frische Platte im Magazin\.", "No fresh plate in the magazine."),
    (r"Kein freies Ablagefach\.", "No free storage slot."),
    (r"Platte aus Fach (?P<n>\d+) eingesetzt \(Simulation\)\.", r"Plate from slot \g<n> inserted (simulation)."),
    (r"Platte aus Fach (?P<n>\d+) eingesetzt\.", r"Plate from slot \g<n> inserted."),
    (r" \(Platte getauscht, Magazin nachgeführt\)", " (plate swapped, magazine updated)"),
    (r" — Wechsel unvollständig", " — change incomplete"),
    (r"; Mechanik prüfen\.", "; check the mechanics."),
    (r"Es gibt keinen unvollständigen Wechsel\.", "There is no incomplete change."),
    (r"Unvollständiger Wechsel bestätigt\.", "Incomplete change confirmed."),
    (r"Magazin aufgefüllt, Ablage geleert\.", "Magazine refilled, storage emptied."),
    (r"Fach-Id fehlt oder ist keine Zahl\.", "Slot id is missing or not a number."),
    (r"Unbekanntes Fach (?P<n>\d+)\.", r"Unknown slot \g<n>."),
    (r"Fach (?P<n>\d+): Etikett '", r"Slot \g<n>: label '"),
    (
        r"Unbekannter Status '(?P<s>[^']*)' für Fach (?P<n>\d+) \(erlaubt: ",
        r"Unknown status '\g<s>' for slot \g<n> (allowed: ",
    ),
    (r"Fach (?P<n>\d+): (?P<s>ready|used|empty|occupied)", r"Slot \g<n>: \g<s>"),
    (r"Keine gültigen Änderungen übermittelt\.", "No valid changes submitted."),
    (r"Hardware-Konfiguration gespeichert\.", "Hardware configuration saved."),
    (r"Konfiguration nicht gespeichert: ", "Configuration not saved: "),
    (r"Unbekannte Schlüssel: ", "Unknown keys: "),
    (r"Modus nur 'simulated' oder 'command'\.", "Mode must be 'simulated' or 'command'."),
    (r"timeout_seconds muss eine Zahl sein\.", "timeout_seconds must be a number."),
    (
        r"(?P<k>\w+_command) muss ein Text oder eine Liste von Texten sein\.",
        r"\g<k> must be a text or a list of texts.",
    ),
    (r"Not-Halt-Sperre aufgehoben\.", "Emergency stop lock lifted."),
    (r"Not-Halt ausgelöst \(Simulation\)\.", "Emergency stop triggered (simulation)."),
    (r"Not-Halt ausgelöst\.", "Emergency stop triggered."),
    (r"Kein Befehl konfiguriert\.", "No command configured."),
    (
        r"Befehl fehlgeschlagen: Zeitlimit von (?P<n>[\d.]+) s überschritten\.",
        r"Command failed: timeout of \g<n> s exceeded.",
    ),
    (r"Befehl fehlgeschlagen: ", "Command failed: "),
    (r"Befehl wurde abgebrochen\.", "Command was aborted."),
    (r"Befehl endete mit Code (?P<n>-?\d+)\.", r"Command exited with code \g<n>."),
    (r"Konfigurationstext erwartet\.", "Configuration body expected."),
    (
        r"Befehle können nur mit eingeschalteter Anmeldung geändert werden \(Einstellungen → Benutzer, oder werkzeuge\\admin_passwort_setzen\.py\)\.",
        r"Commands can only be changed with authentication enabled (Settings → Users, or werkzeuge\\admin_passwort_setzen.py).",
    ),
    (r"\bTür öffnen\b", "Open door"),
    (r"\bTür schließen\b", "Close door"),
    (r"\bPlattenwechsel\b(?! nicht| abgebrochen)", "Plate change"),
    # --- Automatik ----------------------------------------------------------------------------------
    (r"Drucker getrennt — Automatik übersprungen\.", "Printer disconnected — automation skipped."),
    (r"Neuer Druck hat begonnen — Plattenwechsel abgebrochen\.", "A new print has started — plate change cancelled."),
    (
        r"Druckplatte bleibt über (?P<m>\d+)s über (?P<t>[\d.]+)°C \(aktuell (?P<b>[\d.]+)°C\) — kein Wechsel\.",
        r"Bed stays above \g<t>°C for \g<m>s (currently \g<b>°C) — no change.",
    ),
    (r"Automatischer Plattenwechsel abgebrochen\.", "Automatic plate change cancelled."),
    (
        r"Kein weiterer Auftrag wartet — Wechsel übersprungen \(only_with_queue\)\.",
        "No further job is waiting — change skipped (only_with_queue).",
    ),
    (r"Magazin: ", "Magazine: "),
    (r"keine frische Platte mehr", "no fresh plate left"),
    (r"nur noch (?P<n>\d+) frische Platte\(n\)", r"only \g<n> fresh plate(s) left"),
    (r"kein freies Ablagefach mehr", "no free storage slot left"),
    (r"nur noch (?P<n>\d+) freies Ablagefach/-fächer", r"only \g<n> free storage slot(s) left"),
    (r" — bitte auffüllen bzw\. leeren\.", " — please refill or empty."),
    (
        r"Platte frei automatisch bestätigt \(Kamera, (?P<n>\d+)%\)\.",
        r"Plate clear confirmed automatically (camera, \g<n>%).",
    ),
    (r"Platte-frei war nicht angefordert\.", "Plate clear was not requested."),
    (r"Drucker nicht gefunden\.", "Printer not found."),
    (r"Keine Referenz für die Leerbett-Prüfung\.", "No reference for the blank-bed check."),
    (r"Kamera sieht Objekte auf der Platte\.", "Camera sees objects on the plate."),
    (r"Leerbett-Prüfung unsicher \((?P<n>\d+)%\)\.", r"Blank-bed check uncertain (\g<n>%)."),
    (r"Leerbett-Prüfung nicht möglich\.", "Blank-bed check not possible."),
    (r"Platte-frei bitte von Hand bestätigen\.", "Please confirm plate clear manually."),
    # --- Wartungsprogramme ----------------------------------------------------------------------------
    (
        r"Dieses Wartungsprogramm ist nur für den P2S eingerichtet\.",
        "This maintenance program is only set up for the P2S.",
    ),
    (r"Der Drucker ist nicht verbunden\.", "The printer is not connected."),
    (
        r"Der Druckerzustand ist noch unbekannt\. Bitte den ersten Status abwarten\.",
        "The printer state is still unknown. Please wait for the first status.",
    ),
    (r"Das Wartungsprogramm ist während eines Drucks gesperrt\.", "The maintenance program is locked while printing."),
    (
        r"Bitte zuerst bestätigen, dass die Druckplatte frei ist\.",
        "Please confirm first that the build plate is clear.",
    ),
    (r"Wartungsdruck ist nur für den P2S eingerichtet\.", "The maintenance print is only set up for the P2S."),
    (
        r"Kein geslictes Archiv als Vorlage\. Bitte zuerst einen Druck archivieren\.",
        "No sliced archive to use as a template. Please archive a print first.",
    ),
    (r"Die Archivdatei ist nicht mehr vorhanden\.", "The archive file no longer exists."),
    (r"Düse/Bett sind noch heiß \((?P<a>[\d.]+)/(?P<b>[\d.]+) °C\)\. ", r"Nozzle/bed are still hot (\g<a>/\g<b> °C). "),
    (r"Unbekanntes Programm: ", "Unknown program: "),
    (
        r"Auf diesem Drucker läuft bereits ein Wartungsprogramm\.",
        "A maintenance program is already running on this printer.",
    ),
    (r"Grundposition wird angefahren …", "Moving to home position …"),
    (r"Es läuft kein Wartungsprogramm\.", "No maintenance program is running."),
    (
        r"Stopp angefordert – der aktuelle Schritt wird noch beendet\.",
        "Stop requested – the current step is being finished.",
    ),
    (r"Wartungsprogramm wird gestoppt\.", "Maintenance program is being stopped."),
    (r"Der Drucker hat den Befehl nicht angenommen\.", "The printer did not accept the command."),
    (r"Bett fährt \((?P<i>\d+)/(?P<t>\d+)\) …", r"Bed moving (\g<i>/\g<t>) …"),
    (r"Kopf fährt (?P<a>\w+) auf (?P<v>[\d.]+) mm …", r"Head moving \g<a> to \g<v> mm …"),
    (
        r"(?P<n>\d+) s Pause – jetzt Öl auf die Gewindestangen geben\.",
        r"\g<n> s pause – apply oil to the threaded rods now.",
    ),
    (r"(?P<n>\d+) s Pause – gleich folgt der nächste Durchgang\.", r"\g<n> s pause – the next pass follows shortly."),
    (r"Vorlage ist keine \.3mf-Datei\.", "Template is not a .3mf file."),
    (r"Vorlage nicht lesbar: ", "Template not readable: "),
    (r"Zieldatei nicht schreibbar: ", "Target file not writable: "),
    # --- Angebote ---------------------------------------------------------------------------------------
    (r"Kundenname fehlt\.", "Customer name is missing."),
    (r"Archiv-Nummern müssen eine Liste sein\.", "Archive numbers must be a list."),
    (r"Archiv-Nummern müssen positive ganze Zahlen sein\.", "Archive numbers must be positive whole numbers."),
    (r"Höchstens (?P<n>\d+) Drucke pro Angebot\.", r"At most \g<n> prints per quote."),
    (r"Archiv (?P<n>\d+) nicht gefunden\.", r"Archive \g<n> not found."),
    (r"Positionen müssen eine Liste sein\.", "Items must be a list."),
    (r"Höchstens (?P<n>\d+) Positionen\.", r"At most \g<n> items."),
    (r"Position (?P<n>\d+): Beschreibung fehlt\.", r"Item \g<n>: description is missing."),
    (r"Position (?P<n>\d+): Menge muss größer als 0 sein\.", r"Item \g<n>: quantity must be greater than 0."),
    (r"Position (?P<n>\d+): Preis ist ungültig\.", r"Item \g<n>: price is invalid."),
    (r"Betrag „(?P<k>\w+)“ fehlt oder ist ungültig\.", r"Amount “\g<k>” is missing or invalid."),
    (r"Angebot nicht gefunden\.", "Quote not found."),
    (r"Kein Logo hinterlegt\.", "No logo stored."),
    (r"Das Logo ist leer oder größer als 2 MB\.", "The logo is empty or larger than 2 MB."),
    (r"Nur PNG oder JPEG sind als Logo erlaubt\.", "Only PNG or JPEG are allowed as a logo."),
    (
        r"Das Logo konnte nicht gelesen werden \(kein gültiges PNG oder JPEG\)\.",
        "The logo could not be read (not a valid PNG or JPEG).",
    ),
    (
        r"Das Nummernformat braucht \{seq\}, \{seq4\} oder \{seq5\} und darf nur \{prefix\}, \{year\}, \{yy\} enthalten\.",
        "The number format needs {seq}, {seq4} or {seq5} and may only contain {prefix}, {year}, {yy}.",
    ),
    (
        r"„(?P<k>\w+)“ ist zu lang \(höchstens (?P<n>\d+) Zeichen\)\.",
        r"“\g<k>” is too long (at most \g<n> characters).",
    ),
    (r"Umsatzsteuer muss eine Zahl sein\.", "VAT must be a number."),
    (r"Umsatzsteuer muss zwischen 0 und 30 Prozent liegen\.", "VAT must be between 0 and 30 percent."),
    (r"Gültigkeit muss eine ganze Zahl sein\.", "Validity must be a whole number."),
    (r"Gültigkeit muss zwischen 0 und 365 Tagen liegen\.", "Validity must be between 0 and 365 days."),
    (r"Firmendaten müssen ein Objekt sein\.", "Company data must be an object."),
    # --- Fernzugriff (Tailscale) -------------------------------------------------------------------------------
    (r"Fernzugriff nur mit eingeschalteter Anmeldung\.", "Remote access requires authentication to be enabled."),
    (r"Fernzugriff gibt es nur unter Linux\.", "Remote access is only available on Linux."),
    (r"Slicer-Freigabe fehlgeschlagen \(Port (?P<p>\d+)\): ", r"Slicer sharing failed (port \g<p>): "),
    (r"HTTPS-Freigabe fehlgeschlagen: ", "HTTPS sharing failed: "),
    (r"Tailscale ist nicht installiert\.", "Tailscale is not installed."),
    (r"Noch nicht bei Tailscale angemeldet\.", "Not signed in to Tailscale yet."),
    (
        r"Prüfsumme des Tailscale-Downloads stimmt nicht — abgebrochen\.",
        "Checksum of the Tailscale download does not match — aborted.",
    ),
    (r"Prüfsumme von Tailscale nicht lesbar\.", "Tailscale checksum not readable."),
    (r"Kein passendes Tailscale-Paket gefunden\.", "No matching Tailscale package found."),
    (r"Tailscale-Download ist unerwartet groß\.", "Tailscale download is unexpectedly large."),
    (
        r"Das Tailscale-Archiv enthält nicht die erwarteten Programme\.",
        "The Tailscale archive does not contain the expected programs.",
    ),
    (r"Unbekannte Prozessorarchitektur: ", "Unknown processor architecture: "),
    (r"tailscaled hat sich sofort beendet\.", "tailscaled exited immediately."),
    (r"tailscaled ist nicht rechtzeitig bereit geworden\.", "tailscaled did not become ready in time."),
    (r"Tailscale-Anmeldung nicht möglich: ", "Tailscale sign-in not possible: "),
    (r"Freigabe fehlgeschlagen: ", "Sharing failed: "),
    (r"Ungültiger Port\.", "Invalid port."),
    (r"Zeitüberschreitung beim Aufruf von tailscale\.", "Timeout while calling tailscale."),
    (r"Programm nicht startbar: ", "Program could not be started: "),
    # --- Update-Schutz und Signaturprüfung ----------------------------------------------------------------
    (r"Der aktuelle Git-Stand ist nicht lesbar\.", "The current Git state cannot be read."),
    (r"Sicherung nicht möglich: ", "Backup not possible: "),
    (r"Die Sicherung von (?P<f>\S+) ist nicht in Ordnung\.", r"The backup of \g<f> is not valid."),
    (r"Ungültiger Name der Sicherung\.", "Invalid backup name."),
    (r"Diese Sicherung gibt es nicht mehr\.", "This backup no longer exists."),
    (r"Die Sicherung enthält keine Datenbank\.", "The backup contains no database."),
    (
        r"Die Sicherung ist beschädigt \((?P<f>[^)]*)\) und wird nicht eingespielt\.",
        r"The backup is damaged (\g<f>) and will not be restored.",
    ),
    (r"Wiederherstellen nur mit eingeschalteter Anmeldung\.", "Restoring requires authentication to be enabled."),
    (
        r"Wiederherstellen geht nur mit dem Update-Schutz im Dienst \(Installer erneut ausführen\)\.",
        "Restoring needs the update guard in the service (run the installer again).",
    ),
    (r"Ungültiger Tag-Name\.", "Invalid tag name."),
    (r"Der Release-Name ist ungültig\.", "The release name is invalid."),
    (
        r"Die Datei mit den erlaubten Schlüsseln enthält keinen gültigen Schlüssel\.",
        "The file with the allowed keys contains no valid key.",
    ),
    (
        r"ssh-keygen fehlt \(Paket openssh-client\); die Signatur kann nicht geprüft werden\.",
        "ssh-keygen is missing (package openssh-client); the signature cannot be checked.",
    ),
    (r"Die Signaturprüfung hat zu lange gedauert\.", "The signature check took too long."),
    (r"Der Tag (?P<t>\S+) ist nicht gültig signiert ", r"The tag \g<t> is not validly signed "),
    # --- Rechnungen ---------------------------------------------------------------------------------------
    (
        r"„(?P<f>Leistungsdatum|Zahlungsdatum)“ ist kein gültiges Datum \(JJJJ-MM-TT\)\.",
        r"“\g<f>” is not a valid date (YYYY-MM-DD).",
    ),
    (r"Zu diesem Angebot gibt es schon eine Rechnung\.", "There is already an invoice for this quote."),
    (r"Rechnung nicht gefunden\.", "Invoice not found."),
    (r"Eine stornierte Rechnung kann nicht als bezahlt gelten\.", "A cancelled invoice cannot count as paid."),
    (r"Eine stornierte Rechnung lässt sich nicht wieder öffnen\.", "A cancelled invoice cannot be reopened."),
    (
        r"Eine bezahlte Rechnung wird nicht storniert \(Gutschrift mit der Steuerberatung klären\)\.",
        "A paid invoice is not cancelled (clarify a credit note with your tax advisor).",
    ),
    (r"Zahlungsziel muss eine ganze Zahl sein\.", "Payment term must be a whole number."),
    (r"Zahlungsziel muss zwischen 0 und 365 Tagen liegen\.", "Payment term must be between 0 and 365 days."),
    # --- Meldewege ----------------------------------------------------------------------------------------
    (
        r"Meldewege nur mit eingeschalteter Anmeldung ändern\.",
        "Alert channels can only be changed with authentication enabled.",
    ),
    (
        r"Meldewege nur mit eingeschalteter Anmeldung testen\.",
        "Alert channels can only be tested with authentication enabled.",
    ),
    (r"Es ist noch kein Meldeweg eingerichtet\.", "No alert channel is set up yet."),
    (
        r"Die ntfy-Adresse muss mit http:// oder https:// beginnen\.",
        "The ntfy address must start with http:// or https://.",
    ),
    (
        r"Diese ntfy-Adresse ist nicht erlaubt \(lokal oder Link-Local\)\.",
        "This ntfy address is not allowed (local or link-local).",
    ),
    (
        r"Der Telegram-Token hat nicht die Form 123456789:ABC… \(von @BotFather\)\.",
        "The Telegram token does not look like 123456789:ABC… (from @BotFather).",
    ),
    (
        r"Die Telegram-Chat-Nummer ist ungültig \(Zahl oder @Kanalname\)\.",
        "The Telegram chat ID is invalid (number or @channelname).",
    ),
    # --- Kamera-Prüfungen ---------------------------------------------------------------------------------
    (r"Bilder fehlen: (?P<g>.+)\.", r"Images are missing: \g<g>."),
    (r"Höchstens (?P<n>\d+) Bilder je Gruppe\.", r"At most \g<n> images per group."),
    (r"Nur Bilder \(JPEG oder PNG\) sind erlaubt: ", "Only images (JPEG or PNG) are allowed: "),
    (r"Bild zu groß \(höchstens 8 MB\): ", "Image too large (8 MB at most): "),
    (r"Leeres Bild: ", "Empty image: "),
    (
        r"Keine Referenz für diesen Drucker: erst eine Referenz aufnehmen\.",
        "No reference for this printer: capture a reference first.",
    ),
    (
        r"Schwellwert muss eine Zahl zwischen 0,05 und 50 Prozent sein\.",
        "The threshold must be a number between 0.05 and 50 percent.",
    ),
    (
        r"Es werden Bilder mit leerem UND mit belegtem Bett gebraucht\.",
        "Images with an empty AND with an occupied bed are needed.",
    ),
    (r"Abweichungen können nicht negativ sein\.", "Differences cannot be negative."),
    (r"Keine Einmessung gespeichert\.", "No calibration saved."),
    # --- KI-Assistent ---------------------------------------------------------------------------------------
    (
        r"Der Assistent ist ausgeschaltet\. Schalte ihn unter Wartung → Assistent ein\.",
        "The assistant is turned off. Turn it on under Maintenance → Assistant.",
    ),
    (r"Die letzte Nachricht muss vom Benutzer sein\.", "The last message must be from the user."),
    (
        r"Der Assistent beantwortet gerade eine andere Frage\. Bitte kurz warten\.",
        "The assistant is answering another question right now. Please wait a moment.",
    ),
    (r"Die Adresse muss mit http:// oder https:// beginnen\.", "The address must start with http:// or https://."),
    (r"Diese Adresse ist nicht erlaubt \(Link-Local\)\.", "This address is not allowed (link-local)."),
    (r"Der Modellname fehlt oder ist zu lang\.", "The model name is missing or too long."),
    (
        r"Die Zeitgrenze muss zwischen 10 und 900 Sekunden liegen\.",
        "The time limit must be between 10 and 900 seconds.",
    ),
    (
        r"Die Antwortlänge muss zwischen 50 und 4000 Wörtern \(Tokens\) liegen\.",
        "The answer length must be between 50 and 4000 words (tokens).",
    ),
    (r"„enabled“ muss wahr oder falsch sein\.", "“enabled” must be true or false."),
    (
        r"Shell-Zeichen \((?P<c>.+)\) sind nicht erlaubt — bitte den Befehl als Liste eintragen\.",
        r"Shell characters (\g<c>) are not allowed — please enter the command as a list.",
    ),
    (
        r"Kein Modell-Server unter (?P<u>.+) erreichbar\. Läuft Ollama\?",
        r"No model server reachable at \g<u>. Is Ollama running?",
    ),
    (
        r"Modell „(?P<m>.+)“ nicht gefunden\. Auf dem Pi: ollama pull (?P<p>.+)",
        r"Model “\g<m>” not found. On the Pi: ollama pull \g<p>",
    ),
    (
        r"Das Modell hat nicht rechtzeitig geantwortet \(nach (?P<n>\d+) Sekunden\)\.",
        r"The model did not answer in time (after \g<n> seconds).",
    ),
    (r"Der Modell-Server hat mit Fehler (?P<c>\d+) geantwortet\.", r"The model server answered with error \g<c>."),
    (r"Die Antwort des Modells war leer oder unlesbar\.", "The model's answer was empty or unreadable."),
    (r"Die Systemprüfung läuft bereits\.", "The system check is already running."),
    (r"Kein Kamerabild verfügbar\.", "No camera image available."),
    (r"Warp fehlgeschlagen — Einmessung prüfen\.", "Warp failed — check the calibration."),
]
PATTERNS = [(re.compile(pattern), replacement) for pattern, replacement in _RAW]

# Antworten dieser Endpunkte werden übersetzt (alle anderen bleiben unberührt).
PATH_RX = re.compile(
    r"^/api/v1/(printers/\d+/(hardware|maintenance-program|maintenance-print|bed-empty|spaghetti|part-watcher|"
    r"first-layer|plate-calibration|layer-alert|camera/plate-detection/tuning)|quote|remote-access|updates|system/alerts|assistant|selftest)"
)


def wants_english(accept_language: str | None) -> bool:
    """Deutsch (oder keine Angabe) bleibt Originaltext; jede andere Sprache bekommt Englisch."""
    if not accept_language:
        return False
    primary = accept_language.split(",")[0].strip().lower()
    return bool(primary) and not primary.startswith("de") and primary != "*"


def translate(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def translate_json(value: Any) -> Any:
    if isinstance(value, str):
        return translate(value)
    if isinstance(value, list):
        return [translate_json(item) for item in value]
    if isinstance(value, dict):
        return {key: translate_json(item) for key, item in value.items()}
    return value


class ForkI18nMiddleware:
    """Reiner ASGI-Filter: übersetzt JSON-Antworten der Erweiterungs-Endpunkte, wenn nicht Deutsch gewünscht ist."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not PATH_RX.match(scope.get("path", "")):
            return await self.app(scope, receive, send)
        language = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"accept-language"), None)
        if not wants_english(language):
            return await self.app(scope, receive, send)

        start: dict | None = None
        chunks: list[bytes] = []

        async def wrapped_send(message):
            nonlocal start
            if message["type"] == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                if b"application/json" not in headers.get(b"content-type", b""):
                    await send(message)
                    start = {"passthrough": True}
                    return
                start = message
                return
            if message["type"] == "http.response.body" and start is not None and start.get("passthrough"):
                await send(message)
                return
            if message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(chunks)
                try:
                    body = json.dumps(translate_json(json.loads(body)), ensure_ascii=False).encode("utf-8")
                except ValueError:
                    pass
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped_send)

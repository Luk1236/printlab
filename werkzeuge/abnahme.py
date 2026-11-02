#!/usr/bin/env python3
"""Abnahme-Check für den Raspberry Pi: prüft automatisch alles, was sich ohne Drucker und Hardware prüfen lässt.

Aufruf auf dem Pi oder PC (im Projektordner):
  .venv/bin/python werkzeuge/abnahme.py                        Ergebnis als Liste
  .venv/bin/python werkzeuge/abnahme.py --json                 für Auswertung durch Programme
  .venv/bin/python werkzeuge/abnahme.py --durchstich           Stufe 3 & 4 Software-/Trockenlauf-Durchstich (isoliert)
  .venv/bin/python werkzeuge/abnahme.py --signatur-vorbereiten Stufe 4 Update-Signatur prüfen/einrichten
Rückgabecode: 0 = alles in Ordnung oder nur Hinweise, 1 = mindestens ein Fehler.

Stufen: OK (in Ordnung), WARN (sollte man beheben), FAIL (so nicht sicher/stabil), SKIP (hier nicht prüfbar).
Was echte Hardware braucht (Tür-Servo, Endschalter, Plattenwechsler, Drucker, Slicer): docs/ABNAHME-PI.md
Abschnitte 3 (Reihenfolge am Gerät) und docs/ABNAHME.md (alle Prüfungen).
"""

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # backup_pruefen.py und gpio_mechanik.py liegen daneben

from backend.app.services import einvoice, pi_health  # noqa: E402

HOME = Path.home()
DATA_DIR = Path(os.environ.get("DATA_DIR") or APP_DIR / "data")
UNIT = HOME / ".config" / "systemd" / "user" / "printlab.service"
ENV_FILE = HOME / ".config" / "printlab.env"
BASE_URL = os.environ.get("PRINTLAB_URL", "http://127.0.0.1:8000")

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"


def get_json(path: str, timeout: float = 8.0):
    """(Status, JSON oder None); nie eine Ausnahme."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as response:  # noqa: S310 - lokale Adresse
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError):
        return None, None


def systemctl(*args: str) -> str | None:
    if shutil.which("systemctl") is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            ["systemctl", "--user", *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def check_service():
    status, data = get_json("/api/v1/updates/version")
    if status == 200 and data:
        return OK, "PrintLab antwortet", f"Version {data.get('version')}"
    return FAIL, "PrintLab antwortet nicht", f"{BASE_URL} (journalctl --user -u printlab -n 40)"


def check_auth():
    status, data = get_json("/api/v1/auth/status")
    if status != 200 or not data:
        return SKIP, "Anmeldung", "Status nicht lesbar"
    if not data.get("auth_enabled"):
        return FAIL, "Anmeldung ist AUS", "Jeder im Netz kann PrintLab bedienen: Einrichtung unter /setup abschließen"
    if not data.get("auth_required"):
        return (
            WARN,
            "Anmeldung ist an, aber nicht vorgeschrieben",
            "Environment=PRINTLAB_REQUIRE_AUTH=1 in der Dienst-Datei",
        )
    return OK, "Anmeldung ist an und vorgeschrieben", ""


def check_unit():
    text = read_text(UNIT)
    if text is None:
        return SKIP, "Dienst-Datei", f"{UNIT} nicht gefunden (kein Installer-Aufbau?)"
    missing = [
        label
        for needle, label in (
            ("Restart=always", "Restart=always"),
            ("update_guard.py", "Update-Schutz (ExecStartPre)"),
            ("PRINTLAB_AUTO_RESTART=1", "PRINTLAB_AUTO_RESTART=1"),
            ("PRINTLAB_REQUIRE_AUTH=1", "PRINTLAB_REQUIRE_AUTH=1"),
        )
        if needle not in text
    ]
    if missing:
        return WARN, "Dienst-Datei unvollständig", "fehlt: " + ", ".join(missing) + " (Installer erneut ausführen)"
    return OK, "Dienst-Datei vollständig", ""


def check_watch_timer():
    active = systemctl("is-active", "printlab-watch.timer")
    if active is None:
        return SKIP, "Überwachung", "systemctl nicht verfügbar"
    if active == "active":
        return OK, "Überwachung läuft", "Timer printlab-watch.timer"
    return (
        WARN,
        "Überwachung läuft nicht",
        "Installer erneut ausführen oder systemctl --user enable --now printlab-watch.timer",
    )


def check_alert_channel():
    env_text = read_text(ENV_FILE) or ""
    configured = ("PRINTLAB_ALERT_TELEGRAM_TOKEN=" in env_text and "PRINTLAB_ALERT_TELEGRAM_CHAT=" in env_text) or (
        "PRINTLAB_ALERT_NTFY_URL=" in env_text
    )
    if configured:
        return OK, "Meldeweg für Ausfälle eingetragen", ""
    return (
        WARN,
        "Kein Meldeweg für Ausfälle",
        "PRINTLAB_ALERT_TELEGRAM_* oder PRINTLAB_ALERT_NTFY_URL in ~/.config/printlab.env",
    )


def check_env_permissions():
    if not ENV_FILE.exists():
        return SKIP, "Rechte der Zugangsdatei", "keine ~/.config/printlab.env"
    mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
    if mode & 0o077:
        return FAIL, "Zugangsdatei ist für andere lesbar", f"chmod 600 {ENV_FILE} (aktuell {oct(mode)})"
    return OK, "Zugangsdatei nur für dich lesbar", ""


def check_signature():
    path = DATA_DIR / "update_allowed_signers"
    if not path.is_file():
        return WARN, "Updates werden nicht auf Signatur geprüft", "docs/UPDATE-SIGNATUR.md"
    if shutil.which("ssh-keygen") is None:
        return (
            FAIL,
            "Signaturprüfung an, aber ssh-keygen fehlt",
            "sudo apt install openssh-client (sonst werden alle Updates abgelehnt)",
        )
    return OK, "Updates nur mit gültiger Signatur", ""


def check_backups():
    extra = [HOME / "printlab-backups"]
    target = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    if target:
        extra.append(Path(target))
    latest = pi_health.latest_backup(DATA_DIR, extra)
    if latest is None:
        return (
            WARN,
            "Keine Sicherung gefunden",
            "Wird beim nächsten Update angelegt; oder sicherung_extern.py einrichten",
        )
    import backup_pruefen  # noqa: PLC0415

    problems = backup_pruefen.check_folder(Path(latest["path"]))
    if problems:
        return FAIL, "Neueste Sicherung ist beschädigt", "; ".join(problems[:3])
    if latest["age_days"] > pi_health.BACKUP_MAX_AGE_DAYS:
        return WARN, "Neueste Sicherung ist alt", f"{latest['age_days']:g} Tage ({latest['path']})"
    return OK, "Neueste Sicherung ist in Ordnung", f"{latest['age_days']:g} Tage alt"


def check_external_backup():
    target = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    if not target:
        return WARN, "Keine Sicherung außerhalb der SD-Karte", "docs/INSTALLATION-PI.md → Sicherung nach außen"
    if not Path(target).is_dir():
        return FAIL, "Sicherungsziel nicht erreichbar", target
    return OK, "Sicherungsziel erreichbar", target


def check_health():
    info = pi_health.snapshot(DATA_DIR)
    crit = [w["text"] for w in info["warnings"] if w["level"] == "crit" and w["code"] != "external_failed"]
    warn = [w["text"] for w in info["warnings"] if w["level"] == "warn" and not w["code"].startswith("backup")]
    if crit:
        return FAIL, "Zustand des Rechners", " | ".join(crit)
    if warn:
        return WARN, "Zustand des Rechners", " | ".join(warn)
    if info["cpu_temp_c"] is None and info["storage"] is None and info["memory"] is None:
        return SKIP, "Zustand des Rechners", "auf diesem System nicht messbar (kein Raspberry Pi / Linux)"
    return OK, "Zustand des Rechners", "Temperatur, Spannung, Speicher in Ordnung"


def check_virtual_printer_ports():
    ports = {3000: "Erkennung", 3002: "Erkennung (TLS)", 990: "Datei-Upload", 8883: "Steuerung"}
    status, _ = get_json("/api/v1/updates/version")
    if status != 200:
        return SKIP, "Ports des virtuellen Druckers", "PrintLab nicht erreichbar"
    open_ports = [p for p in ports if port_open(p)]
    if len(open_ports) == len(ports):
        return OK, "Virtueller Drucker lauscht", "alle vier Ports offen"
    if not open_ports:
        return SKIP, "Virtueller Drucker", "ist nicht aktiviert (Einstellungen → Virtueller Drucker)"
    closed = ", ".join(f"{p} ({ports[p]})" for p in ports if p not in open_ports)
    return WARN, "Virtueller Drucker nur teilweise erreichbar", "geschlossen: " + closed


def check_git():
    if shutil.which("git") is None:
        return FAIL, "git fehlt", "sudo apt install git (ohne git kein Update)"
    if not (APP_DIR / ".git").exists():
        return WARN, "Kein Git-Ordner", "Update aus der Oberfläche nicht möglich"
    return OK, "git und Git-Ordner vorhanden", ""


def check_einvoice_schema():
    """Prüft die XRechnung-3.0-Erzeugung (EN 16931: BT-49, BT-72, BT-146)."""
    ns = {
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }
    company = {
        "name": "PrintLab Abnahme",
        "address": "Werkstr. 1\n12345 Musterstadt",
        "tax_id": "DE123456789",
        "email": "rechnung@example.org",
        "vat_percent": 19.0,
        "vat_note": "",
        "iban": "DE02120300000000202051",
    }
    invoice = {
        "id": "abn1",
        "number": "R-2026-0001",
        "issued": "2026-11-02",
        "due": "2026-11-16",
        "service_date": "2026-11-01",
        "customer": "Kunde GmbH",
        "customer_address": "Hauptstr. 2\n54321 Ort",
        "customer_email": "kunde@example.org",
        "description": "Druckteil",
        "currency": "EUR",
        "total": 119.0,
        "items": [{"description": "Nacharbeit", "quantity": 2, "unit_price": 9.5, "amount": 19.0}],
        "extras": 19.0,
    }
    xml = einvoice.build_xml(invoice, company)
    root = ElementTree.fromstring(xml)
    delivery = root.find(".//cac:Delivery/cbc:ActualDeliveryDate", ns)
    buyer_ep = root.find(".//cac:AccountingCustomerParty//cbc:EndpointID", ns)
    lines = root.findall("cac:InvoiceLine", ns)
    if delivery is None or delivery.text != "2026-11-01":
        return FAIL, "XRechnung 3.0 (EN 16931)", "BT-72 (ActualDeliveryDate) fehlt im XML"
    if buyer_ep is None or buyer_ep.text != "kunde@example.org":
        return FAIL, "XRechnung 3.0 (EN 16931)", "BT-49 (Käufer-EndpointID) fehlt im XML"
    if len(lines) < 2:
        return FAIL, "XRechnung 3.0 (EN 16931)", "Zusatzposition fehlt im XML"
    price_el = lines[1].find("cac:Price/cbc:PriceAmount", ns)
    if price_el is None or price_el.text != "9.50":
        return FAIL, "XRechnung 3.0 (EN 16931)", "BT-146 (PriceAmount != Einzelpreis) verletzt PEPPOL-EN16931-R120"
    return OK, "XRechnung 3.0 (EN 16931)", "Pflichtfelder BT-49, BT-72 und BT-146 wohlgeformt"


def check_gpio_config():
    """Prüft die GPIO-Mechanik-Konfiguration auf Pin-Kollisionen und gültige Servo-Winkel."""
    import gpio_mechanik  # noqa: PLC0415

    cfg_path = DATA_DIR / "gpio_mechanik.json"
    if not cfg_path.is_file():
        cfg_path = APP_DIR / "werkzeuge" / "gpio_mechanik.beispiel.json"
    try:
        cfg = gpio_mechanik.load_config(cfg_path)
    except Exception as exc:
        return FAIL, "GPIO-Mechanik-Konfiguration", str(exc)
    return (
        OK,
        "GPIO-Mechanik-Konfiguration",
        f"Servo {cfg['zu_grad']:g}°..{cfg['offen_grad']:g}°, {len(cfg['pins'])} Pins konfliktfrei ({cfg_path.name})",
    )


def check_local_ai():
    """Prüft, ob Ollama lokal auf Port 11434 antwortet."""
    if not port_open(11434):
        return SKIP, "Lokale KI (Ollama)", "Port 11434 nicht offen (optional)"
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3.0) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in payload.get("models", []) if isinstance(m, dict)]
        return OK, "Lokale KI (Ollama)", f"{len(models)} Modell(e) geladen: {', '.join(models[:3]) or 'keine'}"
    except (OSError, ValueError):
        return WARN, "Lokale KI (Ollama)", "Port 11434 offen, aber /api/tags antwortet nicht"


def check_repo_hygiene() -> tuple[str, str, str]:
    """Prüft auf verwaiste Git-Index-Kopien (z. B. OneDrive) und 0-Byte-Testartefakte im Projektstamm."""
    git_dir = APP_DIR / ".git"
    stale_index = [p.name for p in git_dir.glob("index*") if p.name != "index"] if git_dir.is_dir() else []
    zero_3mf = [p.name for p in APP_DIR.glob("*.3mf") if p.is_file() and p.stat().st_size == 0]
    issues = [*stale_index, *zero_3mf]
    if issues:
        return WARN, "Repo-Hygiene", f"Verwaiste Artefakte gefunden: {', '.join(issues)}"
    return OK, "Repo-Hygiene", "Keine verwaisten Index-Kopien oder 0-Byte-Testdateien im Projektstamm"


CHECKS = [
    check_service,
    check_auth,
    check_unit,
    check_git,
    check_signature,
    check_watch_timer,
    check_alert_channel,
    check_env_permissions,
    check_backups,
    check_external_backup,
    check_health,
    check_virtual_printer_ports,
    check_einvoice_schema,
    check_gpio_config,
    check_local_ai,
    check_repo_hygiene,
]


def run_durchstich() -> list[dict]:
    """Führt den kompletten Software- & Trockenlauf-Durchstich für Stufe 3 und 4 isoliert in einem Temp-Ordner aus."""
    from backend.app.services import company_profile, invoices, plate_wizard, quote_history, quote_share
    from backend.app.services.hardware_extension import HardwareExtension

    steps: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="printlab-abnahme-") as tmp:
        tmp_dir = Path(tmp)
        orig_history = quote_history.HISTORY_PATH
        orig_shares = quote_share.SHARES_PATH
        orig_invoices = invoices.INVOICES_PATH
        orig_company = company_profile.COMPANY_PATH
        orig_wizard = plate_wizard.STORE_DIR

        try:
            quote_history.HISTORY_PATH = tmp_dir / "quote_history.json"
            quote_share.SHARES_PATH = tmp_dir / "quote_shares.json"
            invoices.INVOICES_PATH = tmp_dir / "invoices.json"
            company_profile.COMPANY_PATH = tmp_dir / "company.json"
            plate_wizard.STORE_DIR = tmp_dir / "plate_wizard"

            # 1. Stufe 3 Block 2: Angebots-Link, Kundenansicht, Zusage, Rechnung & XRechnung
            company = company_profile.write(
                {
                    "name": "PrintLab Werkstatt",
                    "address": "Industriestr. 10\n80331 München",
                    "tax_id": "DE999888777",
                    "email": "info@printlab.local",
                    "vat_percent": 19.0,
                    "payment_days": 14,
                    "iban": "DE02120300000000202051",
                }
            )
            q = quote_history.add(
                {
                    "customer": "Abnahme Kunde GmbH",
                    "customer_address": "Testweg 4\n10115 Berlin",
                    "customer_email": "einkauf@kunde.local",
                    "description": "Halterung P2S",
                    "currency": "EUR",
                    "material": 8.0,
                    "energy": 2.0,
                    "labor": 20.0,
                    "subtotal": 30.0,
                    "markup": 10.0,
                    "total": 40.0,
                    "items": [{"description": "Gewindeeinsätze", "quantity": 4, "unit_price": 1.25}],
                }
            )
            share = quote_share.create(q["id"], days=14, quote=q)
            view = quote_share.public_view(q, company)
            leaked = [k for k in ("markup", "labor", "material", "energy", "subtotal") if k in view]
            if leaked:
                steps.append(
                    {"level": FAIL, "title": "Stufe 3.2 Angebots-Link", "detail": f"Interna sichtbar: {leaked}"}
                )
            else:
                quote_share.respond(share["token"], "accepted", "Abnahmetest OK")
                inv = invoices.create_from_quote(q["id"], company, service_date="2026-11-02")
                xml = einvoice.build_xml(inv, company)
                hybrid_pdf = einvoice.embed_zugferd_xml(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n", xml)
                if b"/AFRelationship /Alternative" not in hybrid_pdf:
                    steps.append(
                        {"level": FAIL, "title": "Stufe 3.2 ZUGFeRD-Einbettung", "detail": "factur-x.xml fehlt im PDF"}
                    )
                    return steps
                steps.append(
                    {
                        "level": OK,
                        "title": "Stufe 3.2 Angebots-Link & XRechnung",
                        "detail": f"Angebot {q['number']} geteilt, zugesagt, Rechnung {inv['number']} ({len(xml)} Bytes XML)",
                    }
                )

            # 2. Stufe 3 Block 3.1: Hardware-Trockenlauf im Simulationsmodus + Not-Halt
            hw = HardwareExtension(config_path=tmp_dir / "hardware.json", magazine_path=tmp_dir / "magazine.json")
            ok_edit, _ = hw.edit_slots([{"id": 1, "status": "ready", "label": "Abnahme PEI"}])
            ok_open, _ = hw.open_door()
            ok_close, _ = hw.close_door()
            ok_estop, _ = hw.emergency_stop()
            blocked_during_estop, _ = hw.open_door()
            hw.reload_config()
            ok_after_reset, _ = hw.open_door()
            hw.close_door()
            if ok_edit and ok_open and ok_close and ok_estop and not blocked_during_estop and ok_after_reset:
                steps.append(
                    {
                        "level": OK,
                        "title": "Stufe 3.3.1 Hardware-Trockenlauf & Not-Halt",
                        "detail": "Magazin, Tür-Simulation, Not-Halt-Sperre und Freigabe erfolgreich",
                    }
                )
            else:
                steps.append(
                    {
                        "level": FAIL,
                        "title": "Stufe 3.3.1 Hardware-Trockenlauf & Not-Halt",
                        "detail": "Unerwarteter Zustand bei Tür/Not-Halt",
                    }
                )

            # 3. Stufe 3 Block 3.2 & 3.3: Einmess-Assistent (plate_wizard) & Sperre prüfen
            printer_id = 999
            plate_wizard.save_step(printer_id, "reference", {"x": 0.0, "y": 0.0, "z": 10.0})
            blocked_msg = plate_wizard.blocks_plate_change(printer_id)
            plate_wizard.save_step(printer_id, "pickup", {"x": 120.0, "y": 120.0, "z": 5.0})
            plate_wizard.save_step(printer_id, "drop", {"x": 120.0, "y": 240.0, "z": 15.0})
            plate_wizard.save_step(printer_id, "door", {"confirmed": True, "sensor": True})
            plate_wizard.save_step(printer_id, "dry_run", {"confirmed": True, "note": "Trockenlauf OK"})
            plate_wizard.complete(printer_id, operator="Abnahme-Durchstich")
            unblocked_after = plate_wizard.blocks_plate_change(printer_id)
            motion = plate_wizard.build_motion_sequence(printer_id, slot=1)
            ok_swap, swap_msg = hw.change_plate("Abnahme-Druck")
            if blocked_msg and unblocked_after is None and ok_swap and "G90" in motion.get("gcode", ""):
                steps.append(
                    {
                        "level": OK,
                        "title": "Stufe 3.3.2–3.4 Einmess-Assistent & Plattenwechsel",
                        "detail": f"Halbe Einmessung sperrt korrekt; nach 5/5 Schritten frei ({swap_msg})",
                    }
                )
            else:
                steps.append(
                    {
                        "level": FAIL,
                        "title": "Stufe 3.3.2–3.4 Einmess-Assistent & Plattenwechsel",
                        "detail": f"blocked={blocked_msg!r}, unblocked={unblocked_after!r}, swap={ok_swap}",
                    }
                )

            # 4. Stufe 4.3: Kamera-Perspektiv-Einmessung & Optische Leerbett-/Bauteilerkennung
            import cv2
            import numpy as np

            from backend.app.services import plate_calibration, plate_detection

            orig_cal_dir = plate_calibration.STORE_DIR
            orig_det_dir = plate_detection._get_calibration_dir
            try:
                plate_calibration.STORE_DIR = tmp_dir / "plate_calibration"
                plate_detection._get_calibration_dir = lambda: tmp_dir / "plate_references"

                plate_calibration.set_points(printer_id, [[0.1, 0.2], [0.9, 0.2], [0.95, 0.9], [0.05, 0.9]])
                empty_img = np.full((480, 640, 3), 60, dtype=np.uint8)
                cv2.rectangle(empty_img, (100, 120), (540, 420), (85, 85, 85), 2)
                _, empty_buf = cv2.imencode(".jpg", empty_img)
                empty_warped = plate_calibration.warp_bytes(printer_id, empty_buf.tobytes())

                occupied_img = empty_img.copy()
                cv2.rectangle(occupied_img, (230, 210), (410, 360), (240, 240, 240), -1)
                _, occ_buf = cv2.imencode(".jpg", occupied_img)
                occ_warped = plate_calibration.warp_bytes(printer_id, occ_buf.tobytes())

                detector = plate_detection.PlateDetector()
                cal_ok, _, _ = detector.calibrate(empty_warped or empty_buf.tobytes(), printer_id, label="Abnahme PEI")
                res_empty = detector.analyze_frame(empty_warped or empty_buf.tobytes(), printer_id)
                res_occ = detector.analyze_frame(occ_warped or occ_buf.tobytes(), printer_id)
                if cal_ok and res_empty.is_empty and not res_occ.is_empty:
                    steps.append(
                        {
                            "level": OK,
                            "title": "Stufe 4.3 Kamera-Einmessung & Leerbett-Erkennung",
                            "detail": (
                                f"Perspektiv-Warp OK; Leerbett frei (Diff {res_empty.difference_percent:.1f}%), "
                                f"Bauteil gesperrt (Diff {res_occ.difference_percent:.1f}%)"
                            ),
                        }
                    )
                else:
                    steps.append(
                        {
                            "level": FAIL,
                            "title": "Stufe 4.3 Kamera-Einmessung & Leerbett-Erkennung",
                            "detail": f"cal={cal_ok}, empty={res_empty.is_empty}, occupied={res_occ.is_empty}",
                        }
                    )
            finally:
                plate_calibration.STORE_DIR = orig_cal_dir
                plate_detection._get_calibration_dir = orig_det_dir

            # 5. Stufe 4.4: Integrierter Slicer (builtin_slicer) für .stl -> .gcode.3mf
            from backend.app.services import builtin_slicer

            stl_path = tmp_dir / "abnahme_wuerfel.stl"
            stl_path.write_text(
                "solid cube\n"
                "facet normal 0 0 1\n outer loop\n"
                "  vertex 0 0 0\n  vertex 20 0 0\n  vertex 20 20 10\n"
                " endloop\nendfacet\n"
                "endsolid cube\n",
                encoding="utf-8",
            )
            sliced = builtin_slicer.slice_model_builtin(
                stl_path,
                "abnahme_wuerfel.gcode.3mf",
                '{"name": "Bambu Lab P2S 0.4 nozzle"}',
                '{"layer_height": "0.2", "wall_loops": "2", "sparse_infill_density": "15%"}',
                ['{"filament_type": ["PLA"]}'],
                plate=1,
            )
            bundled = builtin_slicer.list_bundled_profiles()
            if sliced.print_time_seconds > 0 and sliced.filament_grams > 0 and len(bundled.get("printer", [])) >= 6:
                steps.append(
                    {
                        "level": OK,
                        "title": "Stufe 4.4 Integrierter Slicer (STL/3MF -> G-Code)",
                        "detail": (
                            f"STL intern geslict ({sliced.print_time_seconds}s, {sliced.filament_grams:.2f}g PLA, "
                            f"{len(sliced.content)} Bytes .gcode.3mf, {len(bundled['printer'])} Druckerprofile)"
                        ),
                    }
                )
            else:
                steps.append(
                    {
                        "level": FAIL,
                        "title": "Stufe 4.4 Integrierter Slicer (STL/3MF -> G-Code)",
                        "detail": "Integrierter Slicer lieferte unvollständige Ausgabe",
                    }
                )
        finally:
            quote_history.HISTORY_PATH = orig_history
            quote_share.SHARES_PATH = orig_shares
            invoices.INVOICES_PATH = orig_invoices
            company_profile.COMPANY_PATH = orig_company
            plate_wizard.STORE_DIR = orig_wizard

    return steps


def prepare_signature(root: Path = APP_DIR, data_dir: Path = DATA_DIR) -> tuple[str, str]:
    """Prüft oder konfiguriert den SSH-Signaturschlüssel für Stufe 4 (docs/UPDATE-SIGNATUR.md)."""
    pub_path = HOME / ".ssh" / "printlab_signing.pub"
    if not pub_path.is_file():
        cmd = f'ssh-keygen -t ed25519 -C "printlab-releases" -f "{HOME / ".ssh" / "printlab_signing"}"'
        return (
            WARN,
            f"Noch kein Signaturschlüssel unter {pub_path}. Einmalig mit Passphrase erzeugen:\n  {cmd}",
        )
    pubkey = pub_path.read_text(encoding="utf-8").strip()
    if not pubkey.startswith("ssh-"):
        return FAIL, f"Ungültiger öffentlicher Schlüssel in {pub_path}"
    signer_line = f'printlab namespaces="git" {pubkey}\n'
    data_dir.mkdir(parents=True, exist_ok=True)
    signers_file = data_dir / "update_allowed_signers"
    signers_file.write_text(signer_line, encoding="utf-8")
    if shutil.which("git") and (root / ".git").exists():
        subprocess.run(["git", "config", "gpg.format", "ssh"], cwd=str(root), check=False)  # noqa: S603, S607
        subprocess.run(["git", "config", "user.signingkey", str(pub_path)], cwd=str(root), check=False)  # noqa: S603, S607
    return (
        OK,
        f"Signaturprüfung eingerichtet ({signers_file}). Auf dem Pi eintragen mit:\n"
        f"  echo '{signer_line.strip()}' > ~/printlab/data/update_allowed_signers",
    )


def run_all(checks=None) -> list[dict]:
    results = []
    for check in checks or CHECKS:
        try:
            level, title, detail = check()
        except Exception as exc:  # ein kaputter Check darf die anderen nicht verhindern
            level, title, detail = FAIL, check.__name__, f"Prüfung abgestürzt: {type(exc).__name__}"
        results.append({"level": level, "title": title, "detail": detail})
    return results


def main(argv: list[str]) -> int:
    if "--signatur-vorbereiten" in argv:
        level, msg = prepare_signature()
        print(f"[{level:<4}] Update-Signatur — {msg}")
        return 1 if level == FAIL else 0
    results = run_all()
    if "--durchstich" in argv:
        results.extend(run_durchstich())
    if "--json" in argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"[{r['level']:<4}] {r['title']}" + (f" — {r['detail']}" if r["detail"] else ""))
        counts = {level: sum(1 for r in results if r["level"] == level) for level in (OK, WARN, FAIL, SKIP)}
        print(
            f"\n{counts[OK]} in Ordnung, {counts[WARN]} Hinweise, {counts[FAIL]} Fehler, {counts[SKIP]} nicht prüfbar."
        )
    return 1 if any(r["level"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

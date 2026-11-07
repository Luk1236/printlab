# PrintLab Gesamtaudit & Systembenotung (v2.0.29)

**Stand:** 07. November 2026 · **Zweig:** `bambu-monitor-port` · **Zielsystem:** Raspberry Pi 5 & Windows-Entwicklung  
**Umfang des Audits:** 507 Backend-Python-Dateien (~9,2 MB), 764 Frontend-Dateien (~17,6 MB), >14.000 Backend-Tests & >4.200 Frontend-Tests.

---

## 1. Executive Summary & Notenspiegel

PrintLab ist eine hochgradig spezialisierte, produktionsreife All-in-One-Lösung für 3D-Druck-Farmen mit Bambu Lab Druckern (P1S, X1C, A1, H2D). Die Software kombiniert Druckersteuerung, Schneidprogramm (Slicer), Werkstück-Automatisierung (Plattenwechsler), Kostenrechnung nach EU-Standards (XRechnung) und Spulen-Tracking.

### Notenübersicht der 10 Systembereiche

| # | Systembereich | Note | Status | Kernfokus |
|---|---|:---:|:---:|---|
| 1 | **Slicer & Slicing-Pipeline** | **2,0** *(Gut)* | Stabil | Sentinel-Sanitizer greift; Preset-Manager & Multi-Plate-Batching offen |
| 2 | **Drucker-Anbindung & Protokoll (MQTT/FTPS)** | **1,8** *(Gut)* | Sehr robust | Reconnect-Zyklen solide; `bambu_mqtt.py` (7.544 Z.) Monolith |
| 3 | **Auftrags-Warteschlange & Druck-Scheduler** | **2,2** *(Gut)* | Funktional | Scheduler (`print_scheduler.py`, 3.576 Z.) hochkomplex, Edge-Cases bei Abkühlung |
| 4 | **Filament- & AMS-Management (SpoolBuddy)** | **1,9** *(Gut)* | Innovativ | NFC/RFID top; Automatischer Spool-Fallback (Auto-Switch) fehlt |
| 5 | **Hardware-Automatisierung & Mechanik** | **2,3** *(Befriedigend+)* | Gut konzipiert | Magazin/Tür im Trockenlauf grün; Hardware-Not-Aus & Entprellung am Pi ausstehend |
| 6 | **Optische Prüfung & Computer Vision** | **2,1** *(Gut)* | Gut | Homographie & Leerbett zuverlässig; Spaghetti-Detektor braucht Edge-KI |
| 7 | **Dateiverwaltung, Bibliothek & 3D-Viewer** | **1,7** *(Gut bis Sehr gut)* | Exzellent | Three.js & Diamond-Toolpath stark; `library.py` (5.345 Z.) modularisieren |
| 8 | **Kalkulation, XRechnung & Finanzen** | **1,4** *(Sehr gut)* | Ausgezeichnet | Revisionssichere XRechnung, Stripe-Checkout & BWA-Ready; Spitzenklasse |
| 9 | **Sicherheit, Auth & Rechtemanagement** | **1,5** *(Sehr gut)* | Härtung top | RBAC, SSRF-Filter, signierte Git-Tags; API-Keys noch ohne Feingranularität |
| 10 | **System, DevOps, Updates & Pi-Betrieb** | **1,6** *(Sehr gut)* | Sehr zuverlässig | 1-Klick-Update mit Auto-Rollback; Pi-Systemd-Verwirrung (User vs. Root) |
| **GESAMT** | **Gesamtnote PrintLab** | **1,85** | **Gut (Reif)** | **Produktionsreif mit Optimierungsbedarf bei Monolithen** |

---

## 2. Detaillierte Analyse aller 10 Systembereiche

### Bereich 1: Slicer-Subsystem & Slicing-Pipeline (Note: 2,0)
- **Stärken:** OrcaSlicer-CLI auf ARM64/x86_64, Sentinel-Sanitizer gegen Bambu Studio `-1`-Werte, automatischer Retry bei Range-Fehlern, neuer Cache-Cleaner in v2.0.29.
- **Schwächen/Fehler:** Abhängigkeit von Linux-Paketen (`libwebkit2gtk-4.1-0`); Preset-Auswahl im UI noch unstrukturiert.
- **Verbesserungen/Erweiterungen:** Phase 3 Slicer-Preset-Manager UI, Batch-Slicing für mehrere Druckteile, Cloud-Profil-Import.

### Bereich 2: Drucker-Anbindung & Bambu-Lab-Protokoll (Note: 1,8)
- **Stärken:** Lokales MQTT über TLS ohne Cloud-Zwang, FTPS-Upload, mDNS-Erkennung, Dual-Extruder H2D-Support.
- **Schwächen/Fehler:** Große Monolithen (`bambu_mqtt.py` 7.544 Z., `PrinterCard.tsx` 5.038 Z.), TLS-Timeout bei schlechtem WLAN.
- **Verbesserungen/Erweiterungen:** Aufspaltung von `PrinterCard.tsx`, asynchroner Upload-Pool, Klipper/Moonraker-Brücke.

### Bereich 3: Auftrags-Warteschlange & Druck-Scheduler (Note: 2,2)
- **Stärken:** Material- und Düsen-Matching, Heizbett-Abkühlüberwachung, Express-Prioritäten.
- **Schwächen/Fehler:** `print_scheduler.py` (3.576 Z.) hochkomplex, seltene Race-Condition zwischen Abkühlung und Folgejob.
- **Verbesserungen/Erweiterungen:** Formale Zustandsmaschine (FSM), Drag-and-Drop Neuordnung, Farm-Lastverteilung.

### Bereich 4: Filament- & AMS-Management (SpoolBuddy) (Note: 1,9)
- **Stärken:** NTAG213/215 RFID-Tags, Spoolman-Anbindung, genaue Gewichtsabzüge nach dem Druck.
- **Schwächen/Fehler:** Kein automatischer Spulenwechsel bei leerer Rolle im selben AMS.
- **Verbesserungen/Erweiterungen:** Phase 4 AMS Spool Auto-Fallback, Feuchtigkeitsverlauf-Chart, Spulen-Restlängenrechner.

### Bereich 5: Hardware-Automatisierung & Mechanik (Note: 2,3)
- **Stärken:** Magazin- und Fachlogik für Plattenwechsler, Smart-Plug-Integration (Shelly/Tasmota), Trockenlauf-Tests grün.
- **Schwächen/Fehler:** Bisher reine Simulation ohne Echttest am Pi; keine Hardware-Taster-Entprellung.
- **Verbesserungen/Erweiterungen:** Phase 5 GPIO-Entprellung & Not-Halt-Dienst, Servo-Winkel-Justierassistent, WS2812B Status-LEDs.

### Bereich 6: Optische Qualitätsprüfung & Computer Vision (Note: 2,1)
- **Stärken:** 4-Punkt-Homographie, Leerbett-Erkennung mit SSIM, Multi-Kamera-Wand (Cam-Wall).
- **Schwächen/Fehler:** Wechsellicht kann Fehlalarme auslösen; einfache Schwellenwert-Spaghetti-Erkennung.
- **Verbesserungen/Erweiterungen:** Histogramm-Angleichung (CLAHE), Phase 6 ONNX/YOLOv8 Edge-KI Spaghetti-Detektor auf dem Pi 5.

### Bereich 7: Dateiverwaltung, Bibliothek & 3D-Viewer (Note: 1,7)
- **Stärken:** 3D Three.js G-Code Viewer mit Layer-Slider, STL/3MF-Vorschau, Ordner- und Tag-System.
- **Schwächen/Fehler:** `library.py` (5.345 Z.) überfrachtet, große G-Code-Dateien belasten schwache Mobilgeräte.
- **Verbesserungen/Erweiterungen:** Aufteilung von `library.py`, G-Code Streaming-Parser, 3D-Modell-Drehung & Zuschnitt im Web.

### Bereich 8: Wirtschaftlichkeit, Kalkulation & Abrechnung (Note: 1,4)
- **Stärken:** Präzise Kostensätze (Maschine, Strom, Material, Rüstzeit), EU-konforme XRechnung 3.0.1 (XML), Stripe-Checkout, PDF-Angebote.
- **Schwächen/Fehler:** Währung fest auf EUR, noch kein automatischer Rechnungs-E-Mail-Versand.
- **Verbesserungen/Erweiterungen:** Phase 7 Kundenportal 2.0 (Live-Sofort-Kalkulator mit STL-Upload), DATEV-Export.

### Bereich 9: Sicherheit, Authentifizierung & Rechtemanagement (Note: 1,5)
- **Stärken:** Strikter SSRF-Schutz, Fail-Closed Auth-Modus, RBAC-Rollen, kryptografisch signierte Git-Tags für Updates.
- **Schwächen/Fehler:** Im LAN ohne Tailscale unverschlüsselt (HTTP); API-Keys nicht feingranular auf Drucker einschränkbar.
- **Verbesserungen/Erweiterungen:** Scoped API-Keys, Zwei-Faktor-Authentifizierung (2FA / WebAuthn Passkeys).

### Bereich 10: System, Betrieb, Updates & DevOps (Note: 1,6)
- **Stärken:** 1-Klick-Web-Update mit DB-Integritätsprüfung, automatischer Rollback-Watchdog, Pi 5 Hardware-Monitoring.
- **Schwächen/Fehler:** Verwirrung zwischen Systemd-User (`systemctl --user`) und Root (`sudo`), Log-Verschleiß auf SD-Karten.
- **Verbesserungen/Erweiterungen:** "System Doctor" im UI für 1-Klick-Reparatur von Pi-Paketen, RAM-Disk für Logs, SSD-Migrationsskript.

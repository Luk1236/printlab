# Versionierung — PrintLab

## Quellen

| Version | Quelle | Bedeutung |
|---|---|---|
| `1.3.0` | `backend/app/core/config.py` → `PRINTLAB_VERSION` (= `APP_VERSION`) | Einzige Versionsquelle von PrintLab. Wird in der Oberfläche angezeigt und für die Update-Prüfung gegen `Luk1236/printlab` benutzt; bei jedem Release zusammen mit dem Git-Tag erhöhen. Der Basisstand der Herkunft (Bambuddy 1.2.5.7) steht in `NOTICE`. |
| Fork-Version `1.0.0` | Git-Tags (`v1.0.0`) + Git-Hub-Releases | Eigene Version des Forks; wächst unabhängig vom Upstream. |

## Schema

[SemVer](https://semver.org/): `vX.Y.Z`

- **X (major):** grundlegende Umstrukturierung, inkompatible Einstellungen/Migrationen
- **Y (minor):** neue Funktionen (z. B. die in `TODO.md` geplanten)
- **Z (patch):** Fehlerbehebungen, Design-/Textkorrekturen

## Wie eine Version angelegt wird

```powershell
# 1. Commits fertig und getestet (Build, relevante Tests); PRINTLAB_VERSION in config.py erhöhen
# 2. Tag setzen (annotated)
git tag v1.1.0 -a -m "PrintLab v1.1.0 — Kurzbeschreibung"
# 3. Branch und Tag hochladen
git push origin bambu-monitor-port v1.1.0
# 4. Release anlegen (Notes im Editor oder --notes)
gh release create v1.1.0 --repo Luk1236/printlab --title "PrintLab v1.1.0" --notes "..."
```

Vorlage für Release-Notes: Release v1.0.0 auf GitHub.

## Verhältnis zum Upstream

- Upstream (`upstream` = maziggy/bambuddy) wird **nicht** gepusht, sondern nur geholt:
  `git fetch upstream --tags`
- Merge von Upstream-Fixen hinein, wenn nötig: `git merge upstream/bambu-monitor-port`
- `APP_VERSION` (Upstream-Wert) bleibt aktuell, bis der Upstream selbst neu veröffentlicht;
  die Fork-Version lebt in den Tags und Releases.

## Status

- Repository: <https://github.com/Luk1236/printlab> (privat, Branch `bambu-monitor-port` = Standard)
- Aktuell: **v1.3.0** (2026-10-28) — Fehler-/Verbesserungsbau: Backup-Skript (`printlab.db`), Tür-Status-Endpunkt, Slicer-Token im Client, Audit-Log (Anfügen + `data/`), Startwarnung ohne Anmeldung, CI-Sicherheits-Schwellen
- Davor: v1.2.2, v1.2.1, v1.2.0, v1.1.0, v1.0.0 (2026-10-27) — Bambu-Monitor-Port, PrintLab-Rebrand, Prusa-Design
- Nächste geplante Version: v1.4.0 mit `main.py`-Refactor (Event-Callbacks in Services), eigenem Tab „Hardware & Optik“, kalibrierbaren Kamera-Schwellen je Drucker
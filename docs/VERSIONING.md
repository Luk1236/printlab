# Versionierung — PrintLab

## Quellen

| Version | Quelle | Bedeutung |
|---|---|---|
| `1.10.0` | `backend/app/core/config.py` → `PRINTLAB_VERSION` (= `APP_VERSION`) | Einzige Versionsquelle von PrintLab. Wird in der Oberfläche angezeigt und für die Update-Prüfung gegen `Luk1236/printlab` benutzt; bei jedem Release zusammen mit dem Git-Tag erhöhen. Der Basisstand der Herkunft (Bambuddy 1.2.5.7) steht in `NOTICE`. |
| Fork-Version `1.0.0` | Git-Tags (`v1.0.0`) + Git-Hub-Releases | Eigene Version des Forks; wächst unabhängig vom Upstream. |

## Schema

[SemVer](https://semver.org/): `vX.Y.Z`

- **X (major):** grundlegende Umstrukturierung, inkompatible Einstellungen/Migrationen
- **Y (minor):** neue Funktionen (z. B. die in `TODO.md` geplanten)
- **Z (patch):** Fehlerbehebungen, Design-/Textkorrekturen

## Wie eine Version angelegt wird

```powershell
# 1. Commits fertig und getestet (Build, relevante Tests); PRINTLAB_VERSION in config.py erhöhen,
#    CHANGELOG.md-Abschnitt anlegen und den Stand von static/ vom Build-Workflow holen.
# 2. Release-Skript verwenden: es prüft Version, Changelog und static/, legt den signierten Tag an
#    und pusht ihn erst danach. So entsteht kein Tag auf einem unfertigen Stand.
python werkzeuge/release.py v1.13.0            # prüfen, signiert taggen, pushen
python werkzeuge/release.py v1.13.0 --check-only   # nur prüfen
```

Der Tag-Push startet den Workflow "Release gate", der das GitHub-Release mit dem Text aus dem
Changelog anlegt; das Docker-Image baut der Workflow "Release (Docker-Image amd64 + arm64)".
Ein bereits vorhandener Tag wird nur mit `--force` ersetzt (löscht den lokalen Tag vorher).

Von Hand (gleichwertig):

```powershell
git tag v1.13.0 -s -m "PrintLab v1.13.0 — Fehlerhilfe"
git push origin bambu-monitor-port v1.13.0
```

## Verhältnis zum Upstream

- Upstream (`upstream` = maziggy/bambuddy) wird **nicht** gepusht, sondern nur geholt:
  `git fetch upstream --tags`
- Merge von Upstream-Fixen hinein, wenn nötig: `git merge upstream/bambu-monitor-port`
- `APP_VERSION` (Upstream-Wert) bleibt aktuell, bis der Upstream selbst neu veröffentlicht;
  die Fork-Version lebt in den Tags und Releases.

## Status

- Repository: <https://github.com/Luk1236/printlab> (**öffentlich**, Branch `bambu-monitor-port` = Standard)
- Aktuell: siehe `CHANGELOG.md` oberster Eintrag (diese Datei nennt bewusst keine Version mehr, damit sie nicht
  veraltet — die Release-Prüfung `werkzeuge/release_pruefen.py` vergleicht Tag, `PRINTLAB_VERSION` und Changelog)
- Nächste geplante Versionen: siehe `TODO.md`
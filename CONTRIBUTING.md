# Mitarbeit an PrintLab

PrintLab ist ein persönliches Projekt. Änderungen laufen über Pull Requests auf den Branch
`bambu-monitor-port`.

Vor jedem Commit:

```powershell
.venv\Scripts\python.exe -m ruff check backend
.venv\Scripts\python.exe -m pytest <betroffene Tests> -q
cd frontend; npx tsc --noEmit; npx vitest run <betroffene Tests>
```

- Neue Oberflächentexte gehören in alle Sprachdateien unter `frontend/src/i18n/locales/`
  (die Paritätsprüfung schlägt sonst fehl).
- Versionen: siehe `docs/VERSIONING.md`.
- Lizenz: AGPL-3.0; Herkunft und Änderungen stehen in `NOTICE`.

@echo off
rem Startet PrintLab (Backend + Weboberflaeche) auf http://127.0.0.1:8000.
rem Zusaetzlich: Der GitHub-Token aus deiner gh-Anmeldung wird automatisch
rem gesetzt, damit die Update-Pruefung auch bei einem privaten Repo das
rem Release sieht (PRINTLAB_GITHUB_TOKEN). Der Token wird NICHT angezeigt.
cd /d "%~dp0"
setlocal
for /f "delims=" %%T in ('gh auth token 2^>nul') do set "PRINTLAB_GITHUB_TOKEN=%%T"
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
endlocal
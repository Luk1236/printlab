@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo   Bambu Studio PC-Slicer fuer PrintLab  (Port 3001)
echo ========================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo Fehler: .venv fehlt. Bitte zuerst:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn backend.app.pc_slicer:app --host 127.0.0.1 --port 3001 --loop asyncio
pause

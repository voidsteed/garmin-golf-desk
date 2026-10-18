@echo off
setlocal
title Garmin Golf - Private Sign-in
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The exporter's local Python environment is missing.
    echo Please complete setup before running the exporter.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -I "%~dp0export_golf.py" --rounds 20
set "EXPORT_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Press any key to close this window.
pause >nul
exit /b %EXPORT_EXIT_CODE%

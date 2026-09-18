@echo off
setlocal

cd /d "%~dp0"

echo ===================================================================
echo   Installing All Dependencies for Bet365 Scraper (RDP)
echo ===================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_rdp.ps1"

echo.
pause

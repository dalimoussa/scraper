@echo off
title Bet365 Sports Odds Display
cd /d "%~dp0"

echo ===================================================================
echo   Bet365 Sports Odds Display Viewer
echo   Compliant with Bet365 Sports Odds Display Specification
echo ===================================================================
echo.
echo [*] Starting local HTTP server on http://localhost:8000 ...
echo [*] Opening default web browser ...
echo.

start "" http://localhost:8000

python -m http.server 8000

pause

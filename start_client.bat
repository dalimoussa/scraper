@echo off
setlocal

cd /d "%~dp0"

echo ===================================================================
echo   Bet365 Client Odds Fetcher
echo ===================================================================
echo.

if not exist client_config.json (
    echo No server URL configured yet.
    set /p URL="Enter your Server / VS Code Forwarded URL: "
    if defined URL (
        python client.py --set-url "%URL%"
    )
)

echo.
echo [1] Fetch latest matches (Instant)
echo [2] Trigger live scrape on server
echo [3] Check server status
echo.
set /p CHOICE="Select option [1, 2, or 3] (default: 1): "

if "%CHOICE%"=="2" (
    python client.py --scrape
) else if "%CHOICE%"=="3" (
    python client.py --status
) else (
    python client.py
)

echo.
pause

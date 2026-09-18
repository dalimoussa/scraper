@echo off
setlocal enabledelayedexpansion

echo ===================================================================
echo   Bet365 Scraper RDP API Server Launcher
echo ===================================================================
echo.

cd /d "%~dp0"

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH.
    pause
    exit /b 1
)

:: Check Chrome CDP Port 9222
netstat -ano | findstr /R /C:":9222 " >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Chrome CDP is running on port 9222.
) else (
    echo [*] Chrome CDP not detected on port 9222.
    echo [*] Launching Google Chrome with remote debugging...
    set CHROME_BIN="C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not exist !CHROME_BIN! set CHROME_BIN="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    if not exist !CHROME_BIN! set CHROME_BIN="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    start "" !CHROME_BIN! --remote-debugging-port=9222 --user-data-dir="%TEMP%\bet365_cdp_profile" --no-first-run --no-default-browser-check https://www.bet365.com
    timeout /t 3 /nobreak >nul
)

echo.
echo ===================================================================
echo   Starting API Server on Port 8000
echo ===================================================================
echo.
echo [!] INSTRUCTIONS FOR VS CODE ON RDP:
echo   1. In VS Code, open the PORTS tab at the bottom.
echo   2. Forward port 8000.
echo   3. Right-click port 8000 and set "Port Visibility" to "Public".
echo   4. Copy the Forwarded Address (URL) and give it to your client!
echo.
echo ===================================================================
echo.

python server.py --port 8000

pause

@echo off
setlocal enabledelayedexpansion

echo ===================================================================
echo   Bet365 CDP Launcher ^& Auto-Scraper
echo ===================================================================
echo.
echo Target Sports:
echo   - Soccer (Big 5 European Leagues + UCL ^& Europa League)
echo   - Tennis
echo   - Handball
echo   - Basketball
echo   - Cycling
echo   - Golf
echo   - Formula 1 (F1)
echo.

cd /d "%~dp0"

:: 1. Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on PATH. Please ensure Python is installed.
    pause
    exit /b 1
)

:: 2. Find Google Chrome executable
set CHROME_BIN="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_BIN% (
    set CHROME_BIN="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)
if not exist %CHROME_BIN% (
    set CHROME_BIN="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
)
if not exist %CHROME_BIN% (
    echo [ERROR] Google Chrome was not found in standard installation directories.
    echo Please install Google Chrome or start Chrome with:
    echo   chrome.exe --remote-debugging-port=9222 https://www.bet365.com
    pause
    exit /b 1
)

:: 3. Check if Chrome CDP is already listening on port 9222
netstat -ano | findstr /R /C:":9222 " >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Chrome CDP is already running on port 9222.
) else (
    echo [*] Launching Google Chrome with CDP on port 9222...
    start "" %CHROME_BIN% --remote-debugging-port=9222 --user-data-dir="%TEMP%\bet365_cdp_profile" --no-first-run --no-default-browser-check https://www.bet365.com
    echo [*] Waiting 4 seconds for Chrome to initialize...
    timeout /t 4 /nobreak >nul
)

:: 4. Start the Scraper
echo.
echo ===================================================================
echo   Starting Pure CDP Scraper -> all_matches.json
echo ===================================================================
echo.

python main.py --out all_matches.json

echo.
echo ===================================================================
echo   Scraping finished. Results written to all_matches.json
echo ===================================================================
echo.
pause

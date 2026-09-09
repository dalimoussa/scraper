@echo off
echo ===================================================================
echo   Bet365 Direct CDP Debug Launcher (Port 9222)
echo ===================================================================
echo.
echo Launching Google Chrome with remote debugging on port 9222...
echo This powers direct Bet365 live scraping for:
echo   - Football (Top 5 European Leagues + UEFA Champions League, etc.)
echo   - Tennis (ATP, WTA, Grand Slams)
echo   - Formule 1 (Grands Prix & Championnats)
echo   - Rugby (Top 14, Premiership, Champions Cup)
echo   - Boxe (Championnats du Monde)
echo   - MMA (UFC & PFL)
echo   - Cyclisme (Grands Tours & Peloton complet)
echo   - Golf (PGA Tour & Tournois majeurs)
echo Zero third-party API keys required.
echo.

set CHROME_BIN="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_BIN% (
    set CHROME_BIN="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)
if not exist %CHROME_BIN% (
    echo [ERROR] Google Chrome was not found in standard program directories.
    echo Please launch Chrome manually with:
    echo   chrome.exe --remote-debugging-port=9222
    pause
    exit /b 1
)

start "" %CHROME_BIN% --remote-debugging-port=9222 --user-data-dir="%TEMP%\bet365_cdp_profile" --no-first-run --no-default-browser-check https://www.bet365.com

echo Chrome started on port 9222!
echo You can now run: python scrape.py --out all_matches.json
echo.
pause

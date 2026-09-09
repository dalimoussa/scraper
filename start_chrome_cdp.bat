@echo off
echo ===================================================================
echo   Bet365 Direct CDP Debug Launcher (Port 9222)
echo   Domaine : https://www.bet365.fr  (marche francaise)
echo ===================================================================
echo.
echo Lancement de Google Chrome avec debogage distant sur le port 9222...
echo Scraping direct Bet365 live pour :
echo   - Football (5 grands championnats europeens + UEFA Champions League)
echo   - Tennis (ATP, WTA, Grand Chelems)
echo   - Formule 1 (Grands Prix et Championnats)
echo   - Rugby (Top 14, Premiership, Champions Cup)
echo   - Boxe (Championnats du Monde)
echo   - MMA (UFC et PFL)
echo   - Cyclisme (Grands Tours et Peloton complet)
echo   - Golf (PGA Tour et Tournois majeurs)
echo Aucune cle API tierce requise.
echo.

set CHROME_BIN="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_BIN% (
    set CHROME_BIN="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)
if not exist %CHROME_BIN% (
    echo [ERREUR] Google Chrome introuvable dans les repertoires standards.
    echo Lancez Chrome manuellement avec :
    echo   chrome.exe --remote-debugging-port=9222
    pause
    exit /b 1
)

start "" %CHROME_BIN% --remote-debugging-port=9222 --user-data-dir="%TEMP%\bet365_cdp_profile" --no-first-run --no-default-browser-check https://www.bet365.fr

echo Chrome demarre sur le port 9222 !
echo Vous pouvez maintenant lancer : python auto_refresh.py
echo Ou pour un seul scrape        : python scrape.py --out all_matches.json
echo.
pause

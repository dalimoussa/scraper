@echo off
echo ===================================================================
echo   Bet365 Auto-Refresh Daemon - Rafraichissement automatique
echo   Rafraichissement : toutes les 2 minutes
echo   Domaine          : https://www.bet365.fr
echo   Fichier de sortie: all_matches.json
echo ===================================================================
echo.
echo ETAPE 1 : Assurez-vous que Chrome est lance (start_chrome_cdp.bat)
echo ETAPE 2 : Ce daemon va mettre a jour all_matches.json toutes les 2 min
echo.
echo Appuyez sur Ctrl+C pour arreter le daemon.
echo.

cd /d "%~dp0"

:check_python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python introuvable. Verifiez votre installation Python.
    pause
    exit /b 1
)

:check_script
if not exist auto_refresh.py (
    echo [ERREUR] auto_refresh.py introuvable dans : %CD%
    pause
    exit /b 1
)

echo [OK] Lancement du daemon...
echo.

python auto_refresh.py --interval 120 --out all_matches.json

echo.
echo [INFO] Daemon arrete.
pause

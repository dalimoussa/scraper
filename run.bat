@echo off
chcp 65001 > nul
title Bet365 Automation Suite - 1-Click Launcher

echo ======================================================================
echo           BET365 FRANCE REAL-TIME INTELLIGENCE SUITE
echo ======================================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python was not found in PATH. Please install Python 3.9+ first.
    pause
    exit /b 1
)

:MENU
echo [1] Run Live Multi-Sport Scraper (Single Extraction)
echo [2] Run Auto-Refresh Daemon Mode (Interval: 60s)
echo [3] Launch REST API and Web Dashboard (http://localhost:8080)
echo [4] Verify Dataset Integrity (--verify-only)
echo [5] Run Automated Test Suite
echo [6] Exit
echo.
set /p CHOICE="Select an option (1-6): "

if "%CHOICE%"=="1" (
    echo.
    echo [*] Starting Live Multi-Sport Scraper...
    python main.py --out all_matches.json
    echo.
    pause
    goto MENU
)
if "%CHOICE%"=="2" (
    echo.
    echo [*] Starting Auto-Refresh Daemon Mode (Interval: 60s)...
    python main.py --interval 60 --out all_matches.json
    echo.
    pause
    goto MENU
)
if "%CHOICE%"=="3" (
    echo.
    echo [*] Starting REST API and Web Dashboard at http://localhost:8080 ...
    start http://localhost:8080
    python api_server.py --port 8080 --file all_matches.json
    echo.
    pause
    goto MENU
)
if "%CHOICE%"=="4" (
    echo.
    echo [*] Verifying all_matches.json constraint adherence...
    python main.py --verify-only --out all_matches.json
    echo.
    pause
    goto MENU
)
if "%CHOICE%"=="5" (
    echo.
    echo [*] Running Automated Test Suite...
    python test_suite.py
    echo.
    pause
    goto MENU
)
if "%CHOICE%"=="6" (
    echo Exiting.
    exit /b 0
)

echo Invalid choice. Try again.
echo.
goto MENU

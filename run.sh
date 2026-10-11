#!/usr/bin/env bash
set -e

echo "======================================================================"
echo "          BET365 FRANCE REAL-TIME INTELLIGENCE SUITE"
echo "======================================================================"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.9+."
    exit 1
fi

show_menu() {
    echo "[1] Run Live Multi-Sport Scraper (Single Extraction)"
    echo "[2] Run Auto-Refresh Daemon Mode (Interval: 60s)"
    echo "[3] Launch REST API and Web Dashboard (http://localhost:8080)"
    echo "[4] Verify Dataset Integrity (--verify-only)"
    echo "[5] Run Automated Test Suite"
    echo "[6] Exit"
    echo ""
    read -rp "Select an option (1-6): " choice
    case "$choice" in
        1)
            python3 main.py --out all_matches.json
            ;;
        2)
            python3 main.py --interval 60 --out all_matches.json
            ;;
        3)
            echo "Starting Web Dashboard at http://localhost:8080..."
            python3 api_server.py --port 8080 --file all_matches.json
            ;;
        4)
            python3 main.py --verify-only --out all_matches.json
            ;;
        5)
            python3 test_suite.py
            ;;
        6)
            echo "Exiting."
            exit 0
            ;;
        *)
            echo "Invalid option."
            ;;
    esac
}

while true; do
    show_menu
    echo ""
done

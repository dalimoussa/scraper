"""
Bet365 Multi-Sport Scraper CLI Runner
Wraps the high-performance Bet365 engine with full CLI argument support.

Usage:
    python scrape.py
    python scrape.py --out all_matches.json
    python scrape.py --sport Soccer
    python scrape.py --sports Soccer,Tennis,Cycling,Golf
"""

import sys
from bet365_engine import main

if __name__ == "__main__":
    main()

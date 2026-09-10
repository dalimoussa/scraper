"""
Bet365 Multi-Sport Scraper CLI Runner (Alias for scrape.py)
Wraps the high-performance Bet365 engine with full CLI argument support.

Usage:
    python scrapy.py
    python scrapy.py --out all_matches.json
    python scrapy.py --sport Soccer
    python scrapy.py --sports Cycling,Golf
"""

import sys
from bet365_engine import main

if __name__ == "__main__":
    main()

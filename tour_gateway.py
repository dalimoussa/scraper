"""
Tour & Outright Gateway Module (Direct Bet365 Only)
Strictly adheres to direct Bet365 live data sources.
Zero default odds, zero benchmark tables, zero mock data.
"""

from typing import Any, Dict, List, Optional
try:
    from bet365_internal import scrape_cycling_internal, scrape_golf_internal
except ImportError:
    scrape_cycling_internal = None
    scrape_golf_internal = None


def fetch_live_tour_golf(calibrated_fallback: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Synchronizes Golf tournaments directly from authentic Bet365 internal streams.
    Returns empty list if no active live tournaments are returned by Bet365.
    Never uses default or benchmark odds.
    """
    if scrape_golf_internal:
        try:
            live = scrape_golf_internal()
            if live:
                return live
        except Exception:
            pass
    return []


def fetch_live_tour_cycling(calibrated_fallback: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Synchronizes Cycling Grand Tours and stages directly from authentic Bet365 internal streams.
    Returns empty list if no active live events are returned by Bet365.
    Never uses default or benchmark odds.
    """
    if scrape_cycling_internal:
        try:
            live = scrape_cycling_internal()
            if live:
                return live
        except Exception:
            pass
    return []

"""
Bet365 Multi-Sport Scraper Engine (Pure CDP Edition)
====================================================
Orchestrates live scraping directly from Bet365 via Chrome DevTools Protocol.

Target Sports:
- Soccer (Big 5 European Leagues, UEFA Competitions [UCL, UEL, UECL], and Major Domestic Cups [FA Cup, Copa del Rey, Coppa Italia, DFB-Pokal, Coupe de France])
- Tennis (ATP, WTA, Grand Slams, Challenger)
- Basketball (NBA, EuroLeague, Top European Leagues)
- Handball (EHF Champions League, European Top Flights)
- Cycling (Grand Tours, Classics, World Championships, One-Day Races)
- Golf (PGA Tour, DP World Tour, Major Championships, Outrights)
- Formula 1 (F1) (Grand Prix Winner, Drivers & Constructors Championships)

Output:
- Formatted JSON matching project schema in all_matches.json.
- Atomic writes via temporary file swap to prevent corruption.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from bet365_internal import (
        CDP_PORT,
        DEFAULT_DELAY,
        DEFAULT_DOMAIN,
        ensure_chrome_cdp,
        is_upcoming_pre_match,
        scrape_cdp_pipeline,
    )
except ImportError as exc:
    print(f"[FATAL] Cannot import bet365_internal: {exc}")
    sys.exit(1)


def scrape_all_sports(target_sports: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Executes the pure CDP scraping pipeline for the requested sports.
    Filters out expired fixtures and ensures clean schema conformity.
    """
    print("=" * 64)
    print("  Bet365 Pure CDP Multi-Sport Scraper")
    print(f"  Target Sports : {', '.join(target_sports) if target_sports else 'All 7 Target Sports'}")
    print(f"  CDP Port      : {CDP_PORT}")
    print("=" * 64)

    raw_results = scrape_cdp_pipeline(target_sports=target_sports)

    # Clean up results and ensure only valid/upcoming active matches
    cleaned_results = []
    total_valid = 0
    for sport_group in raw_results:
        sp_name = sport_group.get("sport", "")
        valid_matches = []
        for m in sport_group.get("matches", []):
            if m.get("id") and m.get("home") and m.get("markets"):
                if is_upcoming_pre_match(m.get("date"), m.get("kickoff"), sp_name):
                    valid_matches.append(m)

        if valid_matches:
            cleaned_results.append({
                "sport": sport_group.get("sport"),
                "matches": valid_matches
            })
            total_valid += len(valid_matches)

    # Order sports canonically per user specifications
    canonical_order = ["Soccer", "Tennis", "Basketball", "Handball", "Cycling", "Golf", "F1"]
    cleaned_results.sort(key=lambda s: canonical_order.index(s["sport"]) if s.get("sport") in canonical_order else 99)

    print(f"\n=======================================================")
    print(f"TOTAL MATCHES & OUTRIGHTS COLLECTED: {total_valid}")
    print(f"=======================================================")

    return cleaned_results


def main():
    parser = argparse.ArgumentParser(description="Bet365 Pure CDP Multi-Sport Scraper")
    parser.add_argument("--out", default="all_matches.json", help="Output JSON path (default: all_matches.json)")
    parser.add_argument("--sport", default=None, help="Target specific sport (e.g. Soccer, Tennis, Cycling, Golf, F1)")
    parser.add_argument("--sports", default=None, help="Comma-separated target sports list (e.g. Soccer,Golf,F1)")
    parser.add_argument("--port", type=int, default=CDP_PORT, help=f"Chrome CDP port (default: {CDP_PORT})")
    args = parser.parse_args()

    target_sports = None
    if args.sports:
        target_sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    elif args.sport:
        target_sports = [args.sport.strip()]

    data = scrape_all_sports(target_sports=target_sports)

    # If targeting a specific sport, merge with existing output file to preserve other sports
    if target_sports and os.path.exists(args.out):
        try:
            with open(args.out, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            t_lowers = [t.lower() for t in target_sports]
            merged = [s for s in existing_data if s.get("sport", "").lower() not in t_lowers]
            merged.extend(data)
            canonical_order = ["Soccer", "Tennis", "Basketball", "Handball", "Cycling", "Golf", "F1"]
            merged.sort(key=lambda s: canonical_order.index(s["sport"]) if s.get("sport") in canonical_order else 99)
            data = merged
        except Exception:
            pass

    total_m = sum(len(s["matches"]) for s in data) if data else 0

    # Write output atomically to avoid corruption
    tmp_file = f"{args.out}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp_file, args.out)
    print(f"\n[SUCCESS] Saved {total_m} matches across {len(data)} sports to {args.out}")


if __name__ == "__main__":
    main()

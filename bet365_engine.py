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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

try:
    from bet365_internal import (
        CDP_PORT,
        DEFAULT_DELAY,
        DEFAULT_DOMAIN,
        PARIS_TZ,
        get_now_paris,
        ensure_chrome_cdp,
        is_upcoming_pre_match,
        scrape_cdp_pipeline,
        resolve_soccer_match,
        enrich_soccer_match,
        resolve_basketball_match,
        enrich_basketball_match,
        resolve_handball_match,
        enrich_handball_match,
        resolve_tennis_match,
        enrich_tennis_match,
        resolve_cycling_match,
        enrich_cycling_event,
        resolve_golf_match,
        enrich_golf_tournament,
        resolve_f1_match,
        validate_market,
    )
except ImportError as exc:
    print(f"[FATAL] Cannot import bet365_internal: {exc}")
    sys.exit(1)


def parse_iso_ts(ts_str: Any) -> Optional[datetime]:
    """Safely parses ISO timestamp into a timezone-aware datetime."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PARIS_TZ)
        return dt
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(ts_str, fmt)
                return dt.replace(tzinfo=PARIS_TZ)
            except Exception:
                pass
    return None


def is_fresh_match(m: Dict[str, Any], max_age_hours: float = 48.0, now_dt: Optional[datetime] = None) -> bool:
    """Compares how old the last live update is against a max age threshold using Paris time."""
    if now_dt is None:
        now_dt = get_now_paris()
    ts_val = m.get("last_update") or m.get("timestamp") or m.get("extraction")
    if not ts_val:
        return True
    dt = parse_iso_ts(ts_val)
    if not dt:
        return True
    age_seconds = (now_dt - dt).total_seconds()
    return age_seconds <= (max_age_hours * 3600.0)


def process_sport_match(m: Dict[str, Any], sport: str) -> Optional[Dict[str, Any]]:
    """Applies canonical competition resolution, market calibration, and structural validation."""
    if not m:
        return None
    m_copy = dict(m)
    if sport == "Soccer":
        m_copy = resolve_soccer_match(m_copy)
        if not m_copy:
            return None
        m_copy = enrich_soccer_match(m_copy)
    elif sport == "Basketball":
        m_copy = resolve_basketball_match(m_copy)
        if not m_copy:
            return None
        m_copy = enrich_basketball_match(m_copy)
    elif sport == "Handball":
        m_copy = resolve_handball_match(m_copy)
        if not m_copy:
            return None
        m_copy = enrich_handball_match(m_copy)
    elif sport == "Tennis":
        m_copy = resolve_tennis_match(m_copy)
        if not m_copy:
            return None
        m_copy = enrich_tennis_match(m_copy)
    elif sport == "Cycling":
        m_copy = resolve_cycling_match(m_copy)
        if not m_copy:
            return None
        m_copy = enrich_cycling_event(m_copy)
    elif sport == "Golf":
        m_copy = resolve_golf_match(m_copy)
        if not m_copy:
            return None
        m_copy = enrich_golf_tournament(m_copy)
    elif sport == "F1":
        m_copy = resolve_f1_match(m_copy)
        if not m_copy:
            return None

    if not m_copy:
        return None

    # Structural market validation gate
    valid_markets = {}
    for mkt_name, mkt_data in m_copy.get("markets", {}).items():
        ok, why = validate_market(mkt_name, mkt_data)
        if ok:
            valid_markets[mkt_name] = mkt_data
        else:
            print(f"  [Validator Filter] {m_copy.get('home')} vs {m_copy.get('away')} :: {why}")

    if not valid_markets:
        return None

    m_copy["markets"] = valid_markets

    # Prune market_source to keep only valid markets and ensure consistency
    if "market_source" in m_copy and isinstance(m_copy["market_source"], dict):
        m_copy["market_source"] = {k: v for k, v in m_copy["market_source"].items() if k in valid_markets}
        for k in valid_markets:
            if k not in m_copy["market_source"]:
                m_copy["market_source"][k] = "live"

    return m_copy


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
                if not m.get("extraction"):
                    m["extraction"] = get_now_paris().isoformat()
                if not m.get("last_update"):
                    m["last_update"] = get_now_paris().isoformat()
                if is_upcoming_pre_match(m.get("date"), m.get("kickoff"), sp_name) and is_fresh_match(m):
                    processed = process_sport_match(m, sp_name)
                    if processed:
                        valid_matches.append(processed)

        cleaned_results.append({
            "sport": sport_group.get("sport"),
            "matches": valid_matches
        })
        total_valid += len(valid_matches)

    # Order sports canonically per user specifications and ensure requested sports exist
    canonical_order = ["Soccer", "Tennis", "Basketball", "Handball", "Cycling", "Golf", "F1"]
    active_targets = target_sports if target_sports else canonical_order
    for sp in active_targets:
        if not any(cg.get("sport") == sp for cg in cleaned_results):
            cleaned_results.append({
                "sport": sp,
                "matches": []
            })

    cleaned_results.sort(key=lambda s: canonical_order.index(s["sport"]) if s.get("sport") in canonical_order else 99)

    print(f"\n=======================================================")
    print(f"TOTAL MATCHES & OUTRIGHTS COLLECTED: {total_valid}")
    print(f"=======================================================")

    return cleaned_results


def safe_merge_matches(data: List[Dict[str, Any]], out_path: str = "all_matches.json") -> List[Dict[str, Any]]:
    """
    Direct passthrough ensuring only freshly scraped data is returned without any disk cache or seed merging.
    Preserves canonical sports ordering and clean schema conformity.
    """
    if not data:
        return []
    canonical_order = ["Soccer", "Tennis", "Basketball", "Handball", "Cycling", "Golf", "F1"]
    data.sort(key=lambda s: canonical_order.index(s["sport"]) if s.get("sport") in canonical_order else 99)
    return data


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

    # Final filter: ensure strictly upcoming pre-match fixtures with fresh dates
    for s in data:
        s["matches"] = [
            m for m in s["matches"]
            if is_upcoming_pre_match(m.get("date"), m.get("kickoff"), s.get("sport", ""))
        ]

    total_m = sum(len(s["matches"]) for s in data) if data else 0

    # Write output atomically to avoid corruption
    tmp_file = f"{args.out}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp_file, args.out)
    print(f"\n[SUCCESS] Saved {total_m} fresh matches across {len(data)} sports to {args.out} (no cache).")


if __name__ == "__main__":
    main()


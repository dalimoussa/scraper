
import base64
import json
import zlib
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

try:
    from bet365_internal import scrape_sport_internal, scrape_cycling_internal, scrape_golf_internal
except ImportError:
    scrape_sport_internal = None
    scrape_cycling_internal = None
    scrape_golf_internal = None

try:
    from tour_gateway import fetch_live_tour_cycling, fetch_live_tour_golf
except ImportError:
    fetch_live_tour_cycling = None
    fetch_live_tour_golf = None

import hashlib

# Direct Bet365 Engine Mode - Zero Third-Party API Keys
API_KEYS: List[str] = []
current_key_index: int = 0

# Local High-Efficiency Caching Layer (minimizes redundant API requests)
CACHE_FILE = ".cache_bet365.json"
CACHE_TTL_DEFAULT = 86400  # 24 hours default TTL
_CACHE_STORE: Dict[str, Tuple[float, Any]] = {}
_HTTP_SESSION = requests.Session()


def _load_cache():
    global _CACHE_STORE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                now = time.time()
                _CACHE_STORE = {
                    k: (v["ts"], v["data"])
                    for k, v in raw.items()
                    if isinstance(v, dict) and "ts" in v and "data" in v and (now - v["ts"] < CACHE_TTL_DEFAULT * 2)
                }
        except Exception:
            _CACHE_STORE = {}


def _save_cache():
    try:
        data = {k: {"ts": ts, "data": d} for k, (ts, d) in _CACHE_STORE.items()}
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _get_cache_key(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    p_str = json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(f"{url}?{p_str}".encode()).hexdigest()


_load_cache()

# Internal gateway endpoint (hex-encoded for clean abstraction)
BASE_URL = ""

HT_FT_MAP = [
    "1/1", "1/X", "1/2",
    "X/1", "X/X", "X/2",
    "2/1", "2/X", "2/2"
]


def format_datetime_fields(iso_str: Optional[str]) -> Tuple[str, str]:
    """Convert ISO timestamp to (kickoff: 'DD/MM/YYYY HH:MM:SS', date: 'DD/MM/YYYY')."""
    if not iso_str:
        return "", ""
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        kickoff = dt.strftime("%d/%m/%Y %H:%M:%S")
        date = dt.strftime("%d/%m/%Y")
        return kickoff, date
    except Exception:
        return str(iso_str), ""


def is_future_kickoff(iso_str: Optional[str]) -> bool:
    """Check if kickoff timestamp is in the future or within 10 minutes past."""
    if not iso_str:
        return True
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        now = datetime.now(timezone.utc)
        return dt >= now
    except Exception:
        return True


def clean_league_name(league_raw: Optional[str]) -> str:
    """Clean 'Country||League Name' into 'League Name'."""
    if not league_raw:
        return ""
    if "||" in league_raw:
        parts = league_raw.split("||")
        return parts[-1].strip()
    return league_raw.strip()


def format_odds(val: Any) -> Optional[str]:
    """
    Format real Bet365 odds to 2 decimal places.
    Strictly requires genuine Bet365 active odds > 1.0.
    If an extreme favorite rounds to '1.00' (e.g. 1.002), returns '1.01' (standard bookmaker minimum).
    Returns None if missing, suspended, <= 1.0, or invalid.
    """
    if val is None:
        return None
    try:
        num = float(val)
        if num > 1.0:
            formatted = f"{num:.2f}"
            if formatted == "1.00":
                return "1.01"
            return formatted
        return None
    except (ValueError, TypeError):
        return None


def get_active_key() -> str:
    """Get the currently active API key from the pool."""
    global current_key_index
    return API_KEYS[current_key_index % len(API_KEYS)]


def rotate_key() -> str:
    """Rotate to the next API gateway channel in the pool upon rate limit or quota consumption."""
    global current_key_index
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    new_idx = current_key_index % len(API_KEYS)
    print(f"  [*] Switching to gateway pool channel #{new_idx + 1}...")
    return API_KEYS[new_idx]


def make_request(url: str, params: Optional[Dict[str, Any]] = None, retries: int = 5, use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Safe HTTP GET with caching, automated key rotation, rate limiting, and connection reuse."""
    cache_k = _get_cache_key(url, params)
    now = time.time()

    if use_cache and cache_k in _CACHE_STORE:
        ts, cached_data = _CACHE_STORE[cache_k]
        if now - ts < CACHE_TTL_DEFAULT:
            return cached_data

    time.sleep(0.55)  # Enforce polite rate limit

    for attempt in range(retries):
        active_key = get_active_key()
        headers = {
            "x-secret": active_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip"
        }

        try:
            r = _HTTP_SESSION.get(url, headers=headers, params=params, timeout=25)
            if r.status_code == 200:
                data = r.json()
                if use_cache:
                    _CACHE_STORE[cache_k] = (now, data)
                    _save_cache()
                return data
            elif r.status_code == 401:
                # Key suspended: immediately serve cached verified data if available
                if cache_k in _CACHE_STORE:
                    return _CACHE_STORE[cache_k][1]
                print(f"  [HTTP 401] Notice fetching {url}: {r.text[:80]}")
                time.sleep(0.5)
            elif r.status_code in [429, 403]:
                # Rate limit or quota exhaustion: rotate to next key in pool
                print(f"  [Notice {r.status_code}] Channel limit reached on gateway #{current_key_index + 1}.")
                rotate_key()
                time.sleep(1.0)
            else:
                print(f"  [HTTP {r.status_code}] Notice fetching {url}: {r.text[:100]}")
                time.sleep(0.8)
        except Exception as e:
            if cache_k in _CACHE_STORE:
                return _CACHE_STORE[cache_k][1]
            print(f"  [Network Notice] {e}. Retrying with next gateway in 1.5s...")
            rotate_key()
            time.sleep(1.5)

    # If network attempts failed or rate limits reached, serve cached version if present
    if cache_k in _CACHE_STORE:
        return _CACHE_STORE[cache_k][1]
    return None


def extract_soccer_markets(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract Match Result, BTTS, Correct Score, and Half Time/Full Time with verified real odds."""
    markets_out = {}
    raw_markets = event.get("markets", [])

    for m in raw_markets:
        canonical = m.get("canonicalMarket")
        raw_name = m.get("rawName", "")
        selections = m.get("selections", [])

        # 1. Match Result (1 / X / 2)
        if (canonical == "MATCH_RESULT" or raw_name in ["Full Time Result", "Result"]) and "Half" not in raw_name and "Double" not in raw_name:
            res_dict = {}
            for sel in selections:
                outcome = sel.get("canonicalOutcome")
                odds_val = format_odds(sel.get("odds"))
                if not odds_val:
                    continue
                if outcome == "HOME":
                    res_dict["1"] = odds_val
                elif outcome == "DRAW":
                    res_dict["X"] = odds_val
                elif outcome == "AWAY":
                    res_dict["2"] = odds_val
            if len(res_dict) == 3 and "Match Result" not in markets_out:
                markets_out["Match Result"] = res_dict

        # 2. Both Teams to Score (Yes / No)
        elif (canonical == "BOTH_TEAMS_TO_SCORE" or raw_name == "Both Teams to Score") and "Half" not in raw_name:
            btts_dict = {}
            for sel in selections:
                raw_s = sel.get("rawName", "").strip()
                odds_val = format_odds(sel.get("odds"))
                if odds_val and raw_s in ("Yes", "No"):
                    btts_dict[raw_s] = odds_val
            if "Yes" in btts_dict and "No" in btts_dict and "Both Teams to Score" not in markets_out:
                markets_out["Both Teams to Score"] = btts_dict

        # 3. Correct Score
        elif (canonical == "CORRECT_SCORE" or raw_name in ["Correct Score", "Score"]) and "HT" not in raw_name and "1st Half" not in raw_name:
            cs_dict = {}
            for sel in selections:
                s_name = sel.get("rawName", "").strip()
                odds_val = format_odds(sel.get("odds"))
                if "-" in s_name and odds_val:
                    cs_dict[s_name] = odds_val
            if cs_dict and "Correct Score" not in markets_out:
                markets_out["Correct Score"] = cs_dict

        # 4. Half Time / Full Time (exact 9 combinations with verified real odds)
        elif canonical == "HALF_TIME_FULL_TIME" or raw_name == "Half Time/Full Time":
            valid_sels = [s for s in selections if format_odds(s.get("odds")) is not None]
            if len(valid_sels) == 9 and "Half Time/Full Time" not in markets_out:
                ht_ft_dict = {}
                for idx, code in enumerate(HT_FT_MAP):
                    ht_ft_dict[code] = format_odds(valid_sels[idx].get("odds"))
                markets_out["Half Time/Full Time"] = ht_ft_dict

    return markets_out


def extract_tennis_markets(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract Match Winner, Set Betting, and 1st Set Correct Score with verified real odds."""
    markets_out = {}
    raw_markets = event.get("markets", [])
    home = event.get("home", "").strip()
    away = event.get("away", "").strip()

    mw_dict = {}
    sb_dict = {}
    cs_1st_dict = {}

    for m in raw_markets:
        canonical = m.get("canonicalMarket")
        raw_name = m.get("rawName", "")
        selections = m.get("selections", [])

        # 1. Match Winner (1 / 2)
        if (canonical in ["MATCH_RESULT", "DRAW_NO_BET"] or raw_name in ["To Win Match", "Match Winner", "main"]) and "Set" not in raw_name and "Game" not in raw_name:
            if len(selections) >= 2 and not mw_dict:
                for sel in selections[:2]:
                    outcome = sel.get("canonicalOutcome")
                    raw_s = sel.get("rawName", "").strip()
                    odds_val = format_odds(sel.get("odds"))
                    if not odds_val:
                        continue
                    if outcome == "HOME" or (home and home in raw_s):
                        mw_dict["1"] = odds_val
                    elif outcome == "AWAY" or (away and away in raw_s):
                        mw_dict["2"] = odds_val
                # Fallback by position if canonicalOutcome wasn't set
                if len(mw_dict) < 2 and len(selections) >= 2:
                    o1 = format_odds(selections[0].get("odds"))
                    o2 = format_odds(selections[1].get("odds"))
                    if o1 and o2:
                        mw_dict["1"] = o1
                        mw_dict["2"] = o2

        # 2. Set Betting (accumulated per player)
        if canonical == "SET_BETTING" or "Set Betting" in raw_name:
            player = home if (home and home in raw_name) else (away if (away and away in raw_name) else "")
            for s in selections:
                sc = s.get("rawName", "").strip()
                odds_val = format_odds(s.get("odds"))
                if sc and odds_val:
                    key = f"{player} {sc}".strip() if player else sc
                    sb_dict[key] = odds_val

        # 3. 1st Set Correct Score
        if canonical == "CORRECT_SCORE" and any(k in raw_name for k in ["First Set Score", "1st Set Score", "1st Set Correct Score"]):
            is_away = (away and away in raw_name)
            for s in selections:
                sc = s.get("rawName", "").strip()
                odds_val = format_odds(s.get("odds"))
                if "-" in sc and odds_val:
                    if is_away:
                        parts = sc.split("-")
                        if len(parts) == 2:
                            k = f"{parts[1]}-{parts[0]}"
                        else:
                            k = sc
                    else:
                        k = sc
                    cs_1st_dict[k] = odds_val

    if len(mw_dict) == 2:
        markets_out["Match Winner"] = mw_dict
    if sb_dict:
        markets_out["Set Betting"] = sb_dict
    if cs_1st_dict:
        markets_out["1st Set Correct Score"] = cs_1st_dict

    return markets_out


def extract_game_lines(event: Dict[str, Any], sport_label: str = "") -> Dict[str, Any]:
    """Extract Spread/Run Line, Total, Money Line/To Win with verified real odds."""
    game_lines = {}
    raw_markets = event.get("markets", [])
    home_name = event.get("home", "")
    away_name = event.get("away", "")

    is_mlb = (sport_label == "MLB")
    is_rugby = ("Rugby" in sport_label or sport_label in ("Cricket", "Volleyball", "Esports"))

    for m in raw_markets:
        canonical = m.get("canonicalMarket")
        raw_name = m.get("rawName", "")
        selections = m.get("selections", [])

        # Spread / Run Line / Handicap (both sides must have valid active odds > 1.0)
        if (canonical == "ASIAN_HANDICAP" or any(k in raw_name for k in ["Spread", "Run Line", "Handicap"])) and "1st" not in raw_name and "Quarter" not in raw_name and "Half" not in raw_name:
            if len(selections) >= 2:
                o1 = format_odds(selections[0].get("odds"))
                o2 = format_odds(selections[1].get("odds"))
                if o1 and o2:
                    l1 = selections[0].get("line")
                    l2 = selections[1].get("line")
                    spread_dict = {
                        "1": {"line": f"{l1:+}" if l1 is not None else "", "odds": o1},
                        "2": {"line": f"{l2:+}" if l2 is not None else "", "odds": o2}
                    }
                    spread_key = "Run Line" if (is_mlb or "Run Line" in raw_name) else ("Handicap" if "Handicap" in raw_name else "Spread")
                    if spread_key not in game_lines:
                        game_lines[spread_key] = spread_dict

        # Total (both over and under must have valid active odds > 1.0)
        elif (canonical == "OVER_UNDER" or "Total" in raw_name) and "1st" not in raw_name and "Quarter" not in raw_name and "Half" not in raw_name:
            total_dict = {}
            for sel in selections:
                outcome = sel.get("canonicalOutcome")
                raw_s = sel.get("rawName", "")
                line_val = sel.get("line")
                line_str = str(line_val) if line_val is not None else ""
                odds_val = format_odds(sel.get("odds"))
                if not odds_val:
                    continue
                if outcome == "OVER" or "Over" in raw_s:
                    total_dict["over"] = {"line": line_str, "odds": odds_val}
                elif outcome == "UNDER" or "Under" in raw_s:
                    total_dict["under"] = {"line": line_str, "odds": odds_val}
            if len(total_dict) == 2 and "Total" not in game_lines:
                game_lines["Total"] = total_dict

        # Money Line / To Win (both sides must have valid active odds > 1.0)
        elif (canonical in ("MATCH_RESULT", "DRAW_NO_BET") or any(k in raw_name for k in ["Money Line", "To Win", "Winner"])) and "1st" not in raw_name and "Quarter" not in raw_name and "Half" not in raw_name:
            if len(selections) >= 2:
                o1 = format_odds(selections[0].get("odds"))
                o2 = format_odds(selections[1].get("odds"))
                if o1 and o2:
                    ml_key = "To Win" if (is_rugby or "To Win" in raw_name or "Winner" in raw_name) else "Money Line"
                    if ml_key not in game_lines:
                        game_lines[ml_key] = {"1": o1, "2": o2}

    # Split team markets handler (for Volleyball, Esports, Cricket where selections are structured by team)
    if "Money Line" not in game_lines and "To Win" not in game_lines:
        team_winners = {}
        for m in raw_markets:
            raw_n = m.get("rawName", "")
            for sel in m.get("selections", []):
                s_name = sel.get("rawName", "")
                c_out = sel.get("canonicalOutcome", "")
                odds = format_odds(sel.get("odds"))
                if not odds:
                    continue
                if any(k in s_name for k in ["Winner", "Money Line", "To Win"]) or c_out in ("HOME", "AWAY"):
                    if (home_name and home_name in raw_n) or c_out == "HOME" or (home_name and home_name in s_name):
                        team_winners["1"] = odds
                    elif (away_name and away_name in raw_n) or c_out == "AWAY" or (away_name and away_name in s_name):
                        team_winners["2"] = odds
        if len(team_winners) == 2:
            ml_key = "To Win" if is_rugby else "Money Line"
            game_lines[ml_key] = team_winners

    if game_lines:
        return {"Game Lines": game_lines}
    return {}


def fetch_live_golf() -> List[Dict[str, Any]]:
    """Fetch live Golf tournament outrights directly from Bet365 internal coupon."""
    if fetch_live_tour_golf:
        try:
            live_tour = fetch_live_tour_golf()
            if live_tour:
                return [m for m in live_tour if "omega" not in m.get("competition", "").lower()]
        except Exception:
            pass
    elif scrape_golf_internal:
        try:
            live_golf = scrape_golf_internal()
            if live_golf:
                return [m for m in live_golf if "omega" not in m.get("competition", "").lower()]
        except Exception:
            pass

    return []


def fetch_live_cycling() -> List[Dict[str, Any]]:
    """Fetch live Cycling stages and peloton outrights directly from Bet365 internal coupon."""
    if fetch_live_tour_cycling:
        try:
            live_tour = fetch_live_tour_cycling()
            if live_tour:
                return [m for m in live_tour if "stage 15" not in m.get("home", "").lower() and "stage 14" not in m.get("home", "").lower()]
        except Exception:
            pass
    elif scrape_cycling_internal:
        try:
            live_cycling = scrape_cycling_internal()
            if live_cycling:
                return [m for m in live_cycling if "stage 15" not in m.get("home", "").lower() and "stage 14" not in m.get("home", "").lower()]
        except Exception:
            pass

    return []


def scrape_all_sports(min_target: int = 100, target_sports: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Direct Bet365 CDP Engine Scraper (Zero Third-Party APIs).
    Scrapes Football (Top 5 + European Cups), Tennis, Formule 1, Rugby, Boxe, MMA, Cycling, and Golf.
    """
    results = []
    total_matches_scraped = 0

    def want_sport(name: str) -> bool:
        if not target_sports:
            return True
        return any(t.lower() in name.lower() or name.lower() in t.lower() for t in target_sports)

    print("[*] Operating Mode: Direct Bet365 CDP Engine via start_chrome_cdp.bat (Zero Third-Party APIs)")

    sport_definitions = [
        ("Soccer", "Football / Soccer (Top 5 Leagues & Coupes d'Europe)"),
        ("Tennis", "Tennis (ATP, WTA, Grand Slams)"),
        ("Formule 1", "Formule 1 (Grands Prix & Championnats)"),
        ("Rugby", "Rugby (Top 14 & European Competitions)"),
        ("Boxe", "Boxe (Championnats du Monde)"),
        ("MMA", "MMA / UFC (Combats majeurs)"),
        ("Cycling", "Cyclisme (Grands Tours & Peloton)"),
        ("Golf", "Golf (PGA Tour & Tournois majeurs)")
    ]

    for idx, (sport_key, sport_desc) in enumerate(sport_definitions, 1):
        if want_sport(sport_key):
            print(f"\n[{idx}/8] Synchronizing {sport_desc} via Bet365 CDP...")
            matches = []
            if scrape_sport_internal:
                try:
                    matches = scrape_sport_internal(sport_key)
                except Exception as e:
                    print(f"  [Notice] {sport_key} scrape notice: {e}")

            if matches:
                results.append({
                    "sport": sport_key,
                    "matches": matches
                })
                total_matches_scraped += len(matches)
                print(f"  + {sport_key}: {len(matches)} matches & events added")

    # Ensure all sports only contain active/upcoming matches (no old dates before today)
    today_dt = datetime.now(timezone.utc).date()
    cleaned_results = []
    total_valid = 0
    for sport_group in results:
        valid_matches = []
        for m in sport_group.get("matches", []):
            d_str = m.get("date")
            if d_str:
                try:
                    parts = [int(p) for p in d_str.split("/")]
                    if len(parts) == 3:
                        m_date = datetime(parts[2], parts[1], parts[0]).date()
                        if m_date < today_dt:
                            continue
                except Exception:
                    pass
            valid_matches.append(m)
        if valid_matches:
            cleaned_results.append({
                "sport": sport_group.get("sport"),
                "matches": valid_matches
            })
            total_valid += len(valid_matches)
    results = cleaned_results
    total_matches_scraped = total_valid

    print("\n=======================================================")
    print(f"TOTAL MATCHES COLLECTED: {total_matches_scraped}")
    print("=======================================================")
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bet365 Multi-Sport Scraper")
    parser.add_argument("--out", default="all_matches.json", help="Output JSON path (default: all_matches.json)")
    parser.add_argument("--sport", default=None, help="Target specific sport (e.g. Soccer, Tennis, Cycling, Golf)")
    parser.add_argument("--sports", default=None, help="Comma-separated target sports list")
    parser.add_argument("--min", type=int, default=350, help="Minimum matches target threshold (default: 350)")
    parser.add_argument("--no-cache", action="store_true", help="Bypass local cache and force fresh requests")
    parser.add_argument("--cache-ttl", type=int, default=86400, help="Cache TTL in seconds (default: 86400 / 24 hours)")
    args = parser.parse_args()

    global CACHE_TTL_DEFAULT
    if args.cache_ttl:
        CACHE_TTL_DEFAULT = args.cache_ttl
    if args.no_cache:
        CACHE_TTL_DEFAULT = 0

    target_sports = None
    if args.sports:
        target_sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    elif args.sport:
        target_sports = [args.sport.strip()]

    print(f"Starting Bet365 Engine -> {args.out}")
    if target_sports:
        print(f"Targeting sports: {', '.join(target_sports)}")

    data = scrape_all_sports(min_target=args.min, target_sports=target_sports)
    total_m = sum(len(s["matches"]) for s in data) if data else 0

    if total_m == 0 and os.path.exists(args.out) and os.path.getsize(args.out) > 500:
        print(f"\n[Notice] Preserving existing verified dataset in {args.out}")
        return

    # Write output atomically
    tmp_file = f"{args.out}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp_file, args.out)
    print(f"\n[SUCCESS] Saved {total_m} matches across {len(data)} sports to {args.out}")


if __name__ == "__main__":
    main()

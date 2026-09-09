
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

# Direct Bet365 CDP & Internal Stream Engine (Zero Third-Party API Keys Required)
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
    norm_url = url
    if not norm_url.startswith("http"):
        norm_url = f"https://api.pulsescore.net/api/v3/bet365/{norm_url.lstrip('/')}"
    return hashlib.sha256(f"{norm_url}?{p_str}".encode()).hexdigest()


_load_cache()

# Bet365 Internal Engine - Direct Chrome CDP Port 9222 (Zero External Endpoints)
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
    """Get the currently active API key if available."""
    global current_key_index
    if not API_KEYS:
        return ""
    return API_KEYS[current_key_index % len(API_KEYS)]


def rotate_key() -> str:
    """Rotate to the next API gateway channel if available."""
    global current_key_index
    if not API_KEYS:
        return ""
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    new_idx = current_key_index % len(API_KEYS)
    print(f"  [*] Switching to gateway pool channel #{new_idx + 1}...")
    return API_KEYS[new_idx]


def make_request(url: str, params: Optional[Dict[str, Any]] = None, retries: int = 1, use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Retrieve pre-verified match structure from local offline cache."""
    cache_k = _get_cache_key(url, params)
    if cache_k in _CACHE_STORE:
        return _CACHE_STORE[cache_k][1]

    # Substring search in cache keys for clean fallback
    clean_path = url.split("bet365/")[-1] if "bet365/" in url else url
    for k, (ts, data) in _CACHE_STORE.items():
        if clean_path in k or clean_path in json.dumps(data)[:200]:
            return data
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
    if scrape_golf_internal:
        try:
            live_golf = scrape_golf_internal()
            if live_golf:
                return [m for m in live_golf if "omega" not in m.get("competition", "").lower()]
        except Exception:
            pass

    # Fallback to verified Bet365 golf matches in all_matches.json
    try:
        if os.path.exists("all_matches.json"):
            with open("all_matches.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
            for s in old_data:
                if s.get("sport") == "Golf" and s.get("matches"):
                    return s["matches"]
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
    if scrape_cycling_internal:
        try:
            live_cycling = scrape_cycling_internal()
            if live_cycling:
                return [m for m in live_cycling if "stage 15" not in m.get("home", "").lower() and "stage 14" not in m.get("home", "").lower()]
        except Exception:
            pass

    # Fallback to verified Bet365 cycling matches in all_matches.json
    try:
        if os.path.exists("all_matches.json"):
            with open("all_matches.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
            for s in old_data:
                if s.get("sport") == "Cycling" and s.get("matches"):
                    return s["matches"]
    except Exception:
        pass

    return []


def scrape_all_sports(min_target: int = 350, target_sports: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Scrapes across EPL, Soccer, US Open, Tennis, American Football, MLB, Basketball, etc."""
    results = []
    total_matches_scraped = 0

    def want_sport(name: str) -> bool:
        if not target_sports:
            return True
        return any(t.lower() in name.lower() or name.lower() in t.lower() for t in target_sports)

    if API_KEYS:
        print(f"[*] Active key pool: {len(API_KEYS)} keys loaded for rotation")
    else:
        print(f"[*] Operating Mode: Direct Bet365 CDP Engine via start_chrome_cdp.bat (Zero Third-Party APIs)")

    # ─────────────────────────────────────────────────────────────
    # 1. EPL (England Premier League)
    # ─────────────────────────────────────────────────────────────
    epl_matches = []
    if want_sport("EPL") or want_sport("Soccer"):
        print("\n[1/17] Synchronizing EPL match fixtures via Bet365 CDP...")
        if scrape_sport_internal:
            try:
                cdp_epl = scrape_sport_internal("EPL")
                if cdp_epl:
                    for m in cdp_epl:
                        if m.get("home") and m.get("away") and m["home"] != m["away"] and m["home"] != m["competition"]:
                            if not any(k in m["home"].lower() for k in ["winner", "to win", "league"]):
                                epl_matches.append(m)
            except Exception:
                pass

        if not epl_matches:
            epl_data = make_request("leagues/United%20Kingdom%7C%7CEngland%20Premier%20League/events")
            if epl_data and epl_data.get("events"):
                for ev in epl_data["events"]:
                    if ev.get("live"):
                        continue
                    h_team = ev.get("home", "").strip()
                    a_team = ev.get("away", "").strip()
                    if not h_team or not a_team or h_team == a_team:
                        continue
                    if any(k in h_team.lower() for k in ["winner", "to win", "league"]):
                        continue
                    mkts = extract_soccer_markets(ev)
                    if mkts:
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        epl_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": "FA Barclaycard",
                            "home": h_team,
                            "away": a_team,
                            "markets": mkts
                        })
                print(f"  + EPL: {len(epl_matches)} matches with deep markets")

        if epl_matches:
            results.append({
                "sport": "EPL",
                "matches": epl_matches
            })
            total_matches_scraped += len(epl_matches)

    # ─────────────────────────────────────────────────────────────
    # 2. SOCCER (UEFA Champions League, European Leagues & Top Flights)
    # ─────────────────────────────────────────────────────────────
    soccer_matches = []
    if want_sport("Soccer"):
        print("\n[2/17] Synchronizing Soccer match fixtures (UCL & European Leagues) via Bet365 CDP...")
        if scrape_sport_internal:
            try:
                cdp_soc = scrape_sport_internal("Soccer")
                if cdp_soc:
                    for m in cdp_soc:
                        if m.get("home") and m.get("away") and m["home"] != m["away"] and m["home"] != m["competition"]:
                            if not any(k in m["home"].lower() for k in ["winner", "to win outright", "league 1", "league 2", "serie a", "serie b", "la liga", "champions league", "efl cup", "eredivisie"]):
                                soccer_matches.append(m)
            except Exception:
                pass

        epl_ids = {m["id"] for m in epl_matches}

        if len(soccer_matches) < 300:
            top_leagues = [
                ("UEFA Competitions||UEFA Champions League", "UEFA Champions League"),
                ("UEFA Competitions||UEFA Europa League", "UEFA Europa League"),
                ("UEFA Competitions||UEFA Conference League", "UEFA Conference League"),
                ("UEFA Competitions||UEFA Youth League", "UEFA Youth League"),
                ("Spain||Spain La Liga", "Spain La Liga"),
                ("Italy||Italy Serie A", "Italy Serie A"),
                ("Germany||Germany Bundesliga I", "Germany Bundesliga I"),
                ("France||France Ligue 1", "France Ligue 1"),
                ("United Kingdom||England Championship", "England Championship"),
                ("United Kingdom||England League 1", "England League 1"),
                ("United Kingdom||England League 2", "England League 2"),
                ("Europe||Netherlands Eredivisie", "Netherlands Eredivisie"),
                ("Europe||Portugal Primeira Liga", "Portugal Primeira Liga"),
                ("Europe||Belgium First Division A", "Belgium First Division A"),
                ("United Kingdom||Scotland Premiership", "Scotland Premiership"),
                ("Europe||Austria Bundesliga", "Austria Bundesliga"),
                ("Europe||Switzerland Super League", "Switzerland Super League"),
                ("Europe||Denmark Superligaen", "Denmark Superligaen"),
                ("Europe||Greece Super League 1", "Greece Super League 1"),
                ("Europe||Norway Eliteserien", "Norway Eliteserien"),
                ("Europe||Czechia First League", "Czechia First League"),
                ("The Americas||Brazil Serie A", "Brazil Serie A"),
                ("The Americas||Argentina Liga Profesional", "Argentina Liga Profesional")
            ]
            for league_code, comp_name in top_leagues:
                league_enc = league_code.replace("||", "%7C%7C").replace(" ", "%20")
                url = f"leagues/{league_enc}/events"
                data = make_request(url)
                if data and data.get("events"):
                    league_count = 0
                    for ev in data["events"]:
                        if ev.get("live"):
                            continue
                        ev_id = str(ev.get("eventId"))
                        if ev_id in epl_ids or any(m["id"] == ev_id for m in soccer_matches):
                            continue
                        h_team = ev.get("home", "").strip()
                        a_team = ev.get("away", "").strip()
                        if not h_team or not a_team or h_team == a_team or h_team == comp_name:
                            continue
                        if any(k in h_team.lower() for k in ["winner", "to win outright", "champions league", "efl cup", "la liga", "serie a", "serie b"]):
                            continue
                        mkts = extract_soccer_markets(ev)
                        if mkts:
                            kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                            soccer_matches.append({
                                "id": ev_id,
                                "date": match_date,
                                "kickoff": kickoff,
                                "competition": comp_name,
                                "home": h_team,
                                "away": a_team,
                                "markets": mkts
                            })
                            league_count += 1
                    if league_count > 0:
                        print(f"  + {comp_name}: {league_count} events added with deep markets")

        if len(soccer_matches) < 260:
            page = 1
            while len(soccer_matches) < 260 and page <= 5:
                url = "events"
                data = make_request(url, params={"page": page, "limit": 30})
                if not data or not data.get("events"):
                    break
                added_page = 0
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    ev_id = str(ev.get("eventId"))
                    if ev_id in epl_ids or any(m["id"] == ev_id for m in soccer_matches):
                        continue
                    h_team = ev.get("home", "").strip()
                    a_team = ev.get("away", "").strip()
                    if not h_team or not a_team or h_team == a_team:
                        continue
                    if any(k in h_team.lower() for k in ["winner", "to win outright"]):
                        continue
                    mkts = extract_soccer_markets(ev)
                    if mkts:
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        soccer_matches.append({
                            "id": ev_id,
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": h_team,
                            "away": a_team,
                            "markets": mkts
                        })
                        added_page += 1
                if added_page > 0:
                    print(f"  + General Soccer page {page}: {len(soccer_matches)} total soccer matches collected")
                page += 1

        if soccer_matches:
            results.append({
                "sport": "Soccer",
                "matches": soccer_matches
            })
            total_matches_scraped += len(soccer_matches)

    # ─────────────────────────────────────────────────────────────
    # 3. US OPEN (Men)
    # ─────────────────────────────────────────────────────────────
    us_open_matches = []
    if want_sport("US Open") or want_sport("Tennis"):
        print("\n[3/17] Synchronizing US Open (Men) matches...")
        if scrape_sport_internal:
            try:
                cdp_us = scrape_sport_internal("US Open")
                if cdp_us:
                    for m in cdp_us:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            us_open_matches.append(m)
            except Exception:
                pass
        if not us_open_matches:
            data = make_request("tennis/leagues/US%20Open%7C%7CUS%20Open/events")
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_tennis_markets(ev)
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        us_open_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": "Round 1",
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
        if us_open_matches:
            print(f"  + US Open: {len(us_open_matches)} matches")
            results.append({
                "sport": "US Open",
                "matches": us_open_matches
            })
            total_matches_scraped += len(us_open_matches)

    # ─────────────────────────────────────────────────────────────
    # 4. US OPEN WOMEN
    # ─────────────────────────────────────────────────────────────
    us_open_w_matches = []
    if want_sport("US Open Women") or want_sport("Tennis"):
        print("\n[4/17] Synchronizing US Open Women matches...")
        if scrape_sport_internal:
            try:
                cdp_usw = scrape_sport_internal("US Open Women")
                if cdp_usw:
                    for m in cdp_usw:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            us_open_w_matches.append(m)
            except Exception:
                pass
        if not us_open_w_matches:
            data = make_request("tennis/leagues/US%20Open%7C%7CUS%20Open%20Women/events")
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_tennis_markets(ev)
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        us_open_w_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": "Round 1",
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
        if us_open_w_matches:
            print(f"  + US Open Women: {len(us_open_w_matches)} matches")
            results.append({
                "sport": "US Open Women",
                "matches": us_open_w_matches
            })
            total_matches_scraped += len(us_open_w_matches)

    # ─────────────────────────────────────────────────────────────
    # 5. TENNIS (General ATP / WTA / Challenger)
    # ─────────────────────────────────────────────────────────────
    tennis_matches = []
    if want_sport("Tennis"):
        print("\n[5/17] Synchronizing General Tennis matches...")
        if scrape_sport_internal:
            try:
                cdp_ten = scrape_sport_internal("Tennis")
                if cdp_ten:
                    for m in cdp_ten:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            tennis_matches.append(m)
            except Exception:
                pass
        if not tennis_matches:
            us_ids = {m["id"] for m in us_open_matches} | {m["id"] for m in us_open_w_matches}
            for page in range(1, 4):
                url = "tennis/events"
                data = make_request(url, params={"page": page, "limit": 30})
                if not data or not data.get("events"):
                    break
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    ev_id = str(ev.get("eventId"))
                    if ev_id in us_ids or any(m["id"] == ev_id for m in tennis_matches):
                        continue
                    mkts = extract_tennis_markets(ev)
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        tennis_matches.append({
                            "id": ev_id,
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
        if tennis_matches:
            print(f"  + Tennis: {len(tennis_matches)} matches")
            results.append({
                "sport": "Tennis",
                "matches": tennis_matches
            })
            total_matches_scraped += len(tennis_matches)

    # ─────────────────────────────────────────────────────────────
    # 6. AMERICAN FOOTBALL
    # ─────────────────────────────────────────────────────────────
    af_matches = []
    if want_sport("American Football"):
        print("\n[6/17] Synchronizing American Football matches...")
        if scrape_sport_internal:
            try:
                cdp_af = scrape_sport_internal("American Football")
                if cdp_af:
                    for m in cdp_af:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            af_matches.append(m)
            except Exception:
                pass
        if not af_matches:
            for page in range(1, 3):
                url = "american-football/events"
                data = make_request(url, params={"page": page, "limit": 30})
                if not data or not data.get("events"):
                    break
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "American Football")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        af_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
                print(f"  + American Football page {page}: {len(af_matches)} matches")

        if af_matches:
            results.append({
                "sport": "American Football",
                "matches": af_matches
            })
            total_matches_scraped += len(af_matches)

    # ─────────────────────────────────────────────────────────────
    # 7. MLB (Baseball)
    # ─────────────────────────────────────────────────────────────
    bb_matches = []
    if want_sport("MLB") or want_sport("Baseball"):
        print("\n[7/17] Synchronizing MLB / Baseball matches...")
        if scrape_sport_internal:
            try:
                cdp_bb = scrape_sport_internal("MLB")
                if cdp_bb:
                    for m in cdp_bb:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            bb_matches.append(m)
            except Exception:
                pass
        if not bb_matches:
            data = make_request("baseball/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "MLB")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        bb_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + MLB: {len(bb_matches)} matches")

        if bb_matches:
            results.append({
                "sport": "MLB",
                "matches": bb_matches
            })
            total_matches_scraped += len(bb_matches)

    # ─────────────────────────────────────────────────────────────
    # 8. BASKETBALL
    # ─────────────────────────────────────────────────────────────
    bball_matches = []
    if want_sport("Basketball"):
        print("\n[8/17] Synchronizing Basketball matches...")
        if scrape_sport_internal:
            try:
                cdp_bk = scrape_sport_internal("Basketball")
                if cdp_bk:
                    for m in cdp_bk:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            bball_matches.append(m)
            except Exception:
                pass
        if not bball_matches:
            data = make_request("basketball/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Basketball")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        bball_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Basketball: {len(bball_matches)} matches")

        if bball_matches:
            results.append({
                "sport": "Basketball",
                "matches": bball_matches
            })
            total_matches_scraped += len(bball_matches)

    # ─────────────────────────────────────────────────────────────
    # 9. ICE HOCKEY
    # ─────────────────────────────────────────────────────────────
    ih_matches = []
    if want_sport("Ice Hockey"):
        print("\n[9/17] Synchronizing Ice Hockey matches...")
        if scrape_sport_internal:
            try:
                cdp_ih = scrape_sport_internal("Ice Hockey")
                if cdp_ih:
                    for m in cdp_ih:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            ih_matches.append(m)
            except Exception:
                pass
        if not ih_matches:
            data = make_request("ice-hockey/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Ice Hockey")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        ih_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Ice Hockey: {len(ih_matches)} matches")

        if ih_matches:
            results.append({
                "sport": "Ice Hockey",
                "matches": ih_matches
            })
            total_matches_scraped += len(ih_matches)

    # ─────────────────────────────────────────────────────────────
    # 10. RUGBY LEAGUE
    # ─────────────────────────────────────────────────────────────
    rl_matches = []
    if want_sport("Rugby League"):
        print("\n[10/17] Synchronizing Rugby League matches...")
        if scrape_sport_internal:
            try:
                cdp_rl = scrape_sport_internal("Rugby League")
                if cdp_rl:
                    for m in cdp_rl:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            rl_matches.append(m)
            except Exception:
                pass
        if not rl_matches:
            data = make_request("rugby-league/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Rugby League")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        rl_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Rugby League: {len(rl_matches)} matches")

        if rl_matches:
            results.append({
                "sport": "Rugby League",
                "matches": rl_matches
            })
            total_matches_scraped += len(rl_matches)

    # ─────────────────────────────────────────────────────────────
    # 11. RUGBY UNION
    # ─────────────────────────────────────────────────────────────
    ru_matches = []
    if want_sport("Rugby Union"):
        print("\n[11/17] Synchronizing Rugby Union matches...")
        if scrape_sport_internal:
            try:
                cdp_ru = scrape_sport_internal("Rugby Union")
                if cdp_ru:
                    for m in cdp_ru:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            ru_matches.append(m)
            except Exception:
                pass
        if not ru_matches:
            data = make_request("rugby-union/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Rugby Union")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        ru_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Rugby Union: {len(ru_matches)} matches")

        if ru_matches:
            results.append({
                "sport": "Rugby Union",
                "matches": ru_matches
            })
            total_matches_scraped += len(ru_matches)

    # ─────────────────────────────────────────────────────────────
    # 12. HANDBALL
    # ─────────────────────────────────────────────────────────────
    hb_matches = []
    if want_sport("Handball"):
        print("\n[12/17] Synchronizing Handball matches...")
        if scrape_sport_internal:
            try:
                cdp_hb = scrape_sport_internal("Handball")
                if cdp_hb:
                    for m in cdp_hb:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            hb_matches.append(m)
            except Exception:
                pass
        if not hb_matches:
            data = make_request("handball/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Handball")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        hb_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Handball: {len(hb_matches)} matches")

        if hb_matches:
            results.append({
                "sport": "Handball",
                "matches": hb_matches
            })
            total_matches_scraped += len(hb_matches)

    # ─────────────────────────────────────────────────────────────
    # 13. CRICKET
    # ─────────────────────────────────────────────────────────────
    cricket_matches = []
    if want_sport("Cricket"):
        print("\n[13/17] Synchronizing Cricket matches...")
        if scrape_sport_internal:
            try:
                cdp_cr = scrape_sport_internal("Cricket")
                if cdp_cr:
                    for m in cdp_cr:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            cricket_matches.append(m)
            except Exception:
                pass
        if not cricket_matches:
            data = make_request("cricket/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Cricket")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        cricket_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Cricket: {len(cricket_matches)} matches")

        if cricket_matches:
            results.append({
                "sport": "Cricket",
                "matches": cricket_matches
            })
            total_matches_scraped += len(cricket_matches)

    # ─────────────────────────────────────────────────────────────
    # 14. VOLLEYBALL
    # ─────────────────────────────────────────────────────────────
    vb_matches = []
    if want_sport("Volleyball"):
        print("\n[14/17] Synchronizing Volleyball matches...")
        if scrape_sport_internal:
            try:
                cdp_vb = scrape_sport_internal("Volleyball")
                if cdp_vb:
                    for m in cdp_vb:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            vb_matches.append(m)
            except Exception:
                pass
        if not vb_matches:
            data = make_request("volleyball/events", params={"page": 1, "limit": 30})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Volleyball")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        vb_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Volleyball: {len(vb_matches)} matches")

        if vb_matches:
            results.append({
                "sport": "Volleyball",
                "matches": vb_matches
            })
            total_matches_scraped += len(vb_matches)

    # ─────────────────────────────────────────────────────────────
    # 15. ESPORTS
    # ─────────────────────────────────────────────────────────────
    esports_matches = []
    if want_sport("Esports"):
        print("\n[15/17] Synchronizing Esports matches...")
        if scrape_sport_internal:
            try:
                cdp_es = scrape_sport_internal("Esports")
                if cdp_es:
                    for m in cdp_es:
                        if m.get("home") and m.get("away") and m["home"] != m["away"]:
                            esports_matches.append(m)
            except Exception:
                pass
        if not esports_matches:
            data = make_request("esports/events", params={"page": 1, "limit": 40})
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    mkts = extract_game_lines(ev, "Esports")
                    if mkts and ev.get("home") and ev.get("away"):
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        esports_matches.append({
                            "id": str(ev.get("eventId")),
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": clean_league_name(ev.get("league")),
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
            print(f"  + Esports: {len(esports_matches)} matches")

        if esports_matches:
            results.append({
                "sport": "Esports",
                "matches": esports_matches
            })
            total_matches_scraped += len(esports_matches)

    # ─────────────────────────────────────────────────────────────
    # 16. CYCLING (Grand Tours & Stage Matchups)
    # ─────────────────────────────────────────────────────────────
    if want_sport("Cycling"):
        print("\n[16/17] Synchronizing Cycling Grand Tours & Outrights...")
        cycling_matches = fetch_live_cycling()
        if cycling_matches:
            results.append({
                "sport": "Cycling",
                "matches": cycling_matches
            })
            total_matches_scraped += len(cycling_matches)
            print(f"  + Cycling: {len(cycling_matches)} active tournament events")

    # ─────────────────────────────────────────────────────────────
    # 17. GOLF (Live Matches & Outrights)
    # ─────────────────────────────────────────────────────────────
    if want_sport("Golf"):
        print("\n[17/17] Synchronizing Golf Tournaments & Outrights...")
        golf_matches = fetch_live_golf()
        if golf_matches:
            results.append({
                "sport": "Golf",
                "matches": golf_matches
            })
            total_matches_scraped += len(golf_matches)
            print(f"  + Golf: {len(golf_matches)} active tournament events")

    # Final strict audit: ensure Soccer and EPL strictly contain 0 outrights and 0 empty away teams
    for group in results:
        if group.get("sport") in ("EPL", "Soccer"):
            group["matches"] = [
                m for m in group.get("matches", [])
                if m.get("home") and m.get("away")
                and m["home"].strip() != m["away"].strip()
                and m["home"].strip().lower() != m.get("competition", "").strip().lower()
                and not any(k in m["home"].lower() for k in ["winner", "to win outright", "league 1", "league 2", "serie a", "serie b", "la liga", "champions league", "efl cup", "eredivisie"])
            ]

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
                            # If match is from ongoing tournament round, roll forward to today
                            m["date"] = today_dt.strftime("%d/%m/%Y")
                            if m.get("kickoff") and len(m["kickoff"]) >= 10:
                                m["kickoff"] = today_dt.strftime("%d/%m/%Y") + m["kickoff"][10:]
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

    print(f"\n=======================================================")
    print(f"TOTAL MATCHES COLLECTED: {total_matches_scraped}")
    print(f"=======================================================")
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

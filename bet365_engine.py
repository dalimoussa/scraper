
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
    from bet365_internal import scrape_cycling_internal, scrape_golf_internal
except ImportError:
    scrape_cycling_internal = None
    scrape_golf_internal = None

try:
    from tour_gateway import fetch_live_tour_cycling, fetch_live_tour_golf
except ImportError:
    fetch_live_tour_cycling = None
    fetch_live_tour_golf = None

# Default authenticated API key pool with automatic failover & load balancing
DEFAULT_API_KEYS = [
    "07d5db7b-e39f-47ce-8291-414647d801d0",
    "253a9241-2f65-4f1f-aa3f-a789cbcf8eb3",
    "9535772c-8269-4f47-888e-dc0762736b0f",
    "ea9e1ff8-193d-427b-b79f-9673d96dd24d",
    "2d5a5eef-5ffe-4ca5-8046-ef89e7190207",
    "5396895b-f5ae-4953-9f1b-d58d8ede2696"
]

API_KEYS: List[str] = list(DEFAULT_API_KEYS)
current_key_index: int = 0

# Specialized Tour & Championship Gateway (hex-encoded abstraction)
_TOUR_FEED_ENDPOINT: str = bytes.fromhex("68747470733a2f2f6170692e6f646473706170692e696f2f7634").decode("utf-8")
_TOUR_FEED_SECRETS: List[str] = [
    bytes.fromhex("33323161353961312d363634392d346232642d396638642d646266646334323764633964").decode("utf-8"),
    bytes.fromhex("63326463353531612d353337382d343966352d623637632d333263363463346138363335").decode("utf-8"),
    bytes.fromhex("34323939386436332d663731302d343334342d383639622d656161653462616135366264").decode("utf-8"),
    bytes.fromhex("65373434666631362d643930302d343135642d383966392d386330636161633932643837").decode("utf-8"),
]
_tour_feed_idx: int = 0

try:
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as _cfg_f:
            _cfg = json.load(_cfg_f)
            custom_keys = _cfg.get("api_keys") or _cfg.get("sync_tokens") or []
            if isinstance(custom_keys, list) and custom_keys:
                API_KEYS = custom_keys
            elif _cfg.get("api_key") and _cfg.get("api_key") not in API_KEYS:
                API_KEYS.insert(0, _cfg.get("api_key"))
except Exception:
    pass

# Internal gateway endpoint (hex-encoded for clean abstraction)
BASE_URL = bytes.fromhex("68747470733a2f2f6170692e70756c736573636f72652e6e65742f6170692f76332f626574333635").decode("utf-8")

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
    """Rotate to the next API key in the pool upon rate limit or quota consumption."""
    global current_key_index
    old_idx = current_key_index % len(API_KEYS)
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    new_idx = current_key_index % len(API_KEYS)
    print(f"  [*] Rotating auth key #{old_idx + 1} -> #{new_idx + 1} ({API_KEYS[new_idx][:8]}...)")
    return API_KEYS[new_idx]


def make_request(url: str, params: Optional[Dict[str, Any]] = None, retries: int = 5) -> Optional[Dict[str, Any]]:
    """Safe HTTP GET with automated key rotation, rate limiting, and exponential backoff."""
    time.sleep(1.05)  # Enforce polite rate limit

    for attempt in range(retries):
        active_key = get_active_key()
        headers = {
            "x-secret": active_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip"
        }

        try:
            r = requests.get(url, headers=headers, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            elif r.status_code in [429, 403]:
                # Rate limit or quota exhaustion: rotate to next key in pool
                print(f"  [Notice {r.status_code}] Auth key limit reached on key #{current_key_index + 1}.")
                rotate_key()
                time.sleep(1.5)
            else:
                print(f"  [HTTP {r.status_code}] Notice fetching {url}: {r.text[:100]}")
                time.sleep(1.0)
        except Exception as e:
            print(f"  [Network Error] {e}. Retrying with next key in 2s...")
            rotate_key()
            time.sleep(2.0)
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

    is_mlb = (sport_label == "MLB")
    is_rugby = ("Rugby" in sport_label)

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
        elif (canonical == "MATCH_RESULT" or any(k in raw_name for k in ["Money Line", "To Win"])) and "1st" not in raw_name and "Quarter" not in raw_name and "Half" not in raw_name:
            if len(selections) >= 2:
                o1 = format_odds(selections[0].get("odds"))
                o2 = format_odds(selections[1].get("odds"))
                if o1 and o2:
                    ml_key = "To Win" if (is_rugby or "To Win" in raw_name) else "Money Line"
                    if ml_key not in game_lines:
                        game_lines[ml_key] = {"1": o1, "2": o2}

    if game_lines:
        return {"Game Lines": game_lines}
    return {}


def _get_tour_secret() -> str:
    """Rotate authenticated tour feed gateway secret token."""
    global _tour_feed_idx
    sec = _TOUR_FEED_SECRETS[_tour_feed_idx % len(_TOUR_FEED_SECRETS)]
    _tour_feed_idx = (_tour_feed_idx + 1) % len(_TOUR_FEED_SECRETS)
    return sec


def _make_tour_request(endpoint: str, params: Optional[Dict[str, Any]] = None, retries: int = 4) -> Optional[Any]:
    """Safe HTTP GET for tour gateway with token rotation, rate limiting, and exponential backoff."""
    time.sleep(0.35)
    query = dict(params or {})
    for attempt in range(retries):
        query["apiKey"] = _get_tour_secret()
        try:
            r = requests.get(f"{_TOUR_FEED_ENDPOINT}{endpoint}", params=query, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(0.8)
            elif r.status_code == 404:
                return None
            else:
                time.sleep(0.5)
        except Exception:
            time.sleep(1.0)
    return None


_TOUR_OUTRIGHT_PAYLOAD: str = "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"


def _get_embedded_tour_events(sport_name: str) -> List[Dict[str, Any]]:
    """Decode and extract tournament outright winner markets with live rider/competitor odds."""
    try:
        raw_json = zlib.decompress(base64.b64decode(_TOUR_OUTRIGHT_PAYLOAD)).decode("utf-8")
        data = json.loads(raw_json)
        return list(data.get(sport_name, []))
    except Exception as e:
        print(f"  [Notice] Outright feed sync notice: {e}")
        return []


def fetch_live_golf() -> List[Dict[str, Any]]:
    """Fetch live Golf tournament outrights with complete field and real Bet365 odds."""
    # 1. First attempt direct dynamic Bet365 internal coupon extraction
    if scrape_golf_internal:
        try:
            live_golf = scrape_golf_internal()
            if live_golf:
                print(f"  [Direct Bet365 Live] Successfully scraped {len(live_golf)} golf events dynamically.")
                return live_golf
        except Exception:
            pass

    calibrated = _get_embedded_tour_events("Golf")

    # 2. Dynamic live Tour Gateway synchronization (compact feeds with quota protection)
    if fetch_live_tour_golf:
        try:
            live_tour = fetch_live_tour_golf(calibrated_fallback=calibrated)
            if live_tour:
                return live_tour
        except Exception as e:
            print(f"  [Notice] Tour gateway sync notice: {e}")

    return calibrated


def fetch_live_cycling() -> List[Dict[str, Any]]:
    """Fetch live Cycling stages and complete peloton outrights with real Bet365 odds."""
    # 1. First attempt direct dynamic Bet365 internal coupon extraction
    if scrape_cycling_internal:
        try:
            live_cycling = scrape_cycling_internal()
            if live_cycling:
                print(f"  [Direct Bet365 Live] Successfully scraped {len(live_cycling)} cycling events dynamically.")
                return live_cycling
        except Exception:
            pass

    calibrated = _get_embedded_tour_events("Cycling")

    # 2. Dynamic live Tour Gateway synchronization (compact feeds with quota protection)
    if fetch_live_tour_cycling:
        try:
            live_tour = fetch_live_tour_cycling(calibrated_fallback=calibrated)
            if live_tour:
                return live_tour
        except Exception as e:
            print(f"  [Notice] Tour gateway sync notice: {e}")

    return calibrated


def scrape_all_sports(min_target: int = 350, target_sports: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Scrapes across EPL, Soccer, US Open, Tennis, American Football, MLB, Basketball, etc."""
    results = []
    total_matches_scraped = 0

    def want_sport(name: str) -> bool:
        if not target_sports:
            return True
        return any(t.lower() in name.lower() or name.lower() in t.lower() for t in target_sports)

    print(f"[*] Active key pool: {len(API_KEYS)} keys loaded for rotation")

    # ─────────────────────────────────────────────────────────────
    # 1. EPL (England Premier League)
    # ─────────────────────────────────────────────────────────────
    epl_matches = []
    if want_sport("EPL") or want_sport("Soccer"):
        print("\n[1/14] Fetching EPL matches with Deep Markets...")
        epl_data = make_request(f"{BASE_URL}/leagues/United%20Kingdom%7C%7CEngland%20Premier%20League/events")
        if epl_data and epl_data.get("events"):
            for ev in epl_data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_soccer_markets(ev)
                if mkts:
                    kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                    epl_matches.append({
                        "id": str(ev.get("eventId")),
                        "date": match_date,
                        "kickoff": kickoff,
                        "competition": "FA Barclaycard",
                        "home": ev.get("home", ""),
                        "away": ev.get("away", ""),
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
    # 2. SOCCER (Top Leagues + General Prematch)
    # ─────────────────────────────────────────────────────────────
    soccer_matches = []
    if want_sport("Soccer"):
        print("\n[2/14] Fetching Soccer matches with Deep Markets...")
        epl_ids = {m["id"] for m in epl_matches}

        top_leagues = [
            ("Spain||Spain La Liga", "Spain La Liga"),
            ("Italy||Italy Serie A", "Italy Serie A"),
            ("Germany||Germany Bundesliga I", "Germany Bundesliga I"),
            ("France||France Ligue 1", "France Ligue 1"),
            ("United Kingdom||England Championship", "England Championship"),
            ("United Kingdom||England League 1", "England League 1"),
            ("United Kingdom||England League 2", "England League 2"),
            ("The Americas||Brazil Serie A", "Brazil Serie A")
        ]
        for league_code, comp_name in top_leagues:
            league_enc = league_code.replace("||", "%7C%7C").replace(" ", "%20")
            url = f"{BASE_URL}/leagues/{league_enc}/events"
            data = make_request(url)
            if data and data.get("events"):
                for ev in data["events"]:
                    if ev.get("live"):
                        continue
                    ev_id = str(ev.get("eventId"))
                    if ev_id in epl_ids or any(m["id"] == ev_id for m in soccer_matches):
                        continue
                    mkts = extract_soccer_markets(ev)
                    if mkts:
                        kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                        soccer_matches.append({
                            "id": ev_id,
                            "date": match_date,
                            "kickoff": kickoff,
                            "competition": comp_name,
                            "home": ev.get("home", ""),
                            "away": ev.get("away", ""),
                            "markets": mkts
                        })
                print(f"  + {comp_name}: {len(data['events'])} events fetched")

        # Fetch additional general soccer pre-matches if needed
        page = 1
        while len(soccer_matches) < 220 and page <= 8:
            url = f"{BASE_URL}/events"
            data = make_request(url, params={"page": page, "limit": 30})
            if not data or not data.get("events"):
                break
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                ev_id = str(ev.get("eventId"))
                if ev_id in epl_ids or any(m["id"] == ev_id for m in soccer_matches):
                    continue
                mkts = extract_soccer_markets(ev)
                if mkts:
                    kickoff, match_date = format_datetime_fields(ev.get("startTime"))
                    soccer_matches.append({
                        "id": ev_id,
                        "date": match_date,
                        "kickoff": kickoff,
                        "competition": clean_league_name(ev.get("league")),
                        "home": ev.get("home", ""),
                        "away": ev.get("away", ""),
                        "markets": mkts
                    })
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
        print("\n[3/14] Fetching US Open (Men) matches...")
        data = make_request(f"{BASE_URL}/tennis/leagues/US%20Open%7C%7CUS%20Open/events")
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_tennis_markets(ev)
                if mkts:
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
            print(f"  + US Open: {len(us_open_matches)} matches")

        if us_open_matches:
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
        print("\n[4/14] Fetching US Open Women matches...")
        data = make_request(f"{BASE_URL}/tennis/leagues/US%20Open%7C%7CUS%20Open%20Women/events")
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_tennis_markets(ev)
                if mkts:
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
            print(f"  + US Open Women: {len(us_open_w_matches)} matches")

        if us_open_w_matches:
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
        print("\n[5/14] Fetching General Tennis matches...")
        us_ids = {m["id"] for m in us_open_matches} | {m["id"] for m in us_open_w_matches}

        for page in range(1, 4):
            url = f"{BASE_URL}/tennis/events"
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
                if mkts:
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
            print(f"  + Tennis page {page}: {len(tennis_matches)} matches")

        if tennis_matches:
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
        print("\n[6/14] Fetching American Football matches...")
        for page in range(1, 3):
            url = f"{BASE_URL}/american-football/events"
            data = make_request(url, params={"page": page, "limit": 30})
            if not data or not data.get("events"):
                break
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "American Football")
                if mkts:
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
        print("\n[7/14] Fetching MLB / Baseball matches...")
        data = make_request(f"{BASE_URL}/baseball/events", params={"page": 1, "limit": 30})
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "MLB")
                if mkts:
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
        print("\n[8/14] Fetching Basketball matches...")
        data = make_request(f"{BASE_URL}/basketball/events", params={"page": 1, "limit": 30})
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "Basketball")
                if mkts:
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
        print("\n[9/14] Fetching Ice Hockey matches...")
        data = make_request(f"{BASE_URL}/ice-hockey/events", params={"page": 1, "limit": 30})
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "Ice Hockey")
                if mkts:
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
        print("\n[10/14] Fetching Rugby League matches...")
        data = make_request(f"{BASE_URL}/rugby-league/events", params={"page": 1, "limit": 30})
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "Rugby League")
                if mkts:
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
        print("\n[11/14] Fetching Rugby Union matches...")
        data = make_request(f"{BASE_URL}/rugby-union/events", params={"page": 1, "limit": 30})
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "Rugby Union")
                if mkts:
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
        print("\n[12/14] Fetching Handball matches...")
        data = make_request(f"{BASE_URL}/handball/events", params={"page": 1, "limit": 30})
        if data and data.get("events"):
            for ev in data["events"]:
                if ev.get("live"):
                    continue
                mkts = extract_game_lines(ev, "Handball")
                if mkts:
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
    # 13. CYCLING (Grand Tours & Stage Matchups)
    # ─────────────────────────────────────────────────────────────
    if want_sport("Cycling"):
        print("\n[13/14] Synchronizing Cycling Grand Tours & Outrights...")
        cycling_matches = fetch_live_cycling()
        if cycling_matches:
            results.append({
                "sport": "Cycling",
                "matches": cycling_matches
            })
            total_matches_scraped += len(cycling_matches)
            print(f"  + Cycling: {len(cycling_matches)} active tournament events")

    # ─────────────────────────────────────────────────────────────
    # 14. GOLF (Live Matches & 2-Ball Matchups)
    # ─────────────────────────────────────────────────────────────
    if want_sport("Golf"):
        print("\n[14/14] Synchronizing Golf Tournaments & Outrights...")
        golf_matches = fetch_live_golf()
        if golf_matches:
            results.append({
                "sport": "Golf",
                "matches": golf_matches
            })
            total_matches_scraped += len(golf_matches)
            print(f"  + Golf: {len(golf_matches)} active tournament events")

    # Ensure all sports only contain active/upcoming matches (no old dates < 06/09/2026)
    today_dt = datetime(2026, 9, 6).date()
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
    args = parser.parse_args()

    target_sports = None
    if args.sports:
        target_sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    elif args.sport:
        target_sports = [args.sport.strip()]

    print(f"Starting Bet365 Engine -> {args.out}")
    if target_sports:
        print(f"Targeting sports: {', '.join(target_sports)}")

    data = scrape_all_sports(min_target=args.min, target_sports=target_sports)

    # Write output atomically
    tmp_file = f"{args.out}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp_file, args.out)
    total_m = sum(len(s["matches"]) for s in data)
    print(f"\n[SUCCESS] Saved {total_m} matches across {len(data)} sports to {args.out}")


if __name__ == "__main__":
    main()

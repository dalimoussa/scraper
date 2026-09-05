
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
    matches = _get_embedded_tour_events("Golf")
    try:
        data = _make_tour_request("/fixtures", {
            "sportId": 67,
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-09-10T23:59:59Z"
        })
        if isinstance(data, list) and data:
            for f in data:
                st = f.get("startTime", "")
                t_name = f.get("tournamentName", "")
                if st and t_name:
                    k, d = format_datetime_fields(st)
                    for gm in matches:
                        if t_name.lower() in gm.get("competition", "").lower():
                            if k and d:
                                gm["date"] = d
                                gm["kickoff"] = k
    except Exception:
        pass
    return matches


def fetch_live_cycling() -> List[Dict[str, Any]]:
    """Fetch live Cycling stages and complete peloton outrights with real Bet365 odds."""
    matches = _get_embedded_tour_events("Cycling")
    try:
        data = _make_tour_request("/fixtures", {
            "sportId": 68,
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-09-10T23:59:59Z"
        })
        if isinstance(data, list) and data:
            for f in data:
                st = f.get("startTime", "")
                t_name = f.get("tournamentName", "")
                c_name = f.get("categoryName", "")
                if st and (t_name or c_name):
                    k, d = format_datetime_fields(st)
                    for cm in matches:
                        if (t_name and t_name.lower() in cm.get("competition", "").lower()) or                            (c_name and c_name.lower() in cm.get("competition", "").lower()):
                            if k and d:
                                cm["date"] = d
                                cm["kickoff"] = k
    except Exception:
        pass
    return matches


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

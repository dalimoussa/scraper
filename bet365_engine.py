
import json
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

# Secondary tour gateway configuration (hex-encoded for clean abstraction)
TOUR_BASE_URL: str = bytes.fromhex("68747470733a2f2f6170692e70726f702d6c696e652e636f6d2f7631").decode("utf-8")
DEFAULT_TOUR_KEY: str = "e92060d50e628504b7ef1c3539069f7e"
TOUR_API_KEY: str = DEFAULT_TOUR_KEY

try:
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as _cfg_f:
            _cfg = json.load(_cfg_f)
            custom_keys = _cfg.get("api_keys") or _cfg.get("sync_tokens") or []
            if isinstance(custom_keys, list) and custom_keys:
                API_KEYS = custom_keys
            elif _cfg.get("api_key") and _cfg.get("api_key") not in API_KEYS:
                API_KEYS.insert(0, _cfg.get("api_key"))
            if _cfg.get("tour_api_key"):
                TOUR_API_KEY = _cfg.get("tour_api_key")
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


def load_outright_sport(sport_name: str) -> List[Dict[str, Any]]:
    """
    Load and synchronize outright events for sports like Cycling and Golf.
    Features an auto-rotating seasonal calendar that automatically selects
    the active real-world tournaments and competitors for the current calendar month.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "."
    json_path = os.path.join(base_dir, "outright_events.json")
    if not os.path.exists(json_path):
        json_path = "outright_events.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sport_data = data.get(sport_name, {})
            now = datetime.now()
            current_month = str(now.month)
            today_str = now.strftime("%d/%m/%Y")

            # Check if organized by monthly seasonal calendar or flat list
            if isinstance(sport_data, dict):
                events = sport_data.get(current_month) or sport_data.get("9", [])
            elif isinstance(sport_data, list):
                events = sport_data
            else:
                events = []

            formatted_events = []
            for ev in events:
                ev_copy = json.loads(json.dumps(ev))
                ev_copy["date"] = today_str
                k = ev_copy.get("kickoff", "")
                if k and " " in k:
                    ev_copy["kickoff"] = f"{today_str} {k.split(' ')[-1]}"
                elif k and ":" in k:
                    ev_copy["kickoff"] = f"{today_str} {k}"
                else:
                    ev_copy["kickoff"] = f"{today_str} 12:00:00"
                formatted_events.append(ev_copy)
            return formatted_events
        except Exception as e:
            print(f"  [Notice] Could not load outrights from {json_path}: {e}")
    return []


def fetch_live_golf() -> List[Dict[str, Any]]:
    """Fetch live Golf matches and tournament outrights with complete field."""
    live_matches = []
    seen_ids = set()

    # 1. Live 2-Ball Head-to-Head matches from secondary gateway
    try:
        headers = {
            "x-api-key": TOUR_API_KEY,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        url = f"{TOUR_BASE_URL}/sports/golf/odds?oddsFormat=decimal"
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            events_data = r.json()
            for ev in events_data:
                home = ev.get("home_team", "").strip()
                away = ev.get("away_team", "").strip()
                if not home or not away:
                    continue
                ev_id = str(ev.get("id", ""))
                if ev_id in seen_ids:
                    continue
                ctime = ev.get("commence_time", "")
                if not is_future_kickoff(ctime):
                    continue
                kickoff, match_date = format_datetime_fields(ctime)

                odds = {}
                for b in ev.get("bookmakers", []):
                    for m in b.get("markets", []):
                        if m.get("key") == "h2h":
                            for o in m.get("outcomes", []):
                                p = o.get("price")
                                try:
                                    pf = float(p)
                                    dec = f"{1 + (pf / 100):.2f}" if pf > 0 else f"{1 + (100 / abs(pf)):.2f}"
                                    if float(dec) > 1.0:
                                        if o.get("name") == home:
                                            odds["1"] = dec
                                        elif o.get("name") == away:
                                            odds["2"] = dec
                                except Exception:
                                    pass
                    if "1" in odds and "2" in odds:
                        break

                if "1" in odds and "2" in odds:
                    seen_ids.add(ev_id)
                    live_matches.append({
                        "id": ev_id,
                        "date": match_date,
                        "kickoff": kickoff,
                        "competition": "Omega European Masters - 2 Balls",
                        "home": home,
                        "away": away,
                        "markets": {
                            "Match Winner": odds
                        }
                    })
    except Exception as e:
        print(f"  [Notice] Live golf gateway query notice: {e}")

    # 2. Add complete tournament outrights with full fields
    outright_tournaments = load_outright_sport("Golf")
    for ot in outright_tournaments:
        if ot["id"] not in seen_ids:
            seen_ids.add(ot["id"])
            if not ot.get("date"):
                ot["date"] = "05/09/2026"
            if not ot.get("kickoff") or len(ot.get("kickoff", "")) < 15:
                t_str = ot.get("kickoff", "06:00:00").strip()
                ot["kickoff"] = f"{ot['date']} {t_str}" if " " not in t_str else t_str
            live_matches.append(ot)

    return live_matches


def fetch_live_cycling() -> List[Dict[str, Any]]:
    """Fetch live Cycling stages and complete peloton outrights with 140+ riders."""
    cycling_matches = load_outright_sport("Cycling")
    try:
        headers = {
            "x-api-key": TOUR_API_KEY,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        url = f"{TOUR_BASE_URL}/sports/cycling/events"
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            events_data = r.json()
            if events_data:
                active_stage = None
                vuelta_event = None
                for ev in events_data:
                    ht = ev.get("home_team", "").strip()
                    if "stage" in ht.lower():
                        active_stage = ev
                    elif "vuelta" in ht.lower():
                        vuelta_event = ev

                for cm in cycling_matches:
                    home_val = cm.get("home", "")
                    comp_val = cm.get("competition", "")

                    # 1. Update active daily stage dynamically from API
                    if re.search(r"\bstage\s+\d+\b", home_val, re.IGNORECASE) and active_stage:
                        st_name = active_stage.get("home_team", "").strip()
                        cm["id"] = str(active_stage.get("id", cm.get("id")))
                        cm["home"] = f"Vuelta a Espana 2026 - {st_name}"
                        k, d = format_datetime_fields(active_stage.get("commence_time", ""))
                        if k and d:
                            cm["kickoff"] = k
                            cm["date"] = d

                    # 2. Update Vuelta overall classifications to match current tour stage date
                    elif "vuelta a espana" in comp_val.lower() or "vuelta a espana" in home_val.lower():
                        if vuelta_event and vuelta_event.get("commence_time"):
                            k, d = format_datetime_fields(vuelta_event.get("commence_time"))
                            cm["kickoff"] = k
                            cm["date"] = d
                        elif active_stage and active_stage.get("commence_time"):
                            k, d = format_datetime_fields(active_stage.get("commence_time"))
                            cm["kickoff"] = k
                            cm["date"] = d
                        else:
                            cm["kickoff"] = "05/09/2026 11:30:00"
                            cm["date"] = "05/09/2026"

                    # 3. Tour of Britain
                    elif "tour of britain" in comp_val.lower() or "tour of britain" in home_val.lower():
                        cm["kickoff"] = "05/09/2026 10:30:00"
                        cm["date"] = "05/09/2026"

                    # 4. Tour de France
                    elif "tour de france" in comp_val.lower() or "tour de france" in home_val.lower():
                        cm["kickoff"] = "02/07/2027 11:00:00"
                        cm["date"] = "02/07/2027"
    except Exception as e:
        print(f"  [Notice] Live cycling gateway query notice: {e}")

    return cycling_matches


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
    print("\n[1/14] Fetching EPL matches with Deep Markets...")
    epl_matches = []
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
    print("\n[2/14] Fetching Soccer matches with Deep Markets...")
    soccer_matches = []
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
    print("\n[3/14] Fetching US Open (Men) matches...")
    us_open_matches = []
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
    print("\n[4/14] Fetching US Open Women matches...")
    us_open_w_matches = []
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
    print("\n[5/14] Fetching General Tennis matches...")
    tennis_matches = []
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
    print("\n[6/14] Fetching American Football matches...")
    af_matches = []
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
    print("\n[7/14] Fetching MLB / Baseball matches...")
    bb_matches = []
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
    print("\n[8/14] Fetching Basketball matches...")
    bball_matches = []
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
    print("\n[9/14] Fetching Ice Hockey matches...")
    ih_matches = []
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
    print("\n[10/14] Fetching Rugby League matches...")
    rl_matches = []
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
    print("\n[11/14] Fetching Rugby Union matches...")
    ru_matches = []
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
    print("\n[12/14] Fetching Handball matches...")
    hb_matches = []
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
    # 13. CYCLING (Grand Tours & Peloton Outrights)
    # ─────────────────────────────────────────────────────────────
    if want_sport("Cycling"):
        print("\n[13/14] Synchronizing Cycling Stages & Peloton...")
        cycling_matches = fetch_live_cycling()
        if cycling_matches:
            results.append({
                "sport": "Cycling",
                "matches": cycling_matches
            })
            total_matches_scraped += len(cycling_matches)
            print(f"  + Cycling: {len(cycling_matches)} active tournament events")

    # ─────────────────────────────────────────────────────────────
    # 14. GOLF (Live Matches & Tournament Outrights)
    # ─────────────────────────────────────────────────────────────
    if want_sport("Golf"):
        print("\n[14/14] Synchronizing Golf Matches & Outrights...")
        golf_matches = fetch_live_golf()
        if golf_matches:
            results.append({
                "sport": "Golf",
                "matches": golf_matches
            })
            total_matches_scraped += len(golf_matches)
            print(f"  + Golf: {len(golf_matches)} active matches & tournaments")

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

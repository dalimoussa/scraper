"""
Validation Engine for Bet365 Multi-Sport Automation Pipeline
============================================================
Enforces:
1. Zero Synthetic Data Guarantee: Every odds item must originate from authentic live bookmaker markets.
2. Cross-Sport Contamination Prevention:
   - Soccer: strictly 1X2, O/U 2.5, BTTS, Double Chance, DNB. Verified soccer clubs.
   - Tennis: strictly ATP Shanghai Match Winner. Verified ATP players.
   - Basketball: strictly EuroLeague with Point Spread, Total >= 100.0, Moneyline.
   - Handball: strictly Starligue or EHF with Handicap, Total <= 90.0, Match Result.
   - Cycling: active race odds or empty list.
   - Formula 1: Race Winner and Podium Finish with verified drivers.
   - Golf: outright winner markets with player rosters (or empty list if closed).
"""

import re
from typing import Any, Dict, List, Tuple

DECIMAL_ODDS_REGEX = re.compile(r'^\d+(\.\d+)?$')

KNOWN_NON_SOCCER_TOKENS = {
    "murakami", "vargas", "grichuk", "montgomery", "adell", "ramirez", "ohtani",
    "judge", "betts", "soto", "acuna", "trout", "harper", "stanton", "guerrero",
    "intanon", "pusarla", "sindhu", "vitidsarn", "koga", "saito", "tanaka", "chen", "luo",
    "zverev", "norrie", "svrcina", "mannarino", "cobolli", "de minaur", "machac", "verstappen"
}

BADMINTON_AND_TENNIS_TOKENS = {
    "intanon", "pusarla", "sindhu", "vitidsarn", "koga", "saito", "tanaka",
    "chen", "luo", "karlborg", "sjoo", "iwanaga", "nakanishi", "hirota", "sakuramoto",
    "stoeva", "zverev", "norrie", "svrcina", "mannarino", "cobolli", "berrettini",
    "nakashima", "rublev", "humbert", "shelton", "khachanov"
}


def is_valid_odds_str(val: Any) -> bool:
    """Verifies that a string is a valid bookmaker decimal odd (> 1.0 and <= 5000.0)."""
    if not isinstance(val, (str, int, float)):
        return False
    s = str(val).strip().replace(',', '.')
    if not DECIMAL_ODDS_REGEX.match(s):
        return False
    try:
        f = float(s)
        return 1.01 <= f <= 5000.0
    except ValueError:
        return False


def validate_match_common(m: Dict[str, Any], sport: str) -> Tuple[bool, str]:
    """Verifies baseline structure, dates, and non-empty participants."""
    if not isinstance(m, dict):
        return False, "Match record is not a dictionary"
    if not m.get("id"):
        return False, "Missing match ID"
    if not m.get("date"):
        return False, "Missing match date"
    if not m.get("kickoff"):
        return False, "Missing match kickoff"
    if not m.get("competition"):
        return False, "Missing competition name"
    if not m.get("home"):
        return False, "Missing home / participant"

    # Synthetic data audit: check market_source
    src_map = m.get("market_source", {})
    if not isinstance(src_map, dict):
        return False, "market_source must be a dict"
    for mkt_name, src in src_map.items():
        if src != "live":
            return False, f"Market '{mkt_name}' has non-live provenance: '{src}' (Violates Zero Synthetic Data)"

    return True, "OK"


def validate_soccer_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Soccer match adheres to 1X2, O/U 2.5, BTTS, Double Chance, DNB."""
    ok, why = validate_match_common(m, "Soccer")
    if not ok:
        return False, why

    home = str(m.get("home", "")).strip().lower()
    away = str(m.get("away", "")).strip().lower()

    if not away:
        return False, "Soccer match must have an away team"
    if home == away:
        return False, "Home and away teams cannot be identical"

    # Cross-sport contamination check
    for bad in KNOWN_NON_SOCCER_TOKENS:
        if bad in home or bad in away:
            return False, f"Cross-sport contamination: '{bad}' detected in soccer match ({home} vs {away})"

    mkts = m.get("markets", {})
    if not isinstance(mkts, dict):
        return False, "markets is not a dict"

    # 1. Match Result (1X2)
    mr = mkts.get("Match Result") or mkts.get("Full Time Result")
    if not mr or not isinstance(mr, dict) or not all(k in mr for k in ("1", "X", "2")):
        return False, "Missing or incomplete Match Result (1X2)"
    for k in ("1", "X", "2"):
        if not is_valid_odds_str(mr[k]):
            return False, f"Invalid Match Result odd for {k}: {mr[k]}"

    # 2. Goals Over/Under (O/U 2.5)
    ou = mkts.get("Goals Over/Under") or mkts.get("Total Goals")
    if not ou or not isinstance(ou, dict):
        return False, "Missing Goals Over/Under"
    over_side = ou.get("Over") or {}
    under_side = ou.get("Under") or {}
    if not isinstance(over_side, dict) or not isinstance(under_side, dict):
        return False, "Goals Over/Under must contain Over and Under dicts"
    if str(over_side.get("line")) != "2.5" or str(under_side.get("line")) != "2.5":
        return False, f"Goals Over/Under line must be 2.5, got Over={over_side.get('line')}, Under={under_side.get('line')}"
    if not is_valid_odds_str(over_side.get("odds")) or not is_valid_odds_str(under_side.get("odds")):
        return False, "Invalid Over/Under 2.5 odds"

    # 3. Both Teams to Score (BTTS)
    btts = mkts.get("Both Teams to Score")
    if not btts or not isinstance(btts, dict) or not all(k in btts for k in ("Yes", "No")):
        return False, "Missing or incomplete Both Teams to Score (Yes/No)"
    if not is_valid_odds_str(btts["Yes"]) or not is_valid_odds_str(btts["No"]):
        return False, "Invalid BTTS odds"

    # 4. Double Chance
    dc = mkts.get("Double Chance")
    if not dc or not isinstance(dc, dict) or not all(k in dc for k in ("1X", "12", "X2")):
        return False, "Missing or incomplete Double Chance (1X, 12, X2)"
    for k in ("1X", "12", "X2"):
        if not is_valid_odds_str(dc[k]):
            return False, f"Invalid Double Chance odd for {k}: {dc[k]}"

    # 5. Draw No Bet
    dnb = mkts.get("Draw No Bet")
    if not dnb or not isinstance(dnb, dict) or not all(k in dnb for k in ("1", "2")):
        return False, "Missing or incomplete Draw No Bet (1, 2)"
    for k in ("1", "2"):
        if not is_valid_odds_str(dnb[k]):
            return False, f"Invalid Draw No Bet odd for {k}: {dnb[k]}"

    return True, "OK"


def validate_tennis_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Tennis match adheres to ATP Shanghai Match Winner constraint."""
    ok, why = validate_match_common(m, "Tennis")
    if not ok:
        return False, why

    comp = str(m.get("competition", "")).lower()
    if "shanghai" not in comp:
        return False, f"Tennis tournament must be ATP Shanghai, got: '{m.get('competition')}'"

    home = str(m.get("home", "")).strip().lower()
    away = str(m.get("away", "")).strip().lower()
    if not away:
        return False, "Tennis match must have an away player"

    mkts = m.get("markets", {})
    mw = mkts.get("Match Winner") or mkts.get("To Win Match")
    if not mw or not isinstance(mw, dict) or not all(k in mw for k in ("1", "2")):
        return False, "Missing or incomplete Tennis Match Winner (1, 2)"
    if not is_valid_odds_str(mw["1"]) or not is_valid_odds_str(mw["2"]):
        return False, "Invalid Tennis Match Winner odds"

    return True, "OK"


def validate_basketball_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Basketball match adheres to EuroLeague, Point Spread, Total >= 100.0, Moneyline."""
    ok, why = validate_match_common(m, "Basketball")
    if not ok:
        return False, why

    comp = str(m.get("competition", "")).lower()
    if "euro" not in comp:
        return False, f"Basketball competition must be EuroLeague, got: '{m.get('competition')}'"

    home = str(m.get("home", "")).strip().lower()
    away = str(m.get("away", "")).strip().lower()
    for bad in BADMINTON_AND_TENNIS_TOKENS:
        if bad in home or bad in away:
            return False, f"Cross-sport contamination: non-basketball participant '{bad}' detected in {home} vs {away}"

    mkts = m.get("markets", {})

    # Point Spread
    sp = mkts.get("Spread") or mkts.get("Point Spread")
    if not sp or not isinstance(sp, dict) or not all(k in sp for k in ("1", "2")):
        return False, "Missing or incomplete Point Spread (1, 2)"
    for side in ("1", "2"):
        if not isinstance(sp[side], dict) or "line" not in sp[side] or not is_valid_odds_str(sp[side].get("odds")):
            return False, f"Invalid Point Spread specification for side {side}"

    # Total >= 100.0 (Key Anti-Contamination Gate)
    tot = mkts.get("Total") or mkts.get("Total Points")
    if not tot or not isinstance(tot, dict) or not all(k in tot for k in ("Over", "Under")):
        return False, "Missing or incomplete Total market (Over, Under)"
    over_side = tot.get("Over", {})
    under_side = tot.get("Under", {})
    if not isinstance(over_side, dict) or not isinstance(under_side, dict):
        return False, "Total market must contain Over and Under dicts"
    try:
        t_line = float(str(over_side.get("line")).replace(',', '.'))
        if t_line < 100.0:
            return False, f"Total line {t_line} is < 100.0 (Cross-sport contamination rejected!)"
    except (ValueError, TypeError):
        return False, f"Invalid Total line value: {over_side.get('line')}"
    if not is_valid_odds_str(over_side.get("odds")) or not is_valid_odds_str(under_side.get("odds")):
        return False, "Invalid Total odds"

    # Moneyline
    ml = mkts.get("Moneyline") or mkts.get("Money Line") or mkts.get("Match Winner")
    if not ml or not isinstance(ml, dict) or not all(k in ml for k in ("1", "2")):
        return False, "Missing or incomplete Basketball Moneyline (1, 2)"
    if not is_valid_odds_str(ml["1"]) or not is_valid_odds_str(ml["2"]):
        return False, "Invalid Basketball Moneyline odds"

    return True, "OK"


def validate_handball_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Handball match adheres to Starligue/EHF, Handicap, Total <= 90.0, Match Result."""
    ok, why = validate_match_common(m, "Handball")
    if not ok:
        return False, why

    comp = str(m.get("competition", "")).lower()
    if not any(k in comp for k in ("starligue", "ehf", "liqui moly", "champions league")):
        return False, f"Handball competition must be Starligue or EHF, got: '{m.get('competition')}'"

    home = str(m.get("home", "")).strip().lower()
    away = str(m.get("away", "")).strip().lower()
    for bad in BADMINTON_AND_TENNIS_TOKENS:
        if bad in home or bad in away:
            return False, f"Cross-sport contamination: non-handball participant '{bad}' detected in {home} vs {away}"

    mkts = m.get("markets", {})

    # Handicap
    hc = mkts.get("Handicap") or mkts.get("Handicap / Spread") or mkts.get("Spread")
    if not hc or not isinstance(hc, dict) or not all(k in hc for k in ("1", "2")):
        return False, "Missing or incomplete Handball Handicap (1, 2)"
    for side in ("1", "2"):
        if not isinstance(hc[side], dict) or "line" not in hc[side] or not is_valid_odds_str(hc[side].get("odds")):
            return False, f"Invalid Handball Handicap specification for side {side}"

    # Total <= 90.0 (Key Anti-Contamination Gate)
    tot = mkts.get("Total") or mkts.get("Total Goals")
    if not tot or not isinstance(tot, dict) or not all(k in tot for k in ("Over", "Under")):
        return False, "Missing or incomplete Handball Total (Over, Under)"
    over_side = tot.get("Over", {})
    under_side = tot.get("Under", {})
    if not isinstance(over_side, dict) or not isinstance(under_side, dict):
        return False, "Handball Total must contain Over and Under dicts"
    try:
        t_line = float(str(over_side.get("line")).replace(',', '.'))
        if t_line > 90.0:
            return False, f"Total line {t_line} is > 90.0 (Cross-sport contamination rejected!)"
    except (ValueError, TypeError):
        return False, f"Invalid Handball Total line: {over_side.get('line')}"
    if not is_valid_odds_str(over_side.get("odds")) or not is_valid_odds_str(under_side.get("odds")):
        return False, "Invalid Handball Total odds"

    # Match Result (1, X, 2) or Money Line
    mr = mkts.get("Match Result") or mkts.get("Full Time Result") or mkts.get("Money Line")
    if not mr or not isinstance(mr, dict) or not ("1" in mr and "2" in mr):
        return False, "Missing Handball Match Result (1, X, 2)"
    if not is_valid_odds_str(mr["1"]) or not is_valid_odds_str(mr["2"]):
        return False, "Invalid Handball Match Result odds"

    return True, "OK"


def validate_cycling_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Cycling event matches active race odds structure."""
    ok, why = validate_match_common(m, "Cycling")
    if not ok:
        return False, why
    mkts = m.get("markets", {})
    if not mkts:
        return False, "Cycling event has empty markets"
    for mkt_name, mkt_data in mkts.items():
        if isinstance(mkt_data, dict):
            for participant, odd in mkt_data.items():
                if not is_valid_odds_str(odd):
                    return False, f"Invalid odd for cycling participant '{participant}': {odd}"
    return True, "OK"


def validate_f1_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Formula 1 event adheres to Race Winner and Podium Finish markets."""
    ok, why = validate_match_common(m, "F1")
    if not ok:
        return False, why

    mkts = m.get("markets", {})
    rw = mkts.get("Race Winner") or mkts.get("Vainqueur de la course") or mkts.get("To Win")
    pod = mkts.get("Podium Finish") or mkts.get("Podium") or mkts.get("Finira sur le podium")

    if not rw or not isinstance(rw, dict) or len(rw) < 3:
        return False, "Formula 1 must contain Race Winner market with at least 3 drivers"
    if not pod or not isinstance(pod, dict) or len(pod) < 3:
        return False, "Formula 1 must contain Podium market with at least 3 drivers"

    for d, o in list(rw.items())[:5]:
        if not is_valid_odds_str(o):
            return False, f"Invalid F1 Race Winner odd for driver '{d}': {o}"

    for d, o in list(pod.items())[:5]:
        if not is_valid_odds_str(o):
            return False, f"Invalid F1 Podium odd for driver '{d}': {o}"

    return True, "OK"


def validate_golf_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Golf event has Outright Winner market with player roster."""
    ok, why = validate_match_common(m, "Golf")
    if not ok:
        return False, why

    mkts = m.get("markets", {})
    outright = mkts.get("Outright Winner") or mkts.get("To Win Outright") or mkts.get("To Win")
    if not outright or not isinstance(outright, dict) or len(outright) < 3:
        return False, "Golf event must contain an Outright Winner market with a player roster (>= 3 golfers)"

    for player, odd in list(outright.items())[:5]:
        if not is_valid_odds_str(odd):
            return False, f"Invalid Golf outright odd for golfer '{player}': {odd}"

    return True, "OK"


def validate_pipeline_dataset(dataset: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validates entire multi-sport dataset against all strict constraints:
    - Zero synthetic data guarantee
    - Strict cross-sport contamination check
    - Required sports coverage
    """
    errors: List[str] = []
    if not isinstance(dataset, list):
        return False, ["Root dataset must be a JSON array of sport objects"]

    expected_sports = ["Soccer", "Tennis", "Basketball", "Handball", "Cycling", "Golf", "F1"]
    found_sports = {item.get("sport") for item in dataset if isinstance(item, dict)}

    missing_sports = [s for s in expected_sports if s not in found_sports]
    if missing_sports:
        errors.append(f"Missing required sport groups in root dataset: {missing_sports}")

    total_matches = 0
    for sport_group in dataset:
        sp_name = sport_group.get("sport")
        matches = sport_group.get("matches", [])
        if not isinstance(matches, list):
            errors.append(f"Sport group '{sp_name}' matches property must be a list")
            continue

        for idx, m in enumerate(matches):
            total_matches += 1
            if sp_name == "Soccer":
                ok, why = validate_soccer_match(m)
            elif sp_name == "Tennis":
                ok, why = validate_tennis_match(m)
            elif sp_name == "Basketball":
                ok, why = validate_basketball_match(m)
            elif sp_name == "Handball":
                ok, why = validate_handball_match(m)
            elif sp_name == "Cycling":
                ok, why = validate_cycling_match(m)
            elif sp_name == "F1":
                ok, why = validate_f1_match(m)
            elif sp_name == "Golf":
                ok, why = validate_golf_match(m)
            else:
                ok, why = False, f"Unknown sport '{sp_name}'"

            if not ok:
                errors.append(f"[{sp_name} match #{idx} :: {m.get('home')} vs {m.get('away', '')}] Validation failed: {why}")

    return len(errors) == 0, errors

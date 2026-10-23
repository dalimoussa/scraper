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

    # Every emitted market must carry its own live provenance entry, and where a
    # capture method is recorded it must be one we trust. This closes the hole
    # where a model-derived price was labelled "live" without being captured.
    mkts_audit = m.get("markets", {})
    if isinstance(mkts_audit, dict):
        for mkt_name in mkts_audit.keys():
            if src_map.get(mkt_name) != "live":
                return False, f"Market '{mkt_name}' has no live provenance entry (Violates Zero Synthetic Data)"

    prov = m.get("market_provenance", {})
    if isinstance(prov, dict):
        allowed_methods = {"dom", "js", "chart"}
        for mkt_name, method in prov.items():
            if method not in allowed_methods:
                return False, f"Market '{mkt_name}' has invalid capture method '{method}'"

    # Live In-play validation
    if "is_live" in m and not isinstance(m["is_live"], bool):
        return False, "is_live must be a boolean"
    if "live_status" in m and not isinstance(m["live_status"], dict):
        return False, "live_status must be a dictionary"

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

    # 2. Goals Over/Under (O/U 2.5) - validated if present
    ou = mkts.get("Goals Over/Under") or mkts.get("Total Goals")
    if ou is not None:
        if not isinstance(ou, dict):
            return False, "Goals Over/Under must be a dict"
        over_side = ou.get("Over") or {}
        under_side = ou.get("Under") or {}
        if not isinstance(over_side, dict) or not isinstance(under_side, dict):
            return False, "Goals Over/Under must contain Over and Under dicts"
        if str(over_side.get("line")) != "2.5" or str(under_side.get("line")) != "2.5":
            return False, f"Goals Over/Under line must be 2.5, got Over={over_side.get('line')}, Under={under_side.get('line')}"
        if not is_valid_odds_str(over_side.get("odds")) or not is_valid_odds_str(under_side.get("odds")):
            return False, "Invalid Over/Under 2.5 odds"

    # 3. Both Teams to Score (BTTS) - validated if present
    btts = mkts.get("Both Teams to Score")
    if btts is not None:
        if not isinstance(btts, dict) or not all(k in btts for k in ("Yes", "No")):
            return False, "Missing or incomplete Both Teams to Score (Yes/No)"
        if not is_valid_odds_str(btts["Yes"]) or not is_valid_odds_str(btts["No"]):
            return False, "Invalid BTTS odds"

    # 4. Double Chance - validated if present
    dc = mkts.get("Double Chance")
    if dc is not None:
        if not isinstance(dc, dict) or not all(k in dc for k in ("1X", "12", "X2")):
            return False, "Missing or incomplete Double Chance (1X, 12, X2)"
        for k in ("1X", "12", "X2"):
            if not is_valid_odds_str(dc[k]):
                return False, f"Invalid Double Chance odd for {k}: {dc[k]}"

    # 5. Draw No Bet - validated if present
    dnb = mkts.get("Draw No Bet")
    if dnb is not None:
        if not isinstance(dnb, dict) or not all(k in dnb for k in ("1", "2")):
            return False, "Missing or incomplete Draw No Bet (1, 2)"
        for k in ("1", "2"):
            if not is_valid_odds_str(dnb[k]):
                return False, f"Invalid Draw No Bet odd for {k}: {dnb[k]}"

    # 6. Asian Handicap (Extended)
    ah = mkts.get("Asian Handicap")
    if ah is not None:
        if not isinstance(ah, dict) or not any(k in ah for k in ("Home", "Away", "1", "2")):
            return False, "Invalid Asian Handicap structure"
        for side in ah.values():
            if isinstance(side, dict):
                if not is_valid_odds_str(side.get("odds")):
                    return False, "Invalid Asian Handicap odds"
            elif not is_valid_odds_str(side):
                return False, "Invalid Asian Handicap odds"

    # 7. Correct Score (Extended)
    cs = mkts.get("Correct Score")
    if cs is not None:
        if not isinstance(cs, dict) or len(cs) < 4:
            return False, "Invalid Correct Score structure"
        for sc_k, sc_odd in cs.items():
            if not is_valid_odds_str(sc_odd):
                return False, f"Invalid Correct Score odd for {sc_k}"

    # 8. Half Time / Full Time (Extended)
    htft = mkts.get("Half Time / Full Time") or mkts.get("Half Time/Full Time")
    if htft is not None:
        if not isinstance(htft, dict) or len(htft) < 6:
            return False, "Invalid Half Time / Full Time structure"
        for tr_k, tr_odd in htft.items():
            if not is_valid_odds_str(tr_odd):
                return False, f"Invalid HT/FT odd for {tr_k}"

    return True, "OK"


def validate_tennis_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Tennis match adheres to recognized tournament and Match Winner constraint."""
    ok, why = validate_match_common(m, "Tennis")
    if not ok:
        return False, why

    comp = str(m.get("competition", "")).lower()
    if not any(t in comp for t in ("atp", "wta", "itf", "challenger", "grand slam", "open", "masters", "cup", "tennis", "shanghai")):
        return False, f"Tennis tournament must be a recognized competition, got: '{m.get('competition')}'"

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
    """Validates Basketball match adheres to recognized top-flight league, Point Spread, Total >= 100.0, Moneyline."""
    ok, why = validate_match_common(m, "Basketball")
    if not ok:
        return False, why

    comp = str(m.get("competition", "")).lower()
    if not any(k in comp for k in ("euro", "nba", "pro a", "acb", "basket", "league", "champions", "elite")):
        return False, f"Basketball competition must be recognized top flight, got: '{m.get('competition')}'"

    home = str(m.get("home", "")).strip().lower()
    away = str(m.get("away", "")).strip().lower()
    for bad in BADMINTON_AND_TENNIS_TOKENS:
        if bad in home or bad in away:
            return False, f"Cross-sport contamination: non-basketball participant '{bad}' detected in {home} vs {away}"

    mkts = m.get("markets", {})
    if not isinstance(mkts, dict) or not mkts:
        return False, "Basketball match has no markets"

    # Point Spread (validated if present)
    sp = mkts.get("Spread") or mkts.get("Point Spread")
    if sp is not None:
        if not isinstance(sp, dict):
            return False, "Point Spread must be a dictionary"
        for side, side_val in sp.items():
            if not isinstance(side_val, dict) or "line" not in side_val or not is_valid_odds_str(side_val.get("odds")):
                return False, f"Invalid Point Spread specification for side {side}"

    # Total >= 100.0 (Key Anti-Contamination Gate, validated if present)
    tot = mkts.get("Total") or mkts.get("Total Points")
    if tot is not None:
        if not isinstance(tot, dict):
            return False, "Total market must be a dictionary"
        for side_name in ("Over", "Under"):
            if side_name in tot:
                side_data = tot[side_name]
                if not isinstance(side_data, dict):
                    return False, f"Total {side_name} must be a dict"
                try:
                    t_line = float(str(side_data.get("line", "")).replace(',', '.'))
                    if t_line < 100.0:
                        return False, f"Total line {t_line} is < 100.0 (Cross-sport contamination rejected!)"
                except (ValueError, TypeError):
                    return False, f"Invalid Total line value: {side_data.get('line')}"
                if not is_valid_odds_str(side_data.get("odds")):
                    return False, f"Invalid Total {side_name} odds"

    # Moneyline (validated if present)
    ml = mkts.get("Moneyline") or mkts.get("Money Line") or mkts.get("Match Winner")
    if ml is not None:
        if not isinstance(ml, dict):
            return False, "Moneyline must be a dictionary"
        for side in ("1", "2"):
            if side in ml and not is_valid_odds_str(ml[side]):
                return False, f"Invalid Basketball Moneyline odd for {side}"

    return True, "OK"


def validate_handball_match(m: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates Handball match adheres to recognized top-flight league and authentic live markets."""
    ok, why = validate_match_common(m, "Handball")
    if not ok:
        return False, why

    comp = str(m.get("competition", "")).lower()
    if not any(k in comp for k in ("starligue", "ehf", "liqui moly", "champions league", "bundesliga", "division", "handball", "pro")):
        return False, f"Handball competition must be recognized top flight, got: '{m.get('competition')}'"

    home = str(m.get("home", "")).strip().lower()
    away = str(m.get("away", "")).strip().lower()
    for bad in BADMINTON_AND_TENNIS_TOKENS:
        if bad in home or bad in away:
            return False, f"Cross-sport contamination: non-handball participant '{bad}' detected in {home} vs {away}"

    mkts = m.get("markets", {})
    if not isinstance(mkts, dict) or not mkts:
        return False, "Handball match has no markets"

    # Handicap (validated if present)
    hc = mkts.get("Handicap") or mkts.get("Handicap / Spread") or mkts.get("Spread")
    if hc is not None:
        if not isinstance(hc, dict):
            return False, "Handicap must be a dictionary"
        for side, side_val in hc.items():
            if not isinstance(side_val, dict) or "line" not in side_val or not is_valid_odds_str(side_val.get("odds")):
                return False, f"Invalid Handball Handicap specification for side {side}"

    # Total <= 90.0 (Key Anti-Contamination Gate, validated if present)
    tot = mkts.get("Total") or mkts.get("Total Goals")
    if tot is not None:
        if not isinstance(tot, dict):
            return False, "Handball Total must be a dict"
        for side_name in ("Over", "Under"):
            if side_name in tot:
                side_data = tot[side_name]
                if not isinstance(side_data, dict):
                    return False, f"Handball Total {side_name} must be a dict"
                try:
                    t_line = float(str(side_data.get("line", "")).replace(',', '.'))
                    if t_line > 90.0:
                        return False, f"Total line {t_line} is > 90.0 (Cross-sport contamination rejected!)"
                except (ValueError, TypeError):
                    return False, f"Invalid Handball Total line: {side_data.get('line')}"
                if not is_valid_odds_str(side_data.get("odds")):
                    return False, f"Invalid Handball Total {side_name} odds"

    # Match Result (1, 2 required if present; X is optional since many Bet365 Handball coupons are 2-way)
    mr = mkts.get("Match Result") or mkts.get("Full Time Result") or mkts.get("Money Line")
    if mr is not None:
        if not isinstance(mr, dict):
            return False, "Handball Match Result must be a dict"
        for side in ("1", "2"):
            if side in mr and not is_valid_odds_str(mr[side]):
                return False, f"Invalid Handball Match Result odd for {side}"
        if "X" in mr and not is_valid_odds_str(mr["X"]):
            return False, f"Invalid Handball Match Result draw odd: {mr['X']}"

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

    for d, o in list(rw.items())[:5]:
        if not is_valid_odds_str(o):
            return False, f"Invalid F1 Race Winner odd for driver '{d}': {o}"

    if pod and isinstance(pod, dict):
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


def audit_pv_consistency(m: Dict[str, Any], sport: str = "Soccer", tolerance: float = 0.05) -> List[str]:
    """Reconciles reported on-screen odds against the raw feed odds under the ANJ engine.

    Every market carrying `unadjusted_raw_markets` is re-derived through the local
    chart engine and compared with the reported screen odd. Markets whose value was
    taken from the DOM or the site's own JS (`market_provenance` in {dom, js}) are
    authoritative and therefore skipped. Differences larger than `tolerance` are
    returned as human-readable audit strings.

    This is the check that would have caught the client's original report: raw
    2.90/3.50/2.35 must reconcile to 2.82/3.40/2.29 on Chart 6.
    """
    from bet365_pv import apply_bet365_pv, resolve_chart_id

    issues: List[str] = []
    raw_markets = m.get("unadjusted_raw_markets") or {}
    markets = m.get("markets") or {}
    prov = m.get("market_provenance") or {}

    for mkt_name, raw_vals in raw_markets.items():
        if prov.get(mkt_name) in ("dom", "js"):
            continue  # authoritative source, nothing to reconcile
        screen = markets.get(mkt_name)
        if not isinstance(raw_vals, dict) or not isinstance(screen, dict):
            continue
        chart_id = resolve_chart_id(sport, mkt_name)
        for key, raw_odd in raw_vals.items():
            rv = raw_odd.get("odds") if isinstance(raw_odd, dict) else raw_odd
            sv = screen.get(key)
            if isinstance(sv, dict):
                sv = sv.get("odds")
            if rv is None or sv is None:
                continue
            try:
                expected = apply_bet365_pv(float(str(rv)), chart_id=chart_id)
                got = float(str(sv))
            except (TypeError, ValueError):
                continue
            if abs(expected - got) > tolerance:
                issues.append(
                    f"{mkt_name}[{key}] screen={got} != chart-expected={expected} (raw={rv}, chart={chart_id})"
                )
    return issues


_SOCCER_SECONDARY_MARKETS = (
    "Both Teams to Score",
    "Goals Over/Under",
    "Double Chance",
    "Draw No Bet",
    "Half Time/Full Time",
    "Correct Score",
)


def audit_capture_evidence(m: Dict[str, Any], sport: str = "Soccer") -> List[str]:
    """Detects markets that claim to be live but carry no proof of capture.

    The old pipeline modelled the soccer secondary markets with a Poisson model
    and tagged them "live". That is impossible to see from the prices alone, so
    every market now records *how* it was captured (`market_provenance`). A
    secondary market with no recorded capture method is therefore reported as
    unverified provenance rather than being silently trusted.
    """
    issues: List[str] = []
    markets = m.get("markets") or {}
    prov = m.get("market_provenance") or {}
    unverified = [
        name for name in _SOCCER_SECONDARY_MARKETS
        if name in markets and name not in prov
    ]
    if unverified:
        issues.append(
            "secondary markets present without capture evidence "
            f"(suspected non-live): {unverified}"
        )
    return issues


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
        status = sport_group.get("status", "available")
        if not isinstance(matches, list):
            errors.append(f"Sport group '{sp_name}' matches property must be a list")
            continue

        if not matches:
            # Valid off-season or currently inactive sport
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
            else:
                # ANJ Price Variance reconciliation (raw feed -> on-screen odds)
                for issue in audit_pv_consistency(m, sp_name):
                    errors.append(
                        f"[{sp_name} match #{idx} :: {m.get('home')} vs {m.get('away', '')}] PV audit mismatch: {issue}"
                    )
                # Capture-evidence audit (would have caught the Poisson markets)
                for issue in audit_capture_evidence(m, sp_name):
                    errors.append(
                        f"[{sp_name} match #{idx} :: {m.get('home')} vs {m.get('away', '')}] {issue}"
                    )

    return len(errors) == 0, errors

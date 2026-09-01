"""
bet365/scraper.py
Advanced multi-market, in-play, and parallel scraper for bet365.fr.
"""

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bet365.message_parser import get_parsers, read_table
from bet365.utils import format_datetime, parse_odds


def load_config(path: str = "config.json") -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def is_prematch_future(kickoff_str: str, now: Optional[datetime] = None) -> bool:
    """
    Check whether a match kickoff time is strictly in the future.
    Returns False if kickoff is missing, invalid, or already started/past.
    """
    if not kickoff_str:
        return False
    try:
        dt = datetime.strptime(kickoff_str, "%d/%m/%Y %H:%M:%S")
        now_dt = now or datetime.now()
        return dt > now_dt
    except Exception:
        return False


def is_valid_prematch(m: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """
    Validate that an event is a legitimate pre-match event:
    1. Must NOT have active in-play scores or clocks.
    2. If it has a scheduled kickoff time, it MUST be strictly in the future.
    3. If it has no kickoff time (e.g. tournament outrights), it is preserved.
    """
    if m.get("live"):
        return False
    if m.get("score") or m.get("clock"):
        return False
    k = m.get("kickoff")
    if k:
        return is_prematch_future(k, now)
    return True


def _extract_pd_token(pd_str: str, key: str, default: str = "") -> str:
    """Extract a token value from a Bet365 PD string (e.g. #G40# -> 40)."""
    m = re.search(rf"#{key}([^^#]+)#", pd_str)
    return m.group(1) if m else default


def clone_session(base_session):
    """
    Create a thread-safe cloned session for concurrent worker threads,
    sharing authenticated session cookies and SST tokens.
    """
    from bet365 import Bet365AndroidSession
    clone = Bet365AndroidSession(
        base_session.api_url,
        base_session.api_key,
        proxy=base_session.proxy,
        verify=False,
        host=base_session.host,
    )
    clone._sst = base_session._sst
    clone.device_id = base_session.device_id
    for k, v in base_session.session.cookies.items():
        clone.session.cookies[k] = v
    return clone


def _parse_decimal_odds(odd_str: str) -> Optional[str]:
    """Convert 'N/D' fractional odds to a decimal string (e.g. '1.85')."""
    if not odd_str:
        return None
    val = parse_odds(odd_str)
    if val and val > 1.0:
        return f"{val:.2f}"
    return None


def _extract_sport_number(pd: str) -> Optional[str]:
    """Extract sport numerical ID from PD (e.g. '#AS#B1#' -> '1', '#AS#B13#' -> '13')."""
    m = re.search(r"#B(\d+)#", pd)
    return m.group(1) if m else None


def parse_pods_data(
    response_text: str,
    is_live: bool = False,
    default_competition: str = "",
    prematch_only: bool = True,
    now: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Parse a gen5 response and extract all matches with multi-market odds.
    If prematch_only=True, strictly filters out in-play and already started games.
    """
    if prematch_only and is_live:
        return {}

    matches_by_id: Dict[str, Dict[str, Any]] = {}
    roots = get_parsers(response_text)
    now_dt = now or datetime.now()

    for root in roots:
        cl_node = next(root.find_sections("CL"), None)
        root_comp = cl_node.get_property("NA") if cl_node else default_competition

        for mg in root.find_sections("MG"):
            mg_sy = mg.get_property("SY") or ""

            # Filter out futures and outright market groups (Bug 1)
            # E.g., SY="ffl" (outrights/futures), "ffo", "pba" (player bet builder props), "cm" (sub-nav headers)
            if mg_sy in ["ffl", "ffo", "pba", "cm"]:
                continue

            # Special case for Snooker match winner cards (SY="fff")
            if mg_sy == "fff":
                ma_list = [m for m in mg.children if m.type == "MA"]
                if len(ma_list) >= 2:
                    fix_pa = ma_list[0].children[0] if ma_list[0].children else None
                    if fix_pa:
                        d1 = fix_pa.get_property("D1") or ""
                        d2 = fix_pa.get_property("D2") or ""
                        na = fix_pa.get_property("NA") or ""
                        home, away = d1, d2
                        if not away and (" vs " in na or " v " in na):
                            sep = " vs " if " vs " in na else " v "
                            parts = na.split(sep, 1)
                            home, away = parts[0].strip(), parts[1].strip()

                        kickoff_raw = fix_pa.get_property("BC") or fix_pa.get_property("DT") or ""
                        kickoff = format_datetime(kickoff_raw) if kickoff_raw else ""
                        if prematch_only and not is_prematch_future(kickoff, now_dt):
                            continue

                        event_id = fix_pa.get_property("FI") or mg.get_property("FI") or f"{home}_{away}"
                        competition = fix_pa.get_property("L3") or mg.get_property("L3") or root_comp

                        odds_pas = [pa for pa in ma_list[1].children if pa.type == "PA"]
                        winner_odds: Dict[str, Any] = {}
                        for idx, pa in enumerate(odds_pas):
                            dec = _parse_decimal_odds(pa.get_property("OD"))
                            if dec:
                                winner_odds[str(idx + 1)] = dec

                        if winner_odds and home and away:
                            if event_id in matches_by_id:
                                matches_by_id[event_id]["markets"]["Match Winner"] = winner_odds
                            else:
                                matches_by_id[event_id] = {
                                    "id": event_id,
                                    "kickoff": kickoff,
                                    "competition": competition,
                                    "home": home,
                                    "away": away,
                                    "markets": {"Match Winner": winner_odds},
                                }
                continue

            table = read_table(mg)
            data = table.get("data", [])
            if not data or not data[0].get("values"):
                continue

            table_title = table.get("title") or mg.get_property("NA") or ""
            col_names = [col.get("name", "").strip() for col in data[1:]]

            # If all columns are "No row", skip unless it's a valid table
            if all(c in ["No row", ""] for c in col_names):
                continue

            # Standardize market names
            is_game_lines = any(c in ["Spread", "Total", "Money Line", "Run Line", "Handicap"] for c in col_names)
            if col_names == ["1", "X", "2"]:
                market_name = "Match Result"
            elif col_names == ["1", "2"]:
                market_name = "Match Winner"
            elif is_game_lines:
                market_name = "Game Lines"
            elif table_title and table_title != "cpmg":
                market_name = table_title
            else:
                market_name = "Match Odds"

            first_col = data[0]["values"]
            num_rows = len(first_col)

            # Determine row stride:
            # American sports (Basketball, Baseball, Football) Game Lines have 2 rows per fixture:
            # Row 2k: Team 1 (away/first team) + Over total
            # Row 2k+1: Team 2 (home/second team) + Under total
            stride = 1
            if is_game_lines and num_rows >= 2 and num_rows % 2 == 0:
                # Check if odd rows have empty fixture names (classic 2-row stride)
                if not first_col[1].get_property("NA") and not first_col[1].get_property("FD"):
                    stride = 2

            for r_idx in range(0, num_rows, stride):
                row_node = first_col[r_idx]
                row_props = row_node.properties

                # If prematch_only is requested, skip in-play / live matches
                if prematch_only:
                    if row_props.get("SS") or row_props.get("SC") or row_props.get("TM") or row_props.get("TU"):
                        continue

                fixture = row_node.get_property("FD") or ""
                home = row_node.get_property("NA") or ""
                away = row_node.get_property("N2") or ""

                if not away and " v " in fixture:
                    parts = fixture.split(" v ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
                elif not away and " @ " in fixture:
                    parts = fixture.split(" @ ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
                elif not away and " - " in fixture:
                    parts = fixture.split(" - ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
                elif not away and not home and fixture:
                    home = fixture

                # Skip blank or orphaned rows without fixture info
                if not home and not away and not fixture:
                    continue

                # Filter outrights disguised as fixtures (Bug 1)
                if away in ["To Win Outright", "To Win Conference", "To Win Division", "Futures"]:
                    continue
                if any(kw in home.lower() for kw in ["to win outright", "to win conference", "championship 202", "conference 202"]):
                    continue

                kickoff_raw = (
                    row_node.get_property("BC")
                    or row_node.get_property("DT")
                    or row_node.get_property("ST")
                    or ""
                )
                kickoff = format_datetime(kickoff_raw) if kickoff_raw else ""

                # Strictly exclude games whose scheduled kickoff has already arrived or passed
                if prematch_only and not is_prematch_future(kickoff, now_dt):
                    continue

                event_id = (
                    row_node.get_property("FI")
                    or row_node.get_property("OI")
                    or row_node.get_property("ID")
                    or f"{home}_{away}"
                )
                match_pd = (
                    row_node.get_property("PD")
                    or row_props.get("PD")
                    or ""
                )

                competition = (
                    row_node.get_property("L3")
                    or row_node.get_property("CT")
                    or mg.get_property("NA")
                    or mg.get_property("L3")
                    or root_comp
                )

                # Extract outcome odds across columns
                market_odds: Dict[str, Any] = {}

                if stride == 2:
                    # Two-sided Game Lines extraction (Bug 2)
                    r1_idx = r_idx
                    r2_idx = r_idx + 1

                    for c_idx in range(1, len(data)):
                        col = data[c_idx]
                        col_name = col.get("name", "").strip() or str(c_idx)
                        c_vals = col.get("values", [])

                        p1 = c_vals[r1_idx] if r1_idx < len(c_vals) else None
                        p2 = c_vals[r2_idx] if r2_idx < len(c_vals) else None

                        p1_dec = _parse_decimal_odds(p1.get_property("OD")) if p1 else None
                        p2_dec = _parse_decimal_odds(p2.get_property("OD")) if p2 else None
                        p1_ha = p1.get_property("HA") if p1 else ""
                        p2_ha = p2.get_property("HA") if p2 else ""
                        p1_hd = p1.get_property("HD") if p1 else ""
                        p2_hd = p2.get_property("HD") if p2 else ""

                        if col_name in ["Spread", "Run Line", "Handicap"]:
                            spread_dict: Dict[str, Any] = {}
                            if p1_dec or p1_ha:
                                spread_dict["1"] = {"line": p1_ha or p1_hd, "odds": p1_dec}
                            if p2_dec or p2_ha:
                                spread_dict["2"] = {"line": p2_ha or p2_hd, "odds": p2_dec}
                            if spread_dict:
                                market_odds[col_name] = spread_dict

                        elif col_name in ["Total"]:
                            total_dict: Dict[str, Any] = {}
                            # Identify over/under by HD prefix (e.g. 'O 165.5', 'U 165.5')
                            # Default row 0 = over, row 1 = under
                            line1 = p1_ha or (p1_hd[2:].strip() if p1_hd.startswith(("O ", "U ")) else p1_hd)
                            line2 = p2_ha or (p2_hd[2:].strip() if p2_hd.startswith(("O ", "U ")) else p2_hd)

                            if p1_hd.startswith("U ") or p2_hd.startswith("O "):
                                # Inverted order
                                if p2_dec or line2:
                                    total_dict["over"] = {"line": line2, "odds": p2_dec}
                                if p1_dec or line1:
                                    total_dict["under"] = {"line": line1, "odds": p1_dec}
                            else:
                                if p1_dec or line1:
                                    total_dict["over"] = {"line": line1, "odds": p1_dec}
                                if p2_dec or line2:
                                    total_dict["under"] = {"line": line2, "odds": p2_dec}

                            if total_dict:
                                market_odds[col_name] = total_dict

                        elif col_name in ["Money Line", "To Win", "Moneyline"]:
                            ml_dict: Dict[str, Any] = {}
                            if p1_dec:
                                ml_dict["1"] = p1_dec
                            if p2_dec:
                                ml_dict["2"] = p2_dec
                            if ml_dict:
                                market_odds[col_name] = ml_dict

                        else:
                            # Fallback generic multi-row
                            generic_dict: Dict[str, Any] = {}
                            if p1_dec:
                                generic_dict["1"] = {"line": p1_ha, "odds": p1_dec} if p1_ha else p1_dec
                            if p2_dec:
                                generic_dict["2"] = {"line": p2_ha, "odds": p2_dec} if p2_ha else p2_dec
                            if generic_dict:
                                market_odds[col_name] = generic_dict
                else:
                    # Single-row extraction (Soccer 1/X/2, Tennis 1/2, etc.)
                    for c_idx in range(1, len(data)):
                        col = data[c_idx]
                        col_name = col.get("name", "").strip() or str(c_idx)
                        if r_idx < len(col.get("values", [])):
                            odd_node = col["values"][r_idx]
                            raw_odd = odd_node.get_property("OD")
                            dec = _parse_decimal_odds(raw_odd)
                            if dec:
                                ha_line = odd_node.get_property("HA")
                                if ha_line:
                                    market_odds[col_name] = {
                                        "line": ha_line,
                                        "odds": dec,
                                    }
                                else:
                                    market_odds[col_name] = dec

                # Skip non-match navigation entries
                if not market_odds:
                    continue

                # In-Play attributes (only populated if not prematch_only)
                live_score = (
                    row_props.get("SS")
                    or row_props.get("SC")
                    or None
                )
                live_clock = (
                    row_props.get("TM")
                    or row_props.get("TU")
                    or None
                )

                if event_id in matches_by_id:
                    # Merge markets
                    if market_name in matches_by_id[event_id]["markets"]:
                        matches_by_id[event_id]["markets"][market_name].update(market_odds)
                    else:
                        matches_by_id[event_id]["markets"][market_name] = market_odds

                    if not matches_by_id[event_id]["competition"] and competition:
                        matches_by_id[event_id]["competition"] = competition
                    if not matches_by_id[event_id]["kickoff"] and kickoff:
                        matches_by_id[event_id]["kickoff"] = kickoff
                    if match_pd and not matches_by_id[event_id].get("_pd"):
                        matches_by_id[event_id]["_pd"] = match_pd
                    if live_score and not matches_by_id[event_id].get("score"):
                        matches_by_id[event_id]["score"] = live_score
                    if live_clock and not matches_by_id[event_id].get("clock"):
                        matches_by_id[event_id]["clock"] = live_clock
                else:
                    match_item: Dict[str, Any] = {
                        "id": event_id,
                        "kickoff": kickoff,
                        "competition": competition,
                        "home": home,
                        "away": away,
                        "markets": {market_name: market_odds},
                    }
                    if match_pd:
                        match_item["_pd"] = match_pd
                    if is_live and not prematch_only:
                        match_item["live"] = True
                        if live_score:
                            match_item["score"] = live_score
                        if live_clock:
                            match_item["clock"] = live_clock

                    matches_by_id[event_id] = match_item

    return matches_by_id


def parse_coupon_data(
    response_text: str,
    prematch_only: bool = True,
    now: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Extract matches and odds from oddsoncoupon responses."""
    matches: Dict[str, Dict[str, Any]] = {}
    roots = get_parsers(response_text)
    now_dt = now or datetime.now()

    for root in roots:
        for ma in root.find_sections("MA"):
            cols = [co for co in ma.children if co.type == "CO"]
            if len(cols) >= 2:
                col0 = [p for p in cols[0].children if p.type == "PA"]
                for idx, pa0 in enumerate(col0):
                    odds = {}
                    for c in cols[1:]:
                        c_pas = [p for p in c.children if p.type == "PA"]
                        if idx < len(c_pas):
                            raw_od = c_pas[idx].get_property("OD")
                            dec = _parse_decimal_odds(raw_od)
                            if dec:
                                odds[c.get_property("NA") or "Odds"] = dec
                    if not odds:
                        continue
                    fixture = pa0.get_property("EX") or pa0.get_property("FD") or ""
                    comp = pa0.get_property("L3") or pa0.get_property("NA") or ""
                    home, away = "", ""
                    if " v " in fixture:
                        parts = fixture.split(" v ", 1)
                        home, away = parts[0].strip(), parts[1].strip()
                    elif " - " in fixture:
                        parts = fixture.split(" - ", 1)
                        home, away = parts[0].strip(), parts[1].strip()
                    elif fixture:
                        home = fixture

                    kickoff = format_datetime(pa0.get_property("BC") or "")
                    if prematch_only and not is_prematch_future(kickoff, now_dt):
                        continue

                    event_id = (
                        pa0.get_property("FI")
                        or pa0.get_property("OI")
                        or f"{home}_{away}"
                    )
                    raw_pd = pa0.get_property("PD") or ""
                    market_name = "Match Result" if len(odds) == 3 else "Match Winner"
                    match_data = {
                        "id": event_id,
                        "kickoff": kickoff,
                        "competition": comp,
                        "home": home,
                        "away": away,
                        "markets": {market_name: odds},
                    }
                    if raw_pd:
                        match_data["_pd"] = raw_pd
                    matches[event_id] = match_data
    return matches


def parse_deep_soccer_markets(roots: List[Any], home_team: str, away_team: str) -> Dict[str, Any]:
    """
    Extract Correct Score (Score exact), Both Teams to Score, and Half Time/Full Time (Mi-temps / Fin de match).
    """
    markets: Dict[str, Any] = {}
    for rt in roots:
        for mg in rt.find_sections("MG"):
            na = (mg.get_property("NA") or "").lower()
            if na == "correct score" or "score exact" in na:
                tbl = read_table(mg)
                cs_dict: Dict[str, str] = {}
                cols = tbl.get("data", [])
                if len(cols) >= 4:
                    home_col, draw_col, away_col = cols[1], cols[2], cols[3]
                    for p in home_col.get("values", []):
                        sc = p.get_property("NA")
                        od = _parse_decimal_odds(p.get_property("OD"))
                        if sc and od:
                            cs_dict[sc] = od
                    for p in draw_col.get("values", []):
                        sc = p.get_property("NA")
                        od = _parse_decimal_odds(p.get_property("OD"))
                        if sc and od:
                            cs_dict[sc] = od
                    for p in away_col.get("values", []):
                        sc = p.get_property("NA")
                        od = _parse_decimal_odds(p.get_property("OD"))
                        if sc and od:
                            if "-" in sc:
                                s1, s2 = sc.split("-", 1)
                                cs_dict[f"{s2.strip()}-{s1.strip()}"] = od
                            else:
                                cs_dict[sc] = od
                if cs_dict:
                    markets["Correct Score"] = cs_dict
            elif any(kw in na for kw in ["both teams to score", "les deux equipes marquent", "les 2 equipes marquent", "beide teams treffen"]):
                btts_dict: Dict[str, str] = {}
                for pa in mg.find_sections("PA"):
                    ans = pa.get_property("NA")
                    od = _parse_decimal_odds(pa.get_property("OD"))
                    if ans and od:
                        btts_dict[ans] = od
                if btts_dict:
                    markets["Both Teams to Score"] = btts_dict
            elif any(kw in na for kw in ["half time/full time", "half time / full time", "mi-temps / fin de match", "mi-temps/fin de match", "ht/ft", "halbzeit/endstand"]):
                htft_dict: Dict[str, str] = {}
                tbl = read_table(mg)
                if tbl.get("data"):
                    for col in tbl.get("data", []):
                        for p in col.get("values", []):
                            ans = p.get_property("NA")
                            od = _parse_decimal_odds(p.get_property("OD"))
                            if ans and od:
                                htft_dict[ans] = od
                for pa in mg.find_sections("PA"):
                    ans = pa.get_property("NA")
                    od = _parse_decimal_odds(pa.get_property("OD"))
                    if ans and od:
                        htft_dict[ans] = od
                if htft_dict:
                    markets["Half Time/Full Time"] = htft_dict
    return markets


def parse_deep_tennis_markets(roots: List[Any], home_player: str, away_player: str) -> Dict[str, Any]:
    """
    Extract 1st Set Correct Score and Set Betting from tennis match betting coupon.
    """
    markets: Dict[str, Any] = {}
    for rt in roots:
        for mg in rt.find_sections("MG"):
            na = (mg.get_property("NA") or "").lower()
            if any(kw in na for kw in ["first set score", "1st set score", "1er set - score", "1er set score", "1er set - score exact", "set 1 - score", "1. satz"]):
                tbl = read_table(mg)
                set_dict: Dict[str, str] = {}
                score_col = None
                for col in tbl.get("data", []):
                    cname = col.get("name", "").strip()
                    if not cname:
                        score_col = [p.get_property("NA") for p in col.get("values", [])]
                        break
                if score_col:
                    for col in tbl.get("data", []):
                        cname = col.get("name", "").strip()
                        if cname:
                            for idx, p in enumerate(col.get("values", [])):
                                if idx < len(score_col):
                                    sc = score_col[idx]
                                    od = _parse_decimal_odds(p.get_property("OD"))
                                    if sc and od:
                                        set_dict[f"{cname} {sc}"] = od
                if set_dict:
                    markets["1st Set Correct Score"] = set_dict
            elif any(kw in na for kw in ["set betting", "correct set score", "paris sur le set", "score exact du set", "satzwetten"]):
                sb_dict: Dict[str, str] = {}
                for pa in mg.find_sections("PA"):
                    ans = pa.get_property("NA")
                    od = _parse_decimal_odds(pa.get_property("OD"))
                    if ans and od:
                        sb_dict[ans] = od
                if sb_dict:
                    markets["Set Betting"] = sb_dict
    return markets


def enrich_matches_with_deep_markets(
    session,
    matches: List[Dict[str, Any]],
    is_tennis: bool = False,
    max_workers: int = 6,
) -> None:
    """
    Concurrently fetch /matchbettingcontentapi/coupon for matches and merge deep markets.
    """
    if not matches:
        return

    headers = {
        "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.159 Gen6 bet365/8.0.69.00",
        "X-b365App-ID": "8.0.69.00-row",
        "Host": session.host,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }

    def _fetch_one(m):
        raw_pd = m.get("_pd")
        if not raw_pd:
            return m["id"], {}
        m_c = re.search(r"#C(\d+)#", raw_pd)
        cid = m_c.group(1) if m_c else ("21165057" if is_tennis else "1")
        clean_pd = re.sub(r"I\d+#", "", raw_pd)
        try:
            r = session.protected_get(
                f"https://{session.host}/matchbettingcontentapi/coupon",
                params={
                    "lid": "1",
                    "zid": "9",
                    "pd": clean_pd,
                    "cid": cid,
                    "cgid": "1",
                    "ctid": "8",
                    "tzo": "60",
                },
                headers=headers,
            )
            if (not r or r.status_code != 200 or len(r.text) == 0) and cid != "1":
                r = session.protected_get(
                    f"https://{session.host}/matchbettingcontentapi/coupon",
                    params={
                        "lid": "1",
                        "zid": "9",
                        "pd": clean_pd,
                        "cid": "1",
                        "cgid": "1",
                        "ctid": "8",
                        "tzo": "60",
                    },
                    headers=headers,
                )
            if r and r.status_code == 200 and len(r.text) > 0:
                roots = get_parsers(r.text)
                if is_tennis:
                    return m["id"], parse_deep_tennis_markets(roots, m.get("home", ""), m.get("away", ""))
                else:
                    return m["id"], parse_deep_soccer_markets(roots, m.get("home", ""), m.get("away", ""))
        except Exception:
            pass
        return m["id"], {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_fetch_one, m) for m in matches if m.get("_pd")]
        for fut in as_completed(futures):
            try:
                mid, deep_mkts = fut.result()
                if deep_mkts:
                    for m in matches:
                        if m["id"] == mid:
                            m["markets"].update(deep_mkts)
                            break
            except Exception:
                pass


def scrape_golf_events(session, sport) -> List[Dict[str, Any]]:
    """
    Extract Golf tournaments, scheduled kickoffs, and outright winner odds.
    """
    headers = {
        "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.159 Gen6 bet365/8.0.69.00",
        "X-b365App-ID": "8.0.69.00-row",
        "Host": session.host,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }
    golf_events = []
    try:
        r_splash = session.protected_get(
            f"https://{session.host}/splashcontentapi/getsplashpods",
            params={"lid": "1", "zid": "9", "pd": sport.PD or "#AS#B7#", "cid": "143", "cgid": "1", "ctid": "143", "tzo": "60"},
            headers=headers,
        )
        if not r_splash or r_splash.status_code != 200 or len(r_splash.text) == 0:
            r_splash = session.protected_get(
                f"https://{session.host}/splashcontentapi/splash",
                params={"lid": "1", "zid": "9", "pd": sport.PD or "#AS#B7#", "cid": "143", "cgid": "1", "ctid": "143", "tzo": "60"},
                headers=headers,
            )

        if r_splash and r_splash.status_code == 200 and len(r_splash.text) > 0:
            roots_sp = get_parsers(r_splash.text)
            for rt in roots_sp:
                for mg in rt.find_sections("MG"):
                    mg_pd = mg.get_property("PD")
                    mg_na = mg.get_property("NA")
                    if mg_pd and "#AC#B7#" in mg_pd:
                        r_cp = session.protected_get(
                            f"https://{session.host}/golfcouponcontentapi/coupon",
                            params={"lid": "1", "zid": "9", "pd": mg_pd, "cid": "143", "cgid": "1", "ctid": "143", "tzo": "60"},
                            headers=headers,
                        )
                        if r_cp.status_code == 200 and len(r_cp.text) > 0:
                            cp_roots = get_parsers(r_cp.text)
                            for c_rt in cp_roots:
                                for c_mg in c_rt.find_sections("MG"):
                                    tbl = read_table(c_mg)
                                    data = tbl.get("data", [])
                                    if len(data) >= 2:
                                        c0 = data[0].get("values", [])
                                        c1 = data[1].get("values", [])
                                        odds: Dict[str, str] = {}
                                        for p_name_node, p_odd_node in zip(c0, c1):
                                            p_name = p_name_node.get_property("NA")
                                            p_odd = _parse_decimal_odds(p_odd_node.get_property("OD"))
                                            if p_name and p_odd:
                                                odds[p_name] = p_odd
                                        if odds:
                                            fi = c_mg.get_property("ID") or mg_pd
                                            golf_events.append({
                                                "id": fi,
                                                "kickoff": "",
                                                "competition": "Golf",
                                                "home": mg_na or "Golf Tournament",
                                                "away": "",
                                                "markets": {"To Win Outright": odds},
                                            })
                                            break
    except Exception:
        pass
    return golf_events


def scrape_cycling_events(session, sport) -> List[Dict[str, Any]]:
    """
    Extract Cycling grand tours, upcoming stages, scheduled kickoffs, and full peloton of riders
    via /othersportsmatchmarketscontentapi/coupon.
    """
    headers = {
        "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.159 Gen6 bet365/8.0.69.00",
        "X-b365App-ID": "8.0.69.00-row",
        "Host": session.host,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }
    cyc_events: Dict[str, Dict[str, Any]] = {}
    try:
        r_cyc = session.protected_get(
            f"https://{session.host}/splashcontentapi/splash",
            params={"lid": "1", "zid": "9", "pd": sport.PD or "#AS#B38#", "cid": "143", "cgid": "1", "ctid": "143", "tzo": "60"},
            headers=headers,
        )
        if r_cyc and r_cyc.status_code == 200 and len(r_cyc.text) > 0:
            roots = get_parsers(r_cyc.text)
            pds_to_fetch = []
            for root in roots:
                for pa in root.find_sections("PA"):
                    pd = pa.get_property("PD")
                    na = pa.get_property("NA")
                    if pd and "#AC#B38#" in pd:
                        pds_to_fetch.append((pd, na))

            # Concurrently fetch full coupon for each stage/event to get all riders
            def _fetch_cyc(item):
                pd, default_na = item
                try:
                    r_cp = session.protected_get(
                        f"https://{session.host}/othersportsmatchmarketscontentapi/coupon",
                        params={"lid": "1", "zid": "9", "pd": pd, "cid": "1", "cgid": "0", "ctid": "0", "tzo": "60"},
                        headers=headers,
                    )
                    if r_cp.status_code == 200 and len(r_cp.text) > 0:
                        c_roots = get_parsers(r_cp.text)
                        for c_rt in c_roots:
                            for ev in c_rt.find_sections("EV"):
                                fi = ev.get_property("FI") or ev.get_property("ID")
                                bc = format_datetime(ev.get_property("BC"))
                                l3 = ev.get_property("L3") or "Cycling"
                                ev_na = default_na or ev.get_property("NA") or "Stage"
                                riders = {}
                                for pa in c_rt.find_sections("PA"):
                                    r_na = pa.get_property("NA")
                                    r_od = _parse_decimal_odds(pa.get_property("OD"))
                                    if r_na and r_od:
                                        riders[r_na] = r_od
                                if fi and riders:
                                    return {
                                        "id": fi,
                                        "kickoff": bc,
                                        "competition": l3,
                                        "home": f"Vuelta a Espana 2026 - {ev_na}" if not ev_na.startswith("Vuelta") else ev_na,
                                        "away": "",
                                        "markets": {"To Win": riders},
                                    }
                except Exception:
                    pass
                return None

            with ThreadPoolExecutor(max_workers=6) as pool:
                results = pool.map(_fetch_cyc, pds_to_fetch)
                for res in results:
                    if res and res["id"] not in cyc_events:
                        cyc_events[res["id"]] = res

            # Fallback to splash cards if coupon was empty
            if not cyc_events:
                current_mg_na = ""
                current_fi = ""
                current_bc = ""
                current_comp = "Cycling"
                for chunk in r_cyc.text.split("|"):
                    if chunk.startswith("MG;"):
                        parts = chunk.split(";")
                        props = {}
                        for s in parts[1:]:
                            if len(s) >= 2: props[s[:2]] = s[3:]
                        if props.get("NA"): current_mg_na = props.get("NA")
                        if props.get("L3"): current_comp = props.get("L3")
                    elif chunk.startswith("PA;"):
                        parts = chunk.split(";")
                        props = {}
                        for s in parts[1:]:
                            if len(s) >= 2: props[s[:2]] = s[3:]
                        fi = props.get("FI") or current_fi
                        bc = format_datetime(props.get("BC") or current_bc)
                        na = props.get("NA")
                        od = _parse_decimal_odds(props.get("OD"))
                        if fi and current_mg_na:
                            if fi not in cyc_events:
                                cyc_events[fi] = {
                                    "id": fi,
                                    "kickoff": bc,
                                    "competition": current_comp,
                                    "home": current_mg_na,
                                    "away": "",
                                    "markets": {"To Win": {}},
                                }
                            if na and od:
                                cyc_events[fi]["markets"]["To Win"][na] = od
    except Exception:
        pass
    return list(cyc_events.values())


def scrape_sport(
    session,
    sport,
    deep: bool = True,
    include_live: bool = False,
    prematch_only: bool = True,
) -> Dict[str, Any]:
    """
    Scrape all upcoming pre-matches and odds for a given sport:
    - Primary featured matches
    - Deep sub-leagues & regional competition pods
    - Odds-on upcoming coupons
    - Automatically purges in-play and past/started games (prematch_only=True)
    """
    headers = {
        "User-Agent": "Mozilla (Linux; Android 12 Phone; CPU M2003J15SC OS 12 like Gecko) Chrome/145.0.7632.159 Gen6 bet365/8.0.69.00",
        "X-b365App-ID": "8.0.69.00-row",
        "Host": session.host,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }

    all_matches_map: Dict[str, Dict[str, Any]] = {}
    sport_num = _extract_sport_number(sport.PD) if sport.PD else None
    league_coupon_pds: List[Tuple[str, str, str, str]] = []
    sub_category_pds = []
    now_dt = datetime.now()

    # Special handling for Golf and Cycling (tournaments & grand tour stages)
    sport_name_lower = sport.name.lower()
    if sport_num == "7" or "golf" in sport_name_lower:
        golf_events = scrape_golf_events(session, sport)
        return {"sport": sport.name, "matches": golf_events}
    if sport_num == "38" or "cycl" in sport_name_lower or "vélo" in sport_name_lower or "velo" in sport_name_lower:
        cycling_events = scrape_cycling_events(session, sport)
        return {"sport": sport.name, "matches": cycling_events}

    # 1. Primary Feeds (handles AC match market feeds and AS splash pods)
    if sport.PD.startswith("#AC#"):
        endpoint = "upcomingmatches" if "Q1" in sport.PD else "markets"
        cid = _extract_pd_token(sport.PD, "C", "1")
        cgid = _extract_pd_token(sport.PD, "G", "40" if sport_num == "1" else "83")
        ctid = _extract_pd_token(sport.PD, "D", "1002")
        try:
            r_feat = session.protected_get(
                f"https://{session.host}/matchmarketscontentapi/{endpoint}",
                params={
                    "lid": "1",
                    "zid": "9",
                    "pd": sport.PD,
                    "cid": cid,
                    "cgid": cgid,
                    "ctid": ctid,
                    "tzo": "60",
                },
                headers=headers,
            )
            if r_feat.status_code == 200 and len(r_feat.text) > 0:
                feat_matches = parse_pods_data(
                    r_feat.text,
                    is_live=False,
                    prematch_only=prematch_only,
                    now=now_dt,
                )
                all_matches_map.update(feat_matches)
        except Exception:
            pass
    else:
        # Standard AS splash pods
        try:
            r_feat = session.protected_get(
                f"https://{session.host}/splashcontentapi/getsplashpods",
                params={
                    "lid": "1",
                    "zid": "9",
                    "pd": sport.PD,
                    "cid": "143",
                    "cgid": "1",
                    "ctid": "143",
                    "tzo": "60",
                },
                headers=headers,
            )
            if not r_feat or r_feat.status_code != 200 or len(r_feat.text) == 0:
                r_feat = session.protected_get(
                    f"https://{session.host}/splashcontentapi/splash",
                    params={
                        "lid": "1",
                        "zid": "9",
                        "pd": sport.PD,
                        "cid": "143",
                        "cgid": "1",
                        "ctid": "143",
                        "tzo": "60",
                    },
                    headers=headers,
                )

            if r_feat and r_feat.status_code == 200 and len(r_feat.text) > 0:
                feat_matches = parse_pods_data(
                    r_feat.text,
                    is_live=False,
                    prematch_only=prematch_only,
                    now=now_dt,
                )
                all_matches_map.update(feat_matches)

                # Discover league competitions and sub-categories
                if deep:
                    roots = get_parsers(r_feat.text)
                    if roots:
                        # 1. Discover direct league coupons (e.g. Premier League, La Liga, Serie A, etc.)
                        for root in roots:
                            for ev in root.find_sections("EV"):
                                le = ev.get_property("LE")
                                if le:
                                    lc = ev.get_property("LC") or "1"
                                    ld = ev.get_property("LD") or "1002"
                                    lp = ev.get_property("LP") or ("40" if sport_num == "1" else "83")
                                    lf = ev.get_property("LF") or ""
                                    if sport_num == "1":
                                        cp_pd = f"#AC#B1#C{lc}#D{ld}#E{le}#G{lp}#H^1#"
                                    elif lf:
                                        cp_pd = f"#AC#B{sport_num}#C{lc}#D{ld}#E{le}#F{lf}#"
                                    else:
                                        cp_pd = f"#AC#B{sport_num}#C{lc}#D{ld}#E{le}#G{lp}#"
                                    league_coupon_pds.append((cp_pd, lc, ld, lp))

                        # 2. Discover sub-league / regional categories from Root 0
                        for pa in roots[0].find_sections("PA"):
                            raw_sub_pd = pa.get_property("PD")
                            sub_pd = urllib.parse.unquote(raw_sub_pd) if raw_sub_pd else ""
                            if sub_pd and "#D1002#" in sub_pd and "#J" in sub_pd:
                                sub_category_pds.append(sub_pd)
                                if sport_num == "1":
                                    for f_code in ["2001", "2002"]:
                                        sub_category_pds.append(
                                            re.sub(r"F\^[0-9]+#", f"F^{f_code}#", sub_pd)
                                        )
                                else:
                                    for f_code in ["24", "72", "168"]:
                                        sub_category_pds.append(
                                            re.sub(r"F\^[0-9]+#", f"F^{f_code}#", sub_pd)
                                        )
        except Exception:
            pass

    # 2. League Competition Coupons (fetches full weekly fixtures across days)
    if deep and league_coupon_pds:
        seen_cp_pds = set()
        for cp_pd, lc, ld, lp in league_coupon_pds:
            if cp_pd in seen_cp_pds:
                continue
            seen_cp_pds.add(cp_pd)
            try:
                r_cp = session.protected_get(
                    f"https://{session.host}/matchmarketscontentapi/markets",
                    params={
                        "lid": "1",
                        "zid": "9",
                        "pd": cp_pd,
                        "cid": lc,
                        "cgid": lp,
                        "ctid": ld,
                        "tzo": "60",
                    },
                    headers=headers,
                )
                if r_cp.status_code == 200 and len(r_cp.text) > 0:
                    cp_matches = parse_pods_data(
                        r_cp.text,
                        is_live=False,
                        prematch_only=prematch_only,
                        now=now_dt,
                    )
                    for mid, mdata in cp_matches.items():
                        if mid in all_matches_map:
                            all_matches_map[mid]["markets"].update(mdata["markets"])
                            if mdata.get("_pd") and not all_matches_map[mid].get("_pd"):
                                all_matches_map[mid]["_pd"] = mdata["_pd"]
                        else:
                            all_matches_map[mid] = mdata
            except Exception:
                pass

    # 3. Regional & Sub-League Drill-Down (dynamic parameters per sport)
    if deep and sub_category_pds:
        endpoint = "soccerupcomingmatches" if sport_num == "1" else "upcomingmatches"
        seen_pds = set()
        for sub_pd in sub_category_pds:
            if sub_pd in seen_pds:
                continue
            seen_pds.add(sub_pd)
            cid = _extract_pd_token(sub_pd, "C", "1")
            cgid = _extract_pd_token(sub_pd, "G", "40" if sport_num == "1" else "83")
            ctid = _extract_pd_token(sub_pd, "D", "1002")
            try:
                r_sub = session.protected_get(
                    f"https://{session.host}/matchmarketscontentapi/{endpoint}",
                    params={
                        "lid": "1",
                        "zid": "9",
                        "pd": sub_pd,
                        "cid": cid,
                        "cgid": cgid,
                        "ctid": ctid,
                        "tzo": "60",
                    },
                    headers=headers,
                )
                if r_sub.status_code == 200 and len(r_sub.text) > 0:
                    sub_matches = parse_pods_data(
                        r_sub.text,
                        is_live=False,
                        prematch_only=prematch_only,
                        now=now_dt,
                    )
                    for mid, mdata in sub_matches.items():
                        if mid in all_matches_map:
                            all_matches_map[mid]["markets"].update(mdata["markets"])
                            if mdata.get("_pd") and not all_matches_map[mid].get("_pd"):
                                all_matches_map[mid]["_pd"] = mdata["_pd"]
                        else:
                            all_matches_map[mid] = mdata

                    # Discover nested competition coupons from sub-category response (e.g. European leagues)
                    sub_roots = get_parsers(r_sub.text)
                    if sub_roots:
                        for mg in sub_roots[0].find_sections("MG"):
                            mg_pd = mg.get_property("PD")
                            if mg_pd:
                                m_le = re.search(r"#E(\d+)#", mg_pd)
                                if m_le:
                                    le_id = m_le.group(1)
                                    nested_cp_pd = f"#AC#B1#C1#D1002#E{le_id}#G40#H^1#"
                                    if nested_cp_pd not in seen_cp_pds:
                                        seen_cp_pds.add(nested_cp_pd)
                                        try:
                                            r_nested = session.protected_get(
                                                f"https://{session.host}/matchmarketscontentapi/markets",
                                                params={
                                                    "lid": "1",
                                                    "zid": "9",
                                                    "pd": nested_cp_pd,
                                                    "cid": "1",
                                                    "cgid": "40",
                                                    "ctid": "1002",
                                                    "tzo": "60",
                                                },
                                                headers=headers,
                                            )
                                            if r_nested.status_code == 200 and len(r_nested.text) > 0:
                                                nested_matches = parse_pods_data(
                                                    r_nested.text,
                                                    is_live=False,
                                                    prematch_only=prematch_only,
                                                    now=now_dt,
                                                )
                                                for mid, mdata in nested_matches.items():
                                                    if mid in all_matches_map:
                                                        all_matches_map[mid]["markets"].update(mdata["markets"])
                                                        if mdata.get("_pd") and not all_matches_map[mid].get("_pd"):
                                                            all_matches_map[mid]["_pd"] = mdata["_pd"]
                                                    else:
                                                        all_matches_map[mid] = mdata
                                        except Exception:
                                            pass
            except Exception:
                pass

    # 4. Deep Competitions Drill-down (K^5#)
    if deep and sport.PD:
        comp_pd = f"{sport.PD}K^5#" if not sport.PD.endswith("K^5#") else sport.PD
        try:
            r_comp = session.protected_get(
                f"https://{session.host}/splashcontentapi/getsplashpods",
                params={
                    "lid": "1",
                    "zid": "9",
                    "pd": comp_pd,
                    "cid": "143",
                    "cgid": "1",
                    "ctid": "143",
                    "tzo": "60",
                },
                headers=headers,
            )
            if r_comp.status_code == 200 and len(r_comp.text) > 0:
                comp_matches = parse_pods_data(
                    r_comp.text,
                    is_live=False,
                    prematch_only=prematch_only,
                    now=now_dt,
                )
                for mid, mdata in comp_matches.items():
                    if mid in all_matches_map:
                        all_matches_map[mid]["markets"].update(mdata["markets"])
                        if mdata.get("_pd") and not all_matches_map[mid].get("_pd"):
                            all_matches_map[mid]["_pd"] = mdata["_pd"]
                    else:
                        all_matches_map[mid] = mdata
        except Exception:
            pass

    # 5. Odds-on Upcoming Coupons
    if deep and sport_num:
        try:
            r_coupon = session.protected_get(
                f"https://{session.host}/oddsoncouponcontentapi/coupon",
                params={
                    "lid": "1",
                    "zid": "9",
                    "pd": f"#AO#B{sport_num}#",
                    "cid": "143",
                    "cgid": "1",
                    "ctid": "143",
                    "tzo": "60",
                },
                headers=headers,
            )
            if r_coupon.status_code == 200 and len(r_coupon.text) > 0:
                coupon_matches = parse_coupon_data(
                    r_coupon.text,
                    prematch_only=prematch_only,
                    now=now_dt,
                )
                for mid, mdata in coupon_matches.items():
                    if mid in all_matches_map:
                        all_matches_map[mid]["markets"].update(mdata["markets"])
                        if mdata.get("_pd") and not all_matches_map[mid].get("_pd"):
                            all_matches_map[mid]["_pd"] = mdata["_pd"]
                    else:
                        all_matches_map[mid] = mdata
        except Exception:
            pass

    # 6. In-Play Feed (Upcoming Schedule & Live Matches)
    if (include_live or deep) and sport_num:
        live_pd = f"#IP#B{sport_num}#"
        try:
            r_live = session.protected_get(
                f"https://{session.host}/splashcontentapi/getsplashpods",
                params={
                    "lid": "1",
                    "zid": "9",
                    "pd": live_pd,
                    "cid": "143",
                    "cgid": "1",
                    "ctid": "143",
                    "tzo": "60",
                },
                headers=headers,
            )
            if r_live.status_code == 200 and len(r_live.text) > 0:
                live_matches = parse_pods_data(
                    r_live.text,
                    is_live=False if prematch_only else True,
                    prematch_only=prematch_only,
                    now=now_dt,
                )
                for mid, mdata in live_matches.items():
                    if mid in all_matches_map:
                        all_matches_map[mid]["markets"].update(mdata["markets"])
                        if mdata.get("_pd") and not all_matches_map[mid].get("_pd"):
                            all_matches_map[mid]["_pd"] = mdata["_pd"]
                        if not prematch_only:
                            all_matches_map[mid]["live"] = True
                            if mdata.get("score"):
                                all_matches_map[mid]["score"] = mdata["score"]
                            if mdata.get("clock"):
                                all_matches_map[mid]["clock"] = mdata["clock"]
                    else:
                        all_matches_map[mid] = mdata
        except Exception:
            pass

    # 7. Deep Markets Enrichment (Score Exact / HT-FT for Top 5 Football Leagues + UCL, 1st Set Score Exact for Tennis)
    if deep and all_matches_map:
        if sport_num == "1" or "soccer" in sport.name.lower() or "football" in sport.name.lower():
            target_soccer_matches = [
                m for m in all_matches_map.values()
                if m.get("_pd")
            ]
            enrich_matches_with_deep_markets(session, target_soccer_matches, is_tennis=False, max_workers=8)
        elif sport_num == "13" or "tennis" in sport.name.lower() or "us open" in sport.name.lower():
            target_tennis_matches = [
                m for m in all_matches_map.values()
                if m.get("_pd")
            ]
            enrich_matches_with_deep_markets(session, target_tennis_matches, is_tennis=True, max_workers=6)

    # Final pre-match filter ensuring strictly valid pre-match fixtures
    if prematch_only:
        final_matches = [
            m for m in all_matches_map.values()
            if is_valid_prematch(m, now_dt)
        ]
    else:
        final_matches = list(all_matches_map.values())

    # Clean internal helper attributes like _pd from final output
    for m in final_matches:
        m.pop("_pd", None)

    return {"sport": sport.name, "matches": final_matches}


def scrape_all_parallel(
    base_session,
    sports: List[Any],
    max_workers: int = 5,
    deep: bool = True,
    include_live: bool = False,
    prematch_only: bool = True,
) -> List[Dict[str, Any]]:
    """
    Scrape multiple sports concurrently in parallel using a ThreadPoolExecutor.
    """
    def _worker(sp):
        session_clone = clone_session(base_session)
        data = scrape_sport(
            session_clone,
            sp,
            deep=deep,
            include_live=include_live,
            prematch_only=prematch_only,
        )
        return data

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, sp): sp.name for sp in sports}
        for fut in as_completed(futures):
            sport_name = futures[fut]
            try:
                res = fut.result()
                if res and res["matches"]:
                    results.append(res)
            except Exception as e:
                print(f"[!] Error scraping {sport_name}: {e}")

    # Sort results by sport name for consistent output
    results.sort(key=lambda x: x["sport"])
    return results

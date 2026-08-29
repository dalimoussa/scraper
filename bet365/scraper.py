"""
bet365/scraper.py
Advanced multi-market, in-play, and parallel scraper for bet365.fr.
"""

import json
import re
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
            table = read_table(mg)
            data = table.get("data", [])
            if not data or not data[0].get("values"):
                continue

            # Identify market category
            table_title = table.get("title") or mg.get_property("NA") or ""
            col_names = [col.get("name", "").strip() for col in data[1:]]

            # Standardize market names
            if col_names == ["1", "X", "2"]:
                market_name = "Match Result"
            elif col_names == ["1", "2"]:
                market_name = "Match Winner"
            elif any(c in ["Spread", "Total", "Money Line"] for c in col_names):
                market_name = "Game Lines"
            elif table_title and table_title != "cpmg":
                market_name = table_title
            else:
                market_name = "Match Odds"

            first_col = data[0]["values"]
            num_rows = len(first_col)

            for r_idx in range(num_rows):
                row_node = first_col[r_idx]
                row_props = row_node.properties

                # If prematch_only is requested, skip in-play / live matches
                if prematch_only:
                    if row_props.get("SS") or row_props.get("SC") or row_props.get("TM") or row_props.get("TU"):
                        continue

                # Extract outcome odds across columns
                market_odds: Dict[str, Any] = {}
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

                fixture = row_node.get_property("FD") or ""
                home = row_node.get_property("NA") or ""
                away = row_node.get_property("N2") or ""

                if not away and " v " in fixture:
                    parts = fixture.split(" v ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
                elif not away and " - " in fixture:
                    parts = fixture.split(" - ", 1)
                    home, away = parts[0].strip(), parts[1].strip()
                elif not away and not home and fixture:
                    home = fixture

                # Skip blank or orphaned rows without fixture info
                if not home and not away and not fixture:
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

                competition = (
                    row_node.get_property("L3")
                    or row_node.get_property("CT")
                    or mg.get_property("NA")
                    or mg.get_property("L3")
                    or root_comp
                )

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
                    matches_by_id[event_id]["markets"][market_name] = market_odds
                    if not matches_by_id[event_id]["competition"] and competition:
                        matches_by_id[event_id]["competition"] = competition
                    if not matches_by_id[event_id]["kickoff"] and kickoff:
                        matches_by_id[event_id]["kickoff"] = kickoff
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
                    market_name = "Match Result" if len(odds) == 3 else "Match Winner"
                    matches[event_id] = {
                        "id": event_id,
                        "kickoff": kickoff,
                        "competition": comp,
                        "home": home,
                        "away": away,
                        "markets": {market_name: odds},
                    }
    return matches


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
    sub_category_pds = []
    now_dt = datetime.now()

    # 1. Primary Featured Pods
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
        if r_feat.status_code == 200:
            feat_matches = parse_pods_data(
                r_feat.text,
                is_live=False,
                prematch_only=prematch_only,
                now=now_dt,
            )
            all_matches_map.update(feat_matches)

            # Discover sub-league / regional categories from Root 0 (e.g. UK, Europe, Americas)
            if deep:
                roots = get_parsers(r_feat.text)
                if roots:
                    for pa in roots[0].find_sections("PA"):
                        sub_pd = pa.get_property("PD")
                        if sub_pd and "#D1002#" in sub_pd and "#J" in sub_pd:
                            sub_category_pds.append(sub_pd)
    except Exception:
        pass

    # 2. Regional & Sub-League Drill-Down (soccerupcomingmatches / upcomingmatches)
    if deep and sub_category_pds:
        endpoint = "soccerupcomingmatches" if sport_num == "1" else "upcomingmatches"
        for sub_pd in sub_category_pds:
            try:
                r_sub = session.protected_get(
                    f"https://{session.host}/matchmarketscontentapi/{endpoint}",
                    params={
                        "lid": "1",
                        "zid": "9",
                        "pd": sub_pd,
                        "cid": "1",
                        "cgid": "40",
                        "ctid": "1002",
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
                        else:
                            all_matches_map[mid] = mdata
            except Exception:
                pass

    # 3. Deep Competitions Drill-down (K^5#)
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
            if r_comp.status_code == 200:
                comp_matches = parse_pods_data(
                    r_comp.text,
                    is_live=False,
                    prematch_only=prematch_only,
                    now=now_dt,
                )
                for mid, mdata in comp_matches.items():
                    if mid in all_matches_map:
                        all_matches_map[mid]["markets"].update(mdata["markets"])
                    else:
                        all_matches_map[mid] = mdata
        except Exception:
            pass

    # 4. Odds-on Upcoming Coupons
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
                    else:
                        all_matches_map[mid] = mdata
        except Exception:
            pass

    # 5. Live In-Play Matches (only if explicitly enabled and not prematch_only)
    if include_live and not prematch_only and sport_num:
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
            if r_live.status_code == 200:
                live_matches = parse_pods_data(
                    r_live.text,
                    is_live=True,
                    prematch_only=False,
                    now=now_dt,
                )
                for mid, mdata in live_matches.items():
                    if mid in all_matches_map:
                        all_matches_map[mid]["markets"].update(mdata["markets"])
                        all_matches_map[mid]["live"] = True
                        if mdata.get("score"):
                            all_matches_map[mid]["score"] = mdata["score"]
                        if mdata.get("clock"):
                            all_matches_map[mid]["clock"] = mdata["clock"]
                    else:
                        all_matches_map[mid] = mdata
        except Exception:
            pass

    return {"sport": sport.name, "matches": list(all_matches_map.values())}


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

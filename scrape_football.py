"""
Bet365 Live Football Scraper
============================
Accesses Bet365 via Chrome DevTools Protocol (CDP), bypasses all caches,
and scrapes live football match odds with main odds (Home Win, Draw, Away Win)
and specific odds (correct score, both teams to score, over/under, etc.).

Outputs data as a JSON array of objects:
[
  {
    "match_name": "Team A vs Team B",
    "main_odds": {
      "Home Win": "2.10",
      "Draw": "3.40",
      "Away Win": "3.60"
    },
    "specific_odds": {
      "correct_score": { ... },
      "both_teams_to_score": { ... },
      "goals_over_under_2.5": { ... },
      "double_chance": { ... },
      "draw_no_bet": { ... },
      "half_time_full_time": { ... }
    }
  }
]

If data is unavailable, returns [].
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List

from bet365_internal import (
    CDP_PORT,
    CDPSession,
    ensure_chrome_cdp,
    get_bet365_domain,
    get_now_paris,
    is_upcoming_pre_match,
    parse_soccer_dom,
    resolve_soccer_match,
    enrich_soccer_match,
    match_team,
    ALL_KNOWN_TEAMS,
)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


KNOWN_NON_SOCCER_TOKENS = {
    "murakami", "vargas", "grichuk", "montgomery", "adell", "ramirez", "ohtani",
    "judge", "betts", "soto", "acuna", "trout", "harper", "stanton", "guerrero",
    "n/a", "inconnu", "unknown"
}


def fix_mojibake(s: str) -> str:
    """Corrects any legacy Windows console encoding artifacts for Brazilian/European team names."""
    if not s or not isinstance(s, str):
        return s
    return (
        s.replace("Vitria", "Vitória")
        .replace("Vit\ufffdria", "Vitória")
        .replace("So Paulo", "São Paulo")
        .replace("S\ufffdo Paulo", "São Paulo")
        .replace("Grmio", "Grêmio")
        .replace("Gr\ufffdmio", "Grêmio")
        .replace("Atltico", "Atlético")
        .replace("Atl\ufffdtico", "Atlético")
        .replace("Cuiab", "Cuiabá")
        .replace("Cear", "Ceará")
        .replace("Gois", "Goiás")
    )


def is_valid_football_match(home: str, away: str) -> bool:
    """Verifies that both teams are valid football teams and not individual player props or other sports."""
    if not home or not away:
        return False
    h_l = home.strip().lower()
    a_l = away.strip().lower()
    if h_l == a_l or len(h_l) < 2 or len(a_l) < 2:
        return False
    for bad in KNOWN_NON_SOCCER_TOKENS:
        if bad in h_l or bad in a_l:
            return False
    # Reject numbers or lone words like "over", "under", "total"
    if h_l.isdigit() or a_l.isdigit():
        return False
    return True


def format_football_match(m: Dict[str, Any]) -> Dict[str, Any]:
    """Formats an enriched match dict into the user-specified JSON object schema."""
    home = fix_mojibake(m.get("home", "").strip())
    away = fix_mojibake(m.get("away", "").strip())
    match_name = f"{home} vs {away}" if away else home

    mkts = m.get("markets", {})
    mr = mkts.get("Match Result") or {}

    main_odds = {
        "Home Win": mr.get("1", ""),
        "Draw": mr.get("X", ""),
        "Away Win": mr.get("2", ""),
    }

    specific_odds: Dict[str, Any] = {}
    if "Correct Score" in mkts and mkts["Correct Score"]:
        specific_odds["correct_score"] = mkts["Correct Score"]
    if "Both Teams to Score" in mkts and mkts["Both Teams to Score"]:
        specific_odds["both_teams_to_score"] = mkts["Both Teams to Score"]
    if "Goals Over/Under" in mkts and mkts["Goals Over/Under"]:
        specific_odds["goals_over_under_2.5"] = mkts["Goals Over/Under"]
    if "Double Chance" in mkts and mkts["Double Chance"]:
        specific_odds["double_chance"] = mkts["Double Chance"]
    if "Draw No Bet" in mkts and mkts["Draw No Bet"]:
        specific_odds["draw_no_bet"] = mkts["Draw No Bet"]
    if "Half Time/Full Time" in mkts and mkts["Half Time/Full Time"]:
        specific_odds["half_time_full_time"] = mkts["Half Time/Full Time"]
    if "Next Goalscorer" in mkts and mkts["Next Goalscorer"]:
        specific_odds["next_goalscorer"] = mkts["Next Goalscorer"]

    return {
        "match_name": match_name,
        "main_odds": main_odds,
        "specific_odds": specific_odds,
    }


def scrape_live_football(
    cdp_port: int = CDP_PORT,
    out_path: str = "all_matches.json"
) -> List[Dict[str, Any]]:
    """
    Directly scrapes live football odds from Bet365 via CDP.
    Bypasses all cache. Returns [] if data is unavailable.
    """
    if not HAS_PLAYWRIGHT:
        print("[Error] Playwright is required. Run: pip install playwright")
        return []

    if not ensure_chrome_cdp(cdp_port):
        print(f"[Error] Could not connect to Chrome CDP on port {cdp_port}.")
        _save_output([], out_path)
        return []

    target_domain = get_bet365_domain()
    dom_token = "bet365.fr" if "bet365.fr" in target_domain else "bet365.com"

    results: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            except Exception as e:
                print(f"[Error] CDP connection failed: {e}")
                _save_output([], out_path)
                return []

            context = browser.contexts[0] if browser.contexts else browser.new_context()

            # Locate or create the tab
            page = None
            for p_item in context.pages:
                u = (p_item.url or "").lower()
                if dom_token in u:
                    page = p_item
                    break

            if not page and context.pages:
                page = context.pages[0]
            elif not page:
                page = context.new_page()

            cur_u = (page.url or "").lower()
            if dom_token not in cur_u:
                try:
                    page.goto(target_domain, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(2.0)
                except Exception as e:
                    print(f"  [Warning] Initial navigation to {target_domain}: {e}")

            session = CDPSession(page, target_domain)
            session.accept_cookies_if_needed()
            session.dismiss_error_dialog()

            # Check if Bet365 displays geo-restriction page
            if session.is_geo_blocked():
                print(f"\n  [Geo-Block Notice] Bet365 displays geo-restriction for current IP at {session.domain}.")
                print("  [Geo-Block Notice] Real-time live data is unavailable without a VPN or proxy.")
                print("  [Geo-Block Notice] Per requirements, returning empty array [].\n")
                _save_output([], out_path)
                return []

            print(f"[*] Attached to Bet365 session ({target_domain}) via CDP port {cdp_port}")
            print(f"[*] Navigating to Football on {target_domain} (bypassing cache)...")

            # Click Football nav tab / carousel element
            navigated = False
            for selector in [
                '.hsn-NavTab_Label:has-text("Football")',
                'div.hsn-NavTab_Label',
                'div.crr-1',
                'div[role="button"]'
            ]:
                try:
                    fb_el = page.locator('.hsn-NavTab_Label', has_text='Football').first
                    if fb_el.count() > 0:
                        fb_el.click()
                        navigated = True
                        time.sleep(2.0)
                        break
                except Exception:
                    pass

            if not navigated:
                session.navigate_to_sport("Soccer")
                time.sleep(1.5)

            raw_matches: List[Dict[str, Any]] = []

            # 1. Capture initial DOM
            dom_lines = session.get_dom_lines()
            if dom_lines:
                for m in parse_soccer_dom(dom_lines, default_comp="Football"):
                    if is_valid_football_match(m.get("home", ""), m.get("away", "")):
                        resolve_soccer_match(m)
                        enrich_soccer_match(m)
                        if not any(ex["id"] == m["id"] or (ex["home"] == m["home"] and ex["away"] == m["away"]) for ex in raw_matches):
                            raw_matches.append(m)

            # 2. Virtual scroll down in 5 steps to capture all loaded matches
            for scroll_step in range(5):
                try:
                    page.evaluate("window.scrollBy(0, 1500);")
                    time.sleep(0.5)
                    step_lines = session.get_dom_lines()
                    for m in parse_soccer_dom(step_lines, default_comp="Football"):
                        if is_valid_football_match(m.get("home", ""), m.get("away", "")):
                            resolve_soccer_match(m)
                            enrich_soccer_match(m)
                            if not any(ex["id"] == m["id"] or (ex["home"] == m["home"] and ex["away"] == m["away"]) for ex in raw_matches):
                                raw_matches.append(m)
                except Exception:
                    pass

            print(f"[*] Live/Upcoming Football matches captured: {len(raw_matches)}")

            # Format into required schema
            for m in raw_matches:
                formatted = format_football_match(m)
                if formatted["main_odds"]["Home Win"] and formatted["main_odds"]["Away Win"]:
                    results.append(formatted)

    except Exception as exc:
        print(f"[Error] Scrape execution error: {exc}")

    _save_output(results, out_path)
    return results


def _save_output(data: List[Dict[str, Any]], out_path: str) -> None:
    """Atomic write to output JSON file to prevent partial reads."""
    tmp_path = f"{out_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)
    print(f"[*] Saved {len(data)} live matches to {out_path} (cache bypassed).")


def main():
    parser = argparse.ArgumentParser(description="Bet365 Live Football Match Odds Scraper")
    parser.add_argument("--out", default="all_matches.json", help="Output JSON path (default: all_matches.json)")
    parser.add_argument("--port", type=int, default=CDP_PORT, help=f"Chrome CDP port (default: {CDP_PORT})")
    args = parser.parse_args()

    matches = scrape_live_football(cdp_port=args.port, out_path=args.out)
    print(f"\n[OUTPUT JSON - {len(matches)} MATCHES]")
    print(json.dumps(matches, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

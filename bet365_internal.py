"""
Bet365 Internal & CDP Scraper Module for Cycling (B38) & Golf (B7)
Derived from test_sports_complet_final.py architecture:
- Connects over Chrome DevTools Protocol (CDP IPv4 127.0.0.1:9222)
- Reuses active Bet365 tab for instant in-memory routing
- Supports both bet365.com (default) and bet365.fr
- Parses Bet365 stream delimited protocols (CL, EV, MG, MA, PA, OD, DO, HD)
- Implements French/European regulatory Price Variance (Chart 7 PV) adjustment
- Extracts live stage matches and tournament outrights directly into project schema
- Gracefully handles offline or closed tabs without interrupting other sports
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


CDP_PORT = 9222
TIMEOUT_S = 14
FAST_MODE = True
BLOCK_HEAVY_RESOURCES = True
DEFAULT_DOMAIN = "https://www.bet365.com"

def fraction_to_decimal(s: str) -> float:
    """Convert Bet365 fraction (e.g. '1/12', '10/1', '13/10', '9/2') or decimal string to float."""
    try:
        s = str(s).strip()
        if "/" in s:
            n, d = s.split("/", 1)
            raw_val = int(n) / int(d) + 1.0
            val_3 = round(raw_val, 3)
            val_2 = round(raw_val, 2)
            if abs(val_3 - val_2) > 0.002:
                return val_3
            return val_2
        return round(float(s), 2) if s else 0.0
    except Exception:
        return 0.0


def format_odd_str(val: Any) -> str:
    """Format decimal odds with authentic Bet365 precision (e.g. '1.083' or '11.00')."""
    try:
        f_val = float(val)
        val_3 = round(f_val, 3)
        val_2 = round(f_val, 2)
        if abs(val_3 - val_2) > 0.002:
            return f"{val_3:.3f}"
        return f"{val_2:.2f}"
    except Exception:
        return str(val)


def parse_bet365(raw: str) -> List[Dict[str, str]]:
    """Parse le format delimite de Bet365: blocs separes par |, champs par ;."""
    blocs = []
    for block in raw.split("|"):
        if not block.strip():
            continue
        parts = block.split(";")
        d = {"_type": parts[0]}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                d[k] = v
        blocs.append(d)
    return blocs


def pd_vers_url(pd: str, domain: str = DEFAULT_DOMAIN) -> str:
    """Convertit un identifiant PD Bet365 en URL canonique."""
    pd = str(pd or "").strip()
    if "#IP#" in pd or pd.startswith("IP#"):
        code = pd.strip("#/").replace("IP#", "", 1).strip("#/")
        return f"{domain}/#/IP/{code}/"
    segments = [s.strip("/") for s in pd.strip("#/").split("#") if s.strip("/")]
    return f"{domain}/#/" + "/".join(segments) + "/"


def parser_splash(raw: str, domain: str = DEFAULT_DOMAIN) -> List[Dict[str, Any]]:
    """Decouvre les tournois et marches depuis la reponse splash Bet365."""
    parsed = parse_bet365(raw)
    vus = set()
    competition = "Tournoi"

    for b in parsed:
        if b.get("_type") == "EV":
            tb = b.get("TB", "")
            parties = [p.strip() for p in tb.split("¬") if p.strip()]
            if len(parties) >= 2:
                competition = parties[1].split(",")[0].strip() or competition
            elif parties:
                competition = parties[0].split(",")[0].strip() or competition
            break

    tournois = []
    tournoi_courant = None
    for b in parsed:
        t = b.get("_type")
        if t in ("MG", "MA"):
            nom = b.get("NA", "").strip()
            if nom:
                tournoi_courant = {"nom": nom, "marches": []}
                tournois.append(tournoi_courant)
                pd = b.get("PD", "").strip()
                if pd and ("#AC#" in pd or "#IP#" in pd):
                    tournoi_courant["marches"].append({
                        "nom": nom, "url": pd_vers_url(pd, domain)
                    })
        elif t == "PA" and tournoi_courant:
            pd = b.get("PD", "").strip()
            nom = b.get("NA", "").strip()
            if pd and nom and "#P" not in pd and "E729" not in pd:
                if "#AC#" in pd or "#IP#" in pd:
                    tournoi_courant["marches"].append({
                        "nom": nom, "url": pd_vers_url(pd, domain)
                    })

    if not tournois:
        direct_marches = []
        for b in parsed:
            if b.get("_type") == "PA":
                pd = b.get("PD", "").strip()
                nom = b.get("NA", "").strip() or b.get("FD", "").strip()
                if pd and nom and "#P" not in pd:
                    url = pd_vers_url(pd, domain)
                    if url not in vus:
                        vus.add(url)
                        direct_marches.append({"nom": nom, "url": url})
        if direct_marches:
            tournois.append({"nom": competition, "marches": direct_marches})

    return [t for t in tournois if t.get("marches")]


def parser_page_universel(raw: str, nom_sport: str, nom_event_fallback: str = "Compétition") -> List[Dict[str, Any]]:
    """Super-parseur universel structure extrait selections, participants et cotes."""
    blocs = parse_bet365(raw)
    resultats = []
    tournoi = nom_event_fallback
    current_mg = "Vainqueur"
    current_mg_id = ""
    current_ma = ""
    current_ma_id = ""
    current_team = ""
    dict_participants = {}
    row_headers = []
    row_index = 0

    ignore_ma = {"Oui", "Non", "Gagnant/Placé 1/5 1-2-3", "Gagnant/Placé 1/4 1-2-3",
                 "Paris principaux", "Pari personnalisé", "Course", "Principaux", "Qualifications", "All", "Matches"}

    for b in blocs:
        t = b.get("_type")
        if t == "EV":
            tb = b.get("TB", "")
            if "¬" in tb:
                parties = tb.split("¬")
                tournoi = parties[2].split(",")[0].strip() if len(parties) >= 3 else parties[1].split(",")[0].strip()
            elif b.get("NA"):
                tournoi = b.get("NA").strip()

        elif t == "MG":
            na = b.get("NA", "").strip()
            if na and na not in ignore_ma:
                current_mg = na
                current_mg_id = b.get("ID", "").lstrip("M")
                current_ma = ""
                current_ma_id = ""
                current_team = ""
                row_headers = []

        elif t == "MA":
            na = b.get("NA", "").strip()
            if na and na not in ignore_ma and "Gagnant/Placé" not in na:
                current_ma = na
                current_ma_id = b.get("ID", "").lstrip("M")
            row_index = 0

        elif t == "PA":
            id_raw = b.get("ID", "")
            od = b.get("OD", "")
            na = b.get("NA", "").strip()
            clean_id = "".join(filter(str.isdigit, id_raw))

            if na and not od:
                if clean_id:
                    dict_participants[clean_id] = na
                row_headers.append(na)

            elif od:
                hd_clean = b.get("HD", "").strip()
                participant = hd_clean or na

                if not participant and current_team:
                    participant = current_team
                if not participant:
                    participant = dict_participants.get(clean_id, "")
                if not participant and row_index < len(row_headers):
                    participant = row_headers[row_index]
                if not participant:
                    participant = "Inconnu"

                participant = participant.replace(" - Oui", "").strip()
                marche_final = current_mg
                if current_ma and current_ma != current_mg and current_ma.strip():
                    marche_final = f"{current_mg} - {current_ma}"

                cote_brute = fraction_to_decimal(od)
                row = {
                    "Sport": nom_sport,
                    "Tournoi": tournoi,
                    "Marche": marche_final,
                    "Marche_ID": current_ma_id or current_mg_id,
                    "Participant": participant,
                    "Cote_Fraction_Brute": od,
                    "Cote_Decimale_Brute": cote_brute,
                    "Cote_Fraction": od,
                    "Cote_Decimale": cote_brute,
                    "Cote_PV_Applique": False,
                }
                resultats.append(row)
                row_index += 1

    return resultats


# ─────────────────────────────────────────────────────────────────────────────
# CDP Network Interception
# ─────────────────────────────────────────────────────────────────────────────

def _detect_bet365_domain(context) -> str:
    """Detect if Chrome has bet365.com or bet365.fr currently active."""
    try:
        for page in context.pages:
            u = page.url or ""
            if "bet365.fr" in u:
                return "https://www.bet365.fr"
            elif "bet365.com" in u:
                return "https://www.bet365.com"
    except Exception:
        pass
    return DEFAULT_DOMAIN


def _get_active_bet365_page(context):
    """Reuse existing open Bet365 tab in Chrome to avoid reloading the SPA."""
    try:
        for p in context.pages:
            u = p.url or ""
            if "bet365" in u:
                return p
        if context.pages:
            return context.pages[0]
    except Exception:
        pass
    try:
        return context.new_page()
    except Exception:
        return None


def _intercepter_donnees_sport(page, target_url: str, sport_name: str, sport_code: str, timeout_s: int = TIMEOUT_S) -> Optional[str]:
    """
    Navigates to the sport page on Bet365 and intercepts the splash/coupon data.
    Uses in-page link clicking or hash navigation on the active tab.
    """
    raw = [None]
    raw_secours = []
    ok = [False]

    def handler(response):
        if response.request.resource_type not in ("fetch", "xhr"):
            return
        try:
            u = response.url
            txt = response.text()
            if not txt or "|" not in txt:
                return

            if any(k in u for k in ["splashcontentapi/splash", "othersportsmatch", "coupon", "markets", "sport"]):
                if sport_code in u or sport_code.lstrip("B") in u or ("EV;" in txt and "PA;" in txt):
                    raw[0] = txt
                    ok[0] = True
                    return

            if "PA;" in txt and "OD=" in txt:
                raw_secours.append(txt)
            elif "EV;" in txt:
                raw_secours.append(txt)
        except Exception:
            pass

    try:
        page.on("response", handler)
    except Exception:
        pass

    # Try 1: Click the sport link in the sidebar if present (most reliable for Bet365 SPA)
    navigated_by_click = False
    try:
        terms = [sport_name]
        if sport_name.lower() == "cyclisme":
            terms.append("Cycling")
        elif sport_name.lower() == "golf":
            terms.append("Golf")

        for term in terms:
            el = page.query_selector(f'text="{term}"')
            if el:
                el.click()
                navigated_by_click = True
                break
    except Exception:
        pass

    # Try 2: If click was not possible, navigate to target_url
    if not navigated_by_click:
        try:
            page.goto(target_url, wait_until="commit", timeout=timeout_s * 1000)
        except Exception:
            try:
                page.evaluate(f"window.location.href = '{target_url}'")
            except Exception:
                pass

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if FAST_MODE and ok[0] and raw[0] and ("PA;" in raw[0] or "EV;" in raw[0]):
            break
        try:
            page.wait_for_timeout(200)
        except Exception:
            break

    if not ok[0] and raw_secours:
        # Fallback to the largest captured Bet365 data frame
        raw[0] = max(raw_secours, key=len)

    return raw[0]


def _intercepter_coupon_url(page, url: str, timeout_s: int = 8) -> Optional[str]:
    """Intercepte un coupon individuel via l'onglet actif."""
    raw = [None]
    ok = [False]

    def handler(response):
        if response.request.resource_type not in ("fetch", "xhr"):
            return
        try:
            txt = response.text()
            if txt and "|" in txt and ("PA;" in txt or "OD=" in txt):
                raw[0] = txt
                ok[0] = True
        except Exception:
            pass

    try:
        page.on("response", handler)
    except Exception:
        pass

    try:
        page.goto(url, wait_until="commit", timeout=timeout_s * 1000)
    except Exception:
        pass

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if ok[0] and raw[0]:
            break
        try:
            page.wait_for_timeout(150)
        except Exception:
            break

    return raw[0]


# ─────────────────────────────────────────────────────────────────────────────
# Live Golf & Cycling Scraping Routines
# ─────────────────────────────────────────────────────────────────────────────

def scrape_golf_internal(cdp_port: int = CDP_PORT) -> List[Dict[str, Any]]:
    """
    Scrapes live Golf tournaments (Sport B7) directly from Bet365 via CDP.
    Supports both bet365.com and bet365.fr.
    Returns structured list of matches adhering to all_matches.json schema.
    """
    if not HAS_PLAYWRIGHT:
        return []

    matches_out: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            try:
                # Explicit IPv4 address 127.0.0.1 to avoid Windows IPv6 resolution issues
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            except Exception:
                print(f"  [Notice] Chrome CDP (port {cdp_port}) is not active. (Run start_chrome_cdp.bat to enable)")
                return []

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = _get_active_bet365_page(context)
            if not page:
                print("  [Notice] No usable browser page found in CDP.")
                return []

            domain = _detect_bet365_domain(context)
            sport_url = f"{domain}/#/AS/B7/"
            print(f"  [CDP Golf] Intercepting Golf discovery from {domain} (Sport B7)...")

            raw_splash = _intercepter_donnees_sport(page, sport_url, "Golf", "B7", timeout_s=12)
            if not raw_splash:
                print("  [Notice] Golf stream response empty.")
                return []

            tournois = parser_splash(raw_splash, domain)
            if not tournois:
                print("  [Notice] No active Golf tournaments found in splash stream.")
                return []

            today_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
            kickoff_str = datetime.now(timezone.utc).strftime("%d/%m/%Y 08:00:00")

            for i, tournoi in enumerate(tournois[:3]):
                t_nom = tournoi.get("nom", "Golf Tournament")
                marches = tournoi.get("marches", [])
                for j, marche in enumerate(marches[:3]):
                    m_url = marche.get("url")
                    if not m_url:
                        continue
                    m_nom = marche.get("nom", t_nom)
                    raw_c = _intercepter_coupon_url(page, m_url, timeout_s=8)
                    if not raw_c:
                        continue

                    rows = parser_page_universel(raw_c, "Golf", m_nom)
                    if not rows:
                        continue

                    odds_dict = {}
                    for r in rows:
                        p_name = r.get("Participant", "").strip()
                        c_dec = r.get("Cote_Decimale")
                        if p_name and c_dec and float(c_dec) > 1.0 and p_name not in ["Inconnu", "Oui", "Non"]:
                            odds_dict[p_name] = format_odd_str(c_dec)

                    if odds_dict:
                        sorted_odds = dict(sorted(odds_dict.items(), key=lambda x: float(x[1])))
                        comp_title = f"{t_nom} - {m_nom}" if m_nom != t_nom else t_nom
                        match_id = str(abs(hash(comp_title)) % 100000000)
                        matches_out.append({
                            "id": match_id,
                            "date": today_str,
                            "kickoff": kickoff_str,
                            "competition": comp_title,
                            "home": f"{comp_title} - To Win Outright",
                            "away": "",
                            "markets": {
                                "To Win Outright": sorted_odds
                            }
                        })
                        print(f"  + [Golf] Captured {len(sorted_odds)} selections for {comp_title}")

    except BaseException as e:
        print(f"  [Golf CDP Notice] {e}")

    return matches_out


def scrape_cycling_internal(cdp_port: int = CDP_PORT) -> List[Dict[str, Any]]:
    """
    Scrapes live Cycling outrights & stages (Sport B38) directly from Bet365 via CDP.
    Supports both bet365.com and bet365.fr.
    Returns structured list of matches adhering to all_matches.json schema.
    """
    if not HAS_PLAYWRIGHT:
        return []

    matches_out: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            except Exception:
                print(f"  [Notice] Chrome CDP (port {cdp_port}) is not active. (Run start_chrome_cdp.bat to enable)")
                return []

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = _get_active_bet365_page(context)
            if not page:
                print("  [Notice] No usable browser page found in CDP.")
                return []

            domain = _detect_bet365_domain(context)
            sport_url = f"{domain}/#/AS/B38/"
            print(f"  [CDP Cycling] Intercepting Cycling discovery from {domain} (Sport B38)...")

            raw_splash = _intercepter_donnees_sport(page, sport_url, "Cyclisme", "B38", timeout_s=12)
            if not raw_splash:
                print("  [Notice] Cycling stream response empty.")
                return []

            tournois = parser_splash(raw_splash, domain)
            if not tournois:
                print("  [Notice] No active Cycling events found in splash stream.")
                return []

            today_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
            kickoff_str = datetime.now(timezone.utc).strftime("%d/%m/%Y 12:00:00")

            for i, tournoi in enumerate(tournois[:3]):
                t_nom = tournoi.get("nom", "Cycling Event")
                marches = tournoi.get("marches", [])
                for j, marche in enumerate(marches[:3]):
                    m_url = marche.get("url")
                    if not m_url:
                        continue
                    m_nom = marche.get("nom", t_nom)
                    raw_c = _intercepter_coupon_url(page, m_url, timeout_s=8)
                    if not raw_c:
                        continue

                    rows = parser_page_universel(raw_c, "Cyclisme", m_nom)
                    if not rows:
                        continue

                    odds_dict = {}
                    for r in rows:
                        p_name = r.get("Participant", "").strip()
                        c_dec = r.get("Cote_Decimale")
                        if p_name and c_dec and float(c_dec) > 1.0 and p_name not in ["Inconnu", "Oui", "Non"]:
                            odds_dict[p_name] = format_odd_str(c_dec)

                    if odds_dict:
                        sorted_odds = dict(sorted(odds_dict.items(), key=lambda x: float(x[1])))
                        comp_title = f"{t_nom} - {m_nom}" if m_nom != t_nom else t_nom
                        match_id = str(abs(hash(comp_title)) % 100000000)
                        matches_out.append({
                            "id": match_id,
                            "date": today_str,
                            "kickoff": kickoff_str,
                            "competition": comp_title,
                            "home": f"{comp_title} - To Win",
                            "away": "",
                            "markets": {
                                "To Win": sorted_odds
                            }
                        })
                        print(f"  + [Cycling] Captured {len(sorted_odds)} riders for {comp_title}")

    except BaseException as e:
        print(f"  [Cycling CDP Notice] {e}")

    return matches_out

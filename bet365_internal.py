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

# Chart 7 extrait de PV_CHARTS pour le profil Bet365
PV_DEFAULT_CHART_7 = [
    (1.0, 1.001, 0.0), (1.001, 1.002, 0.0), (1.002, 1.003, 0.001),
    (1.003, 1.004, 0.0015), (1.004, 1.006, 0.002), (1.006, 1.008, 0.003),
    (1.008, 1.01, 0.004), (1.01, 1.015, 0.005), (1.015, 1.02, 0.0075),
    (1.02, 1.025, 0.01), (1.025, 1.03, 0.015), (1.03, 1.04, 0.017),
    (1.04, 1.05, 0.02), (1.05, 1.06, 0.025), (1.06, 1.08, 0.03),
    (1.08, 1.1, 0.04), (1.1, 1.12, 0.04), (1.12, 1.15, 0.04),
    (1.15, 1.2, 0.05), (1.2, 1.25, 0.05), (1.25, 1.3, 0.05),
    (1.3, 1.35, 0.05), (1.35, 1.4, 0.05), (1.4, 1.45, 0.05),
    (1.45, 1.5, 0.05), (1.5, 1.55, 0.06), (1.55, 1.6, 0.06),
    (1.6, 1.7, 0.06), (1.7, 1.8, 0.06), (1.8, 1.9, 0.06),
    (1.9, 2.0, 0.06), (2.0, 2.1, 0.06), (2.1, 2.2, 0.07),
    (2.2, 2.3, 0.07), (2.3, 2.4, 0.07), (2.4, 2.5, 0.07),
    (2.5, 2.6, 0.08), (2.6, 2.7, 0.08), (2.7, 2.8, 0.08),
    (2.8, 2.9, 0.1), (2.9, 3.0, 0.1), (3.0, 3.2, 0.1),
    (3.2, 3.4, 0.15), (3.4, 3.6, 0.15), (3.6, 3.8, 0.15),
    (3.8, 4.0, 0.15), (4.0, 4.5, 0.2), (4.5, 5.0, 0.2),
    (5.0, 5.5, 0.25), (5.5, 6.0, 0.3), (6.0, 6.5, 0.4),
    (6.5, 7.0, 0.5), (7.0, 8.0, 0.7), (8.0, 9.0, 0.8),
    (9.0, 11.0, 1.0), (11.0, 13.0, 1.5), (13.0, 15.0, 2.0),
    (15.0, 17.0, 2.5), (17.0, 19.0, 3.0), (19.0, 21.0, 3.5),
    (21.0, 26.0, 4.0), (26.0, 31.0, 4.5), (31.0, 41.0, 5.0),
    (41.0, 51.0, 5.5), (51.0, 61.0, 6.0), (61.0, 71.0, 7.0),
    (71.0, 81.0, 8.0), (81.0, 91.0, 9.0), (91.0, 101.0, 10.0),
    (101.0, 121.0, 12.0), (121.0, 151.0, 14.0), (151.0, 201.0, 16.0),
    (201.0, 351.0, 18.0), (351.0, 501.0, 20.0), (501.0, 751.0, 25.0),
    (751.0, 1001.0, 35.0), (1001.0, 10001.0, 50.0),
]


def fraction_to_decimal(s: str) -> float:
    """Convert fraction (e.g. '13/10', '9/2') or decimal string to float."""
    try:
        s = str(s).strip()
        if "/" in s:
            n, d = s.split("/", 1)
            return round(int(n) / int(d) + 1.0, 2)
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def appliquer_pv_fallback(row: Dict[str, Any]) -> bool:
    """Applique le chart 7 Price Variance lorsque le moteur JS n'est pas initialise."""
    brute = row.get("Cote_Decimale_Brute")
    fraction_brute = row.get("Cote_Fraction_Brute") or row.get("Cote_Fraction") or ""
    try:
        if "/" in str(fraction_brute):
            n, d = str(fraction_brute).split("/", 1)
            valeur_exacte = int(n) / int(d) + 1.0
        else:
            valeur_exacte = float(brute)
    except Exception:
        valeur_exacte = float(brute or 0)
    if not valeur_exacte:
        return False
    for borne_basse, borne_haute, ajustement in PV_DEFAULT_CHART_7:
        if borne_basse <= valeur_exacte < borne_haute:
            ajustee = int((valeur_exacte - ajustement + 1e-12) * 100) / 100
            fractionnelle = Fraction(max(ajustee - 1.0, 0)).limit_denominator(1000)
            fraction = f"{fractionnelle.numerator}/{fractionnelle.denominator}"
            row["Cote_Fraction"] = fraction
            row["Cote_Decimale"] = ajustee
            row["Cote_PV_Applique"] = True
            row["Source_Cote"] = "price_variance_chart_7"
            return True
    return False


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
                appliquer_pv_fallback(row)
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

            if any(k in u for k in ["splashcontentapi/splash", "othersportsmatch", "coupon", "markets"]):
                if sport_code in u:
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
        # Look for the sport text in French or English
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
                            odds_dict[p_name] = f"{float(c_dec):.2f}"

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
                            odds_dict[p_name] = f"{float(c_dec):.2f}"

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


# ─────────────────────────────────────────────────────────────────────────────
# Generalized Multi-Sport CDP Scraper for All Sports (Fixtures & Matches)
# ─────────────────────────────────────────────────────────────────────────────

SPORT_CODE_MAP: Dict[str, Tuple[str, str]] = {
    "epl": ("Football", "B1"),
    "soccer": ("Football", "B1"),
    "football": ("Football", "B1"),
    "tennis": ("Tennis", "B13"),
    "us open": ("Tennis", "B13"),
    "us open women": ("Tennis", "B13"),
    "basketball": ("Basketball", "B18"),
    "american football": ("American Football", "B12"),
    "nfl": ("American Football", "B12"),
    "baseball": ("Baseball", "B16"),
    "mlb": ("Baseball", "B16"),
    "ice hockey": ("Ice Hockey", "B17"),
    "nhl": ("Ice Hockey", "B17"),
    "rugby league": ("Rugby League", "B19"),
    "rugby union": ("Rugby Union", "B8"),
    "handball": ("Handball", "B78"),
    "cricket": ("Cricket", "B3"),
    "volleyball": ("Volleyball", "B91"),
    "esports": ("Esports", "B151"),
    "cycling": ("Cyclisme", "B38"),
    "golf": ("Golf", "B7"),
}


def parse_bc_datetime(bc_str: str) -> Tuple[str, str]:
    """Converts Bet365 BC timestamp 'YYYYMMDDHHMMSS' to (kickoff, date)."""
    if bc_str and len(bc_str) >= 12:
        try:
            dt = datetime.strptime(bc_str[:14], "%Y%m%d%H%M%S")
            return dt.strftime("%d/%m/%Y %H:%M:%S"), dt.strftime("%d/%m/%Y")
        except Exception:
            pass
    now = datetime.now(timezone.utc)
    return now.strftime("%d/%m/%Y 18:00:00"), now.strftime("%d/%m/%Y")


_CHROME_PROC = None

def ensure_chrome_cdp(cdp_port: int = CDP_PORT) -> bool:
    """Verify if Chrome CDP is responsive on cdp_port; if not, auto-launch it."""
    global _CHROME_PROC
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=1.5)
        return True
    except Exception:
        pass

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    ]
    chrome_bin = next((p for p in chrome_paths if os.path.exists(p)), None)
    if not chrome_bin:
        print("  [Notice] Google Chrome not found in standard directories.")
        return False

    temp_profile = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "bet365_cdp_profile")
    cmd = [
        chrome_bin,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.bet365.com"
    ]
    try:
        import subprocess
        # Launch detached and store reference so it stays active
        _CHROME_PROC = subprocess.Popen(cmd, creationflags=0x00000008 | 0x00000200, close_fds=True)
        print(f"  [*] Auto-launched Google Chrome on CDP port {cdp_port}...")
        for _ in range(12):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=1.0)
                return True
            except Exception:
                pass
    except Exception as e:
        print(f"  [Notice] Could not auto-launch Chrome: {e}")
    return False


def extract_dom_coupon_matches(page, competition_name: str, sport_name: str) -> List[Dict[str, Any]]:
    """Extracts matches and 1X2 / 2-way odds directly from Bet365 DOM coupon tables."""
    try:
        return page.evaluate("""([comp, sport]) => {
            const results = [];
            let currentDate = '';
            const today = new Date();
            const year = today.getFullYear();
            const monthMap = {
                'janv': '01', 'fevr': '02', 'févr': '02', 'mars': '03', 'avr': '04',
                'mai': '05', 'juin': '06', 'juil': '07', 'aout': '08', 'août': '08',
                'sept': '09', 'oct': '10', 'nov': '11', 'dec': '12', 'déc': '12',
                'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05',
                'jun': '06', 'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10',
                'nov': '11', 'dec': '12'
            };

            const elements = Array.from(document.querySelectorAll('div'));
            for (const el of elements) {
                const text = el.innerText ? el.innerText.trim() : '';
                const dm = text.match(/(\\d{1,2})\\s*([a-zéû]+)/i);
                if (el.children.length === 0 && dm && (text.length < 20)) {
                    const day = dm[1].padStart(2, '0');
                    const mStr = dm[2].toLowerCase().slice(0, 4);
                    const month = monthMap[mStr] || '09';
                    currentDate = `${day}/${month}/${year}`;
                }

                if (el.className && el.className.includes('rrc-9') && el.innerText) {
                    const lines = el.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
                    if (lines.length >= 4) {
                        const timeMatch = lines[0].match(/^(\\d{1,2}:\\d{2})$/);
                        if (timeMatch) {
                            const timeStr = timeMatch[1] + ':00';
                            let idx = 1;
                            // Skip badge number or markets count indicator if present
                            if (idx < lines.length && /^\\d+$/.test(lines[idx])) {
                                idx++;
                            }
                            const home = lines[idx++];
                            const away = lines[idx++];
                            const odds = lines.slice(idx).filter(l => /^\\d+\\.\\d+$/.test(l) || /^\\d+\\/\\d+$/.test(l));

                            // Strict validation: must be a real fixture between two distinct teams
                            if (!home || !away || home === away || home === comp) continue;
                            if (home.toLowerCase().includes('winner') || away.toLowerCase().includes('winner')) continue;

                            const mDate = currentDate || `${today.getDate().toString().padStart(2, '0')}/${(today.getMonth() + 1).toString().padStart(2, '0')}/${year}`;
                            const kickoff = `${mDate} ${timeStr}`;
                            const mId = Math.abs((home + away + kickoff).split('').reduce((a, b) => ((a << 5) - a) + b.charCodeAt(0), 0)).toString();

                            if (odds.length >= 3) {
                                results.push({
                                    id: mId,
                                    date: mDate,
                                    kickoff: kickoff,
                                    competition: comp,
                                    home: home,
                                    away: away,
                                    markets: {
                                        "Match Result": {
                                            "1": odds[0],
                                            "X": odds[1],
                                            "2": odds[2]
                                        }
                                    }
                                });
                            } else if (odds.length === 2) {
                                const mktName = (sport.toLowerCase().includes('soccer') || sport.toLowerCase().includes('football')) ? "Match Result" : "Match Winner";
                                results.push({
                                    id: mId,
                                    date: mDate,
                                    kickoff: kickoff,
                                    competition: comp,
                                    home: home,
                                    away: away,
                                    markets: {
                                        [mktName]: {
                                            "1": odds[0],
                                            "2": odds[1]
                                        }
                                    }
                                });
                            }
                        }
                    }
                }
            }
            return results;
        }""", [competition_name, sport_name])
    except Exception:
        return []


def scrape_sport_internal(sport_name: str, cdp_port: int = CDP_PORT) -> List[Dict[str, Any]]:
    """
    Direct Bet365 CDP Scraper for any sport (Soccer, EPL, Tennis, Basketball, NFL, MLB, etc.).
    Connects to Chrome on port 9222 (launched via start_chrome_cdp.bat).
    Extracts authentic MATCHES and FIXTURES (Home vs Away) with decimal odds.
    Zero third-party API keys required.
    """
    s_clean = sport_name.strip().lower()
    if s_clean in ["cycling", "cyclisme"]:
        return scrape_cycling_internal(cdp_port)
    if s_clean == "golf":
        return scrape_golf_internal(cdp_port)

    if not HAS_PLAYWRIGHT:
        return []

    # Ensure Chrome CDP is running
    ensure_chrome_cdp(cdp_port)

    bet365_sport_name, sport_code = SPORT_CODE_MAP.get(s_clean, ("Football", "B1"))
    matches_out: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            except Exception:
                return []

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = _get_active_bet365_page(context)
            if not page:
                return []

            domain = _detect_bet365_domain(context)

            # ─────────────────────────────────────────────────────────
            # 1. EPL (England Premier League) Matches
            # ─────────────────────────────────────────────────────────
            if s_clean == "epl":
                print(f"  [CDP EPL] Scraping England Premier League matches directly from {domain}...")
                page.goto(f"{domain}/#/AS/B1/", wait_until="commit")
                time.sleep(2)
                comp_tab = page.query_selector('text="Competitions"') or page.query_selector('text="Compétitions"')
                if comp_tab:
                    page.evaluate("el => el.click()", comp_tab)
                    time.sleep(2)
                epl_el = page.query_selector('text="England Premier League"')
                if epl_el:
                    page.evaluate("el => el.click()", epl_el)
                    time.sleep(2)
                    m_tab = page.query_selector('text="Matches"') or page.query_selector('text="Matchs"')
                    if m_tab:
                        page.evaluate("el => el.click()", m_tab)
                        time.sleep(3)
                    epl_found = extract_dom_coupon_matches(page, "FA Barclaycard", "Football")
                    # Strict validation: match must have both home and away
                    for m in epl_found:
                        if m.get("home") and m.get("away") and m["home"] != m["away"] and m["home"] != m["competition"]:
                            matches_out.append(m)
                    if matches_out:
                        print(f"  + [EPL] Captured {len(matches_out)} real match fixtures via Bet365 CDP")
                return matches_out

            # ─────────────────────────────────────────────────────────
            # 2. SOCCER (UEFA Champions League, European Top Leagues)
            # ─────────────────────────────────────────────────────────
            if s_clean == "soccer":
                print(f"  [CDP Soccer] Scraping Soccer matches (UCL & European Leagues) directly from {domain}...")
                page.goto(f"{domain}/#/AS/B1/", wait_until="commit")
                time.sleep(2)

                top_leagues = [
                    ("UEFA Champions League", "UEFA Champions League"),
                    ("England Championship", "England Championship"),
                    ("Spain La Liga", "Spain La Liga"),
                    ("Italy Serie A", "Italy Serie A"),
                    ("Germany Bundesliga I", "Germany Bundesliga I"),
                    ("France Ligue 1", "France Ligue 1"),
                    ("Netherlands Eredivisie", "Netherlands Eredivisie"),
                    ("USA MLS", "USA MLS")
                ]

                # First check Popular tab on Soccer home page
                for league_click_name, comp_title in top_leagues[:4]:
                    l_el = page.query_selector(f'text="{league_click_name}"')
                    if l_el:
                        try:
                            page.evaluate("el => el.click()", l_el)
                            time.sleep(2)
                            m_tab = page.query_selector('text="Matches"') or page.query_selector('text="Matchs"')
                            if m_tab:
                                page.evaluate("el => el.click()", m_tab)
                                time.sleep(2.5)
                            found = extract_dom_coupon_matches(page, comp_title, "Football")
                            for m in found:
                                if m.get("home") and m.get("away") and m["home"] != m["away"] and m["home"] != m["competition"]:
                                    if not any(x["id"] == m["id"] for x in matches_out):
                                        matches_out.append(m)
                            # Go back to Soccer
                            page.goto(f"{domain}/#/AS/B1/", wait_until="commit")
                            time.sleep(1.5)
                        except Exception:
                            pass

                # Then check Competitions tab for remaining leagues
                comp_tab = page.query_selector('text="Competitions"') or page.query_selector('text="Compétitions"')
                if comp_tab:
                    try:
                        page.evaluate("el => el.click()", comp_tab)
                        time.sleep(2)
                        for league_click_name, comp_title in top_leagues[4:]:
                            l_el = page.query_selector(f'text="{league_click_name}"')
                            if l_el:
                                page.evaluate("el => el.click()", l_el)
                                time.sleep(2)
                                m_tab = page.query_selector('text="Matches"') or page.query_selector('text="Matchs"')
                                if m_tab:
                                    page.evaluate("el => el.click()", m_tab)
                                    time.sleep(2.5)
                                found = extract_dom_coupon_matches(page, comp_title, "Football")
                                for m in found:
                                    if m.get("home") and m.get("away") and m["home"] != m["away"] and m["home"] != m["competition"]:
                                        if not any(x["id"] == m["id"] for x in matches_out):
                                            matches_out.append(m)
                                page.goto(f"{domain}/#/AS/B1/", wait_until="commit")
                                time.sleep(1.5)
                                c_tab2 = page.query_selector('text="Competitions"') or page.query_selector('text="Compétitions"')
                                if c_tab2:
                                    page.evaluate("el => el.click()", c_tab2)
                                    time.sleep(1.5)
                    except Exception:
                        pass

                if matches_out:
                    print(f"  + [Soccer] Captured {len(matches_out)} real match fixtures via Bet365 CDP")
                return matches_out

            # ─────────────────────────────────────────────────────────
            # 3. TENNIS / US OPEN / US OPEN WOMEN
            # ─────────────────────────────────────────────────────────
            if s_clean in ["tennis", "us open", "us open women"]:
                print(f"  [CDP {sport_name}] Scraping Tennis matches directly from {domain}...")
                page.goto(f"{domain}/#/AS/B13/", wait_until="commit")
                time.sleep(2.5)
                m_tab = page.query_selector('text="Matches"') or page.query_selector('text="Matchs"')
                if m_tab:
                    page.evaluate("el => el.click()", m_tab)
                    time.sleep(3)
                found = extract_dom_coupon_matches(page, sport_name, "Tennis")
                for m in found:
                    if m.get("home") and m.get("away") and m["home"] != m["away"]:
                        matches_out.append(m)
                if matches_out:
                    print(f"  + [{sport_name}] Captured {len(matches_out)} matches via Bet365 CDP")
                return matches_out

            # ─────────────────────────────────────────────────────────
            # 4. OTHER TEAM SPORTS (Basketball, Baseball/MLB, NFL, NHL, Rugby, etc.)
            # ─────────────────────────────────────────────────────────
            sport_url = f"{domain}/#/AS/{sport_code}/"
            print(f"  [CDP {sport_name}] Scraping {sport_name} matches from {domain} (Sport {sport_code})...")
            page.goto(sport_url, wait_until="commit")
            time.sleep(2.5)

            m_tab = page.query_selector('text="Matches"') or page.query_selector('text="Matchs"') or page.query_selector('text="Lines"') or page.query_selector('text="Games"')
            if m_tab:
                page.evaluate("el => el.click()", m_tab)
                time.sleep(3)

            found = extract_dom_coupon_matches(page, sport_name, sport_name)
            for m in found:
                if m.get("home") and m.get("away") and m["home"] != m["away"] and m["home"] != m["competition"]:
                    matches_out.append(m)

            if matches_out:
                print(f"  + [{sport_name}] Captured {len(matches_out)} matches via Bet365 CDP")

    except BaseException as e:
        pass

    return matches_out




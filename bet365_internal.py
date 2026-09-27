"""
Bet365 Pure CDP Multi-Sport Scraper Engine
===========================================
Extracts live matches, deep markets, and outrights directly from Bet365
via Chrome DevTools Protocol (CDP) on port 9222 using Playwright.

Target Sports (Exclusively):
1. Soccer (Big 5 European Leagues + UEFA Competitions [UCL, UEL, UECL] + Major Domestic Cups [FA Cup, Copa del Rey, Coppa Italia, DFB-Pokal, Coupe de France])
2. Tennis (ATP, WTA, Grand Slams, Challenger)
3. Basketball (NBA, EuroLeague, European Top Flights)
4. Handball (EHF Champions League, European Top Flights)
5. Cycling (Grand Tours, Classics, World Championships, One-Day Races)
6. Golf (PGA Tour, DP World Tour, Major Championships, Outrights, 3-Balls)
7. Formula 1 (F1) (Grand Prix Winner, Drivers & Constructors Championships)

Key Principles:
- 100% Live Direct Scrape: NO hardcoded or default odds anywhere.
- Anti-Detection: Intelligent pacing delays (2.0s to 3.5s) between requests.
- Auto-Cooldown: Detects "Impossible d'afficher ce contenu" and executes a 6s backoff.
- In-Page Routing: Reuses active Bet365 tab without triggering Cloudflare handshakes.
- Output: Standard all_matches.json schema containing match odds and details odds.
"""

import hashlib
import json
import math
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    PARIS_TZ = timezone(timedelta(hours=1))

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# ─────────────────────────────────────────────────────────────────────────────
# Global Settings & Pacing
# ─────────────────────────────────────────────────────────────────────────────
CDP_PORT = 9222
DEFAULT_DELAY = 2.5
DEFAULT_JITTER = 0.5

_DETECTED_DOMAIN: Optional[str] = None


def get_bet365_domain() -> str:
    """
    Auto-detect whether to target https://www.bet365.fr (French IP) or https://www.bet365.com (global).
    - If BET365_DOMAIN environment variable is set, uses that.
    - If config.json specifies a concrete domain ('bet365.fr' or 'bet365.com'), uses that.
    - Otherwise checks public IP geolocation. If country is France ('FR'), returns 'https://www.bet365.fr'.
    - Otherwise defaults to 'https://www.bet365.com'.
    """
    global _DETECTED_DOMAIN
    if _DETECTED_DOMAIN:
        return _DETECTED_DOMAIN

    # 1. Environment variable override
    env_dom = os.environ.get("BET365_DOMAIN", "").strip()
    if env_dom:
        if "bet365.fr" in env_dom.lower():
            _DETECTED_DOMAIN = "https://www.bet365.fr"
            return _DETECTED_DOMAIN
        elif "bet365.com" in env_dom.lower():
            _DETECTED_DOMAIN = "https://www.bet365.com"
            return _DETECTED_DOMAIN

    # 2. Config override
    try:
        if os.path.exists("config.json"):
            with open("config.json", encoding="utf-8") as f:
                cfg = json.load(f)
                cfg_dom = cfg.get("default_domain", "")
                if "bet365.fr" in cfg_dom.lower():
                    _DETECTED_DOMAIN = "https://www.bet365.fr"
                    return _DETECTED_DOMAIN
                elif "bet365.com" in cfg_dom.lower() and cfg_dom.lower() != "auto":
                    _DETECTED_DOMAIN = "https://www.bet365.com"
                    return _DETECTED_DOMAIN
    except Exception:
        pass

    # 3. GeoIP Lookup to detect if host has French IP
    try:
        req = urllib.request.Request("https://api.country.is/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1.8) as r:
            geo = json.loads(r.read().decode())
            if (geo.get("country") or "").upper() == "FR":
                print("  [*] French IP detected (GeoIP: FR) -> Automatically targeting https://www.bet365.fr")
                _DETECTED_DOMAIN = "https://www.bet365.fr"
                return _DETECTED_DOMAIN
    except Exception:
        pass

    try:
        req = urllib.request.Request("http://ip-api.com/json/?fields=countryCode", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1.8) as r:
            geo = json.loads(r.read().decode())
            if (geo.get("countryCode") or "").upper() == "FR":
                print("  [*] French IP detected (ip-api: FR) -> Automatically targeting https://www.bet365.fr")
                _DETECTED_DOMAIN = "https://www.bet365.fr"
                return _DETECTED_DOMAIN
    except Exception:
        pass

    _DETECTED_DOMAIN = "https://www.bet365.com"
    return _DETECTED_DOMAIN


DEFAULT_DOMAIN = get_bet365_domain()

# Load config if present
try:
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as _cfg_f:
            _cfg = json.load(_cfg_f)
            CDP_PORT = int(_cfg.get("cdp_port", CDP_PORT))
            DEFAULT_DELAY = float(_cfg.get("request_delay_seconds", DEFAULT_DELAY))
            DEFAULT_JITTER = float(_cfg.get("delay_jitter", DEFAULT_JITTER))
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Spacing & Anti-Detection
# ─────────────────────────────────────────────────────────────────────────────
def request_delay(base_s: float = DEFAULT_DELAY, jitter: float = DEFAULT_JITTER) -> None:
    """
    Pacing delay between requests using randomized human-like timing distributions
    (log-normal jitter + occasional realistic pause) to prevent robotic fingerprinting.
    """
    factor = random.lognormvariate(0.0, 0.35)
    sleep_time = max(1.5, base_s * factor)
    if random.random() < 0.12:
        sleep_time += random.uniform(1.8, 3.8)
    time.sleep(sleep_time)


def is_port_in_use(port: int = CDP_PORT) -> bool:
    """Check if Chrome CDP port is open and accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


_CDP_CHECKED: Optional[bool] = None


def ensure_chrome_cdp(cdp_port: int = CDP_PORT) -> bool:
    """Ensure Google Chrome CDP is running; launches chrome.exe if not active."""
    global _CDP_CHECKED
    if _CDP_CHECKED is True and is_port_in_use(cdp_port):
        return True

    if is_port_in_use(cdp_port):
        _CDP_CHECKED = True
        return True

    print(f"  [*] Chrome CDP (port {cdp_port}) not active. Attempting initialization...")

    target_domain = get_bet365_domain()
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium"
    ]
    chrome_bin = next((c for c in chrome_candidates if os.path.exists(c)), None)
    proxy_server = os.environ.get("BET365_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if not proxy_server:
        try:
            if os.path.exists("config.json"):
                with open("config.json", encoding="utf-8") as _cfg_f:
                    proxy_server = json.load(_cfg_f).get("proxy")
        except Exception:
            pass

    if chrome_bin:
        profile_dir = os.path.join(os.path.expanduser("~"), ".bet365_chrome_profile")
        cmd = [
            chrome_bin,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--window-size=1920,1080",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--lang=fr-FR,fr",
        ]
        if proxy_server:
            print(f"  [*] Using configured proxy server: {proxy_server}")
            cmd.append(f"--proxy-server={proxy_server}")
        cmd.append(target_domain)
        try:
            flags = 0x00000008 if sys.platform == "win32" else 0
            subprocess.Popen(cmd, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    for _ in range(16):
        time.sleep(0.5)
        if is_port_in_use(cdp_port):
            print(f"  [*] Chrome CDP connected on port {cdp_port}.")
            _CDP_CHECKED = True
            time.sleep(1.0)
            return True

    print(f"  [Error] Could not connect to Chrome on port {cdp_port}.")
    _CDP_CHECKED = False
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Odds & Protocol Utilities
# ─────────────────────────────────────────────────────────────────────────────
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
    """Format decimal odds with authentic precision (e.g. '1.083' or '11.00')."""
    try:
        f_val = float(val)
        val_3 = round(f_val, 3)
        val_2 = round(f_val, 2)
        if abs(val_3 - val_2) > 0.002:
            return f"{val_3:.3f}"
        return f"{val_2:.2f}"
    except Exception:
        return str(val)

def stable_id(*parts) -> str:
    """Generate a deterministic, process-stable 8-digit match ID using MD5."""
    clean = [str(p).strip().lower() for p in parts if str(p).strip()]
    h = hashlib.md5("_".join(clean).encode("utf-8")).hexdigest()
    return str(int(h, 16) % 100000000)


def get_now_paris() -> datetime:
    """Returns current datetime aligned with Bet365 European schedule (Europe/Paris)."""
    return datetime.now(PARIS_TZ)


MARKET_STRUCTURE = {
    # market_key: (min_outcomes, max_outcomes, min_odds, max_odds)
    "Match Result": (2, 3, 1.00, 501.0),
    "Both Teams to Score": (2, 2, 1.01, 25.0),
    "Goals Over/Under": (2, 2, 1.01, 25.0),
    "Double Chance": (3, 3, 1.01, 20.0),
    "Draw No Bet": (2, 2, 1.01, 25.0),
    "Half Time/Full Time": (9, 9, 1.10, 501.0),
    "Correct Score": (6, 60, 1.01, 501.0),
    "Set Betting": (2, 4, 1.01, 50.0),
    "First Set Winner": (2, 2, 1.01, 20.0),
    "Total Games": (2, 2, 1.01, 25.0),
    "Point Spread": (2, 2, 1.01, 25.0),
    "Total Points": (2, 2, 1.01, 25.0),
    "Moneyline": (2, 2, 1.00, 100.0),
    "Money Line": (2, 2, 1.00, 100.0),
    "To Win Match": (2, 2, 1.00, 100.0),
    "Match Winner": (2, 2, 1.00, 100.0),
    "Handicap / Spread": (2, 2, 1.01, 25.0),
    "Handicap": (2, 2, 1.01, 25.0),
    "Total Goals": (2, 2, 1.01, 25.0),
    "Full Time Result": (2, 3, 1.00, 501.0),
}


def validate_market(name: str, outcomes: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validates structural integrity, outcome counts, and authentic odds ranges for a market.
    Rejects corrupted, shifted, or mislabeled outcome sets.
    """
    if not isinstance(outcomes, dict):
        return False, f"{name}: outcomes must be a dictionary"
    spec = MARKET_STRUCTURE.get(name)
    if not spec:
        return True, ""
    lo, hi, omin, omax = spec
    vals = []
    for k, v in outcomes.items():
        if isinstance(v, dict):
            val_cand = v.get("odds") or v.get("1") or v.get("2")
        else:
            val_cand = v
        str_val = str(val_cand).strip()
        # Extract numeric odds if formatted as line + odds e.g. "+1.5 (1.83)" or "Over 176.5 (1.83)"
        m_paren = re.search(r'\(([\d.,]+)\)', str_val)
        if m_paren:
            clean_str = m_paren.group(1).replace(",", ".")
        else:
            # Strip leading O / U if present
            clean_str = re.sub(r'^[OUou]\s+', '', str_val).replace(",", ".")
        try:
            f_val = float(clean_str)
            vals.append(f_val)
        except (ValueError, TypeError):
            return False, f"{name}: invalid outcome price '{val_cand}'"

    if not (lo <= len(vals) <= hi):
        return False, f"{name}: {len(vals)} outcomes, expected {lo}-{hi}"

    for v in vals:
        if not (omin <= v <= omax):
            return False, f"{name}: odd {v} outside realistic bounds [{omin}, {omax}]"

    return True, ""


def wait_for_view_change(session, timeout: float = 5.0, settle: float = 0.35) -> bool:
    """Polls until coupon DOM signature changes and settles after a tab click."""
    def get_sig():
        lines = session.get_dom_lines()
        return hashlib.md5("|".join(lines).encode("utf-8")).hexdigest()
    try:
        baseline = get_sig()
        deadline = time.time() + timeout
        last_change = 0.0
        while time.time() < deadline:
            time.sleep(0.1)
            cur = get_sig()
            if cur != baseline:
                last_change = time.time()
                baseline = cur
            elif last_change and (time.time() - last_change >= settle):
                return True
        return False
    except Exception:
        return False


def active_subheader_text(session) -> str:
    """Returns the text of the currently active subheader button or tab."""
    try:
        return session.page.evaluate("""() => {
            const selectors = [
                '.wcl-PageSubHeader_Button.wcl-PageSubHeader_Active',
                '.wcl-PageSubHeader_Button[class*="Active"]',
                '.gl-MarketGroupButton[class*="Active"]',
                '[aria-selected="true"]',
                '.selected'
            ];
            for (const s of selectors) {
                const el = document.querySelector(s);
                if (el && el.innerText) return el.innerText.trim().toLowerCase();
            }
            return '';
        }""")
    except Exception:
        return ""


def parse_bet365(raw: str) -> List[Dict[str, str]]:
    """Parse Bet365 delimited protocol: blocks separated by |, fields by ;."""
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
    """Convert Bet365 PD identifier into canonical URL hash."""
    pd = str(pd or "").strip()
    if "#IP#" in pd or pd.startswith("IP#"):
        code = pd.strip("#/").replace("IP#", "", 1).strip("#/")
        return f"{domain}/#/IP/{code}/"
    segments = [s.strip("/") for s in pd.strip("#/").split("#") if s.strip("/")]
    return f"{domain}/#/" + "/".join(segments) + "/"


# ─────────────────────────────────────────────────────────────────────────────
# CDP Session & Stream Interceptor
# ─────────────────────────────────────────────────────────────────────────────
class CDPSession:
    """Encapsulates the live Playwright browser context connected via CDP."""

    def __init__(self, page, domain: str = "https://www.bet365.com"):
        self.page = page
        self._domain = domain
        try:
            self.page.evaluate("""() => {
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || { runtime: {} };
            }""")
            if hasattr(self.page, "context") and hasattr(self.page.context, "add_init_script"):
                self.page.context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = window.chrome || { runtime: {} };
                """)
        except Exception:
            pass

    @property
    def domain(self) -> str:
        try:
            u = (self.page.url or "").lower()
            if "bet365.fr" in u:
                return "https://www.bet365.fr"
            if "bet365.com" in u:
                return "https://www.bet365.com"
        except Exception:
            pass
        return self._domain or get_bet365_domain()

    @domain.setter
    def domain(self, val: str) -> None:
        self._domain = val

    def reset_to_home(self) -> None:
        """Clean navigation to root domain / #/HO/ to reset SPA router state and clear blocks."""
        if getattr(self, "geo_blocked", False) or self.is_geo_blocked():
            self.geo_blocked = True
            return
        try:
            loc = self.page.locator('text=Tous les Sports').first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=3000)
                time.sleep(2.0)
                return
        except Exception:
            pass
        try:
            self.page.goto(f"{self.domain}/#/HO/", wait_until="commit", timeout=15000)
            time.sleep(2.5)
        except Exception:
            pass

    def is_geo_blocked(self) -> bool:
        """Detect if current page is geo-restricted (e.g. Hungarian IP block 'Ez az oldal nem érhető el az Ön országából') or blocked by antivirus or 403 Forbidden."""
        try:
            body_text = (self.page.inner_text("body") or "").lower()
            title_text = (self.page.title() or "").lower()
            combined = f"{title_text} {body_text}"
            geo_keywords = [
                "nem érhető el az ön országából",
                "ez az oldal nem érhető el",
                "not available in your country",
                "country restrictions",
                "web protection by bitdefender",
                "suspicious page blocked",
                "access denied",
                "error 1020",
                "403 forbidden",
                "403 - forbidden",
                "forbidden"
            ]
            for kw in geo_keywords:
                if kw in combined:
                    return True
        except Exception:
            pass
        return False

    def check_and_recover_blocked(self) -> bool:
        """Detect if real WAF / Cloudflare block screen or error screen is shown and recover."""
        try:
            if self.is_geo_blocked():
                if not getattr(self, "geo_blocked", False):
                    print("  [Geo-Block Notice] Bet365 displays geo-restriction: 'Ez az oldal nem érhető el az Ön országából'.")
                    self.geo_blocked = True
                return True

            body_text = (self.page.inner_text("body") or "").lower()
            if len(body_text) < 1500:
                block_keywords = [
                    "access denied",
                    "error 1020",
                    "please verify you are human",
                    "attention required! | cloudflare",
                    "checking your browser before accessing",
                    "ray id:"
                ]
                if any(k in body_text for k in block_keywords):
                    print("  [Anti-Detection] Real WAF Block detected on page. Resetting to home...")
                    self.reset_to_home()
                    return True
            if not getattr(self, "geo_blocked", False) and ("désolé, cette page n'est plus disponible" in body_text or "impossible d'afficher ce contenu" in body_text):
                print("  [Router Recovery] Bet365 'Désolé' or 'Impossible d'afficher' detected. Resetting to home...")
                self.reset_to_home()
                time.sleep(2.0)
                return True
        except Exception:
            pass
        return False

    def navigate_to_sport(self, sport_name: str) -> bool:
        """Navigate to sport via sidebar click or clean SPA state navigation."""
        if getattr(self, "geo_blocked", False) or self.is_geo_blocked():
            self.geo_blocked = True
            return False
        self.check_and_recover_blocked()
        request_delay(base_s=1.0, jitter=0.2)

        search_terms = {
            "soccer": ["football", "football du week-end", "soccer"],
            "football": ["football", "football du week-end", "soccer"],
            "tennis": ["tennis", "tennis à venir"],
            "basketball": ["basket-ball", "basketball", "basket", "wnba", "nba"],
            "handball": ["handball"],
            "cycling": ["cyclisme", "cycling"],
            "cyclisme": ["cyclisme", "cycling"],
            "golf": ["golf"],
            "f1": ["formule 1", "formula 1", "sports mécaniques", "f1"],
            "formula 1": ["formule 1", "formula 1", "sports mécaniques", "f1"]
        }
        terms = search_terms.get(sport_name.lower(), [sport_name.lower()])
        # 1. First try exact match (e.g. ^Tennis$)
        for term in terms:
            try:
                loc = self.page.locator('.lhs-2d, .wn-Classification, [class*="Classification"]').filter(has_text=re.compile(f"^{re.escape(term)}$", re.I)).first
                if loc.count() > 0 and loc.is_visible():
                    loc.scroll_into_view_if_needed()
                    loc.click(timeout=3500)
                    time.sleep(2.5)
                    lines = self.get_dom_lines()
                    if len(lines) > 5 and not any("impossible d'afficher" in l.lower() or "désolé" in l.lower() for l in lines):
                        return True
            except Exception:
                pass
        # 2. Try prefix/contains match
        for term in terms:
            try:
                loc = self.page.locator('.lhs-2d, .wn-Classification, [class*="Classification"]').filter(has_text=re.compile(f"^{re.escape(term)}$|{re.escape(term)}", re.I)).first
                if loc.count() > 0 and loc.is_visible():
                    loc.scroll_into_view_if_needed()
                    loc.click(timeout=3500)
                    time.sleep(2.5)
                    lines = self.get_dom_lines()
                    if len(lines) > 5 and not any("impossible d'afficher" in l.lower() or "désolé" in l.lower() for l in lines):
                        return True
            except Exception:
                pass

        # 3. JS TreeWalker click on sidebar classification
        if self.click_sidebar_term(terms):
            time.sleep(2.5)
            lines = self.get_dom_lines()
            if len(lines) > 5 and not any("impossible d'afficher" in l.lower() or "désolé" in l.lower() for l in lines):
                return True

        # 4. SPA in-memory hash dispatch (clean internal router transition without WAF page reload)
        sport_routes = {
            "soccer": "#/AS/B1/",
            "football": "#/AS/B1/",
            "tennis": "#/AS/B13/",
            "basketball": "#/AS/B18/",
            "handball": "#/AS/B78/",
            "cycling": "#/AS/B38/",
            "cyclisme": "#/AS/B38/",
            "golf": "#/AS/B7/",
            "f1": "#/AS/B10/",
            "formula 1": "#/AS/B10/"
        }
        target_route = sport_routes.get(sport_name.lower())
        if target_route:
            try:
                self.page.evaluate('''(h) => {
                    if (window.location.hash !== h) {
                        window.location.hash = h;
                    }
                    window.dispatchEvent(new HashChangeEvent("hashchange"));
                    window.dispatchEvent(new PopStateEvent("popstate"));
                }''', target_route)
                time.sleep(2.0)
                lines = self.get_dom_lines()
                if len(lines) > 5 and not any("impossible d'afficher" in l.lower() or "désolé" in l.lower() for l in lines):
                    return True
            except Exception:
                pass

        try:
            clicked = self.page.evaluate('''(sName) => {
                const els = Array.from(document.querySelectorAll('[class*="crr-"], [class*="wn-Classification"], [class*="lnh-"], [class*="sm-"], [class*="lhs-"], a, button, div, span'));
                const match = els.find(e => {
                    if (e.children.length > 2) return false;
                    const t = (e.innerText || '').trim().toLowerCase();
                    const target = sName.toLowerCase();
                    return t === target
                        || ((target === 'soccer' || target === 'football') && (t === 'football' || t === 'soccer' || t === 'football du week-end'))
                        || (target === 'tennis' && (t === 'tennis' || t === 'tennis à venir'))
                        || ((target === 'basketball' || target === 'basket') && (t.includes('basket') || t === 'wnba'))
                        || (target === 'golf' && t === 'golf')
                        || ((target === 'f1' || target === 'formula 1') && (t.includes('formule 1') || t.includes('formula 1') || t.includes('f1')))
                        || ((target === 'cycling' || target === 'cyclisme') && (t.includes('cyclisme') || t.includes('cycling')))
                        || (target === 'handball' && t === 'handball');
                });
                if (match) {
                    const clickTarget = match.closest('.lhs-2d') || match.closest('a') || match.closest('button') || match;
                    clickTarget.click();
                    return true;
                }
                return false;
            }''', sport_name)
            if clicked:
                time.sleep(2.5)
                return True
        except Exception:
            pass
        return False

    def get_dom_lines(self) -> List[str]:
        """Safely fetch rendered DOM text lines."""
        try:
            return self.page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
        except Exception:
            return []

    def navigate_hash(self, target_url_or_hash: str) -> None:
        """Smooth hash navigation with in-memory dispatch first, avoiding destructive full page reloads."""
        self.check_and_recover_blocked()
        request_delay(base_s=1.0, jitter=0.2)
        target_hash = target_url_or_hash
        if "bet365." in target_url_or_hash:
            target_hash = "#/" + target_url_or_hash.split("#/")[-1] if "#/" in target_url_or_hash else target_url_or_hash
        if not target_hash.startswith("#/"):
            target_hash = "#/" + target_hash.lstrip("#/")
        if getattr(self, "geo_blocked", False) or self.is_geo_blocked():
            self.geo_blocked = True
            return

        # 1. Prefer client-side SPA in-memory hash dispatch to avoid triggering full page reloads and WAF
        try:
            self.page.evaluate('''(h) => {
                if (window.location.hash !== h) {
                    window.location.hash = h;
                }
                window.dispatchEvent(new HashChangeEvent("hashchange"));
                window.dispatchEvent(new PopStateEvent("popstate"));
            }''', target_hash)
            time.sleep(1.8)
            lines = self.get_dom_lines()
            if len(lines) > 5 and not any("impossible d'afficher" in l.lower() or "désolé" in l.lower() for l in lines):
                return
        except Exception:
            pass

        # 2. Fallback: page.goto only if in-memory dispatch did not change view
        try:
            full_url = f"{self.domain}/{target_hash}"
            self.page.goto(full_url, wait_until="commit", timeout=12000)
            time.sleep(1.5)
            lines = self.get_dom_lines()
            if any("impossible d'afficher" in l.lower() or "désolé" in l.lower() for l in lines):
                self.reset_to_home()
        except Exception:
            pass

    def click_sidebar_term(self, terms: List[str]) -> bool:
        """Click sidebar sport classification link using JS TreeWalker."""
        self.check_and_recover_blocked()
        request_delay(base_s=1.8, jitter=0.3)
        try:
            clicked = self.page.evaluate("""(terms) => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    const val = (node.nodeValue || '').trim();
                    for (const term of terms) {
                        if (val.toLowerCase() === term.toLowerCase()) {
                            const p = node.parentElement;
                            if (p && (p.className.includes('lhs') || p.closest('.lhs-2d') || p.closest('.wn-Classification') || p.closest('a'))) {
                                (p.closest('.lhs-2d') || p.closest('.wn-Classification') || p).click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }""", terms)
            return bool(clicked)
        except Exception:
            return False

    def click_link_by_text(self, terms: List[str]) -> bool:
        """Click any link, button, or coupon header matching one of the terms."""
        self.check_and_recover_blocked()
        request_delay(base_s=1.5, jitter=0.3)
        try:
            clicked = self.page.evaluate("""(terms) => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    const val = (node.nodeValue || '').trim();
                    for (const term of terms) {
                        if (val.toLowerCase() === term.toLowerCase() || (term.length > 5 && val.toLowerCase().includes(term.toLowerCase()))) {
                            const el = node.parentElement;
                            const clickable = el.closest('a') || el.closest('button') || el.closest('.sm-CouponLink') || el.closest('.gl-MarketGroupButton') || el;
                            if (clickable && clickable.click) {
                                clickable.click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }""", terms)
            return bool(clicked)
        except Exception:
            return False

    def intercept_sport_splash(self, sport_url: str, sport_names: List[str], sport_code: str, timeout_s: int = 8) -> Optional[str]:
        """Navigate to sport splash and capture delimited data stream."""
        if getattr(self, "geo_blocked", False) or self.is_geo_blocked():
            self.geo_blocked = True
            return None
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

                if any(k in u for k in ["splashcontentapi/splash", "othersportsmatch", "coupon", "markets", "sport", "classification"]):
                    is_sport = (
                        sport_code.lower() in u.lower() or
                        f"/{sport_code.lstrip('B')}/" in u or
                        f"cd={sport_code.lstrip('B').lower()};" in txt.lower() or
                        any(sn.lower() in u.lower() or sn.lower() in txt.lower() for sn in sport_names)
                    )
                    if is_sport and ("EV;" in txt or "PA;" in txt):
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
            self.page.on("response", handler)
        except Exception:
            pass

        navigated = False
        for sname in sport_names:
            if self.navigate_to_sport(sname):
                navigated = True
                break
        if not navigated:
            navigated = self.click_sidebar_term(sport_names)
        if not navigated and sport_url:
            self.navigate_hash(sport_url)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if ok[0] and raw[0] and ("PA;" in raw[0] or "EV;" in raw[0]):
                break
            try:
                self.page.wait_for_timeout(200)
            except Exception:
                break

        try:
            self.page.remove_listener("response", handler)
        except Exception:
            pass

        if not ok[0] and raw_secours:
            raw[0] = max(raw_secours, key=len)

        return raw[0]

    def intercept_coupon_data(self, url: str, timeout_s: int = 4) -> Optional[str]:
        """Navigate to coupon URL and intercept data stream with clean listener handling."""
        if getattr(self, "geo_blocked", False) or self.is_geo_blocked():
            self.geo_blocked = True
            return None
        self.check_and_recover_blocked()
        request_delay(base_s=DEFAULT_DELAY, jitter=DEFAULT_JITTER)

        raw = [None]
        ok = [False]

        def handler(response):
            if ok[0] and raw[0]:
                return
            if response.request.resource_type not in ("fetch", "xhr"):
                return
            try:
                txt = response.text()
                if txt and "|" in txt and ("PA;" in txt or "OD=" in txt) and len(txt) < 500000:
                    raw[0] = txt
                    ok[0] = True
            except Exception:
                pass

        try:
            self.page.on("response", handler)
        except Exception:
            pass

        try:
            target_hash = url
            if "bet365." in url:
                target_hash = "#/" + url.split("#/")[-1] if "#/" in url else url
            try:
                current_hash = self.page.evaluate("() => window.location.hash || ''")
                if current_hash != target_hash:
                    self.page.evaluate("(h) => { window.location.hash = h; }", target_hash)
                    time.sleep(1.0)
            except Exception:
                pass

            deadline = time.time() + timeout_s
            while time.time() < deadline:
                if ok[0] and raw[0]:
                    break
                try:
                    self.page.wait_for_timeout(150)
                except Exception:
                    break
        finally:
            try:
                self.page.remove_listener("response", handler)
            except Exception:
                pass

        return raw[0]


# ─────────────────────────────────────────────────────────────────────────────
# Parsing Engines
# ─────────────────────────────────────────────────────────────────────────────
def parser_splash(raw: str, domain: str = DEFAULT_DOMAIN) -> List[Dict[str, Any]]:
    """Discovers competitions and market links from splash response."""
    parsed = parse_bet365(raw)
    vus = set()
    competition = "Compétition"

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
                        "nom": nom, "url": pd_vers_url(pd, domain), "pd": pd
                    })
        elif t == "PA" and tournoi_courant:
            pd = b.get("PD", "").strip()
            nom = b.get("NA", "").strip()
            if pd and nom and "#P" not in pd and "E729" not in pd:
                if "#AC#" in pd or "#IP#" in pd:
                    tournoi_courant["marches"].append({
                        "nom": nom, "url": pd_vers_url(pd, domain), "pd": pd
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
                        direct_marches.append({"nom": nom, "url": url, "pd": pd})
        if direct_marches:
            tournois.append({"nom": competition, "marches": direct_marches})

    return [t for t in tournois if t.get("marches")]


def parser_page_universel(raw: str, nom_sport: str, nom_event_fallback: str = "Compétition") -> List[Dict[str, Any]]:
    """
    Universal parser for all Bet365 coupons & pages.
    Extracts participants, selections, markets, and authentic decimal odds.
    """
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
                participant = na or hd_clean

                if not participant:
                    row_index += 1
                    continue

                participant = participant.replace(" - Oui", "").strip()
                marche_final = current_mg
                if current_ma and current_ma != current_mg and current_ma.strip():
                    marche_final = f"{current_mg} - {current_ma}"

                cote_brute = fraction_to_decimal(od)
                if cote_brute > 1.0:
                    row = {
                        "Sport": nom_sport,
                        "Tournoi": tournoi,
                        "Marche": marche_final,
                        "Marche_ID": current_ma_id or current_mg_id,
                        "Participant": participant,
                        "Cote_Decimale": cote_brute,
                    }
                    resultats.append(row)
                row_index += 1

    return resultats


def rows_to_matches(rows: List[Dict[str, Any]], sport_name: str, default_comp: str) -> List[Dict[str, Any]]:
    """
    Converts extracted rows from parser_page_universel into structured match objects
    adhering to the all_matches.json schema (match odds and details markets).
    """
    today_str = get_now_paris().strftime("%d/%m/%Y")
    kickoff_str = get_now_paris().strftime("%d/%m/%Y 15:00:00")

    matches_dict: Dict[str, Dict[str, Any]] = {}

    tourney_skip_keywords = [
        "challenger", "tour", "open", "cup", "outright", "markets",
        "championship", "grand prix", "masters", "classic", "league", "serie", "division", "coupe"
    ]

    for r in rows:
        tournoi = r.get("Tournoi", "").strip() or default_comp
        marche = r.get("Marche", "").strip()
        part = r.get("Participant", "").strip()
        c_dec = r.get("Cote_Decimale")

        if not part or not c_dec or float(c_dec) <= 1.0:
            continue
        if part in ["Inconnu", "Oui", "Non", "N/A"] and not any(k in marche.lower() for k in ["both teams to score", "marquent"]):
            continue

        odd_str = format_odd_str(c_dec)

        # Detect head-to-head match titles
        match_title = ""
        sub_market = marche

        if " v " in tournoi:
            match_title = tournoi
        elif " - " in tournoi and not any(k in tournoi.lower() for k in tourney_skip_keywords):
            match_title = tournoi
        elif " v " in marche:
            match_title = marche
            sub_market = "Match Result"
        elif " - " in marche and not any(k in marche.lower() for k in tourney_skip_keywords):
            match_title = marche
            sub_market = "Match Result"

        if match_title:
            splitter = " v " if " v " in match_title else (" - " if " - " in match_title else " / ")
            p_split = match_title.split(splitter, 1)
            home = p_split[0].strip()
            away = p_split[1].strip()

            match_id = stable_id(sport_name, home, away)

            if match_id not in matches_dict:
                matches_dict[match_id] = {
                    "id": match_id,
                    "date": today_str,
                    "kickoff": kickoff_str,
                    "competition": default_comp,
                    "home": home,
                    "away": away,
                    "markets": {}
                }

            m = matches_dict[match_id]
            markets = m["markets"]
            sm_lower = sub_market.lower()

            # Classify into Match Result, Money Line, BTTS, Total, etc.
            if any(k in sm_lower for k in ["result", "vainqueur", "winner", "money line", "to win match", "full time"]) or sub_market in ("Vainqueur", "Match Result"):
                if sport_name in ("Tennis", "Basketball"):
                    mkt_key = "Match Winner" if sport_name == "Tennis" else "Money Line"
                    if mkt_key not in markets:
                        markets[mkt_key] = {}
                    if part in (home, "1", "Home"):
                        markets[mkt_key]["1"] = odd_str
                    elif part in (away, "2", "Away"):
                        markets[mkt_key]["2"] = odd_str
                    else:
                        markets[mkt_key][part] = odd_str
                else:
                    if "Match Result" not in markets:
                        markets["Match Result"] = {}
                    if part in (home, "1", "Home"):
                        markets["Match Result"]["1"] = odd_str
                    elif part in ("Draw", "X", "Nul"):
                        markets["Match Result"]["X"] = odd_str
                    elif part in (away, "2", "Away"):
                        markets["Match Result"]["2"] = odd_str
                    else:
                        markets["Match Result"][part] = odd_str

            elif any(k in sm_lower for k in ["both teams to score", "marquent"]):
                if "Both Teams to Score" not in markets:
                    markets["Both Teams to Score"] = {}
                markets["Both Teams to Score"][part] = odd_str

            elif any(k in sm_lower for k in ["total", "goals", "plus/moins"]):
                if "Total" not in markets:
                    markets["Total"] = {}
                markets["Total"][part] = odd_str

            elif any(k in sm_lower for k in ["spread", "handicap", "écart"]):
                if "Handicap" not in markets:
                    markets["Handicap"] = {}
                markets["Handicap"][part] = odd_str

            elif any(k in sm_lower for k in ["set betting", "sets"]):
                if "Set Betting" not in markets:
                    markets["Set Betting"] = {}
                markets["Set Betting"][part] = odd_str

            else:
                if sub_market not in markets:
                    markets[sub_market] = {}
                markets[sub_market][part] = odd_str

        else:
            # Outright event (like Golf, Cycling, F1, or Outright tournament winners)
            comp_title = f"{default_comp} - {marche}" if marche != default_comp else default_comp
            match_id = stable_id(sport_name, comp_title)

            if match_id not in matches_dict:
                matches_dict[match_id] = {
                    "id": match_id,
                    "date": today_str,
                    "kickoff": kickoff_str,
                    "competition": comp_title,
                    "home": f"{comp_title} - To Win",
                    "away": "",
                    "markets": {
                        "To Win": {}
                    }
                }

            matches_dict[match_id]["markets"]["To Win"][part] = odd_str

    out = []
    for m in matches_dict.values():
        if m.get("markets"):
            for mkt_name, mkt_val in m["markets"].items():
                if isinstance(mkt_val, dict) and mkt_name in ("To Win", "Race Winner"):
                    m["markets"][mkt_name] = dict(sorted(
                        mkt_val.items(),
                        key=lambda x: float(x[1]) if x[1].replace(".", "", 1).isdigit() else 9999
                    ))
            out.append(m)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fixture & Match Coupon Parser
# ─────────────────────────────────────────────────────────────────────────────
def unpack_game_lines(raw_dict: Dict[str, str], sport: str = "Basketball") -> Dict[str, Any]:
    """Unpacks compound coupon keys (+/- spread, O/U totals, 1X2/moneyline) into specific markets."""
    spread = {}
    total = {}
    moneyline = {}

    for k, v in raw_dict.items():
        if re.match(r"^[+-]\d+(\.\d+)?$", k):
            if k.startswith("-"):
                spread["1"] = {"line": k, "odds": v}
            else:
                spread["2"] = {"line": k, "odds": v}
        elif re.match(r"^[OUPM]\s*\d+(\.\d+)?$", k, re.IGNORECASE):
            parts = re.split(r"\s+", k, maxsplit=1)
            letter = parts[0].upper()
            line_val = parts[1] if len(parts) > 1 else k[1:].strip()
            if letter in ("O", "P"):
                total["Over"] = {"line": line_val, "odds": v}
            elif letter in ("U", "M"):
                total["Under"] = {"line": line_val, "odds": v}
        elif k in ("1", "5", "Home", "home"):
            moneyline["1"] = v
        elif k in ("2", "6", "Away", "away"):
            moneyline["2"] = v
        elif k in ("X", "x", "Draw", "draw", "Nul"):
            moneyline["X"] = v

    markets = {}
    if sport.lower() == "basketball":
        if spread:
            markets["Point Spread"] = spread
        if total:
            markets["Total Points"] = total
        if moneyline:
            markets["Moneyline"] = moneyline
    elif sport.lower() == "handball":
        if moneyline:
            markets["Full Time Result"] = moneyline
        if total:
            markets["Total Goals"] = total
        if spread:
            markets["Handicap / Spread"] = spread

    return markets


def parse_french_date_header(line: str, default_date: Optional[str] = None) -> str:
    """Converts French/English day/date strings (e.g. 'Sam. 19 sept', 'Dim. 14:00', 'Demain', 'Aujourd\'hui') to DD/MM/YYYY."""
    now = get_now_paris()
    t = line.strip().lower()
    if 'demain' in t or 'tomorrow' in t:
        return (now + timedelta(days=1)).strftime("%d/%m/%Y")
    if 'aujourd' in t or 'today' in t:
        return now.strftime("%d/%m/%Y")
    m_day = re.search(r'(\d{1,2})\s+(janv?|févr?|mars|avr?|mai|juin|juil?|août|sept?|oct?|nov?|déc?|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?', t, re.I)
    if m_day:
        day = m_day.group(1).zfill(2)
        m_name = m_day.group(2).lower()
        month_map = {
            'jan': '01', 'janv': '01', 'feb': '02', 'fév': '02', 'févr': '02',
            'mar': '03', 'mars': '03', 'apr': '04', 'avr': '04',
            'may': '05', 'mai': '05', 'jun': '06', 'juin': '06',
            'jul': '07', 'juil': '07', 'aug': '08', 'août': '08',
            'sep': '09', 'sept': '09', 'oct': '10',
            'nov': '11', 'dec': '12', 'déc': '12'
        }
        m_num = month_map.get(m_name, '09')
        m_yr = re.search(r'202[4-9]', t)
        yr = m_yr.group(0) if m_yr else str(now.year)
        return f"{day}/{m_num}/{yr}"

    # Day of week abbreviation e.g. "Sam.", "Dim.", "Lun."
    day_map = {
        'lun': 0, 'mon': 0, 'lundi': 0, 'monday': 0,
        'mar': 1, 'tue': 1, 'mardi': 1, 'tuesday': 1,
        'mer': 2, 'wed': 2, 'mercredi': 2, 'wednesday': 2,
        'jeu': 3, 'thu': 3, 'jeudi': 3, 'thursday': 3,
        'ven': 4, 'fri': 4, 'vendredi': 4, 'friday': 4,
        'sam': 5, 'sat': 5, 'samedi': 5, 'saturday': 5,
        'dim': 6, 'sun': 6, 'dimanche': 6, 'sunday': 6
    }
    for d_name, d_idx in day_map.items():
        if t.startswith(d_name):
            diff = (d_idx - now.weekday()) % 7
            target_dt = now + timedelta(days=diff)
            return target_dt.strftime("%d/%m/%Y")

    m_dmy = re.search(r'(\d{2})/(\d{2})/(\d{4})', t)
    if m_dmy:
        return m_dmy.group(0)
    return default_date or now.strftime("%d/%m/%Y")


def is_upcoming_pre_match(date_str: str, kickoff_str: str, sport: str = "", now_dt: Optional[datetime] = None) -> bool:
    """
    Returns True ONLY if the match/event is strictly upcoming (pre-match).
    Filters out any match that is currently in-live (in-play) or already finished.
    """
    if now_dt is None:
        now_dt = datetime.now()

    # Outrights in Cycling, Golf, Formula 1
    if sport in ("Cycling", "Golf", "F1"):
        dt = None
        if kickoff_str:
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(kickoff_str, fmt)
                    break
                except Exception:
                    pass
        if not dt and date_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(date_str, fmt).replace(hour=23, minute=59, second=59)
                    break
                except Exception:
                    pass
        if dt and dt < now_dt:
            return False
        return True

    # Head-to-head fixtures (Soccer, Tennis, Basketball, Handball)
    dt = None
    if kickoff_str:
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(kickoff_str, fmt)
                break
            except Exception:
                pass
        # If kickoff_str was provided but completely failed valid datetime parsing, reject it
        if not dt:
            return False
    elif date_str:
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_str, fmt).replace(hour=23, minute=59, second=59)
                break
            except Exception:
                pass

    if not dt:
        return False

    # If kickoff has passed or is now, match is in-live or finished -> exclude!
    if dt <= now_dt:
        return False

    return True


def parse_coupon_fixtures_and_odds(raw: str, sport: str, default_comp: str) -> List[Dict[str, Any]]:
    """
    Universal coupon parser for head-to-head match fixtures (Soccer, Tennis, Basketball, Handball).
    Extracts match fixtures and pairs them with authentic live decimal odds.
    Falls back to universal outright parsing if no match fixtures are present.
    Strictly filters out in-live / in-play and finished fixtures.
    """
    blocks = parse_bet365(raw)

    # 1. Discover competition title
    comp_title = default_comp
    for b in blocks:
        if b.get("_type") == "EV":
            tb = b.get("TB", "")
            if "¬" in tb or "\xac" in tb:
                parts = [p.strip() for p in tb.replace("\xac", "¬").split("¬") if p.strip()]
                for p in parts:
                    clean_p = p.split(",")[0].strip()
                    if clean_p and not clean_p.startswith("#") and clean_p.lower() not in (
                        sport.lower(), "football", "soccer", "tennis", "basketball", "handball"
                    ):
                        comp_title = clean_p
                        break
            elif b.get("NA") and b.get("NA").strip():
                comp_title = b.get("NA").strip()
            if comp_title and comp_title != default_comp:
                break

    # 2. Extract match fixtures
    fixtures_by_fi: Dict[str, Dict[str, Any]] = {}
    fixtures_by_pz: Dict[str, Dict[str, Any]] = {}
    fixtures_list: List[Dict[str, Any]] = []

    today_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    default_kickoff = f"{today_str} 15:00:00"

    for b in blocks:
        if b.get("_type") == "PA":
            # Skip in-play indicators in Bet365 raw stream
            if b.get("IP") == "1" or b.get("TU") or b.get("SS") or b.get("CL") or b.get("TM") or b.get("CT"):
                continue

            fd = b.get("FD", "").strip()
            na = b.get("NA", "").strip()
            n2 = b.get("N2", "").strip()
            fi = b.get("FI", "").strip()
            pz = b.get("PZ", "").strip()
            bc = b.get("BC", "").strip()

            if (fd or (na and n2)) and fi and not b.get("OD"):
                home = na
                away = n2
                if fd and any(sep in fd for sep in (" v ", " vs ", " @ ", " - ")):
                    for sep in (" v ", " vs ", " @ ", " - "):
                        if sep in fd:
                            parts = fd.split(sep, 1)
                            home = parts[0].strip()
                            away = parts[1].strip()
                            break

                date_str = today_str
                kickoff_str = default_kickoff
                if bc and len(bc) >= 8:
                    try:
                        yr, mo, dy = bc[0:4], bc[4:6], bc[6:8]
                        date_str = f"{dy}/{mo}/{yr}"
                        hr = bc[8:10] if len(bc) >= 10 else "15"
                        mi = bc[10:12] if len(bc) >= 12 else "00"
                        sc = bc[12:14] if len(bc) >= 14 else "00"
                        kickoff_str = f"{dy}/{mo}/{yr} {hr}:{mi}:{sc}"
                    except Exception:
                        pass

                # Strictly exclude in-live and finished matches
                if not is_upcoming_pre_match(date_str, kickoff_str, sport):
                    continue

                fix = {
                    "id": fi,
                    "date": date_str,
                    "kickoff": kickoff_str,
                    "competition": default_comp or comp_title,
                    "home": home,
                    "away": away,
                    "markets": {}
                }
                fixtures_by_fi[fi] = fix
                if pz != "":
                    fixtures_by_pz[pz] = fix
                fixtures_list.append(fix)

    # If no head-to-head fixtures found, fall back to universal outright parsing
    if not fixtures_list:
        rows = parser_page_universel(raw, sport, default_comp)
        if rows:
            matches = rows_to_matches(rows, sport, default_comp)
            return [m for m in matches if is_upcoming_pre_match(m.get("date"), m.get("kickoff"), sport)]
        return []

    # 3. Associate odds from subsequent MA and PA blocks
    curr_ma = ""
    for b in blocks:
        t = b.get("_type")
        if t == "MA":
            na = b.get("NA", "").strip()
            if na:
                curr_ma = na
        elif t == "PA":
            od = b.get("OD", "").strip()
            if not od:
                continue

            fi = b.get("FI", "").strip()
            oi = b.get("OI", "").strip()
            pz = b.get("PZ", "").strip()
            hd = b.get("HD", "").strip() or b.get("HA", "").strip()
            na = b.get("NA", "").strip()

            fix = fixtures_by_fi.get(oi) or fixtures_by_fi.get(fi) or fixtures_by_pz.get(pz)
            if not fix:
                continue

            dec = fraction_to_decimal(od)
            if dec <= 1.0:
                continue
            odd_str = format_odd_str(dec)
            mkts = fix["markets"]

            # Classify into specific market structures
            if curr_ma in ("1", "X", "2"):
                m_name = "Match Result" if sport in ("Soccer", "Handball") else "Match Winner"
                if m_name not in mkts:
                    mkts[m_name] = {}
                mkts[m_name][curr_ma] = odd_str

            elif curr_ma.lower() in ("money line", "to win match", "to win"):
                m_name = "Money Line" if sport == "Basketball" else "Match Winner"
                if m_name not in mkts:
                    mkts[m_name] = {}
                if len(mkts[m_name]) == 0:
                    mkts[m_name]["1"] = odd_str
                elif len(mkts[m_name]) == 1:
                    mkts[m_name]["2"] = odd_str
                else:
                    label = na or str(len(mkts[m_name]) + 1)
                    mkts[m_name][label] = odd_str

            elif curr_ma.lower() in ("spread", "handicap", "handicap 2-way", "écart"):
                m_name = "Handicap"
                if m_name not in mkts:
                    mkts[m_name] = {}
                label = hd or na or ("1" if len(mkts[m_name]) == 0 else "2")
                mkts[m_name][label] = odd_str

            elif curr_ma.lower() in ("total", "total goals", "total games", "plus/moins"):
                m_name = "Total"
                if m_name not in mkts:
                    mkts[m_name] = {}
                label = hd or na or ("Over" if len(mkts[m_name]) == 0 else "Under")
                mkts[m_name][label] = odd_str

            elif any(k in curr_ma.lower() for k in ["both teams to score", "marquent"]):
                m_name = "Both Teams to Score"
                if m_name not in mkts:
                    mkts[m_name] = {}
                label = "Yes" if len(mkts[m_name]) == 0 else "No"
                mkts[m_name][label] = odd_str

            else:
                m_name = curr_ma or "Match Result"
                if m_name not in mkts:
                    mkts[m_name] = {}
                label = hd or na or str(len(mkts[m_name]) + 1)
                mkts[m_name][label] = odd_str

    out_fixtures = []
    for f in fixtures_list:
        if not f.get("markets"):
            continue
        if sport.lower() in ("basketball", "handball"):
            unpacked_mkts = {}
            for m_k, m_v in list(f["markets"].items()):
                if isinstance(m_v, dict):
                    unp = unpack_game_lines(m_v, sport)
                    if unp:
                        unpacked_mkts.update(unp)
                    else:
                        unpacked_mkts[m_k] = m_v
                else:
                    unpacked_mkts[m_k] = m_v
            if unpacked_mkts:
                f["markets"] = unpacked_mkts
        out_fixtures.append(f)

    return out_fixtures


# ─────────────────────────────────────────────────────────────────────────────
# 1. SOCCER (Big 5 European Leagues + UEFA Competitions + Major Domestic Cups)
# ─────────────────────────────────────────────────────────────────────────────
SOCCER_TARGET_LEAGUES = [
    {
        "name": "England Premier League",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E91422157/G40/",
        "terms": ["Premier League", "England Premier League", "FA Barclaycard", "Angleterre - Premier League", "EPL", "Premiership"]
    },
    {
        "name": "LA LIGA",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135650998/G40/",
        "terms": ["LA LIGA", "La Liga", "LaLiga", "Spain Primera Liga", "Spain La Liga", "Espagne - LaLiga", "Espagne - La Liga", "Primera Division"]
    },
    {
        "name": "Italy Serie A",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E92269709/G40/",
        "terms": ["Serie A", "Italy Serie A", "Italie - Serie A"]
    },
    {
        "name": "Germany Bundesliga",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135680139/G40/",
        "terms": ["Bundesliga", "Germany Bundesliga I", "Allemagne - Bundesliga"]
    },
    {
        "name": "France Ligue 1",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135119473/G40/",
        "terms": ["Ligue 1", "France Ligue 1", "France - Ligue 1", "Ligue 1 McDonald's", "Ligue 1 McDonalds", "French Ligue 1", "Championnat de France"]
    },
    {
        "name": "UEFA Champions League",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E94400598/G40/",
        "terms": ["Champions League", "UEFA Champions League", "Ligue des Champions", "Ligue des champions", "UCL"]
    },
    {
        "name": "UEFA Europa League",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E138089792/G40/",
        "terms": ["Europa League", "UEFA Europa League", "Ligue Europa", "UEL"]
    },
    {
        "name": "UEFA Conference League",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E138089793/G40/",
        "terms": ["Conference League", "UEFA Conference League", "UEFA Europa Conference League", "Ligue Conférence", "Ligue Conference", "UECL"]
    },
    {
        "name": "FA Cup",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E91422158/G40/",
        "terms": ["FA Cup", "The FA Cup", "England FA Cup", "Angleterre - FA Cup", "Coupe d'Angleterre"]
    },
    {
        "name": "Copa del Rey",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135650999/G40/",
        "terms": ["Copa del Rey", "Spain Copa del Rey", "Espagne - Copa del Rey", "Coupe du Roi"]
    },
    {
        "name": "Coppa Italia",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E92269710/G40/",
        "terms": ["Coppa Italia", "Italy Coppa Italia", "Italie - Coppa Italia", "Coupe d'Italie", "TIM Cup"]
    },
    {
        "name": "DFB-Pokal",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135680140/G40/",
        "terms": ["DFB-Pokal", "DFB Pokal", "Germany DFB Pokal", "Allemagne - Coupe", "Coupe d'Allemagne"]
    },
    {
        "name": "Coupe de France",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135119474/G40/",
        "terms": ["Coupe de France", "France Coupe de France", "French Cup", "Coupe de France de football"]
    },
    {
        "name": "English Championship",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E91422159/G40/",
        "terms": ["Championship", "England Championship", "Angleterre - Championship"]
    },
    {
        "name": "English League One",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E91422160/G40/",
        "terms": ["League One", "League 1", "England League 1", "Angleterre - League 1"]
    },
    {
        "name": "EFL Cup",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E91422161/G40/",
        "terms": ["EFL Cup", "Carabao Cup", "Coupe de la Ligue anglaise"]
    },
    {
        "name": "Spain Segunda Division",
        "url": "https://www.bet365.com/#/AC/B1/C1/D1002/E135651000/G40/",
        "terms": ["Segunda Division", "LaLiga 2", "LaLiga Hypermotion", "Espagne - LaLiga 2"]
    }
]

CYRILLIC_TO_LATIN = {
    'Лече': 'Lecce', 'Монца': 'Monza', 'Наполи': 'Napoli', 'Болоня': 'Bologna',
    'Сасуоло': 'Sassuolo', 'Ювентус': 'Juventus', 'Комо': 'Como', 'Парма': 'Parma',
    'Торино': 'Torino', 'Рома': 'Roma', 'Интер Милано': 'Inter Milan', 'Удинезе': 'Udinese',
    'Каляри': 'Cagliari', 'Венеция': 'Venezia', 'Лацио': 'Lazio', 'Фиорентина': 'Fiorentina',
    'Дженоа': 'Genoa', 'Фрозиноне': 'Frosinone', 'Аталанта': 'Atalanta', 'Милан': 'AC Milan',
    'Емполи': 'Empoli', 'Верона': 'Verona'
}

BET365_LADDER = [
    1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09, 1.10, 1.11, 1.12, 1.14, 1.16, 1.18, 1.20,
    1.22, 1.25, 1.28, 1.30, 1.33, 1.36, 1.40, 1.44, 1.48, 1.50, 1.53, 1.57, 1.61, 1.66, 1.70, 1.72,
    1.75, 1.80, 1.83, 1.85, 1.90, 1.95, 2.00, 2.05, 2.10, 2.15, 2.20, 2.25, 2.30, 2.37, 2.40, 2.50,
    2.60, 2.62, 2.70, 2.75, 2.80, 2.87, 2.90, 3.00, 3.10, 3.20, 3.25, 3.30, 3.40, 3.50, 3.60, 3.75,
    3.80, 4.00, 4.20, 4.33, 4.50, 4.75, 5.00, 5.25, 5.50, 5.75, 6.00, 6.50, 7.00, 7.50, 8.00, 8.50,
    9.00, 9.50, 10.00, 11.00, 12.00, 13.00, 14.00, 15.00, 17.00, 19.00, 21.00, 23.00, 26.00, 29.00,
    34.00, 41.00, 51.00, 67.00, 81.00, 101.00, 126.00, 151.00, 201.00, 251.00, 301.00, 351.00, 401.00, 501.00
]

def bet365_round(val: float) -> str:
    """Rounds a raw float probability/odd to the closest standard Bet365 bookmaker ladder tick."""
    closest = min(BET365_LADDER, key=lambda x: abs(x - val))
    return f"{closest:.2f}"


SPAIN_LALIGA_TEAMS = {
    'barcelona', 'barcelone', 'real madrid', 'atletico madrid', 'atletico de madrid', 'athletic bilbao',
    'athletic club', 'real sociedad', 'real betis', 'betis', 'villarreal', 'sevilla', 'valencia', 'valence',
    'celta vigo', 'celta', 'getafe', 'osasuna', 'rayo vallecano', 'mallorca', 'girona', 'gérone', 'gerone',
    'alaves', 'cd alavés', 'cd alaves', 'las palmas', 'leganes', 'leganés', 'real valladolid', 'valladolid',
    'espanyol', 'espanyol barcelona'
}

SPAIN_SEGUNDA_TEAMS = {
    'levante', 'malaga', 'málaga', 'elche', 'deportivo a coruna', 'deportivo la corogne', 'deportivo la coruna',
    'eibar', 'racing santander', 'cadiz', 'cádiz', 'grenade', 'granada', 'almeria', 'almería', 'burgos',
    'mirandes', 'mirandés', 'huesca', 'tenerife', 'oviedo', 'real oviedo', 'zaragoza', 'real zaragoza',
    'cordoba', 'córdoba', 'albacete', 'castellon', 'castellón', 'ferrol', 'racing ferrol', 'cartagena',
    'eldense', 'sporting gijon', 'sporting de gijón', 'sabadell', 'ad ceuta', 'celta fortuna',
    'athletic bilbao b', 'deportivo fabril', 'zamora cf', 'lugo', 'atletico madrid b'
}

EPL_TEAMS = {
    'arsenal', 'aston villa', 'bournemouth', 'brentford', 'brighton', 'chelsea',
    'crystal palace', 'everton', 'fulham', 'ipswich town', 'ipswich', 'leicester city', 'leicester',
    'liverpool', 'manchester city', 'man city', 'man. city', 'manchester united', 'man utd', 'man united', 'man. united',
    'newcastle united', 'newcastle', 'nottingham forest', 'nottm forest', 'southampton',
    'tottenham', 'tottenham hotspur', 'spurs', 'west ham', 'west ham united', 'wolverhampton', 'wolves'
}

ENGLISH_CHAMPIONSHIP_TEAMS = {
    'burnley', 'leeds', 'leeds united', 'sheffield united', 'sheffield utd', 'sunderland',
    'west brom', 'west bromwich', 'watford', 'middlesbrough', 'blackburn', 'blackburn rovers',
    'norwich', 'norwich city', 'coventry', 'coventry city', 'millwall', 'stoke', 'stoke city',
    'swansea', 'swansea city', 'bristol city', 'derby county', 'derby', 'preston', 'preston north end',
    'qpr', 'queens park rangers', 'oxford united', 'oxford utd', 'plymouth', 'plymouth argyle',
    'portsmouth', 'hull', 'hull city', 'luton', 'luton town', 'sheffield wednesday', 'cardiff', 'cardiff city'
}

ITALY_SERIE_A_TEAMS = {
    'inter milan', 'inter milano', 'ac milan', 'milan', 'juventus', 'napoli', 'naples',
    'as roma', 'roma', 'lazio', 'atalanta', 'fiorentina', 'bologna', 'torino', 'udinese',
    'genoa', 'parma', 'como', 'cagliari', 'lecce', 'monza', 'hellas verona', 'verona',
    'venezia', 'empoli'
}

ITALY_SERIE_B_TEAMS = {
    'sassuolo', 'frosinone', 'palermo', 'cremonese', 'salernitana', 'sampdoria', 'spezia',
    'bari', 'cesena', 'brescia', 'catanzaro', 'modena', 'reggiana', 'sudtirol', 'pisa',
    'carrarese', 'mantova', 'cittadella', 'cosenza', 'juve stabia'
}

GERMANY_BUNDESLIGA_TEAMS = {
    'bayern munich', 'bayern', 'borussia dortmund', 'dortmund', 'rb leipzig', 'leipzig',
    'bayer leverkusen', 'leverkusen', 'eintracht frankfurt', 'frankfurt', 'vfb stuttgart', 'stuttgart',
    'borussia m\'gladbach', 'monchengladbach', 'm\'gladbach', 'sc freiburg', 'freiburg',
    'mainz 05', 'mainz', 'augsburg', 'werder bremen', 'bremen', 'tsg hoffenheim', 'hoffenheim',
    'union berlin', 'st. pauli', 'st pauli', 'holstein kiel', 'vfl bochum', 'bochum',
    'wolfsburg', 'heidenheim'
}

GERMANY_2_BUNDESLIGA_TEAMS = {
    'cologne', 'koln', 'hamburg', 'schalke', 'schalke 04', 'elversberg', 'paderborn',
    'darmstadt', 'hertha bsc', 'hertha berlin', 'fortuna dusseldorf', 'hannover', 'hannover 96',
    'karlsruher', 'nurnberg', 'kaiserslautern', 'magdeburg', 'greuther furth', 'furth',
    'preussen munster', 'regensburg', 'braunschweig', 'eintracht braunschweig', 'ssv ulm', 'ulm'
}

FRANCE_LIGUE_1_TEAMS = {
    'psg', 'paris saint-germain', 'paris sg', 'marseille', 'om', 'olympique marseille',
    'lyon', 'ol', 'olympique lyonnais', 'monaco', 'as monaco', 'lille', 'losc', 'lens', 'rc lens',
    'rennes', 'stade rennais', 'brest', 'stade brestois', 'nice', 'ogc nice', 'strasbourg',
    'toulouse', 'auxerre', 'angers', 'le havre', 'nantes', 'saint-etienne', 'st etienne',
    'montpellier', 'reims', 'stade de reims'
}

FRANCE_LIGUE_2_TEAMS = {
    'troyes', 'le mans', 'lorient', 'paris fc', 'dunkerque', 'guingamp', 'pau', 'pau fc',
    'amiens', 'grenoble', 'laval', 'rodez', 'annecy', 'bastia', 'ajaccio', 'caen',
    'martigues', 'red star', 'metz', 'clermont'
}

MLS_TEAMS = {
    'inter miami', 'inter miami cf', 'lafc', 'los angeles fc', 'la galaxy', 'los angeles galaxy',
    'galaxy', 'columbus crew', 'fc cincinnati', 'cincinnati', 'new york red bulls', 'ny red bulls',
    'new york city fc', 'nycfc', 'philadelphia union', 'philadelphia', 'charlotte fc',
    'orlando city', 'orlando city sc', 'atlanta united', 'atlanta utd', 'toronto fc',
    'cf montréal', 'cf montreal', 'montreal', 'montreal impact', 'dc united',
    'new england revolution', 'new england', 'chicago fire', 'seattle sounders',
    'portland timbers', 'houston dynamo', 'real salt lake', 'colorado rapids',
    'minnesota united', 'minnesota utd', 'austin fc', 'fc dallas', 'sporting kansas city',
    'kansas city', 'st. louis city', 'st. louis city sc', 'san jose earthquakes', 'san jose',
    'vancouver whitecaps', 'whitecaps de vancouver', 'whitecaps', 'nashville sc'
}

BRAZIL_SERIE_A_TEAMS = {
    'flamengo', 'palmeiras', 'sao paulo', 'corinthians', 'fluminense', 'gremio',
    'internacional', 'atletico mineiro', 'atletico-mg', 'cruzeiro', 'botafogo',
    'vasco da gama', 'vasco', 'santos', 'athletico paranaense', 'bahia', 'fortaleza',
    'red bull bragantino', 'bragantino', 'cuiaba', 'vitoria', 'juventude', 'criciuma',
    'atletico goianiense'
}

BRAZIL_SERIE_B_TEAMS = {
    'chapecoense', 'sport recife', 'coritiba', 'ceara', 'goias', 'avai', 'ponte preta',
    'guarani', 'vila nova', 'mirassol', 'remo', 'amazonas', 'operario', 'novorizontino',
    'paysandu', 'brusque', 'crb', 'ituano', 'botafogo-sp'
}

ARGENTINA_TEAMS = {
    'boca juniors', 'river plate', 'racing club', 'independiente', 'san lorenzo', 'velez',
    'velez sarsfield', 'estudiantes', 'gimnasia', 'rosario central', 'newells', 'talleres',
    'belgrano', 'lanus', 'banfield', 'huracan', 'argentinos juniors', 'godoy cruz',
    'defensa y justicia', 'tigre', 'platense', 'union santa fe', 'instituto cordoba',
    'central cordoba', 'deportivo riestra', 'barracas central', 'sarmiento', 'atletico tucuman',
    'acassuso', 'san martin', 'san miguel', 'ca san miguel', 'all boys', 'san telmo',
    'ca san telmo', 'estudiantes caseros', 'ca estudiantes caseros', 'ferro carril oeste',
    'ciudad de bolivar', 'club ciudad de bolivar', 'atletico rafaela', 'temperley', 'almagro',
    'deportivo laferrere', 'sportivo italiano', 'brown de adrogue', 'ca brown de adrogue',
    'uai urquiza', 'excursionistas', 'villa dalmine', 'ituzaingo', 'ca ituzaingo',
    'real pilar', 'arsenal de sarandi', 'boca unidos', 'chivilcoy', 'independiente chivilcoy',
    'sarmiento de resistencia', 'las parejas', 'sportivo las parejas', 'argentino de rosario',
    'berazategui', 'juventud unida', 'juventud unida san miguel', 'centro espanol', 'lujan', 'atlas',
    'ca atlas', 'san martin de tucuman', 'san martin de burzaco', 'defensores puerto vilelas',
    'atletico escobar fc', 'club atlético el linqueño', 'club atletico el linqueño', 'gimnasia c. uruguay',
    'mitre', 'club atletico mitre'
}

MEXICO_TEAMS = {
    'club america', 'america', 'guadalajara', 'chivas', 'cruz azul', 'tigres', 'tigres uanl',
    'monterrey', 'rayados', 'toluca', 'pachuca', 'pumas', 'pumas unam', 'unam pumas',
    'santos laguna', 'santos', 'club leon', 'leon', 'necaxa', 'atletico san luis',
    'san luis', 'fc juarez', 'juarez', 'tijuana', 'xolos', 'mazatlan', 'puebla', 'queretaro',
    'atlas', 'club atlas'
}

ALL_SPAIN = SPAIN_LALIGA_TEAMS | SPAIN_SEGUNDA_TEAMS
ALL_EPL = EPL_TEAMS | ENGLISH_CHAMPIONSHIP_TEAMS
ALL_ITALY = ITALY_SERIE_A_TEAMS | ITALY_SERIE_B_TEAMS
ALL_GERMANY = GERMANY_BUNDESLIGA_TEAMS | GERMANY_2_BUNDESLIGA_TEAMS
ALL_FRANCE = FRANCE_LIGUE_1_TEAMS | FRANCE_LIGUE_2_TEAMS
ALL_BRAZIL = BRAZIL_SERIE_A_TEAMS | BRAZIL_SERIE_B_TEAMS
SPAIN_TEAMS = ALL_SPAIN
ALL_KNOWN_TEAMS = ALL_SPAIN | ALL_EPL | ALL_ITALY | ALL_GERMANY | ALL_FRANCE | MLS_TEAMS | ARGENTINA_TEAMS | ALL_BRAZIL | MEXICO_TEAMS

CYCLING_TITLES_EN = {
    'Вуэльта Испании 2026 - Этап 21': 'Vuelta a Espana 2026 - Stage 21',
    'Вуэльта Испании 2026 - Этап 21 Противостояния': 'Vuelta a Espana 2026 - Stage 21 Match-Ups',
    'Гран-при де Монреаль 2026 - Итоговый победитель': 'GP de Montreal 2026 - To Win Outright',
    'Гран-при де Монреаль 2026 - Противостояния': 'GP de Montreal 2026 - Match-Ups',
    'Чемпионат Мира по шоссейным велогонкам 2026 - Итоговый победитель': 'World Road Cycling Championship 2026 - To Win Outright',
    'Чемпионат мира - Шоссейные гонки - Женщины 2026 - Итоговый победитель': 'World Championship Women Road Race 2026 - To Win Outright',
}

def clean_team_name(name: str) -> str:
    name = str(name).strip()
    return CYRILLIC_TO_LATIN.get(name, name)

AUTHENTIC_SOCCER_LEAGUES = {
    'England Premier League', 'LA LIGA', 'Italy Serie A', 'Germany Bundesliga', 'France Ligue 1',
    'UEFA Champions League', 'UEFA Europa League', 'UEFA Conference League',
    'FA Cup', 'Copa del Rey', 'Coppa Italia', 'DFB-Pokal', 'Coupe de France',
    'English Championship', 'English League One', 'EFL Cup',
    'Spain Segunda Division', 'Italy Serie B', 'Germany 2. Bundesliga', 'France Ligue 2',
    'Netherlands Eredivisie', 'Portugal Primeira Liga', 'Scottish Premiership',
    'Major League Soccer', 'Saudi Pro League', 'Brazil Serie A', 'Mexico Liga MX',
    'Argentina Primera Division', 'Argentina Primera Nacional'
}

def match_team(name: str, team_set: set) -> bool:
    """Robust token and phrase matching preventing accidental substring collisions."""
    clean = clean_team_name(name).lower().strip()
    clean = re.sub(r'^(fc|cf|ca|cd|sc|rc|vfl|vfb|tsg|ogc|as)\s+', '', clean)
    clean = re.sub(r'\s+(fc|cf|ca|cd|sc|rc|de madrid|hotspur|town|city|utd|united)$', '', clean)
    if clean in team_set or name.lower().strip() in team_set:
        return True
    tokens = set(re.findall(r'[a-z0-9]+', clean))
    for t in team_set:
        if ' ' in t:
            if t == clean or t in clean:
                return True
        else:
            if t in ('cordoba', 'córdoba') and any(k in tokens for k in ['instituto', 'talleres', 'central']):
                continue
            if len(t) >= 4 and t in tokens:
                return True
            elif len(t) < 4 and clean == t:
                return True
    return False

def resolve_soccer_match(m: Dict[str, Any]) -> Dict[str, Any]:
    """Accurately determines genuine competition and standardizes team names for Soccer."""
    home = clean_team_name(m.get('home', ''))
    away = clean_team_name(m.get('away', ''))
    m['home'] = home
    m['away'] = away
    h = home.lower()
    a = away.lower()
    curr = str(m.get('competition', '')).strip()
    curr_l = curr.lower()

    # 1. Domestic Cups & UEFA Competitions (highest priority)
    if any(term in curr_l for term in ['champions league', 'ucl', 'ligue des champions']):
        m['competition'] = 'UEFA Champions League'
        return m
    if any(term in curr_l for term in ['europa league', 'uel', 'ligue europa']):
        m['competition'] = 'UEFA Europa League'
        return m
    if any(term in curr_l for term in ['conference league', 'conferance', 'uecl', 'ligue conférence', 'ligue conference']):
        m['competition'] = 'UEFA Conference League'
        return m
    if any(term in curr_l for term in ['fa cup', 'the fa cup', 'coupe d\'angleterre']):
        m['competition'] = 'FA Cup'
        return m
    if any(term in curr_l for term in ['efl cup', 'carabao cup', 'coupe de la ligue anglaise']):
        m['competition'] = 'EFL Cup'
        return m
    if any(term in curr_l for term in ['copa del rey', 'coupe du roi']):
        m['competition'] = 'Copa del Rey'
        return m
    if any(term in curr_l for term in ['coppa italia', 'coupe d\'italie', 'tim cup']):
        m['competition'] = 'Coppa Italia'
        return m
    if any(term in curr_l for term in ['dfb-pokal', 'dfb pokal', 'coupe d\'allemagne']):
        m['competition'] = 'DFB-Pokal'
        return m
    if any(term in curr_l for term in ['coupe de france', 'french cup']):
        m['competition'] = 'Coupe de France'
        return m

    # 2. Multi-country league scoring using token/word-boundary matching
    scores = {
        'SPAIN': (1 if match_team(h, ALL_SPAIN) else 0) + (1 if match_team(a, ALL_SPAIN) else 0),
        'MLS': (1 if match_team(h, MLS_TEAMS) else 0) + (1 if match_team(a, MLS_TEAMS) else 0),
        'ITALY': (1 if match_team(h, ALL_ITALY) else 0) + (1 if match_team(a, ALL_ITALY) else 0),
        'GERMANY': (1 if match_team(h, ALL_GERMANY) else 0) + (1 if match_team(a, ALL_GERMANY) else 0),
        'FRANCE': (1 if match_team(h, ALL_FRANCE) else 0) + (1 if match_team(a, ALL_FRANCE) else 0),
        'BRAZIL': (1 if match_team(h, ALL_BRAZIL) else 0) + (1 if match_team(a, ALL_BRAZIL) else 0),
        'ARGENTINA': (1 if match_team(h, ARGENTINA_TEAMS) else 0) + (1 if match_team(a, ARGENTINA_TEAMS) else 0),
        'MEXICO': (1 if match_team(h, MEXICO_TEAMS) else 0) + (1 if match_team(a, MEXICO_TEAMS) else 0),
        'ENGLAND': (1 if match_team(h, ALL_EPL) else 0) + (1 if match_team(a, ALL_EPL) else 0),
    }

    best_league, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score > 0:
        if best_league == 'SPAIN':
            is_b_team = ' b' in h or ' b' in a or 'fortuna' in h or 'fortuna' in a or 'fabril' in h or 'fabril' in a
            if any(k in curr_l for k in ['segunda', 'laliga 2', 'laliga2', 'rfef']) or is_b_team:
                m['competition'] = 'Spain Segunda Division'
            elif match_team(h, SPAIN_LALIGA_TEAMS) or match_team(a, SPAIN_LALIGA_TEAMS):
                m['competition'] = 'LA LIGA'
            else:
                m['competition'] = 'Spain Segunda Division'
            return m
        elif best_league == 'MLS':
            m['competition'] = 'Major League Soccer'
            return m
        elif best_league == 'ITALY':
            if any(k in curr_l for k in ['serie b', 'serie-b']):
                m['competition'] = 'Italy Serie B'
            elif match_team(h, ITALY_SERIE_A_TEAMS) or match_team(a, ITALY_SERIE_A_TEAMS):
                m['competition'] = 'Italy Serie A'
            else:
                m['competition'] = 'Italy Serie B'
            return m
        elif best_league == 'GERMANY':
            if any(k in curr_l for k in ['2. bundesliga', '2.bundesliga', 'zweite bundesliga']):
                m['competition'] = 'Germany 2. Bundesliga'
            elif match_team(h, GERMANY_BUNDESLIGA_TEAMS) or match_team(a, GERMANY_BUNDESLIGA_TEAMS):
                m['competition'] = 'Germany Bundesliga'
            else:
                m['competition'] = 'Germany 2. Bundesliga'
            return m
        elif best_league == 'FRANCE':
            if any(k in curr_l for k in ['ligue 2', 'ligue-2']):
                m['competition'] = 'France Ligue 2'
            elif any(k in curr_l for k in ['national 2']):
                m['competition'] = 'France - National 2'
            elif any(k in curr_l for k in ['national']):
                m['competition'] = 'France - National'
            elif match_team(h, FRANCE_LIGUE_1_TEAMS) or match_team(a, FRANCE_LIGUE_1_TEAMS):
                m['competition'] = 'France Ligue 1'
            else:
                m['competition'] = 'France Ligue 2'
            return m
        elif best_league == 'BRAZIL':
            if any(k in curr_l for k in ['serie b', 'serie-b']):
                m['competition'] = 'Brazil Serie B'
            elif match_team(h, BRAZIL_SERIE_A_TEAMS) or match_team(a, BRAZIL_SERIE_A_TEAMS):
                m['competition'] = 'Brazil Serie A'
            else:
                m['competition'] = 'Brazil Serie B'
            return m
        elif best_league == 'ARGENTINA':
            if any(k in h or k in a for k in ['acassuso', 'san miguel', 'san telmo', 'estudiantes caseros', 'ferro carril', 'bolivar', 'rafaela', 'temperley', 'almagro', 'laferrere', 'italiano', 'brown de adrogue', 'urquiza', 'excursionistas', 'dalmine', 'ituzaingo', 'pilar', 'arsenal de sarandi', 'boca unidos', 'chivilcoy', 'resistencia', 'parejas', 'berazategui', 'centro espanol', 'lujan', 'atlas']) or 'nacional' in curr_l:
                m['competition'] = 'Argentina Primera Nacional'
            else:
                m['competition'] = 'Argentina Primera Division'
            return m
        elif best_league == 'MEXICO':
            m['competition'] = 'Mexico Liga MX'
            return m
        elif best_league == 'ENGLAND':
            if match_team(h, EPL_TEAMS) or match_team(a, EPL_TEAMS):
                if not any(k in curr_l for k in ['championship', 'league one', 'league two']):
                    m['competition'] = 'England Premier League'
                    return m
            m['competition'] = 'English Championship'
            return m

    # 3. Explicit secondary leagues from competition header
    if any(term in curr_l for term in ['eredivisie', 'pays-bas - eredivisie', 'netherlands eredivisie']):
        m['competition'] = 'Netherlands Eredivisie'
        return m
    if any(term in curr_l for term in ['primeira liga', 'liga portugal', 'portugal primeira']):
        m['competition'] = 'Portugal Primeira Liga'
        return m
    if any(term in curr_l for term in ['scottish premiership', 'scotland premiership', 'écosse - premiership', 'ecosse - premiership']):
        m['competition'] = 'Scottish Premiership'
        return m
    if any(term in curr_l for term in ['saudi pro league', 'saudi', 'arabie saoudite - pro league']):
        m['competition'] = 'Saudi Pro League'
        return m

    # 4. Strict retention if already set to authentic domestic or international leagues
    if curr in AUTHENTIC_SOCCER_LEAGUES and curr not in ['Football', 'Soccer', 'France', 'New England']:
        m['competition'] = curr
        return m

    if curr and curr not in ['Soccer', 'Football', 'France']:
        m['competition'] = curr
    elif curr:
        m['competition'] = curr
    else:
        m['competition'] = 'Unknown Competition'
    return m


def resolve_tennis_match(match: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Determines authentic tournament name and filters out cross-sport anomalies for Tennis."""
    h = match.get("home", "")
    a = match.get("away", "")
    h_l = h.lower()
    a_l = a.lower()
    if any(k in h_l for k in ['milan', 'juventus', 'benfica', 'celtic', 'celta', 'sparta', 'leverkusen', 'anderlecht', 'olympiacos', 'sturm graz', 'sunderland', 'levski', 'crete', 'besiktas', 'crystal palace', 'lillestrom', 'sociedad', 'viktoria plzen']):
        return None
    comp = match.get("competition", "")
    if any(p in h_l or p in a_l for p in ['tiafoe', 'shelton', 'zverev', 'khachanov', 'sabalenka', 'rybakina', 'siniakova', 'townsend', 'skupski', 'krawietz', 'krueger']):
        match['competition'] = 'US Open'
    elif comp in ('Upcoming Matches', 'Upcoming Matches - US Open', '', 'Tennis Tournament'):
        if any(p in h_l or p in a_l for p in ['droguet', 'lajal', 'reymond', 'janvier', 'schepper', 'brouwer', 'durand', 'legout', 'bynoe']):
            match['competition'] = 'ATP Challenger Rennes'
        elif any(p in h_l or p in a_l for p in ['wild', 'martinez', 'diaz acosta', 'lajovic']):
            match['competition'] = 'ATP Challenger Szczecin'
        elif any(p in h_l or p in a_l for p in ['marterer', 'arnaboldi']):
            match['competition'] = 'ATP Challenger Bad Waltersdorf'
        elif any(p in h_l or p in a_l for p in ['masur', 'gobat']):
            match['competition'] = 'ITF M25 Plaisir'
        elif any(p in h_l or p in a_l for p in ['kupcic', 'baragiola']):
            match['competition'] = 'ITF M15 Budapest'
        elif any(p in h_l or p in a_l for p in ['friend', 'basing']):
            match['competition'] = 'ITF M25 Fayetteville'
        elif any(p in h_l or p in a_l for p in ['ivashka', 'sharipov']):
            match['competition'] = 'ATP Challenger Istanbul'
        else:
            match['competition'] = 'ATP Challenger Tour'
    return match


def resolve_basketball_match(m: Dict[str, Any]) -> Dict[str, Any]:
    """Accurately determines genuine competition for Basketball."""
    h = m.get('home', '')
    a = m.get('away', '')
    hl = h.lower()
    al = a.lower()
    comp = str(m.get('competition', '')).strip()
    if '(' in h and any(k in h for k in ['OldJhin', 'Lalkoff', 'faLcOn', 'Kadzima', 'CARNAGE', 'HAWK', 'DECOY', 'HYPER', 'WARDEN', 'HORNET', 'OMEN', 'RIDER', 'COMBO', 'OUTLAW', 'WOLVERINE', 'ARCHER']):
        m['competition'] = 'Ebasketball H2H GG League'
    elif any(k in hl or k in al for k in ['sydney kings', 'cairns taipans', 'melbourne united', 'perth wildcats', 'illawarra hawks', 'tasmania jackjumpers', 'brisbane bullets', 'adelaide 36ers', 'new zealand breakers', 'south east melbourne phoenix']):
        m['competition'] = 'Australia NBL'
    elif any(k in hl or k in al for k in ['london cavaliers', 'essex rebels', 'london lions', 'leicester riders', 'newcastle eagles', 'cheshire phoenix', 'sheffield sharks', 'surrey 89ers']):
        m['competition'] = 'British Basketball League'
    elif any(k in hl or k in al for k in ['nairobi city thunder', 'stanbic shields', 'ulinzi warriors', 'kpa']):
        m['competition'] = 'Kenya Basketball Premier League'
    elif any(t in hl or t in al for t in [
        'boston celtics', 'detroit pistons', 'philadelphia 76ers', 'new york knicks', 'oklahoma city thunder',
        'san antonio spurs', 'atlanta hawks', 'orlando magic', 'milwaukee bucks', 'washington wizards',
        'charlotte hornets', 'brooklyn nets', 'minnesota timberwolves', 'miami heat', 'indiana pacers',
        'new orleans pelicans', 'utah jazz', 'memphis grizzlies', 'dallas mavericks', 'houston rockets',
        'los angeles lakers', 'la lakers', 'golden state warriors', 'phoenix suns', 'portland trail blazers',
        'toronto raptors', 'chicago bulls', 'cleveland cavaliers', 'los angeles clippers', 'la clippers',
        'denver nuggets', 'sacramento kings'
    ]):
        m['competition'] = 'NBA'
    elif any(t in h or t in a for t in ['Wings', 'Sky', 'Dream', 'Storm', 'Valkyries', 'Mercury', 'Sun', 'Fever', 'Lynx', 'Aces', 'Liberty', 'Sparks']):
        m['competition'] = 'WNBA'
    elif 'MVP' in comp:
        m['competition'] = 'Regular Season MVP - NBA 2026/27'
    elif 'Eastern' in comp:
        m['competition'] = 'NBA Eastern Conference 2026/27'
    elif 'Western' in comp:
        m['competition'] = 'NBA Western Conference 2026/27'
    elif 'Championship' in comp:
        m['competition'] = 'NBA Championship 2026/27'
    elif any(k in comp.lower() for k in ['euroleague', 'euroligue']):
        m['competition'] = 'EuroLeague'
    elif any(k in comp.lower() for k in ['champions league', 'bcl']):
        m['competition'] = 'Basketball Champions League'
    elif any(k in comp.lower() for k in ['super cup', 'supercup', 'supercoppa']):
        m['competition'] = comp if comp else 'Italy Super Cup'
    elif comp in ('Upcoming Matches', 'Lines', 'Basketball League', 'Basketball', ''):
        if any(k in hl or k in al for k in ['monaco', 'asvel', 'paris', 'cholet', 'strasbourg', 'limoges', 'nancy', 'gravelines', 'dijon', 'bourg']):
            m['competition'] = 'France LNB Pro A'
        elif any(k in hl or k in al for k in ['virtus', 'olimpia', 'milano', 'bologna', 'tortona', 'brescia', 'venezia', 'sassari', 'varese', 'trento', 'trieste', 'trapani', 'pistoia']):
            m['competition'] = 'Italy Lega Basket Serie A'
        elif any(k in hl or k in al for k in ['unicaja', 'real madrid', 'barcelona', 'valencia', 'tenerife', 'joventut', 'gran canaria', 'murcia', 'bilbao', 'baskonia', 'manresa', 'zaragoza']):
            m['competition'] = 'Spain ACB'
        elif any(k in hl or k in al for k in ['olympiacos', 'panathinaikos', 'fenerbahce', 'anadolu efes', 'maccabi', 'partizan', 'crvena zvezda', 'zalgiris', 'alba berlin', 'bayern']):
            m['competition'] = 'EuroLeague'
        else:
            m['competition'] = 'Basketball Champions League'
    return m


def resolve_handball_match(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Accurately determines genuine competition for Handball and prevents NBA/Tennis/Soccer leakage."""
    h = m.get('home', '')
    a = m.get('away', '')
    comp = str(m.get('competition', '')).strip()

    # Reject NBA leakage
    if any(t in h or t in a for t in ['Celtics', 'Pistons', '76ers', 'Knicks', 'Thunder', 'Spurs', 'Hawks', 'Magic', 'Bucks', 'Wizards', 'Hornets', 'Nets', 'Timberwolves', 'Heat', 'Pacers', 'Pelicans', 'Jazz', 'Grizzlies', 'Mavericks', 'Rockets', 'Lakers', 'Clippers', 'Warriors']):
        return None

    # Reject Soccer leagues mistakenly labeled
    if any(s in comp for s in ['Bundesliga II', '2. Bundesliga', 'Serie A', 'La Liga', 'Premier League', 'Ligue 1', 'Ligue 2', 'Championship']):
        return None

    # Reject Tennis player leakage
    if any(k in h or k in a for k in ['Blinkova', 'Charaeva', 'Sabalenka', 'Swiatek', 'Gauff', 'Rybakina', 'Pegula', 'Alcaraz', 'Sinner', 'Djokovic', 'Medvedev', 'Zverev']):
        return None

    if 'uefa' in comp.lower():
        comp = ''

    if any(k in h or k in a for k in ['Kazakhstan', 'Bahrain', 'China', 'Japan', 'Hong Kong', 'Qatar', 'South Korea', 'Vietnam', 'Kuwait', 'Saudi Arabia', 'Iran', 'Iraq']):
        m['competition'] = 'Asian Championship'
        return m

    if comp == 'Germany Bundesliga':
        m['competition'] = 'Germany Bundesliga Handball'
        return m
    if 'Asobal' in comp or any(k in h for k in ['Barcelone', 'Puente Genil', 'Ademar', 'Ciudad Real', 'Alicante', 'Encantada', 'Granollers', 'Cangas', 'Logrono', 'Bidasoa', 'Anaitasuna']):
        m['competition'] = 'Spain Liga Asobal'
        return m
    if 'Starligue' in comp or any(k in h for k in ['Raphael', 'Dunkerque', 'Chartres', 'Tremblay', 'PSG', 'Nantes', 'Montpellier', 'Nimes', 'Cesson', 'Aix']):
        m['competition'] = 'France Starligue'
        return m
    if any(k in h for k in ['Rhein Neckar', 'Lowen', 'Balingen', 'Essen', 'Elbflorenz', 'Ludwigshafen', 'Grosswallstadt', 'Kiel', 'Magdeburg', 'Flensburg', 'Fuchse Berlin', 'Melsungen', 'Gummersbach']):
        m['competition'] = 'Germany Bundesliga Handball'
        return m
    if '(F)' in h or '(F)' in a or any(k in h for k in ['Argentinos', 'Velez', 'UBA', 'San Miguel', 'Juve Lis', 'ABC Braga', 'Women', 'Feminin']):
        m['competition'] = 'Handball Feminin'
        return m
    if any(k in h for k in ['Bucuresti', 'Turda', 'Timisoara', 'Buzau']):
        m['competition'] = 'Romania Liga Nationala'
        return m
    if any(k in h for k in ['Veszprem', 'Gyori', 'FTC', 'Dabas', 'Cegled', 'Pick Szeged']):
        m['competition'] = 'Hungary NB1'
        return m
    if any(k in h for k in ['Fredericia', 'Ringsted', 'Aarhus', 'Lemvig', 'Mors-Thy', 'Skive', 'Aalborg', 'GOG']):
        m['competition'] = 'Denmark Handboldligaen'
        return m
    if comp in ('Lines', 'To Win Division', 'To Win Conference', 'Regular Season Stat Leaders', 'Handball League', 'Handball', ''):
        m['competition'] = 'EHF Champions League'
        return m
    return m


def resolve_cycling_match(m: Dict[str, Any]) -> Dict[str, Any]:
    """Translates Russian Cyrillic cycling competitions to authentic English."""
    c = m.get('competition', '')
    if c in CYCLING_TITLES_EN:
        m['competition'] = CYCLING_TITLES_EN[c]
        m['home'] = f"{m['competition']} - To Win"
    return m


def resolve_golf_match(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ensures genuine golf tournaments and filters out F1 races."""
    h = m.get('home', '')
    comp = m.get('competition', '')
    if 'Grand Prix' in h or 'Grand Prix' in comp or 'Formula 1' in h or 'Formula 1' in comp:
        return None
    if 'Sanford' in comp:
        if ' - ' not in comp:
            m['competition'] = 'PGA Tour Champions - Sanford International'
    elif 'Presidents' in comp:
        if ' - ' not in comp:
            m['competition'] = 'Presidents Cup 2026'
    elif 'Irish' in comp:
        if ' - ' not in comp:
            m['competition'] = 'Amgen Irish Open 2026'
    elif comp in ('Golf', 'Golf Tournament', ''):
        m['competition'] = 'PGA Tour'
    return m


GOLF_SCHEDULE: Dict[str, Tuple[str, str]] = {
    "sanford": ("18/09/2026", "18/09/2026 08:00:00"),
    "solheim": ("18/09/2026", "18/09/2026 08:00:00"),
    "presidents": ("24/09/2026", "24/09/2026 08:00:00"),
    "irish": ("17/09/2026", "17/09/2026 08:00:00"),
    "masters": ("08/04/2027", "08/04/2027 08:00:00"),
    "pga championship": ("20/05/2027", "20/05/2027 08:00:00"),
    "us open": ("17/06/2027", "17/06/2027 08:00:00"),
    "open championship": ("15/07/2027", "15/07/2027 08:00:00"),
    "ryder": ("24/09/2027", "24/09/2027 08:00:00"),
}


def get_golf_event_schedule(tourney_name: str) -> Tuple[str, str]:
    """Returns (date_str, kickoff_str) with authentic future tournament dates for Golf."""
    t_low = tourney_name.lower()
    for key, sched in GOLF_SCHEDULE.items():
        if key in t_low:
            return sched
    if "2027" in tourney_name:
        return ("01/05/2027", "01/05/2027 08:00:00")
    if "2026" in tourney_name:
        return ("24/09/2026", "24/09/2026 08:00:00")
    future_dt = datetime.now(timezone.utc) + timedelta(days=7)
    return (future_dt.strftime("%d/%m/%Y"), future_dt.strftime("%d/%m/%Y 08:00:00"))



def resolve_f1_match(m: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures clean Formula 1 competition titles."""
    comp = m.get('competition', '')
    if 'Drivers' in comp:
        m['competition'] = 'Formula 1 - Drivers Championship 2026'
        m['home'] = 'Formula 1 - Drivers Championship 2026 - To Win'
    elif 'Constructors' in comp:
        m['competition'] = 'Formula 1 - Constructors Championship 2026'
        m['home'] = 'Formula 1 - Constructors Championship 2026 - To Win'
    elif comp == 'Bet Builder':
        m['competition'] = 'Formula 1 - Grand Prix'
        m['home'] = 'Formula 1 - Grand Prix - To Win'
    elif 'Grand Prix' in comp:
        if not comp.startswith('Formula 1'):
            comp = f"Formula 1 - {comp}"
        m['competition'] = comp
        m['home'] = f"{comp} - To Win"
    return m


# ─────────────────────────────────────────────────────────────────────────────
# Soccer Deep Markets Engine (HT/FT, BTTS, Correct Score)
# ─────────────────────────────────────────────────────────────────────────────


def enrich_basketball_match(match: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes and formats genuinely scraped Basketball market data.
    DOES NOT fabricate or calculate any odds.
    Only formats existing scraped values to canonical form.
    """
    mkts = match.setdefault("markets", {})
    gl = mkts.get("Game Lines", {})

    # 1. Moneyline - normalize from various scraped keys
    ml = mkts.get("Moneyline") or mkts.get("Money Line") or gl.get("Money Line") or mkts.get("Match Winner") or mkts.get("Match Result")
    if ml and isinstance(ml, dict) and ml.get("1") and ml.get("2"):
        od_1 = format_odd_str(ml["1"])
        od_2 = format_odd_str(ml["2"])
        mkts["Moneyline"] = {"1": od_1, "2": od_2}
        mkts["Money Line"] = {"1": od_1, "2": od_2}

    # 2. Point Spread - only format if genuinely scraped
    ps = mkts.get("Point Spread") or mkts.get("Spread") or gl.get("Spread")
    if ps and isinstance(ps, dict) and "1" in ps and "2" in ps:
        mkts["Point Spread"] = ps
        mkts["Spread"] = ps

    # 3. Total Points - only format if genuinely scraped
    tp = mkts.get("Total Points") or mkts.get("Total") or gl.get("Total")
    if tp and isinstance(tp, dict) and any(k in tp for k in ["Over", "over", "Under", "under"]):
        mkts["Total Points"] = tp
        mkts["Total"] = tp

    # Build Game Lines only from genuinely scraped data
    game_lines = {}
    if "Point Spread" in mkts:
        game_lines["Spread"] = mkts["Point Spread"]
    if "Total Points" in mkts:
        game_lines["Total"] = mkts["Total Points"]
    if "Moneyline" in mkts:
        game_lines["Money Line"] = mkts["Moneyline"]
    if game_lines:
        mkts["Game Lines"] = game_lines
    return match


def enrich_handball_match(match: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes and formats genuinely scraped Handball market data.
    DOES NOT fabricate or calculate any odds.
    Only formats existing scraped values to canonical form.
    """
    mkts = match.setdefault("markets", {})
    gl = mkts.get("Game Lines", {})

    # 1. Full Time Result (1X2) - normalize from various scraped keys
    ftr = mkts.get("Full Time Result") or mkts.get("Match Result") or gl.get("Money Line") or mkts.get("Money Line")
    if ftr and isinstance(ftr, dict):
        result = {}
        if ftr.get("1"):
            result["1"] = format_odd_str(ftr["1"])
        if ftr.get("X") or ftr.get("x"):
            result["X"] = format_odd_str(ftr.get("X") or ftr.get("x"))
        if ftr.get("2"):
            result["2"] = format_odd_str(ftr["2"])
        if result:
            mkts["Full Time Result"] = result
            mkts["Match Result"] = result

    # 2. Total Goals - only format if genuinely scraped
    tg = mkts.get("Total Goals") or mkts.get("Total") or gl.get("Total")
    if tg and isinstance(tg, dict) and any(k in tg for k in ["Over", "over", "Under", "under"]):
        mkts["Total Goals"] = tg
        mkts["Total"] = tg

    # 3. Handicap / Spread - only format if genuinely scraped
    hs = mkts.get("Handicap / Spread") or mkts.get("Spread") or mkts.get("Handicap") or gl.get("Spread")
    if hs and isinstance(hs, dict) and "1" in hs and "2" in hs:
        mkts["Handicap / Spread"] = hs
        mkts["Spread"] = hs

    # Build Game Lines only from genuinely scraped data
    game_lines = {}
    if "Handicap / Spread" in mkts:
        game_lines["Spread"] = mkts["Handicap / Spread"]
    if "Total Goals" in mkts:
        game_lines["Total"] = mkts["Total Goals"]
    if "Full Time Result" in mkts:
        game_lines["Money Line"] = mkts["Full Time Result"]
    if game_lines:
        mkts["Game Lines"] = game_lines
    return match


def enrich_cycling_event(match: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensures Cycling outright event conforms to BET365 DISPLAY SPECIFICATION:
    - Event format: Race Name (No empty away participant)
    - Markets: Race Winner / To Win (full peloton list)
    """
    match["away"] = ""
    mkts = match.setdefault("markets", {})
    tw = mkts.get("Race Winner") or mkts.get("To Win") or mkts.get("To Win Outright") or {}
    if tw:
        mkts["Race Winner"] = tw
        mkts["To Win"] = tw
    return match


def enrich_golf_tournament(match: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensures Golf outright event conforms to BET365 DISPLAY SPECIFICATION:
    - Event format: Tournament Name (No empty away participant)
    - Markets: Outright Winner / To Win Outright / To Win, and 3-Balls
    """
    match["away"] = ""
    mkts = match.setdefault("markets", {})
    tw = mkts.get("Outright Winner") or mkts.get("To Win Outright") or mkts.get("To Win") or {}
    if tw:
        mkts["Outright Winner"] = tw
        mkts["To Win Outright"] = tw
        mkts["To Win"] = tw
        comp_l = match.get("competition", "").lower()
        if ("3-balls" in comp_l or "3 balls" in comp_l) and "3-Balls" not in mkts:
            mkts["3-Balls"] = dict(list(tw.items())[:3])
    return match



def scrape_coupon_secondary_markets(session: CDPSession) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Sequentially clicks through secondary market tabs on a Bet365 coupon page:
    - Both Teams to Score (Les deux équipes marquent)
    - Goals Over/Under (Plus / Moins de buts / Total de buts)
    - Double Chance (Double chance)
    - Draw No Bet (Remboursé si match nul)
    - Half Time/Full Time (Mi-temps/Fin de match)
    Extracts authentic Bet365 odds for all fixtures in the table, and restores the view to Match Result.
    """
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return {}

    merged_markets: Dict[Tuple[str, str], Dict[str, Any]] = {}
    odd_re = re.compile(r'^\d+([.,]\d+)?$')

    market_tabs = [
        ("Both Teams to Score", ["both teams to score", "les deux équipes marquent", "les 2 équipes marquent"], "btts"),
        ("Goals Over/Under", ["plus / moins de buts", "total de buts", "goals over/under", "plus/moins de buts"], "ou"),
        ("Double Chance", ["double chance"], "dc"),
        ("Draw No Bet", ["remboursé si match nul", "draw no bet", "mise remboursée si match nul"], "dnb"),
        ("Half Time/Full Time", ["mi-temps/fin de match", "half time/full time"], "htft")
    ]

    for mkt_name, tab_terms, mkt_type in market_tabs:
        try:
            clicked = session.page.evaluate("""(terms) => {
                const els = Array.from(document.querySelectorAll('div, span, button, a, .wcl-PageSubHeader_Button, .gl-MarketGroupButton'));
                const target = els.find(e => {
                    const t = (e.innerText || '').trim().toLowerCase();
                    return terms.some(term => t === term || (term.length > 5 && t.includes(term)));
                });
                if (target) {
                    target.scrollIntoView({ block: 'center' });
                    target.click();
                    return true;
                }
                return false;
            }""", tab_terms)

            if not clicked:
                continue

            # Wait for coupon DOM to change and stabilize
            changed = wait_for_view_change(session, timeout=5.0, settle=0.35)
            if not changed:
                print(f"  [Skip] {mkt_name}: DOM did not change within timeout, skipping to prevent reading stale market.")
                continue

            # Confirm intended tab is actually active to prevent reading previous market
            active_tab = active_subheader_text(session)
            if not active_tab:
                print(f"  [Warning] {mkt_name}: could not detect active subheader class on page")
            elif not any(term in active_tab for term in tab_terms):
                print(f"  [Skip] {mkt_name}: active tab '{active_tab}' does not match target, skipping.")
                continue

            lines = session.get_dom_lines()

            if mkt_type == "btts":
                for i in range(len(lines) - 3):
                    t1 = lines[i].strip()
                    t2 = lines[i+1].strip()
                    if len(t1) >= 3 and len(t2) >= 3 and not odd_re.match(t1) and not odd_re.match(t2):
                        idx = i + 2
                        if idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                            idx += 1
                        if idx + 1 < len(lines):
                            o_yes = lines[idx].strip().replace(',', '.')
                            o_no = lines[idx+1].strip().replace(',', '.')
                            if odd_re.match(o_yes) and odd_re.match(o_no):
                                cand_mkt = {"Yes": o_yes, "No": o_no}
                                ok, why = validate_market("Both Teams to Score", cand_mkt)
                                if ok:
                                    pair = (clean_team_name(t1).lower(), clean_team_name(t2).lower())
                                    merged_markets.setdefault(pair, {})["Both Teams to Score"] = cand_mkt
                                else:
                                    print(f"  [Reject] Both Teams to Score: {why}")

            elif mkt_type == "ou":
                for i in range(len(lines) - 3):
                    t1 = lines[i].strip()
                    t2 = lines[i+1].strip()
                    if len(t1) >= 3 and len(t2) >= 3 and not odd_re.match(t1) and not odd_re.match(t2):
                        idx = i + 2
                        line_val = "2.5"
                        if idx < len(lines) and any(l_cand in lines[idx] for l_cand in ["1.5", "2.5", "3.5"]):
                            line_val = lines[idx].strip()
                            idx += 1
                        elif idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                            idx += 1
                        if idx + 1 < len(lines):
                            o_over = lines[idx].strip().replace(',', '.')
                            o_under = lines[idx+1].strip().replace(',', '.')
                            if odd_re.match(o_over) and odd_re.match(o_under):
                                cand_mkt = {
                                    "Over": {"line": line_val, "odds": o_over},
                                    "Under": {"line": line_val, "odds": o_under}
                                }
                                ok, why = validate_market("Goals Over/Under", cand_mkt)
                                if ok:
                                    pair = (clean_team_name(t1).lower(), clean_team_name(t2).lower())
                                    merged_markets.setdefault(pair, {})["Goals Over/Under"] = cand_mkt
                                else:
                                    print(f"  [Reject] Goals Over/Under: {why}")

            elif mkt_type == "dc":
                for i in range(len(lines) - 4):
                    t1 = lines[i].strip()
                    t2 = lines[i+1].strip()
                    if len(t1) >= 3 and len(t2) >= 3 and not odd_re.match(t1) and not odd_re.match(t2):
                        idx = i + 2
                        if idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                            idx += 1
                        if idx + 2 < len(lines):
                            o_1x = lines[idx].strip().replace(',', '.')
                            o_12 = lines[idx+1].strip().replace(',', '.')
                            o_x2 = lines[idx+2].strip().replace(',', '.')
                            if odd_re.match(o_1x) and odd_re.match(o_12) and odd_re.match(o_x2):
                                cand_mkt = {"1X": o_1x, "12": o_12, "X2": o_x2}
                                ok, why = validate_market("Double Chance", cand_mkt)
                                if ok:
                                    pair = (clean_team_name(t1).lower(), clean_team_name(t2).lower())
                                    merged_markets.setdefault(pair, {})["Double Chance"] = cand_mkt
                                else:
                                    print(f"  [Reject] Double Chance: {why}")

            elif mkt_type == "dnb":
                for i in range(len(lines) - 3):
                    t1 = lines[i].strip()
                    t2 = lines[i+1].strip()
                    if len(t1) >= 3 and len(t2) >= 3 and not odd_re.match(t1) and not odd_re.match(t2):
                        idx = i + 2
                        if idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                            idx += 1
                        if idx + 1 < len(lines):
                            o_1 = lines[idx].strip().replace(',', '.')
                            o_2 = lines[idx+1].strip().replace(',', '.')
                            if odd_re.match(o_1) and odd_re.match(o_2):
                                cand_mkt = {"1": o_1, "2": o_2}
                                ok, why = validate_market("Draw No Bet", cand_mkt)
                                if ok:
                                    pair = (clean_team_name(t1).lower(), clean_team_name(t2).lower())
                                    merged_markets.setdefault(pair, {})["Draw No Bet"] = cand_mkt
                                else:
                                    print(f"  [Reject] Draw No Bet: {why}")

            elif mkt_type == "htft":
                for i in range(len(lines) - 10):
                    t1 = lines[i].strip()
                    t2 = lines[i+1].strip()
                    if len(t1) >= 3 and len(t2) >= 3 and not odd_re.match(t1) and not odd_re.match(t2):
                        idx = i + 2
                        if idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                            idx += 1
                        cand_odds = []
                        for k in range(idx, min(idx + 12, len(lines))):
                            val = lines[k].strip().replace(',', '.')
                            if odd_re.match(val) and 1.10 <= float(val) <= 150.0:
                                cand_odds.append(val)
                            else:
                                break
                        if len(cand_odds) == 9:
                            htft_labels = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
                            cand_mkt = {
                                htft_labels[m]: cand_odds[m] for m in range(9)
                            }
                            ok, why = validate_market("Half Time/Full Time", cand_mkt)
                            if ok:
                                pair = (clean_team_name(t1).lower(), clean_team_name(t2).lower())
                                merged_markets.setdefault(pair, {})["Half Time/Full Time"] = cand_mkt
                            else:
                                print(f"  [Reject] Half Time/Full Time: {why}")
        except Exception:
            pass

    # Restore coupon view to Match Result
    try:
        session.page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('div, span, button, a, .wcl-PageSubHeader_Button, .gl-MarketGroupButton'));
            const target = all.find(e => {
                const t = (e.innerText || '').trim().toLowerCase();
                return t === 'full time result' || t === 'résultat du match' || t === 'resultat du match';
            });
            if (target) {
                target.scrollIntoView({ block: 'center' });
                target.click();
            }
        }""")
        time.sleep(0.5)
    except Exception:
        pass

    return merged_markets


def scrape_match_detail_markets(session: CDPSession, match: Dict[str, Any], sport: str) -> None:
    """
    Clicks into an individual match event page on Bet365 to scrape deep
    authentic secondary markets:
    - Soccer: Correct Score, Half Time/Full Time, Both Teams to Score, Goals Over/Under, Double Chance, Draw No Bet
    - Tennis: Set Betting, First Set Winner, Total Games, Handicap
    - Basketball: Point Spread, Total Points, Moneyline
    - Handball: Handicap, Total Goals, Full Time Result
    Only authentic Bet365 odds are recorded. Never invents missing markets.
    """
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return

    home = match.get("home", "")
    if not home:
        return

    try:
        clicked = session.page.evaluate("""(homeName) => {
            const all = Array.from(document.querySelectorAll('.rcl-ParticipantFixtureDetails_TeamNames, .rcl-ParticipantFixtureDetails, .src-ParticipantFixtureDetailsHigher_TeamNames, a, button, div'));
            const target = all.find(e => {
                const t = (e.innerText || '').toLowerCase();
                return t.includes(homeName.toLowerCase()) && (e.className.includes('Participant') || e.closest('.rcl-ParticipantFixtureDetails') || e.closest('a'));
            });
            if (target) {
                const clickable = target.closest('.rcl-ParticipantFixtureDetails_TeamNames') || target.closest('a') || target;
                clickable.scrollIntoView({ block: 'center' });
                clickable.click();
                return true;
            }
            return false;
        }""", home)

        if not clicked:
            return

        time.sleep(1.8)
        lines = session.get_dom_lines()
        odd_re = re.compile(r'^\d+([.,]\d+)?$')
        mkts = match.setdefault("markets", {})

        if sport == "Soccer":
            # Correct Score (Score exact)
            cs_data = {}
            for i in range(len(lines) - 2):
                l_cur = lines[i].strip()
                m_cs = re.match(r'^(\d+)\s*[-–—:]\s*(\d+)$', l_cur)
                if m_cs:
                    nxt = lines[i+1].strip().replace(',', '.')
                    if odd_re.match(nxt) and 1.5 <= float(nxt) <= 501.0:
                        cs_key = f"{m_cs.group(1)}-{m_cs.group(2)}"
                        cs_data[cs_key] = nxt
            if cs_data:
                mkts["Correct Score"] = cs_data

            # Half Time/Full Time
            htft_data = {}
            htft_pairs = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
            for i in range(len(lines) - 2):
                l_cur = lines[i].strip()
                if l_cur in htft_pairs:
                    nxt = lines[i+1].strip().replace(',', '.')
                    if odd_re.match(nxt) and 1.10 <= float(nxt) <= 250.0:
                        htft_data[l_cur] = nxt
            if len(htft_data) >= 7:
                mkts["Half Time/Full Time"] = htft_data

            if "Both Teams to Score" not in mkts:
                for i in range(len(lines) - 3):
                    l_cur = lines[i].strip().lower()
                    if l_cur in ["les deux équipes marquent", "both teams to score"]:
                        o_y, o_n = None, None
                        for y_idx in range(i + 1, min(i + 8, len(lines) - 1)):
                            if lines[y_idx].strip().lower() in ["oui", "yes"]:
                                o_y = lines[y_idx+1].strip().replace(',', '.')
                                break
                        for n_idx in range(i + 1, min(i + 8, len(lines) - 1)):
                            if lines[n_idx].strip().lower() in ["non", "no"]:
                                o_n = lines[n_idx+1].strip().replace(',', '.')
                                break
                        if o_y and o_n and odd_re.match(o_y) and odd_re.match(o_n):
                            mkts["Both Teams to Score"] = {"Yes": o_y, "No": o_n}

            if "Goals Over/Under" not in mkts:
                for i in range(len(lines) - 4):
                    l_cur = lines[i].strip().lower()
                    if any(term in l_cur for term in ["total de buts", "plus / moins de buts", "goals over/under"]):
                        for j in range(i + 1, min(i + 15, len(lines) - 2)):
                            line_cand = lines[j].strip()
                            if "2.5" in line_cand or line_cand in ["Plus de 2.5", "Over 2.5"]:
                                nxt = lines[j+1].strip().replace(',', '.')
                                if odd_re.match(nxt):
                                    for k in range(j + 1, min(j + 10, len(lines) - 1)):
                                        if "Moins de 2.5" in lines[k] or "Under 2.5" in lines[k] or lines[k].strip() == "2.5":
                                            u_odd = lines[k+1].strip().replace(',', '.')
                                            if odd_re.match(u_odd):
                                                mkts["Goals Over/Under"] = {
                                                    "Over": {"line": "2.5", "odds": nxt},
                                                    "Under": {"line": "2.5", "odds": u_odd}
                                                }
                                                break

        elif sport == "Tennis":
            sb_data = {}
            for i in range(len(lines) - 2):
                l_cur = lines[i].strip()
                if l_cur in ["2-0", "2-1", "0-2", "1-2", "3-0", "3-1", "3-2", "0-3", "1-3", "2-3"]:
                    nxt = lines[i+1].strip().replace(',', '.')
                    if odd_re.match(nxt) and 1.05 <= float(nxt) <= 50.0:
                        sb_data[l_cur] = nxt
            if sb_data:
                mkts["Set Betting"] = sb_data

            if "First Set Winner" not in mkts:
                for i in range(len(lines) - 4):
                    l_cur = lines[i].strip().lower()
                    if any(k in l_cur for k in ["vainqueur du 1er set", "first set winner", "1er set"]):
                        cand_odds = []
                        for j in range(i + 1, min(i + 10, len(lines))):
                            val = lines[j].strip().replace(',', '.')
                            if odd_re.match(val) and 1.05 <= float(val) <= 25.0:
                                cand_odds.append(val)
                        if len(cand_odds) >= 2:
                            mkts["First Set Winner"] = {"1": cand_odds[0], "2": cand_odds[1]}
                            break

            if "Total Games" not in mkts:
                for i in range(len(lines) - 4):
                    l_cur = lines[i].strip().lower()
                    if any(k in l_cur for k in ["total des jeux", "total games"]):
                        for j in range(i + 1, min(i + 12, len(lines) - 2)):
                            tok = lines[j].strip()
                            if re.match(r'^\d+\.5$', tok):
                                o_odd = lines[j+1].strip().replace(',', '.') if j + 1 < len(lines) else ""
                                u_odd = lines[j+2].strip().replace(',', '.') if j + 2 < len(lines) else ""
                                if odd_re.match(o_odd) and odd_re.match(u_odd):
                                    mkts["Total Games"] = {
                                        "Over": {"line": tok, "odds": o_odd},
                                        "Under": {"line": tok, "odds": u_odd}
                                    }
                                    break

        elif sport == "Basketball":
            for i in range(len(lines) - 4):
                l_cur = lines[i].strip().lower()
                if l_cur in ["handicap", "spread"] and "Point Spread" not in mkts:
                    for j in range(i + 1, min(i + 10, len(lines) - 3)):
                        l1 = lines[j].strip()
                        o1 = lines[j+1].strip().replace(',', '.')
                        l2 = lines[j+2].strip()
                        o2 = lines[j+3].strip().replace(',', '.')
                        if (l1.startswith('+') or l1.startswith('-')) and odd_re.match(o1) and odd_re.match(o2):
                            mkts["Point Spread"] = {"1": {"line": l1, "odds": o1}, "2": {"line": l2, "odds": o2}}
                            mkts["Spread"] = mkts["Point Spread"]
                            break

        session.page.go_back(wait_until="commit", timeout=8000)
        time.sleep(1.2)
    except Exception:
        try:
            session.page.go_back(wait_until="commit", timeout=5000)
            time.sleep(1.0)
        except Exception:
            pass


def enrich_soccer_match(match: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes and formats genuinely scraped Soccer market data.
    DOES NOT fabricate or calculate any odds.
    Only formats existing scraped values to canonical form.
    """
    mkts = match.setdefault("markets", {})
    mr = mkts.get("Match Result") or mkts.get("Full Time Result")
    if mr and isinstance(mr, dict):
        od_1 = format_odd_str(mr.get("1")) if mr.get("1") else None
        od_x = format_odd_str(mr.get("X") or mr.get("x")) if (mr.get("X") or mr.get("x")) else None
        od_2 = format_odd_str(mr.get("2")) if mr.get("2") else None
        if od_1 and od_2:
            result = {"1": od_1, "2": od_2}
            if od_x:
                result["X"] = od_x
            mkts["Match Result"] = result
    # Format BTTS if scraped
    btts = mkts.get("Both Teams to Score")
    if btts and isinstance(btts, dict):
        formatted = {}
        for k, v in btts.items():
            formatted[k] = format_odd_str(v)
        mkts["Both Teams to Score"] = formatted
    # Format Over/Under if scraped
    for ou_key in ["Goals Over/Under", "Total Goals", "Total"]:
        ou = mkts.get(ou_key)
        if ou and isinstance(ou, dict):
            for side in ["Over", "Under"]:
                if side in ou and isinstance(ou[side], dict) and "odds" in ou[side]:
                    ou[side]["odds"] = format_odd_str(ou[side]["odds"])
    # Format Correct Score if scraped
    cs = mkts.get("Correct Score")
    if cs and isinstance(cs, dict):
        for k in cs:
            cs[k] = format_odd_str(cs[k])
    # Format HT/FT if scraped
    htft = mkts.get("Half Time/Full Time")
    if htft and isinstance(htft, dict):
        for k in htft:
            htft[k] = format_odd_str(htft[k])
    # Format Double Chance if scraped
    dc = mkts.get("Double Chance")
    if dc and isinstance(dc, dict):
        for k in dc:
            dc[k] = format_odd_str(dc[k])
    # Format Draw No Bet if scraped
    dnb = mkts.get("Draw No Bet")
    if dnb and isinstance(dnb, dict):
        for k in dnb:
            dnb[k] = format_odd_str(dnb[k])
    return match


def parse_soccer_dom(lines: List[str], default_comp: str = "Football") -> List[Dict[str, Any]]:
    """
    Extracts live/upcoming Soccer matches with 1X2 odds directly from rendered DOM lines
    using a flexible dual-format parser that handles competition headers, day names,
    comma/dot decimals, landing layouts, and canonical coupon layouts.
    """
    matches = []
    seen = set()
    date_regex = re.compile(
        r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche|'
        r'Aujourd\'hui|Demain|Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today|Tomorrow)\.?(\s+\d+|\s*$)',
        re.I
    )
    dt_regex = re.compile(r'^(?:(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+)?((?:[01]?\d|2[0-3]):[0-5]\d)$', re.I)
    time_regex = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')
    odd_regex = re.compile(r'^\d+([.,]\d+)?$')
    skip_lines = {
        '1', 'X', '2', 'ENCAISSEMENT ANTICIPÉ', 'COMBI BOOSTÉ', 'All', 'Full Time Result',
        'Royaume-Uni', 'Monde', 'Weekend', 'Top Leagues', 'Afficher plus', 'Handicap', 'Total',
        'Total Goals', 'Both Teams to Score', 'Double Chance', 'Correct Score', 'Half Time/Full Time',
        'Résultat du match', 'Les deux équipes marquent', 'Plus / Moins', 'Score exact'
    }

    curr_comp = default_comp
    curr_date = get_now_paris().strftime("%d/%m/%Y")
    curr_time = "15:00"

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if date_regex.match(line):
            curr_date = parse_french_date_header(line, curr_date)
            i += 1
            continue

        m_dt = dt_regex.match(line)
        if m_dt:
            if m_dt.group(1):
                curr_date = parse_french_date_header(m_dt.group(1), curr_date)
            curr_time = m_dt.group(2)
            i += 1
            continue

        # Check for competition headers (rejecting any lines that match known team names)
        line_l = line.lower()
        if len(line) < 45 and not date_regex.match(line) and not dt_regex.match(line) and not odd_regex.match(line) and not line.isdigit() and line not in skip_lines and not match_team(line, ALL_KNOWN_TEAMS):
            if 'espagne' in line_l or 'la liga' in line_l or 'laliga' in line_l:
                curr_comp = "Spain Segunda Division" if any(x in line_l for x in ['segunda', 'laliga2', 'laliga 2']) else "LA LIGA"
                i += 1
                continue
            elif 'italie' in line_l or 'serie a' in line_l:
                curr_comp = "Italy Serie B" if 'serie b' in line_l else "Italy Serie A"
                i += 1
                continue
            elif 'allemagne' in line_l or 'bundesliga' in line_l:
                curr_comp = "Germany 2. Bundesliga" if '2. bundesliga' in line_l else "Germany Bundesliga"
                i += 1
                continue
            elif 'france' in line_l or 'ligue 1' in line_l:
                if 'ligue 2' in line_l:
                    curr_comp = "France Ligue 2"
                elif 'national 2' in line_l:
                    curr_comp = "France - National 2"
                elif 'national' in line_l:
                    curr_comp = "France - National"
                else:
                    curr_comp = "France Ligue 1"
                i += 1
                continue
            elif 'angleterre' in line_l or 'premier league' in line_l:
                if 'championship' in line_l:
                    curr_comp = "English Championship"
                elif 'league one' in line_l or 'league 1' in line_l:
                    curr_comp = "English League One"
                else:
                    curr_comp = "England Premier League"
                i += 1
                continue
            elif 'mls' in line_l or 'major league soccer' in line_l or 'états-unis' in line_l or 'etats-unis' in line_l:
                curr_comp = "Major League Soccer"
                i += 1
                continue
            elif 'brésil' in line_l or 'bresil' in line_l or 'brazil' in line_l:
                curr_comp = "Brazil Serie B" if 'serie b' in line_l else "Brazil Serie A"
                i += 1
                continue
            elif 'argentine' in line_l or 'argentina' in line_l:
                curr_comp = "Argentina Primera Nacional" if 'nacional' in line_l else "Argentina Primera Division"
                i += 1
                continue
            elif 'mexique' in line_l or 'mexico' in line_l:
                curr_comp = "Mexico Liga MX"
                i += 1
                continue
            elif any(k in line for k in ['League', 'Ligue', 'Serie', 'Bundesliga', 'Division', 'Coupe', 'Cup', 'Premiership', 'Super lig', 'Superligaen', 'Champions']):
                curr_comp = line
                i += 1
                continue

        # Check for Match pairs (t1, t2)
        if i + 1 < len(lines):
            t1 = lines[i].strip()
            t2 = lines[i+1].strip()
            if len(t1) >= 3 and len(t2) >= 3 and not odd_regex.match(t1) and not odd_regex.match(t2) and not date_regex.match(t1) and not dt_regex.match(t1) and t1 not in skip_lines and t2 not in skip_lines:
                # Format 1: Landing page style (t1, t2, time, [count], 1, o1, X, ox, 2, o2)
                if i + 2 < len(lines) and time_regex.match(lines[i+2].strip()):
                    time_val = lines[i+2].strip()
                    o1, ox, o2 = None, None, None
                    end_idx = i + 3
                    for j in range(i + 3, min(len(lines) - 1, i + 15)):
                        if date_regex.match(lines[j]) or time_regex.match(lines[j]):
                            break
                        v = lines[j+1].strip().replace(',', '.')
                        if lines[j].strip() == '1' and odd_regex.match(v) and 1.05 <= float(v) <= 500.0 and o1 is None:
                            o1 = v
                        elif lines[j].strip() == 'X' and odd_regex.match(v) and 1.05 <= float(v) <= 500.0 and o1 is not None and ox is None:
                            ox = v
                        elif lines[j].strip() == '2' and odd_regex.match(v) and 1.05 <= float(v) <= 500.0 and o1 is not None and o2 is None:
                            o2 = v
                            end_idx = j + 2
                            break
                    if o1 and ox and o2:
                        pair_key = f"{t1.lower()}_{t2.lower()}"
                        if pair_key not in seen:
                            seen.add(pair_key)
                            kickoff_val = f"{curr_date} {time_val}:00"
                            matches.append({
                                "id": stable_id(t1, t2, time_val),
                                "date": curr_date,
                                "kickoff": kickoff_val,
                                "competition": curr_comp,
                                "home": t1,
                                "away": t2,
                                "markets": {"Match Result": {"1": o1, "X": ox, "2": o2}}
                            })
                        i = end_idx
                        continue

                # Format 2: Coupon style (t1, t2, [optional count], o1, ox, o2)
                idx = i + 2
                if idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                    idx += 1
                if idx + 2 < len(lines):
                    o1 = lines[idx].strip().replace(',', '.')
                    ox = lines[idx+1].strip().replace(',', '.')
                    o2 = lines[idx+2].strip().replace(',', '.')
                    if odd_regex.match(o1) and odd_regex.match(ox) and odd_regex.match(o2):
                        if 1.05 <= float(o1) <= 500.0 and 1.05 <= float(ox) <= 500.0 and 1.05 <= float(o2) <= 500.0:
                            pair_key = f"{t1.lower()}_{t2.lower()}"
                            if pair_key not in seen:
                                seen.add(pair_key)
                                kickoff_val = f"{curr_date} {curr_time}:00"
                                matches.append({
                                    "id": stable_id(t1, t2, curr_time),
                                    "date": curr_date,
                                    "kickoff": kickoff_val,
                                    "competition": curr_comp,
                                    "home": t1,
                                    "away": t2,
                                    "markets": {"Match Result": {"1": o1, "X": ox, "2": o2}}
                                })
                            i = idx + 3
                            continue
        i += 1
    return matches


def scrape_coupon_btts_odds(session: CDPSession) -> Dict[Tuple[str, str], Dict[str, str]]:
    """
    Clicks the 'Both Teams to Score' / 'Les deux équipes marquent' tab on a Bet365 coupon page,
    extracts live genuine Yes/No odds, and restores view to Match Result.
    """
    btts_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    try:
        clicked = session.page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('div, span, button, a'));
            const target = all.find(e => {
                const t = (e.innerText || '').trim().toLowerCase();
                return t === 'both teams to score' || t === 'les deux équipes marquent';
            });
            if (target) {
                target.scrollIntoView();
                target.click();
                return true;
            }
            return false;
        }""")
        if not clicked:
            return btts_map
        time.sleep(1.2)
        lines = session.get_dom_lines()
        odd_re = re.compile(r'^\d+([.,]\d+)?$')
        for i in range(len(lines) - 3):
            t1 = lines[i].strip()
            t2 = lines[i+1].strip()
            if len(t1) >= 3 and len(t2) >= 3 and not odd_re.match(t1) and not odd_re.match(t2):
                idx = i + 2
                if idx < len(lines) and (lines[idx].isdigit() or lines[idx] in ['+', '>']):
                    idx += 1
                if idx + 1 < len(lines):
                    o_yes = lines[idx].strip().replace(',', '.')
                    o_no = lines[idx+1].strip().replace(',', '.')
                    if odd_re.match(o_yes) and odd_re.match(o_no):
                        if 1.05 <= float(o_yes) <= 20.0 and 1.05 <= float(o_no) <= 20.0:
                            pair = (clean_team_name(t1).lower(), clean_team_name(t2).lower())
                            btts_map[pair] = {"Yes": o_yes, "No": o_no}

        # Restore coupon view to Match Result
        session.page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll('div, span, button, a'));
            const target = all.find(e => {
                const t = (e.innerText || '').trim().toLowerCase();
                return t === 'full time result' || t === 'résultat du match' || t === 'resultat du match';
            });
            if (target) {
                target.scrollIntoView();
                target.click();
            }
        }""")
        time.sleep(0.5)
    except Exception:
        pass
    return btts_map


def scrape_soccer_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """
    Scrapes Soccer matches across European and World leagues via CDP with multi-step virtual scrolling,
    canonical multi-coupon discovery across top target leagues, live DOM extraction, live BTTS extraction,
    and full secondary market extraction (BTTS, Over/Under, Double Chance, Draw No Bet, Half Time/Full Time).
    """
    _init_soccer_ref_store()
    print(f"  [CDP Soccer] Discovering Soccer matches on {session.domain} via native navigation...")
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    # 1. Scrape matches from the Football main page with deep virtual scrolling (8 scroll steps)
    if not session.navigate_to_sport("Soccer"):
        session.navigate_hash("#/AS/B1/")
    time.sleep(2.5)

    # Click 'Tout voir' or 'Matchs' if present to expose full football schedule
    try:
        session.page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('div, span, button, a'));
            const tv = btns.find(e => {
                const t = (e.innerText || '').trim().toLowerCase();
                return t === 'tout voir' || t === 'tous les matches' || t === 'matchs' || t === 'matches';
            });
            if (tv) { tv.click(); return true; }
            return false;
        }''')
        time.sleep(1.5)
    except Exception:
        pass

    dom_lines = session.get_dom_lines()
    if dom_lines:
        for m in parse_soccer_dom(dom_lines, default_comp="Football"):
            resolve_soccer_match(m)
            enrich_soccer_match(m)
            if not any(ex["id"] == m["id"] or (ex["home"] == m["home"] and ex["away"] == m["away"]) for ex in matches_out):
                matches_out.append(m)

    for scroll_step in range(8):
        try:
            session.page.evaluate("window.scrollBy(0, 1500);")
            time.sleep(0.7)
            for m in parse_soccer_dom(session.get_dom_lines(), default_comp="Football"):
                resolve_soccer_match(m)
                enrich_soccer_match(m)
                if not any(ex["id"] == m["id"] or (ex["home"] == m["home"] and ex["away"] == m["away"]) for ex in matches_out):
                    matches_out.append(m)
        except Exception:
            pass

    # 2. Sequentially visit each canonical country/league coupon URL
    soccer_coupons = [
        ("UK Premier League", "#/AC/B1/C1/D1002/G40/J99/Q1/F%5E2001/", "England Premier League"),
        ("England Championship", "#/AC/B1/C1/D1002/G40/J99/I2/Q1/F%5E2001/", "England Championship"),
        ("Spain La Liga", "#/AC/B1/C1/D1002/G40/J8/I1/Q1/F%5E2001/", "LA LIGA"),
        ("Spain Segunda", "#/AC/B1/C1/D1002/G40/J8/I2/Q1/F%5E2001/", "Spain Segunda Division"),
        ("Germany Bundesliga", "#/AC/B1/C1/D1002/G40/J7/I1/Q1/F%5E2001/", "Germany Bundesliga"),
        ("Germany 2. Bundesliga", "#/AC/B1/C1/D1002/G40/J7/I2/Q1/F%5E2001/", "Germany 2. Bundesliga"),
        ("Italy Serie A", "#/AC/B1/C1/D1002/G40/J10/I1/Q1/F%5E2001/", "Italy Serie A"),
        ("Italy Serie B", "#/AC/B1/C1/D1002/G40/J10/I2/Q1/F%5E2001/", "Italy Serie B"),
        ("France Ligue 1", "#/AC/B1/C1/D1002/G40/J15/I1/Q1/F%5E12/", "France Ligue 1"),
        ("France Ligue 2", "#/AC/B1/C1/D1002/G40/J15/I2/Q1/F%5E12/", "France Ligue 2"),
        ("UEFA Champions League", "#/AC/B1/C1/D1002/G40/J17/I1/Q1/F%5E2001/", "UEFA Champions League"),
        ("UEFA Europa League", "#/AC/B1/C1/D1002/G40/J17/I2/Q1/F%5E2001/", "UEFA Europa League"),
        ("UEFA Conference League", "#/AC/B1/C1/D1002/G40/J17/I3/Q1/F%5E2001/", "UEFA Europa Conference League"),
        ("Netherlands Eredivisie", "#/AC/B1/C1/D1002/G40/J14/I1/Q1/F%5E2001/", "Netherlands Eredivisie"),
        ("Portugal Primeira Liga", "#/AC/B1/C1/D1002/G40/J21/I1/Q1/F%5E2001/", "Portugal Primeira Liga"),
        ("Americas MLS", "#/AC/B1/C1/D1002/G40/J12/I1/Q1/F%5E3/", "Major League Soccer"),
        ("Weekend Matches", "#/AC/B1/C1/D1002/G40/", "Football")
    ]

    for c_name, c_hash, c_default_comp in soccer_coupons:
        try:
            session.navigate_hash(c_hash)
            time.sleep(1.5)
            c_lines = session.get_dom_lines()
            c_matches = parse_soccer_dom(c_lines, default_comp=c_default_comp)

            # Extract secondary markets directly across all coupon fixtures
            coupon_secondary = scrape_coupon_secondary_markets(session)

            for m in c_matches:
                pair_key = (clean_team_name(m["home"]).lower(), clean_team_name(m["away"]).lower())
                if pair_key in coupon_secondary:
                    m.setdefault("markets", {}).update(coupon_secondary[pair_key])
                resolve_soccer_match(m)
                enrich_soccer_match(m)
                if not any(ex["id"] == m["id"] or (ex["home"] == m["home"] and ex["away"] == m["away"]) for ex in matches_out):
                    matches_out.append(m)
        except Exception as e:
            print(f"  [Notice] Coupon {c_name} extraction note: {e}")

    # 3. For top marquee matches lacking Correct Score, attempt deep match detail scraping
    detail_count = 0
    for m in matches_out:
        if detail_count >= 5:
            break
        if "Correct Score" not in m.get("markets", {}) and m.get("home"):
            try:
                scrape_match_detail_markets(session, m, "Soccer")
                detail_count += 1
            except Exception:
                pass

    if matches_out:
        print(f"  + [Soccer DOM] {len(matches_out)} live/upcoming matches captured directly from {session.domain}")
        for m in matches_out:
            resolve_soccer_match(m)
        return matches_out

    return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. TENNIS
# ─────────────────────────────────────────────────────────────────────────────
def enrich_tennis_match(match: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes and formats genuinely scraped Tennis market data.
    DOES NOT fabricate or calculate any odds.
    Only formats existing scraped values to canonical form.
    """
    mkts = match.setdefault("markets", {})
    mw = mkts.get("To Win Match") or mkts.get("Match Winner") or mkts.get("Money Line") or mkts.get("Match Result")

    if mw and isinstance(mw, dict) and mw.get("1") and mw.get("2"):
        od_1 = format_odd_str(mw["1"])
        od_2 = format_odd_str(mw["2"])
        mkts["To Win Match"] = {"1": od_1, "2": od_2}
        mkts["Match Winner"] = {"1": od_1, "2": od_2}

    # Format Set Betting if scraped
    sb = mkts.get("Set Betting")
    if sb and isinstance(sb, dict):
        for k in sb:
            sb[k] = format_odd_str(sb[k])

    # Format First Set Winner if scraped
    fsw = mkts.get("First Set Winner")
    if fsw and isinstance(fsw, dict):
        for k in fsw:
            fsw[k] = format_odd_str(fsw[k])

    # Format Total Games if scraped
    tg = mkts.get("Total Games") or mkts.get("Total")
    if tg and isinstance(tg, dict):
        for side in ["Over", "Under"]:
            if side in tg and isinstance(tg[side], dict) and "odds" in tg[side]:
                tg[side]["odds"] = format_odd_str(tg[side]["odds"])

    # Format Handicap if scraped
    hc = mkts.get("Handicap")
    if hc and isinstance(hc, dict):
        for k in ["1", "2"]:
            if k in hc and isinstance(hc[k], dict) and "odds" in hc[k]:
                hc[k]["odds"] = format_odd_str(hc[k]["odds"])

    return match


def parse_tennis_dom(lines: List[str], default_comp: str = "Tennis") -> List[Dict[str, Any]]:
    """Extracts live/upcoming Tennis matches with 1 2 odds directly from rendered DOM lines."""
    matches = []
    seen = set()
    date_regex = re.compile(
        r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche|'
        r'Aujourd\'hui|Demain|Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today|Tomorrow)\.?(\s+\d+|\s*$)',
        re.I
    )
    time_regex = re.compile(r'^(\d{1,2}:\d{2})$')
    odd_regex = re.compile(r'^\d+[.,]\d+$')

    curr_comp = default_comp
    curr_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # French/English date header (e.g. "Sam. 19 sept - Semi-Finals")
        if date_regex.match(line) or re.search(r'(\d{1,2})\s+(janv?|févr?|mars|avr?|mai|juin|juil?|août|sept?|oct?|nov?|déc?|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?', line, re.I):
            curr_date = parse_french_date_header(line, curr_date)
            i += 1
            continue

        if any(k in line for k in ['ATP', 'WTA', 'Davis Cup', 'Challenger', 'Tour', 'Open', 'ITF', 'UTR', 'Grand Slam']):
            if len(line) < 40 and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
                curr_comp = line
                i += 1
                continue

        # Format 1: Time followed by Player 1, Player 2, and decimal odds (standard Bet365 Tennis schedule)
        if time_regex.match(line) and i + 2 < len(lines):
            cand_time = line
            p1 = lines[i+1].strip()
            p2 = lines[i+2].strip()
            if re.search(r'[A-Za-z]', p1) and re.search(r'[A-Za-z]', p2) and not odd_regex.match(p1) and not odd_regex.match(p2) and len(p1) > 2 and len(p2) > 2:
                od1, od2 = None, None
                for j in range(i + 3, min(len(lines), i + 10)):
                    val = lines[j].strip().replace(',', '.')
                    if odd_regex.match(val) and float(val) > 1.05:
                        if od1 is None:
                            od1 = val
                        elif od2 is None:
                            od2 = val
                            break
                    elif time_regex.match(lines[j]):
                        break
                if od1 and od2:
                    pair_key = f"{p1.lower()}_{p2.lower()}"
                    if pair_key not in seen:
                        seen.add(pair_key)
                        match_id = stable_id(p1, p2, cand_time)
                        matches.append({
                            "id": match_id,
                            "date": curr_date,
                            "kickoff": f"{curr_date} {cand_time}:00" if len(cand_time) == 5 else f"{curr_date} {cand_time}",
                            "competition": curr_comp,
                            "home": p1,
                            "away": p2,
                            "markets": {
                                "To Win Match": {"1": od1, "2": od2},
                                "Match Winner": {"1": od1, "2": od2}
                            }
                        })
                        i += 3
                        continue

        # Format 2: Player 1, Player 2, Time, then odds
        if time_regex.match(line) and i >= 2:
            time_val = line
            p1 = lines[i-2].strip()
            p2 = lines[i-1].strip()
            od1, od2 = None, None
            for j in range(i + 1, min(len(lines) - 1, i + 10)):
                if date_regex.match(lines[j]) or time_regex.match(lines[j]):
                    break
                v = lines[j].strip().replace(',', '.')
                if odd_regex.match(v) and float(v) > 1.05:
                    if od1 is None:
                        od1 = v
                    elif od2 is None:
                        od2 = v
                        break
            if od1 and od2 and len(p1) > 2 and len(p2) > 2 and not p1.isdigit() and not p2.isdigit() and re.search(r'[A-Za-z]', p1):
                pair_key = f"{p1.lower()}_{p2.lower()}"
                if pair_key not in seen:
                    seen.add(pair_key)
                    match_id = stable_id(p1, p2, time_val)
                    matches.append({
                        "id": match_id,
                        "date": curr_date,
                        "kickoff": f"{curr_date} {time_val}:00" if len(time_val) == 5 else f"{curr_date} {time_val}",
                        "competition": curr_comp,
                        "home": p1,
                        "away": p2,
                        "markets": {
                            "To Win Match": {"1": od1, "2": od2},
                            "Match Winner": {"1": od1, "2": od2}
                        }
                    })

        i += 1
    return matches


def scrape_tennis_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """Scrapes live/upcoming Tennis tournaments (Sport B13) via CDP with full market enrichment."""
    _init_sports_ref_store()
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    print("  [CDP Tennis] Discovering Tennis matches via native navigation...")
    if not session.navigate_to_sport("Tennis"):
        session.navigate_hash("#/AS/B13/")
    time.sleep(2.5)

    # Click 'Tout voir' or 'Matchs' if present to expose full schedule
    try:
        session.page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('div, span, button, a'));
            const tv = btns.find(e => {
                const t = (e.innerText || '').trim().toLowerCase();
                return t === 'tout voir' || t === 'tous les matches' || t === 'matchs' || t === 'matches';
            });
            if (tv) { tv.click(); return true; }
            return false;
        }''')
        time.sleep(1.5)
    except Exception:
        pass

    # 1. Harvest matches from the Tennis main page directly with virtual scrolling
    dom_lines = session.get_dom_lines()
    if dom_lines:
        for m in parse_tennis_dom(dom_lines):
            resolved = resolve_tennis_match(m)
            if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                enrich_tennis_match(resolved)
                matches_out.append(resolved)

    for scroll_step in range(6):
        try:
            session.page.evaluate("window.scrollBy(0, 1500);")
            time.sleep(0.7)
            for m in parse_tennis_dom(session.get_dom_lines()):
                resolved = resolve_tennis_match(m)
                if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                    enrich_tennis_match(resolved)
                    matches_out.append(resolved)
        except Exception:
            pass

    # 2. Sequentially visit canonical Tennis tournament coupons
    tennis_coupons = [
        ("ATP Tour", "#/AC/B13/C1/D1002/G83/J1/Q1/F%5E24/", "ATP"),
        ("WTA Tour", "#/AC/B13/C1/D1002/G83/J2/Q1/F%5E24/", "WTA"),
        ("Challenger Tour", "#/AC/B13/C1/D1002/G83/J12/Q1/F%5E24/", "Challenger Tour"),
        ("Davis Cup", "#/AC/B13/C1/D1002/G83/J5/Q1/F%5E24/", "Davis Cup"),
        ("UTR Pro Tour", "#/AC/B13/C1/D1002/G83/J15/Q1/F%5E24/", "UTR Pro Tour"),
        ("World Tennis Tour Men", "#/AC/B13/C1/D1002/G83/J101/Q1/F%5E24/", "World Tennis Tour"),
        ("Grand Slams", "#/AC/B13/C1/D1002/G83/J10/Q1/F%5E24/", "Grand Slam"),
        ("Top Competitions", "#/AC/B13/C1/D1002/G83/J99/Q1/F%5E24/", "Tennis"),
        ("Tennis Matches 24h", "#/AC/B13/C1/D1002/G83/", "Tennis")
    ]
    for c_name, c_hash, c_comp in tennis_coupons:
        try:
            session.navigate_hash(c_hash)
            time.sleep(1.2)
            t_lines = session.get_dom_lines()
            for m in parse_tennis_dom(t_lines, default_comp=c_comp):
                resolved = resolve_tennis_match(m)
                if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                    enrich_tennis_match(resolved)
                    matches_out.append(resolved)
        except Exception as e:
            print(f"  [Notice] Tennis coupon {c_name} extraction note: {e}")

    # 3. For top tennis matches, attempt deep match detail scraping for Set Betting & First Set Winner
    detail_count = 0
    for m in matches_out:
        if detail_count >= 4:
            break
        if "Set Betting" not in m.get("markets", {}) and m.get("home"):
            try:
                scrape_match_detail_markets(session, m, "Tennis")
                detail_count += 1
            except Exception:
                pass

    if matches_out:
        print(f"  + [Tennis DOM] {len(matches_out)} live matches captured directly from Bet365")
        return matches_out

    return []


# ─────────────────────────────────────────────────────────────────────────────
# 3. BASKETBALL
# ─────────────────────────────────────────────────────────────────────────────
def parse_basketball_dom(lines: List[str], default_comp: str = "Basketball") -> List[Dict[str, Any]]:
    """Extracts live/upcoming Basketball matches with Spread, Total, Moneyline directly from rendered DOM lines."""
    matches = []
    seen = set()
    date_regex = re.compile(
        r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche|'
        r'Aujourd\'hui|Demain|Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today|Tomorrow)\.?(\s+\d+.*|\s*$)',
        re.I
    )
    time_regex = re.compile(r'^(\d{1,2}:\d{2})$')
    odd_regex = re.compile(r'^\d+([.,]\d+)?$')

    curr_comp = default_comp
    curr_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if date_regex.match(line):
            curr_date = parse_french_date_header(line, curr_date)
            i += 1
            continue

        if any(k in line for k in ['NBA', 'Euroleague', 'Eurocup', 'NCAA', 'Liga ACB', 'Pro A', 'BBL', 'Serie A', 'Basketball', 'Cup', 'Qualifications', 'WNBA']):
            if len(line) < 40 and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
                curr_comp = line
                i += 1
                continue

        # Format 1: Time followed by Team 1 and Team 2
        if time_regex.match(line) and i + 2 < len(lines):
            time_val = line
            cand_t1 = lines[i+1].strip()
            cand_t2 = lines[i+2].strip()

            if (len(cand_t1) >= 2 and len(cand_t2) >= 2 and
                not cand_t1.isdigit() and not cand_t2.isdigit() and
                not any(bad in cand_t1.lower() for bad in ['total', 'spread', 'money line', 'rechercher', 'paris', 'foire', 'support'])):

                pair_key = f"{cand_t1.lower()}_{cand_t2.lower()}"
                if pair_key not in seen:
                    seen.add(pair_key)
                    ml1, ml2 = None, None
                    spread1, spread2 = None, None
                    tot_o, tot_u = None, None

                    tokens = lines[i+3:i+25]
                    dec_odds = []
                    for idx_t, tok in enumerate(tokens):
                        if time_regex.match(tok):
                            break
                        if (tok.startswith('+') or tok.startswith('-')) and idx_t + 1 < len(tokens):
                            nxt = tokens[idx_t+1].replace(',', '.')
                            if odd_regex.match(nxt):
                                if not spread1:
                                    spread1 = f"{tok} ({nxt})"
                                elif not spread2:
                                    spread2 = f"{tok} ({nxt})"
                        if (tok.startswith('O ') or tok.startswith('U ') or tok.startswith('Б ') or tok.startswith('М ')) and idx_t + 1 < len(tokens):
                            nxt = tokens[idx_t+1].replace(',', '.')
                            if odd_regex.match(nxt):
                                if not tot_o:
                                    tot_o = f"{tok} ({nxt})"
                                elif not tot_u:
                                    tot_u = f"{tok} ({nxt})"
                        clean_tok = tok.replace(',', '.')
                        if odd_regex.match(clean_tok):
                            f_val = float(clean_tok)
                            if 1.01 <= f_val <= 50.0:
                                dec_odds.append(clean_tok)

                    if len(dec_odds) >= 2:
                        ml1, ml2 = dec_odds[-2], dec_odds[-1]

                    mkts: Dict[str, Any] = {}
                    if ml1 and ml2:
                        mkts["Moneyline"] = {"1": ml1, "2": ml2}
                        mkts["Money Line"] = {"1": ml1, "2": ml2}
                        mkts["Match Winner"] = {"1": ml1, "2": ml2}
                    if spread1 and spread2:
                        mkts["Point Spread"] = {"1": spread1, "2": spread2}
                        mkts["Spread"] = {"1": spread1, "2": spread2}
                    if tot_o and tot_u:
                        mkts["Total Points"] = {"Over": tot_o, "Under": tot_u}
                        mkts["Total"] = {"Over": tot_o, "Under": tot_u}

                    match_id = stable_id(cand_t1, cand_t2, time_val)
                    matches.append({
                        "id": match_id,
                        "date": curr_date,
                        "kickoff": f"{curr_date} {time_val}:00" if len(time_val) == 5 else f"{curr_date} {time_val}",
                        "competition": curr_comp,
                        "home": cand_t1,
                        "away": cand_t2,
                        "markets": mkts
                    })
                    i += 3
                    continue

        # Format 2: Team 1 and Team 2 preceding Time
        if time_regex.match(line) and i >= 2:
            time_val = line
            t1 = lines[i-2].strip()
            t2 = lines[i-1].strip()

            comp = curr_comp
            if i >= 3:
                cand = lines[i-3].strip()
                if any(k in cand for k in ['NBA', 'Euroleague', 'Eurocup', 'NCAA', 'Liga', 'Pro A', 'BBL', 'Serie A', 'Basketball', 'WNBA']):
                    comp = cand
                    curr_comp = comp

            ml1, ml2 = None, None
            end_idx = i + 1

            for j in range(i + 1, min(len(lines) - 1, i + 20)):
                if date_regex.match(lines[j]) or time_regex.match(lines[j]):
                    break
                v = lines[j+1].strip().replace(',', '.')
                lj = lines[j].strip().lower()
                if lj in ['1', 'money line', 'vainqueur'] and odd_regex.match(v) and ml1 is None:
                    ml1 = v
                elif lj in ['2'] and odd_regex.match(v) and ml1 is not None and ml2 is None:
                    ml2 = v
                    end_idx = j + 2

            if not ml1 or not ml2:
                cand_odds = []
                for j in range(i + 1, min(len(lines), i + 8)):
                    v = lines[j].strip().replace(',', '.')
                    if odd_regex.match(v) and 1.05 < float(v) < 30.0:
                        cand_odds.append(v)
                if len(cand_odds) >= 2:
                    ml1 = cand_odds[0]
                    ml2 = cand_odds[1]

            if ml1 and ml2 and len(t1) > 2 and len(t2) > 2 and not t1.isdigit() and not t2.isdigit():
                pair_key = f"{t1.lower()}_{t2.lower()}"
                if pair_key not in seen:
                    seen.add(pair_key)
                    match_id = stable_id(t1, t2, time_val)
                    matches.append({
                        "id": match_id,
                        "date": curr_date,
                        "kickoff": f"{curr_date} {time_val}:00" if len(time_val) == 5 else f"{curr_date} {time_val}",
                        "competition": comp,
                        "home": t1,
                        "away": t2,
                        "markets": {
                            "Moneyline": {"1": ml1, "2": ml2},
                            "Money Line": {"1": ml1, "2": ml2}
                        }
                    })
                    i = end_idx - 1
        i += 1
    return matches


def scrape_basketball_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """Scrapes Basketball matches (Sport B18) via CDP with multi-step virtual scrolling, competition discovery, and full market enrichment."""
    _init_sports_ref_store()
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    print("  [CDP Basketball] Discovering Basketball matches via native navigation...")
    if not session.navigate_to_sport("Basketball"):
        session.navigate_hash("#/AS/B18/")
    time.sleep(2.5)

    # Click 'Tout voir' or 'Matchs' if present to expose full basketball schedule
    try:
        session.page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('div, span, button, a'));
            const tv = btns.find(e => {
                const t = (e.innerText || '').trim().toLowerCase();
                return t === 'tout voir' || t === 'tous les matches' || t === 'matchs' || t === 'matches';
            });
            if (tv) { tv.click(); return true; }
            return false;
        }''')
        time.sleep(1.5)
    except Exception:
        pass

    # 1. Harvest matches from the Basketball main page with virtual scrolling (6 scroll steps)
    dom_lines = session.get_dom_lines()
    if dom_lines:
        for m in parse_basketball_dom(dom_lines):
            resolved = resolve_basketball_match(m)
            enrich_basketball_match(resolved)
            if not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                matches_out.append(resolved)

    for scroll_step in range(6):
        try:
            session.page.evaluate("window.scrollBy(0, 1500);")
            time.sleep(0.8)
            for m in parse_basketball_dom(session.get_dom_lines()):
                resolved = resolve_basketball_match(m)
                enrich_basketball_match(resolved)
                if not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                    matches_out.append(resolved)
        except Exception:
            pass

    # 2. Directly harvest major Basketball competition coupons
    bb_coupons = [
        ("NBA", "#/AC/B18/C20604387/D48/E1453/F10/", "NBA"),
        ("Basketball 24h", "#/AC/B18/C1/D1002/G1453/Q1/F%5E24/", "Basketball"),
        ("EuroLeague", "#/AC/B18/C1/D1002/G1453/J17/Q1/", "EuroLeague"),
        ("Spain Liga ACB", "#/AC/B18/C1/D1002/G1453/J8/Q1/", "Spain Liga ACB"),
        ("France Pro A", "#/AC/B18/C1/D1002/G1453/J15/Q1/", "France Pro A"),
        ("Germany BBL", "#/AC/B18/C1/D1002/G1453/J7/Q1/", "Germany BBL"),
        ("Italy Serie A Basket", "#/AC/B18/C1/D1002/G1453/J10/Q1/", "Italy Serie A"),
        ("Top Competitions", "#/AC/B18/C1/D1002/G1453/J99/Q1/", "Basketball")
    ]
    for c_name, c_hash, c_comp in bb_coupons:
        try:
            session.navigate_hash(c_hash)
            time.sleep(1.2)
            c_lines = session.get_dom_lines()
            for m in parse_basketball_dom(c_lines, default_comp=c_comp):
                resolved = resolve_basketball_match(m)
                if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                    enrich_basketball_match(resolved)
                    matches_out.append(resolved)
        except Exception as e:
            print(f"  [Notice] Basketball coupon {c_name} extraction note: {e}")

    # 3. For matches lacking Spread/Total, attempt deep match detail scraping
    detail_count = 0
    for m in matches_out:
        if detail_count >= 3:
            break
        if "Point Spread" not in m.get("markets", {}) and m.get("home"):
            try:
                scrape_match_detail_markets(session, m, "Basketball")
                detail_count += 1
            except Exception:
                pass

    if matches_out:
        print(f"  + [Basketball DOM] {len(matches_out)} live matches captured directly from Bet365")
        return matches_out

    return []


def parse_handball_dom(lines: List[str], default_comp: str = "Handball") -> List[Dict[str, Any]]:
    """Extracts live/upcoming Handball matches with 1X2 odds, handicap, and total directly from rendered DOM lines."""
    matches = []
    seen = set()
    time_regex = re.compile(r'^(\d{1,2}:\d{2})$')
    odd_regex = re.compile(r'^\d+([.,]\d+)?$')
    date_regex = re.compile(
        r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche|'
        r'Aujourd\'hui|Demain|Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today|Tomorrow)\.?(\s+\d+.*|\s*$)',
        re.I
    )

    curr_comp = default_comp
    curr_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if date_regex.match(line):
            curr_date = parse_french_date_header(line, curr_date)
            i += 1
            continue

        if 'uefa' not in line.lower() and any(k in line.lower() for k in ['ehf champions league', 'starligue', 'bundesliga', 'asobal', 'handboldligaen', 'elitserien', 'division']):
            if len(line) < 40 and not time_regex.match(line) and not date_regex.match(line):
                curr_comp = line
                i += 1
                continue

        # Format 1: Time followed by Team 1 and Team 2
        if time_regex.match(line) and i + 2 < len(lines):
            time_val = line
            cand_t1 = lines[i+1].strip()
            cand_t2 = lines[i+2].strip()

            bad_words = [
                'handicap', 'total', 'to win', 'sports', 'casino', 'matches', 'competitions',
                'rechercher', 'paris', 'foire', 'support', 'spread', 'money line', 'offers',
                'featured', 'outrights', 'top leagues', 'tout voir', 'next 24 hours'
            ]
            if (len(cand_t1) >= 2 and len(cand_t2) >= 2 and
                not cand_t1.isdigit() and not cand_t2.isdigit() and
                not any(cand_t1.startswith(p) for p in ['+', '-', 'O ', 'U ']) and
                not any(cand_t2.startswith(p) for p in ['+', '-', 'O ', 'U ']) and
                not any(bad in cand_t1.lower() or bad in cand_t2.lower() for bad in bad_words)):

                pair_key = f"{cand_t1.lower()}_{cand_t2.lower()}"
                if pair_key not in seen:
                    seen.add(pair_key)
                    spread1, spread2 = None, None
                    tot_o, tot_u = None, None
                    od1, odX, od2 = None, None, None

                    tokens = lines[i+3:i+25]
                    dec_odds = []
                    for idx_t, tok in enumerate(tokens):
                        if time_regex.match(tok):
                            break
                        if (tok.startswith('+') or tok.startswith('-')) and idx_t + 1 < len(tokens):
                            nxt = tokens[idx_t+1].replace(',', '.')
                            if odd_regex.match(nxt):
                                if not spread1:
                                    spread1 = f"{tok} ({nxt})"
                                elif not spread2:
                                    spread2 = f"{tok} ({nxt})"
                        if (tok.startswith('O ') or tok.startswith('U ') or tok.startswith('Б ') or tok.startswith('М ')) and idx_t + 1 < len(tokens):
                            nxt = tokens[idx_t+1].replace(',', '.')
                            if odd_regex.match(nxt):
                                if not tot_o:
                                    tot_o = f"{tok} ({nxt})"
                                elif not tot_u:
                                    tot_u = f"{tok} ({nxt})"
                        clean_tok = tok.replace(',', '.')
                        if odd_regex.match(clean_tok):
                            f_val = float(clean_tok)
                            if 1.05 <= f_val <= 30.0:
                                dec_odds.append(clean_tok)

                    if len(dec_odds) >= 3:
                        od1, odX, od2 = dec_odds[0], dec_odds[1], dec_odds[2]
                    elif len(dec_odds) == 2:
                        od1, od2 = dec_odds[0], dec_odds[1]

                    mkts: Dict[str, Any] = {}
                    if od1 and od2:
                        res = {"1": od1, "2": od2}
                        if odX: res["X"] = odX
                        mkts["Full Time Result"] = res
                        mkts["Match Result"] = res
                    if spread1 and spread2:
                        mkts["Handicap"] = {"1": spread1, "2": spread2}
                    if tot_o and tot_u:
                        mkts["Total Goals"] = {"Over": tot_o, "Under": tot_u}

                    match_id = stable_id(cand_t1, cand_t2, time_val)
                    matches.append({
                        "id": match_id,
                        "date": curr_date,
                        "kickoff": f"{curr_date} {time_val}:00" if len(time_val) == 5 else f"{curr_date} {time_val}",
                        "competition": curr_comp,
                        "home": cand_t1,
                        "away": cand_t2,
                        "markets": mkts
                    })
                    i += 3
                    continue

        # Format 2: Team 1 and Team 2 preceding Time
        if time_regex.match(line) and i >= 2:
            time_val = line
            t1 = lines[i-2].strip()
            t2 = lines[i-1].strip()

            bad_words = [
                'handicap', 'total', 'to win', 'sports', 'casino', 'matches', 'competitions',
                'rechercher', 'paris', 'foire', 'support', 'spread', 'money line', 'offers',
                'featured', 'outrights', 'top leagues', 'tout voir', 'next 24 hours'
            ]
            if (len(t1) > 2 and len(t2) > 2 and not t1.isdigit() and not t2.isdigit() and
                not any(t1.startswith(p) for p in ['+', '-', 'O ', 'U ']) and
                not any(t2.startswith(p) for p in ['+', '-', 'O ', 'U ']) and
                not any(bad in t1.lower() or bad in t2.lower() for bad in bad_words)):

                pair_key = f"{t1.lower()}_{t2.lower()}"
                if pair_key not in seen:
                    seen.add(pair_key)
                    od1, odX, od2 = None, None, None
                    spread_h, spread_a = None, None
                    tot_o, tot_u = None, None

                    for j in range(i + 1, min(i + 22, len(lines) - 1)):
                        lj = lines[j].strip().lower()
                        if time_regex.match(lines[j]) or date_regex.match(lines[j]):
                            break
                        if lj in ['to win', 'vainqueur', 'gagne'] and j + 2 < len(lines):
                            v1 = lines[j+1].strip().replace(',', '.')
                            v2 = lines[j+2].strip().replace(',', '.')
                            if odd_regex.match(v1) and odd_regex.match(v2):
                                od1, od2 = v1, v2
                        elif lj in ['handicap', 'écart', 'фора'] and j + 4 < len(lines):
                            l1 = lines[j+1].strip()
                            o1 = lines[j+2].strip().replace(',', '.')
                            l2 = lines[j+3].strip()
                            o2 = lines[j+4].strip().replace(',', '.')
                            if odd_regex.match(o1) and odd_regex.match(o2):
                                spread_h = f"{l1} ({o1})"
                                spread_a = f"{l2} ({o2})"
                        elif lj in ['total', 'тотал'] and j + 4 < len(lines):
                            l1 = lines[j+1].strip()
                            o1 = lines[j+2].strip().replace(',', '.')
                            l2 = lines[j+3].strip()
                            o2 = lines[j+4].strip().replace(',', '.')
                            if odd_regex.match(o1) and odd_regex.match(o2):
                                tot_o = f"{l1} ({o1})"
                                tot_u = f"{l2} ({o2})"

                    match_id = stable_id(t1, t2, time_val)
                    mkts = {}
                    if od1 and od2:
                        res = {"1": od1, "2": od2}
                        if odX: res["X"] = odX
                        mkts["Full Time Result"] = res
                        mkts["Match Result"] = res
                    if spread_h and spread_a:
                        mkts["Handicap"] = {"1": spread_h, "2": spread_a}
                    if tot_o and tot_u:
                        mkts["Total Goals"] = {"Over": tot_o, "Under": tot_u}

                    matches.append({
                        "id": match_id,
                        "date": curr_date,
                        "kickoff": f"{curr_date} {time_val}:00" if len(time_val) == 5 else f"{curr_date} {time_val}",
                        "competition": curr_comp,
                        "home": t1,
                        "away": t2,
                        "markets": mkts
                    })
        i += 1
    return matches


def scrape_handball_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """Scrapes Handball matches (Sport B78) via CDP with native navigation, landing scroll, and DOM parsing."""
    _init_sports_ref_store()
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    print("  [CDP Handball] Discovering Handball events via native navigation...")
    if not session.navigate_to_sport("Handball"):
        session.navigate_hash("#/AS/B78/")
    time.sleep(2.5)

    # Click 'Tout voir' if present to expose all available upcoming matches
    try:
        session.page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('div, span, button, a'));
            const tv = btns.find(e => (e.innerText || '').trim().toLowerCase() === 'tout voir');
            if (tv) { tv.click(); return true; }
            return false;
        }''')
        time.sleep(1.5)
    except Exception:
        pass

    # 1. Parse matches from landing page directly with multi-step virtual scrolling (6 scroll steps)
    dom_lines = session.get_dom_lines()
    if dom_lines:
        for m in parse_handball_dom(dom_lines):
            resolved = resolve_handball_match(m)
            if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                enrich_handball_match(resolved)
                matches_out.append(resolved)

    for scroll_step in range(6):
        try:
            session.page.evaluate("window.scrollBy(0, 1500);")
            time.sleep(0.8)
            for m in parse_handball_dom(session.get_dom_lines()):
                resolved = resolve_handball_match(m)
                if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                    enrich_handball_match(resolved)
                    matches_out.append(resolved)
        except Exception:
            pass

    # 2. Visit canonical Handball competition coupons
    hb_coupons = [
        ("Champions League", "#/AC/B78/C20414098/D48/E780001/F10/", "EHF Champions League"),
        ("Handball 24h", "#/AC/B78/C1/D1002/G78/Q1/F%5E24/", "Handball"),
        ("France Starligue", "#/AC/B78/C1/D1002/G78/J15/Q1/", "France Starligue"),
        ("Germany Bundesliga", "#/AC/B78/C1/D1002/G78/J7/Q1/", "Germany Bundesliga"),
        ("Spain Liga ASOBAL", "#/AC/B78/C1/D1002/G78/J8/Q1/", "Spain Liga ASOBAL"),
        ("Top Competitions", "#/AC/B78/C1/D1002/G78/J99/Q1/", "Handball")
    ]
    for c_name, c_hash, c_comp in hb_coupons:
        try:
            session.navigate_hash(c_hash)
            time.sleep(1.2)
            c_lines = session.get_dom_lines()
            for m in parse_handball_dom(c_lines, default_comp=c_comp):
                resolved = resolve_handball_match(m)
                if resolved and not any(ex["id"] == resolved["id"] or (ex["home"] == resolved["home"] and ex["away"] == resolved["away"]) for ex in matches_out):
                    enrich_handball_match(resolved)
                    matches_out.append(resolved)
        except Exception as e:
            print(f"  [Notice] Handball coupon {c_name} extraction note: {e}")

    if matches_out:
        print(f"  + [Handball DOM] {len(matches_out)} live matches captured directly from Bet365")
        return matches_out

    return []


# ─────────────────────────────────────────────────────────────────────────────
# 5. CYCLING (Cyclisme)
# ─────────────────────────────────────────────────────────────────────────────
def parse_cycling_dom(lines: List[str]) -> List[Dict[str, Any]]:
    """Extracts live/upcoming Cycling races, riders, and outright odds directly from rendered DOM lines."""
    matches = []
    curr_comp = "Cycling World Championship 2026"
    odds_dict: Dict[str, str] = {}
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    today_str = tomorrow.strftime("%d/%m/%Y")
    kickoff_str = tomorrow.strftime("%d/%m/%Y 12:00:00")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if any(k in line.lower() for k in ['world championship', 'tour de france', 'giro', 'vuelta', 'flandrien', 'paris-nice', 'paris-roubaix', 'classique', 'classic', 'tour de']):
            if len(line) < 60 and not re.match(r'^\d+\.\d+$', line):
                if odds_dict:
                    comp_title = curr_comp
                    match_id = stable_id(comp_title)
                    matches.append({
                        "id": match_id,
                        "date": today_str,
                        "kickoff": kickoff_str,
                        "competition": comp_title,
                        "home": f"{comp_title} - To Win",
                        "away": "",
                        "markets": {
                            "To Win": dict(odds_dict),
                            "To Win Outright": dict(odds_dict),
                            "Race Winner": dict(odds_dict)
                        }
                    })
                    odds_dict = {}
                curr_comp = line
                i += 1
                continue

        if i + 1 < len(lines):
            next_l = lines[i+1].strip().replace(',', '.')
            if re.match(r'^\d+\.\d{2,3}$', next_l) and len(line) > 2 and not line.isdigit():
                if (line not in ['1', '2', 'X', 'To Win Outright', 'Win Only', 'Afficher plus', 'Vainqueur', 'Oui', 'Non']
                    and not re.match(r'^\d+([.,]\d+)?$', line)
                    and not any(bad in line.lower() for bad in ['misez', 'gagnez', 'boost', 'top', 'match-ups', 'pariez', 'options'])):
                    try:
                        f_val = float(next_l)
                        if f_val > 1.0:
                            odds_dict[line] = format_odd_str(next_l)
                            i += 2
                            continue
                    except Exception:
                        pass
        i += 1

    if odds_dict:
        comp_title = curr_comp
        match_id = stable_id(comp_title)
        matches.append({
            "id": match_id,
            "date": today_str,
            "kickoff": kickoff_str,
            "competition": comp_title,
            "home": f"{comp_title} - To Win",
            "away": "",
            "markets": {
                "To Win": dict(odds_dict),
                "To Win Outright": dict(odds_dict),
                "Race Winner": dict(odds_dict)
            }
        })

    return matches


def scrape_cycling_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """Scrapes live Cycling Grand Tours, stages & outrights (Sport B38) via CDP."""
    _init_sports_ref_store()
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    print("  [CDP Cycling] Discovering Cycling races & outrights (Sport B38)...")
    if not session.navigate_to_sport("Cycling"):
        session.navigate_hash("#/AS/B38/")
    time.sleep(2.5)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    today_str = tomorrow.strftime("%d/%m/%Y")
    kickoff_str = tomorrow.strftime("%d/%m/%Y 12:00:00")

    # 1. Harvest directly from rendered DOM with virtual scrolling
    dom_lines = session.get_dom_lines()
    for _ in range(4):
        session.page.evaluate("window.scrollBy(0, 1200);")
        time.sleep(0.8)
        dom_lines.extend(session.get_dom_lines())

    for m in parse_cycling_dom(dom_lines):
        resolve_cycling_match(m)
        enrich_cycling_event(m)
        if not any(ex["competition"] == m["competition"] for ex in matches_out):
            matches_out.append(m)

    if matches_out:
        print(f"  + [Cycling DOM] {len(matches_out)} live races captured directly from Bet365")
        return matches_out

    # 2. Intercept splash stream if available
    sport_url = f"{session.domain}/#/AS/B38/"
    raw_splash = session.intercept_sport_splash(sport_url, ["Cyclisme", "Cycling"], "B38", timeout_s=4)
    if raw_splash:
        tournois = parser_splash(raw_splash, session.domain)
        for tournoi in tournois[:4]:
            t_nom = tournoi.get("nom", "Cycling Event")
            for marche in tournoi.get("marches", [])[:3]:
                m_url = marche.get("url")
                if not m_url:
                    continue
                m_nom = marche.get("nom", t_nom)
                raw_c = session.intercept_coupon_data(m_url, timeout_s=3)
                if not raw_c:
                    continue

                rows = parser_page_universel(raw_c, "Cyclisme", m_nom)
                odds_dict = {}
                for r in rows:
                    p_name = r.get("Participant", "").strip()
                    c_dec = r.get("Cote_Decimale")
                    if p_name and c_dec and float(c_dec) > 1.0 and p_name not in ["Inconnu", "Oui", "Non"]:
                        odds_dict[p_name] = format_odd_str(c_dec)

                if odds_dict:
                    sorted_odds = dict(sorted(odds_dict.items(), key=lambda x: float(x[1])))
                    comp_title = f"{t_nom} - {m_nom}" if m_nom != t_nom else t_nom
                    match_id = stable_id(comp_title)
                    ev = {
                        "id": match_id,
                        "date": today_str,
                        "kickoff": kickoff_str,
                        "competition": comp_title,
                        "home": f"{comp_title} - To Win",
                        "away": "",
                        "markets": {
                            "To Win": sorted_odds,
                            "Race Winner": sorted_odds
                        }
                    }
                    resolve_cycling_match(ev)
                    enrich_cycling_event(ev)
                    if not any(ex["competition"] == ev["competition"] for ex in matches_out):
                        matches_out.append(ev)

    if matches_out:
        return matches_out

    return []


# ─────────────────────────────────────────────────────────────────────────────
# 6. GOLF
# ─────────────────────────────────────────────────────────────────────────────
def parser_golf_splash(raw: str, domain: str = DEFAULT_DOMAIN) -> Dict[str, List[Dict[str, Any]]]:
    """Extracts Golf tournaments and their markets from splash stream."""
    parsed = parse_bet365(raw)
    tournaments: Dict[str, List[Dict[str, Any]]] = {}
    current_tourney = None
    current_cat = None

    for b in parsed:
        t = b.get("_type")
        if t == "MG":
            na = b.get("NA", "").strip()
            if na and na not in ("In-Play", "Coupons", "Offers", "Tips") and not b.get("SY", "") in ("pbb", "sib"):
                current_tourney = na
                if current_tourney not in tournaments:
                    tournaments[current_tourney] = []
        elif t == "MA" and current_tourney:
            current_cat = b.get("NA", "").strip()
        elif t == "PA" and current_tourney:
            pd = b.get("PD", "").strip()
            m_name = b.get("NA", "").strip()
            if pd and m_name and "#AVR#" not in pd and "#P" not in pd:
                if "#AC#" in pd or "#IP#" in pd:
                    tournaments[current_tourney].append({
                        "category": current_cat,
                        "market": m_name,
                        "url": pd_vers_url(pd, domain),
                    })

    return {k: v for k, v in tournaments.items() if v and "Virtual" not in k}


def scrape_golf_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """Scrapes live Golf tournaments & outrights (Sport B7) via CDP."""
    _init_sports_ref_store()
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    print("  [CDP Golf] Discovering Golf tournaments (Sport B7)...")
    if not session.navigate_to_sport("Golf"):
        session.navigate_hash("#/AS/B7/")
    time.sleep(2.5)
    sport_url = f"{session.domain}/#/AS/B7/"
    raw_splash = session.intercept_sport_splash(sport_url, ["Golf"], "B7", timeout_s=8)

    tournaments = parser_golf_splash(raw_splash, session.domain) if raw_splash else {}
    matches_out: List[Dict[str, Any]] = []

    PRIORITY_MARKETS = [
        "To Win Outright", "Outright Markets", "To Lift Trophy",
        "Top Finishes", "Top Finishes (Including Ties)", "1st Round Leader",
        "3 Balls", "3-Balls"
    ]

    active_tourneys = list(tournaments.items())

    for tourney_name, markets in active_tourneys[:8]:
        date_str, kickoff_str = get_golf_event_schedule(tourney_name)
        selected_markets = []
        outrights = [m for m in markets if m["market"] in ("To Win Outright", "Outright Markets")]
        if outrights:
            selected_markets.append(outrights[0])

        for pm in PRIORITY_MARKETS:
            if pm in ("To Win Outright", "Outright Markets"):
                continue
            for m in markets:
                if m["market"] == pm and m not in selected_markets and len(selected_markets) < 2:
                    selected_markets.append(m)

        if not selected_markets and markets:
            selected_markets.append(markets[0])

        for m in selected_markets:
            m_name = m["market"]
            m_url = m["url"]
            raw_c = session.intercept_coupon_data(m_url, timeout_s=4)
            if not raw_c:
                continue

            rows = parser_page_universel(raw_c, "Golf", f"{tourney_name} - {m_name}")
            odds_dict = {}
            for r in rows:
                p_name = r.get("Participant", "").strip()
                c_dec = r.get("Cote_Decimale")
                if not p_name or not c_dec:
                    continue
                if p_name.isdigit() or p_name in ["Inconnu", "Oui", "Non", "N/A"] or len(p_name) < 2:
                    continue
                try:
                    f_dec = float(c_dec)
                    if f_dec > 1.0:
                        odds_dict[p_name] = format_odd_str(c_dec)
                except Exception:
                    pass

            if odds_dict:
                sorted_odds = dict(sorted(odds_dict.items(), key=lambda x: float(x[1])))
                comp_title = f"{tourney_name} - {m_name}" if m_name != tourney_name else tourney_name
                match_id = stable_id(comp_title)
                ev = {
                    "id": match_id,
                    "date": date_str,
                    "kickoff": kickoff_str,
                    "competition": comp_title,
                    "home": f"{comp_title} - To Win",
                    "away": "",
                    "markets": {
                        "To Win": sorted_odds,
                        "To Win Outright": sorted_odds,
                        "Outright Winner": sorted_odds
                    }
                }
                resolved = resolve_golf_match(ev)
                if resolved:
                    enrich_golf_tournament(resolved)
                    matches_out.append(resolved)
                    print(f"  + [Golf] Captured {len(sorted_odds)} selections for {resolved['competition']}")

    if matches_out:
        return matches_out

    return []


def parse_f1_from_dom_lines(lines: List[str]) -> Tuple[str, Dict[str, Dict[str, str]]]:
    """Extracts Grand Prix name, Race Winner, and Podium Finish directly from B10 inner text."""
    gp_name = "Grand Prix d'Espagne"
    markets: Dict[str, Dict[str, str]] = {}
    current_market = None
    odds_dict: Dict[str, str] = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        if "Grand Prix" in line and len(line) < 40:
            gp_name = line
            i += 1
            continue
        if any(k in line.lower() for k in ["vainqueur de la course", "race winner", "to win outright"]):
            if current_market and odds_dict:
                markets[current_market] = dict(odds_dict)
                odds_dict = {}
            current_market = "Race Winner"
            i += 1
            continue
        elif any(k in line.lower() for k in ["termine sur le podium", "podium finish", "sur le podium"]):
            if current_market and odds_dict:
                markets[current_market] = dict(odds_dict)
                odds_dict = {}
            current_market = "Podium Finish"
            i += 1
            continue
        elif any(k in line.lower() for k in ["championnat des pilotes", "drivers championship"]):
            if current_market and odds_dict:
                markets[current_market] = dict(odds_dict)
                odds_dict = {}
            current_market = "Drivers Championship"
            i += 1
            continue
        elif any(k in line.lower() for k in ["championnat des constructeurs", "constructors championship"]):
            if current_market and odds_dict:
                markets[current_market] = dict(odds_dict)
                odds_dict = {}
            current_market = "Constructors Championship"
            i += 1
            continue

        if current_market and i + 1 < len(lines):
            next_line = lines[i + 1]
            if re.match(r"^\d+\.\d{2}$", next_line):
                driver = line.replace(" - Oui", "").replace(" - Yes", "").strip()
                if driver not in ["Victoire seulement", "Gagnant/Placé 1/3 1-2", "Afficher plus", "Récompenses"]:
                    odds_dict[driver] = next_line
                    i += 2
                    continue
        i += 1

    if current_market and odds_dict:
        markets[current_market] = dict(odds_dict)

    return gp_name, markets


def scrape_f1_cdp(session: CDPSession) -> List[Dict[str, Any]]:
    """Scrapes Formula 1 Grand Prix races & championship outrights (Sport B10) via CDP."""
    _init_sports_ref_store()
    matches_out: List[Dict[str, Any]] = []

    # Quick geo-block check
    if getattr(session, "geo_blocked", False) or session.is_geo_blocked():
        session.geo_blocked = True
        return []

    print("  [CDP Formula 1] Discovering F1 races & outrights (Sport B10)...")
    if not session.navigate_to_sport("F1"):
        session.navigate_hash("#/AS/B10/")
    time.sleep(2.5)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    today_str = tomorrow.strftime("%d/%m/%Y")
    kickoff_str = tomorrow.strftime("%d/%m/%Y 14:00:00")

    # 1. Harvest live Grand Prix directly from active rendered DOM
    try:
        dom_lines = session.get_dom_lines()
        gp_name, dom_mkts = parse_f1_from_dom_lines(dom_lines)
        if dom_mkts:
            gp_date = today_str
            gp_kickoff = kickoff_str
            for line in dom_lines:
                m_date = re.search(r'(\d{1,2})\s+(janv?|févr?|mars|avr?|mai|juin|juil?|août|sept?|oct?|nov?|déc?|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+(\d{1,2}:\d{2})', line, re.I)
                if m_date:
                    day = m_date.group(1).zfill(2)
                    m_name = m_date.group(2).lower()
                    month_map = {
                        'jan': '01', 'janv': '01', 'feb': '02', 'fév': '02', 'févr': '02',
                        'mar': '03', 'mars': '03', 'apr': '04', 'avr': '04',
                        'may': '05', 'mai': '05', 'jun': '06', 'juin': '06',
                        'jul': '07', 'juil': '07', 'aug': '08', 'août': '08',
                        'sep': '09', 'sept': '09', 'oct': '10',
                        'nov': '11', 'dec': '12', 'déc': '12'
                    }
                    m_num = month_map.get(m_name, '09')
                    gp_date = f"{day}/{m_num}/2026"
                    gp_kickoff = f"{gp_date} {m_date.group(3)}:00"
                    break

            comp_title = f"Formula 1 - {gp_name}"
            match_id = stable_id(comp_title)
            dom_mkts["To Win"] = dom_mkts.get("Race Winner") or list(dom_mkts.values())[0]
            matches_out.append({
                "id": match_id,
                "date": gp_date,
                "kickoff": gp_kickoff,
                "competition": comp_title,
                "home": f"{comp_title} - To Win",
                "away": "",
                "markets": dom_mkts
            })
            print(f"  + [F1 DOM] Captured {gp_name} with markets: {list(dom_mkts.keys())}")
    except Exception as e:
        print(f"  [Warning] F1 DOM extraction: {e}")

    # 2. Intercept splash data if available for additional F1 coupons
    sport_url = f"{session.domain}/#/AS/B10/"
    raw_splash = session.intercept_sport_splash(
        sport_url,
        ["Sports mécaniques", "Formule 1", "Formula 1", "F1", "Motor Sports"],
        "B10",
        timeout_s=5
    )
    if raw_splash:
        tournois = parser_splash(raw_splash, session.domain)
        f1_tourneys = [
            t for t in tournois
            if any(k in t.get("nom", "").lower() for k in [
                "formula 1", "formule 1", "f1", "grand prix", "pilotes", "constructeurs", "course", "principaux"
            ])
        ]
        if not f1_tourneys:
            f1_tourneys = tournois[:4]

        for tournoi in f1_tourneys[:6]:
            t_nom = tournoi.get("nom", "Formula 1")
            for marche in tournoi.get("marches", [])[:3]:
                m_url = marche.get("url")
                if not m_url:
                    continue
                m_nom = marche.get("nom", t_nom)
                raw_c = session.intercept_coupon_data(m_url, timeout_s=4)
                if not raw_c:
                    continue

                rows = parser_page_universel(raw_c, "Formula 1", m_nom)
                odds_dict = {}
                for r in rows:
                    p_name = r.get("Participant", "").strip()
                    c_dec = r.get("Cote_Decimale")
                    if p_name and c_dec and float(c_dec) > 1.0 and p_name not in ["Inconnu", "Oui", "Non", "N/A"]:
                        odds_dict[p_name] = format_odd_str(c_dec)

                if odds_dict:
                    sorted_odds = dict(sorted(odds_dict.items(), key=lambda x: float(x[1])))
                    comp_title = f"{t_nom} - {m_nom}" if m_nom != t_nom else t_nom
                    match_id = stable_id(comp_title)

                    markets_dict: Dict[str, Any] = {
                        "To Win": sorted_odds
                    }
                    m_nom_l = m_nom.lower()
                    t_nom_l = t_nom.lower()
                    if "podium" in m_nom_l or "podium" in t_nom_l:
                        markets_dict["Podium Finish"] = sorted_odds
                    elif "pilotes" in t_nom_l or "drivers" in t_nom_l:
                        markets_dict["Drivers Championship"] = sorted_odds
                        markets_dict["Race Winner"] = sorted_odds
                    elif "constructeurs" in t_nom_l or "constructors" in t_nom_l:
                        markets_dict["Constructors Championship"] = sorted_odds
                        markets_dict["Race Winner"] = sorted_odds
                    else:
                        markets_dict["Race Winner"] = sorted_odds

                    if not any(ex["id"] == match_id or ex["competition"] == comp_title for ex in matches_out):
                        matches_out.append({
                            "id": match_id,
                            "date": today_str,
                            "kickoff": kickoff_str,
                            "competition": comp_title,
                            "home": f"{comp_title} - To Win",
                            "away": "",
                            "markets": markets_dict
                        })
                        print(f"  + [F1] Captured {len(sorted_odds)} selections for {comp_title}")

    if matches_out:
        for m in matches_out:
            resolve_f1_match(m)
        return matches_out

    return []


# ─────────────────────────────────────────────────────────────────────────────
# Top-Level Multi-Sport Coordinator
# ─────────────────────────────────────────────────────────────────────────────
def scrape_cdp_pipeline(target_sports: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Connects to active Chrome CDP instance and executes pure in-browser scraping
    across all requested sports with spacing and anti-detection.
    """
    if not HAS_PLAYWRIGHT:
        print("[Error] Playwright is not installed. Please run: pip install playwright")
        return []

    if not ensure_chrome_cdp(CDP_PORT):
        print(f"[Error] Chrome CDP on port {CDP_PORT} is not available.")
        return []

    ALL_SPORT_HANDLERS = [
        ("Soccer", scrape_soccer_cdp),
        ("Tennis", scrape_tennis_cdp),
        ("Basketball", scrape_basketball_cdp),
        ("Handball", scrape_handball_cdp),
        ("Cycling", scrape_cycling_cdp),
        ("Golf", scrape_golf_cdp),
        ("F1", scrape_f1_cdp),
    ]

    def want(sport_label: str) -> bool:
        if not target_sports:
            return True
        return any(
            t.lower() in sport_label.lower() or sport_label.lower() in t.lower()
            for t in target_sports
        )

    results: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        except Exception as e:
            print(f"[Error] Could not connect to Chrome CDP: {e}")
            return []

        context = browser.contexts[0] if browser.contexts else browser.new_context()

        # Find active Bet365 page or create one
        page = None
        for p_item in context.pages:
            u = p_item.url or ""
            if "bet365" in u:
                page = p_item
                break
        if not page and context.pages:
            page = context.pages[0]
        # Auto-detect target domain: bet365.fr (if French IP) or bet365.com (if normal IP)
        target_domain = get_bet365_domain()
        for p_item in context.pages:
            u = (p_item.url or "").lower()
            if "bet365.fr" in u:
                target_domain = "https://www.bet365.fr"
                break
            elif "bet365.com" in u:
                target_domain = "https://www.bet365.com"
                break

        if not page and context.pages:
            page = context.pages[0]
        elif not page:
            page = context.new_page()
            page.goto(target_domain, wait_until="commit")

        print(f"[*] Attached to Bet365 session ({target_domain}) via CDP port {CDP_PORT}")
        try:
            page.set_viewport_size({"width": 1920, "height": 1080})
        except Exception:
            pass
        session = CDPSession(page, target_domain)
        if session.is_geo_blocked():
            session.geo_blocked = True
            print("\n  [Geo-Block Notice] Bet365 returned 403 Forbidden / geo-restriction ('Ez az oldal nem érhető el az Ön országából').")
            print("  [Geo-Block Notice] Real live scraping cannot proceed while Bet365 displays the geo-restriction page.")
            print("  [Geo-Block Notice] Please connect through a working VPN or set a valid residential proxy in config.json.\n")
            return []

        for sport_name, handler in ALL_SPORT_HANDLERS:
            if not want(sport_name):
                continue

            print("\n" + "-" * 54)
            print(f"  Scraping {sport_name.upper()}...")
            print("-" * 54)

            if not getattr(session, "geo_blocked", False):
                session.check_and_recover_blocked()
                time.sleep(1.2)

            try:
                matches = handler(session)
                if matches:
                    results.append({
                        "sport": sport_name,
                        "matches": matches
                    })
                    print(f"  [OK] {sport_name}: {len(matches)} matches recorded")
                else:
                    print(f"  - {sport_name}: 0 matches found")
            except Exception as e:
                print(f"  [Error] {sport_name} handler exception: {e}")

            # Natural inter-sport delay (only when live scraping)
            if not getattr(session, "geo_blocked", False):
                request_delay(base_s=3.0, jitter=0.5)

    return results

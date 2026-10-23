"""
live_markets.py  —  Bet365 France live market extraction (on-screen first)
==========================================================================
This module is the single place that turns a raw Bet365 feed stream into the
market objects the client sees.  It exists to kill three defects at once:

  1. SYNTHETIC SECONDARY MARKETS
     Secondary markets (BTTS, O/U, Double Chance, Draw No Bet, HT/FT, Correct
     Score) are *only* emitted when a real selection was captured from the
     live feed/DOM.  There is no model, no fallback, no interpolation here.
     If a market is not captured it is simply absent.

  2. WRONG / MISSING PRICE VARIANCE (ANJ Chart)
     Every raw odd is converted to the on-screen French odd through
     `screen_rows()`, in this order of trust:
        a) the site's own JS   window.PriceVarianceLib.pvOdds.getAdjustmentValue(
              raw, ki, l3, marketId, 'PV_CHARTS')      <- authoritative
        b) the local Python chart engine (bet365_pv), keyed per market
     The raw (unadjusted) value is always retained for the audit trail.

  3. GUEST vs LOGGED-IN / BOOSTED ODDS
     `screen_rows()` prefers a value already rendered on the page DOM
     (`screen_odd_from_display`) over any reconstruction, so what the user
     sees in their session is what we report.

Provenance is recorded per market in `market_provenance`:
    "dom"     -> read straight off the rendered page
    "js"      -> adjusted by the site's own PriceVarianceLib
    "chart"   -> adjusted by the local ANJ chart engine
Nothing else is ever written, and `market_source` stays "live" because every
value genuinely originates from the live bookmaker feed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from bet365_pv import (
    apply_bet365_pv,
    format_french_odd,
    resolve_chart_id,
    screen_odd_from_display,
)

# ─────────────────────────────────────────────────────────────────────────────
# Market identity
# ─────────────────────────────────────────────────────────────────────────────
# Canonical sale names emitted by the pipeline, with the market id Bet365 uses
# in `getAdjustmentValue(raw, ki, l3, marketId, 'PV_CHARTS')`.  The feed very
# often carries the id in the MA/MG block ("ID"); when it does we use the feed
# id and ignore this table.
CANONICAL_MARKET_IDS: Dict[str, str] = {
    "Match Result": "40",
    "Both Teams to Score": "10150",
    "Goals Over/Under": "981",
    "Double Chance": "10114",
    "Draw No Bet": "10149",
    "Half Time/Full Time": "10152",
    "Correct Score": "10151",
    "Asian Handicap": "10148",
    "Match Winner": "40",
    "Moneyline": "40",
    "Race Winner": "40",
    "Podium Finish": "40",
    "Outright Winner": "40",
}

# French / English market-name tokens -> canonical market name.
_MARKET_ALIASES: List[Tuple[str, Tuple[str, ...]]] = [
    ("Match Result", ("résultat du match", "resultat du match", "full time result",
                      "match result", "vainqueur du match", "match winner", "moneyline")),
    ("Both Teams to Score", ("les deux équipes marquent", "les 2 équipes marquent",
                             "both teams to score", "btts")),
    ("Goals Over/Under", ("total de buts", "total goals", "plus / moins", "plus/moins",
                          "goals over/under", "over/under", "total points", "total")),
    ("Double Chance", ("double chance", "double résultat")),
    ("Draw No Bet", ("remboursé si nul", "rembourse si nul", "draw no bet", "dnb")),
    ("Half Time/Full Time", ("mi-temps / fin de match", "mi-temps/fin de match",
                             "half time/full time", "ht/ft", "mi temps / fin de match")),
    ("Correct Score", ("score exact", "correct score")),
    ("Asian Handicap", ("handicap asiatique", "asian handicap")),
    ("Point Spread", ("point spread", "handicap", "spread")),
]

_OBVIOUSLY_SYNTHETIC = {"synthetic", "model", "poisson", "estimated", "computed", "default"}


def canonical_market_name(raw_name: str) -> Optional[str]:
    """Map a feed market label to a canonical name, or None if unrecognised."""
    if not raw_name:
        return None
    low = str(raw_name).strip().lower()
    for canonical, tokens in _MARKET_ALIASES:
        if any(tok in low for tok in tokens):
            return canonical
    return None


# ─────────────────────────────────────────────────────────────────────────────
# The authoritative PV path: ask the page itself
# ─────────────────────────────────────────────────────────────────────────────
_JS_APPLY_PV = r"""
(rows, ki, l3) => {
    const lib = window.PriceVarianceLib || window.ns_pricevariancelib ||
                window.ns_pricevariancelib_util;
    if (!lib || !lib.pvOdds || typeof lib.pvOdds.getAdjustmentValue !== 'function') {
        return null;
    }
    return rows.map(function (row) {
        const out = { raw: row.raw, screen: null, adjustment: null };
        try {
            const adj = lib.pvOdds.getAdjustmentValue(
                Number(row.raw).toFixed(4), String(ki || '1'),
                String(l3 || ''), String(row.marketId || '40'), 'PV_CHARTS'
            );
            if (adj !== false && adj !== null && adj !== undefined) {
                const value = Number(row.raw) - Number(adj || 0);
                const decimals = value < 1.1 ? 3 : 2;
                const factor = Math.pow(10, decimals);
                out.screen = Math.trunc((value + Number.EPSILON * value) * factor) / factor;
                out.adjustment = Number(adj || 0);
            } else {
                out.screen = Number(row.raw);
                out.adjustment = 0;
            }
        } catch (e) {
            out.screen = null;
        }
        return out;
    });
}
"""


def _js_screen_rows(page: Any, rows: List[Dict[str, Any]], ki: str, l3: str) -> Optional[List[Dict[str, Any]]]:
    if page is None:
        return None
    payload = [
        {
            "raw": r.get("Cote_Decimale_Brute"),
            "marketId": r.get("Marche_ID") or CANONICAL_MARKET_IDS.get(
                canonical_market_name(r.get("Marche", "")) or "", "40"),
        }
        for r in rows
    ]
    try:
        res = page.evaluate(_JS_APPLY_PV, [payload, str(ki or "1"), str(l3 or "")])
    except Exception:
        return None
    if not res or not isinstance(res, list) or len(res) != len(rows):
        return None
    return res


def screen_rows(page: Any, rows: List[Dict[str, Any]], ki: str = "1", l3: str = "",
                sport: str = "", dom_values: Optional[Dict[Tuple[str, str, str], str]] = None) -> List[Dict[str, Any]]:
    """Annotate parsed feed rows with the on-screen odd.

    Adds:
        Cote_Decimale_Brute : the raw (unadjusted) decimal odd
        Cote_Decimale_PV    : the on-screen (ANJ-adjusted) decimal odd
        Cote_Decimale       : == Cote_Decimale_PV (kept for compatibility)
        _pv_method          : "dom" | "js" | "chart"

    `dom_values` optionally maps (market_label, participant_label, line) to a
    string already displayed on the page; those take absolute precedence.
    """
    for r in rows:
        raw = r.get("Cote_Decimale_Brute")
        if raw is None:
            raw = r.get("Cote_Decimale")
        r["Cote_Decimale_Brute"] = raw

    js_out = _js_screen_rows(page, rows, ki, l3)

    for idx, r in enumerate(rows):
        raw = r.get("Cote_Decimale_Brute")
        if raw is None:
            continue

        # 1. DOM ground truth
        dom_key = (r.get("Marche", ""), r.get("Participant", ""), str(r.get("Line", "")))
        dom_val = (dom_values or {}).get(dom_key)
        dom_screen = screen_odd_from_display(dom_val) if dom_val else None
        if dom_screen is not None:
            r["Cote_Decimale_PV"] = float(dom_screen)
            r["Cote_Decimale"] = r["Cote_Decimale_PV"]
            r["_pv_method"] = "dom"
            continue

        # 2. Site JS
        if js_out is not None:
            entry = js_out[idx] or {}
            if entry.get("screen") is not None:
                r["Cote_Decimale_PV"] = round(float(entry["screen"]), 3)
                r["Cote_Decimale"] = r["Cote_Decimale_PV"]
                r["_pv_method"] = "js"
                continue

        # 3. Local chart engine (per-market chart)
        canonical = canonical_market_name(r.get("Marche", "")) or ""
        r["Cote_Decimale_PV"] = apply_bet365_pv(raw, chart_id=resolve_chart_id(sport, canonical))
        r["Cote_Decimale"] = r["Cote_Decimale_PV"]
        r["_pv_method"] = "chart"

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Raw-feed parsing (independent of bet365_internal's universal parser)
# ─────────────────────────────────────────────────────────────────────────────
def parse_bet365_blocks(raw: str) -> List[Dict[str, str]]:
    """Bet365 frame decoding: blocks by '|', fields by ';', key=value."""
    out: List[Dict[str, str]] = []
    for block in str(raw or "").split("|"):
        if not block.strip():
            continue
        parts = block.split(";")
        d = {"_type": parts[0]}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                d[k] = v
        out.append(d)
    return out


def fraction_to_decimal(frac: Any) -> float:
    try:
        s = str(frac).strip()
        if not s:
            return 0.0
        if "/" in s:
            n, d = s.split("/", 1)
            return round(int(n) / int(d) + 1.0, 4)
        return round(float(s.replace(",", ".")), 4)
    except Exception:
        return 0.0


def _french_decimal(text: Any) -> Optional[float]:
    m = re.search(r"\d+(?:[.,]\d+)?", str(text or ""))
    if not m:
        return None
    try:
        f = float(m.group(0).replace(",", "."))
    except ValueError:
        return None
    return f if f > 1.0 else None


def extract_market_rows(raw: str) -> List[Dict[str, Any]]:
    """Walk a Bet365 stream and emit one row per (market, selection).

    Row: {Marche, Marche_ID, Participant, Line, Cote_Decimale_Brute}
    Only selections carrying a real odd are emitted.
    """
    rows: List[Dict[str, Any]] = []
    cur_market = ""
    cur_market_id = ""
    for b in parse_bet365_blocks(raw):
        t = b.get("_type")
        if t in ("MG", "MA"):
            if b.get("NA"):
                cur_market = b.get("NA", "").strip()
                cur_market_id = str(b.get("ID", "")).lstrip("M")
        elif t == "PA":
            od = b.get("OD", "").strip()
            if not od:
                continue
            dec = fraction_to_decimal(od)
            if dec <= 1.0:
                continue
            na = str(b.get("NA", "")).strip()
            hd = str(b.get("HD", "")).strip() or str(b.get("HA", "")).strip()
            participant = na or hd
            rows.append({
                "Marche": cur_market,
                "Marche_ID": cur_market_id,
                "Participant": participant,
                "Line": hd,
                "Cote_Decimale_Brute": dec,
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Row -> canonical market objects  (never invents a selection)
# ─────────────────────────────────────────────────────────────────────────────
def _clean_odd(val: Any) -> Optional[str]:
    try:
        f = float(str(val).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if f <= 1.0:
        return None
    return f"{f:.3f}" if f < 1.10 else f"{f:.2f}"


def _match_result_keys(participant: str, home: str, away: str) -> Optional[str]:
    p = participant.strip()
    if p in ("1", "Home", "Domicile"):
        return "1"
    if p in ("X", "x", "Nul", "Draw", "N"):
        return "X"
    if p in ("2", "Away", "Extérieur", "Exterieur"):
        return "2"
    pl, hl, al = p.lower(), home.strip().lower(), away.strip().lower()
    if hl and (hl in pl or pl in hl):
        return "1"
    if al and (al in pl or pl in al):
        return "2"
    if any(t in pl for t in ("nul", "draw")):
        return "X"
    return None


def build_soccer_markets(rows: List[Dict[str, Any]], home: str, away: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Group screened rows into canonical soccer markets.

    Returns (markets, market_source, market_provenance, unadjusted_raw_markets).
    A market is emitted only when it was fully captured.
    """
    markets: Dict[str, Any] = {}
    source: Dict[str, str] = {}
    provenance: Dict[str, str] = {}
    raw_markets: Dict[str, Any] = {}

    # Collect per canonical market
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        name = canonical_market_name(r.get("Marche", ""))
        if name:
            buckets.setdefault(name, []).append(r)

    def _screen(r: Dict[str, Any]) -> Optional[str]:
        return _clean_odd(r.get("Cote_Decimale_PV", r.get("Cote_Decimale")))

    def _raw(r: Dict[str, Any]) -> Optional[str]:
        return _clean_odd(r.get("Cote_Decimale_Brute"))

    def _prov(rs: List[Dict[str, Any]]) -> str:
        methods = {r.get("_pv_method", "chart") for r in rs}
        if "dom" in methods:
            return "dom"
        if "js" in methods:
            return "js"
        return "chart"

    # --- Match Result (1X2) ---
    mr_sel = {}
    mr_raw = {}
    mr_rows = []
    for r in buckets.get("Match Result", []):
        key = _match_result_keys(r.get("Participant", ""), home, away)
        s = _screen(r)
        raw = _raw(r)
        if key and s and raw and key not in mr_sel:
            mr_sel[key] = s
            mr_raw[key] = raw
            mr_rows.append(r)
    if all(k in mr_sel for k in ("1", "X", "2")):
        markets["Match Result"] = mr_sel
        source["Match Result"] = "live"
        provenance["Match Result"] = _prov(mr_rows)
        raw_markets["Match Result"] = mr_raw

    # --- Both Teams to Score ---
    btts = {}
    btts_raw = {}
    btts_rows = []
    for r in buckets.get("Both Teams to Score", []):
        p = r.get("Participant", "").lower()
        key = "Yes" if p in ("oui", "yes", "o") else "No" if p in ("non", "no", "n") else None
        s = _screen(r)
        raw = _raw(r)
        if key and s and raw and key not in btts:
            btts[key] = s
            btts_raw[key] = raw
            btts_rows.append(r)
    if all(k in btts for k in ("Yes", "No")):
        markets["Both Teams to Score"] = btts
        source["Both Teams to Score"] = "live"
        provenance["Both Teams to Score"] = _prov(btts_rows)
        raw_markets["Both Teams to Score"] = btts_raw

    # --- Goals Over/Under 2.5 ---
    ou = {}
    ou_raw = {}
    ou_rows = []
    for r in buckets.get("Goals Over/Under", []):
        p = r.get("Participant", "").lower()
        line = _french_decimal(r.get("Line") or r.get("Participant"))
        if line is None or abs(line - 2.5) > 1e-9:
            continue
        side = None
        if any(t in p for t in ("plus", "over", ">")) :
            side = "Over"
        elif any(t in p for t in ("moins", "under", "<")):
            side = "Under"
        s = _screen(r)
        raw = _raw(r)
        if side and s and raw and side not in ou:
            ou[side] = {"line": "2.5", "odds": s}
            ou_raw[side] = raw
            ou_rows.append(r)
    if "Over" in ou and "Under" in ou:
        markets["Goals Over/Under"] = ou
        source["Goals Over/Under"] = "live"
        provenance["Goals Over/Under"] = _prov(ou_rows)
        raw_markets["Goals Over/Under"] = ou_raw

    # --- Double Chance ---
    dc = {}
    dc_raw = {}
    dc_rows = []
    for r in buckets.get("Double Chance", []):
        p = r.get("Participant", "").upper().replace(" ", "")
        key = None
        if "1X" in p:
            key = "1X"
        elif "12" in p:
            key = "12"
        elif "X2" in p:
            key = "X2"
        s = _screen(r)
        raw = _raw(r)
        if key and s and raw and key not in dc:
            dc[key] = s
            dc_raw[key] = raw
            dc_rows.append(r)
    if all(k in dc for k in ("1X", "12", "X2")):
        markets["Double Chance"] = dc
        source["Double Chance"] = "live"
        provenance["Double Chance"] = _prov(dc_rows)
        raw_markets["Double Chance"] = dc_raw

    # --- Draw No Bet ---
    dnb = {}
    dnb_raw = {}
    dnb_rows = []
    for r in buckets.get("Draw No Bet", []):
        key = _match_result_keys(r.get("Participant", ""), home, away)
        if key not in ("1", "2"):
            continue
        s = _screen(r)
        raw = _raw(r)
        if s and raw and key not in dnb:
            dnb[key] = s
            dnb_raw[key] = raw
            dnb_rows.append(r)
    if all(k in dnb for k in ("1", "2")):
        markets["Draw No Bet"] = dnb
        source["Draw No Bet"] = "live"
        provenance["Draw No Bet"] = _prov(dnb_rows)
        raw_markets["Draw No Bet"] = dnb_raw

    # --- Correct Score ---
    cs = {}
    cs_raw = {}
    cs_rows = []
    for r in buckets.get("Correct Score", []):
        p = str(r.get("Participant", "")).strip()
        m = re.match(r"^(\d+)\s*[-–:]\s*(\d+)$", p)
        if not m:
            continue
        key = f"{m.group(1)}-{m.group(2)}"
        s = _screen(r)
        raw = _raw(r)
        if s and raw and key not in cs:
            cs[key] = s
            cs_raw[key] = raw
            cs_rows.append(r)
    if len(cs) >= 4:
        markets["Correct Score"] = cs
        source["Correct Score"] = "live"
        provenance["Correct Score"] = _prov(cs_rows)
        raw_markets["Correct Score"] = cs_raw

    # --- Half Time / Full Time ---
    htft = {}
    htft_raw = {}
    htft_rows = []
    for r in buckets.get("Half Time/Full Time", []):
        p = r.get("Participant", "").upper().replace(" ", "")
        key = None
        for cand in ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"):
            if cand.replace("/", "") in p.replace("/", ""):
                key = cand
                break
        s = _screen(r)
        raw = _raw(r)
        if key and s and raw and key not in htft:
            htft[key] = s
            htft_raw[key] = raw
            htft_rows.append(r)
    if len(htft) >= 6:
        markets["Half Time/Full Time"] = htft
        source["Half Time/Full Time"] = "live"
        provenance["Half Time/Full Time"] = _prov(htft_rows)
        raw_markets["Half Time/Full Time"] = htft_raw

    return markets, source, provenance, raw_markets


def filter_synthetic(dataset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Defensive guard: strip any market whose provenance is explicitly not live.

    Kept as an explicit, testable safety net so that no future code path can leak
    a model-derived price into the export. A market with no provenance entry at
    all is left in place so programmatic validation can flag it loudly instead of
    the pipeline silently discarding real data.
    """
    for group in dataset:
        for match in group.get("matches", []) or []:
            src = match.get("market_source") or {}
            markets = match.get("markets") or {}
            for name in list(markets.keys()):
                src_val = src.get(name)
                if src_val is None:
                    continue
                if str(src_val).lower() in _OBVIOUSLY_SYNTHETIC or src_val != "live":
                    markets.pop(name, None)
                    src.pop(name, None)
    return dataset

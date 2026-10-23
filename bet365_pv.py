"""
Bet365 France — ANJ Price Variance (PV) Engine  v2.0
====================================================
Single source of truth for turning a raw feed odd (the number Bet365's
binary/WebSocket feed hands the client) into the exact decimal odd the
French market renders on screen under ANJ TRJ ceilings.

Mirrors the behaviour of Bet365's own client library:

    window.PriceVarianceLib.pvOdds.getAdjustmentValue(
        rawDecimal, ki, l3, marketId, 'PV_CHARTS'
    )

Semantics that are load-bearing:

  * getAdjustmentValue() returns a DEDUCTION value, or a falsy value
    (false / null / undefined) when NO chart row applies to that
    (chart, market) pair.  A falsy return means "leave the price alone".
  * The chart is NOT always Chart 6.  Which chart applies is chosen by the
    (ki classification, l3 league, marketId) tuple.  Chart 6 is the FR ANJ
    standard for the main soccer markets and is the default here, but a
    per-market map can override it (pv_market_map.json) and the live
    calibrator (pv_calibrate.py) can regenerate it from the site itself.
  * Rounding: 3 decimals when the adjusted odd is < 1.10, else 2 decimals.
  * Floor: the minimum displayed odd is 1.01.

Two ways to get the on-screen number, in order of trust:

  1. read it straight off the DOM         -> screen_odd_from_display()
     (immune to boosts, logged-in adjustments, and chart drift)
  2. reconstruct it from the feed odd     -> screen_odd()
     (used for the audit trail and when only the feed is available)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

CHARTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bet365_pv_charts.json")
MARKET_MAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pv_market_map.json")

DEFAULT_CHART_ID = "6"
MIN_SCREEN_ODD = 1.01

# ─────────────────────────────────────────────────────────────────────────────
# Embedded Chart 6 (French ANJ TRJ standard).  Used only if the charts file
# is missing so the default path never silently falls back to the wrong chart.
# ─────────────────────────────────────────────────────────────────────────────
_EMBEDDED_CHART_6: List[Dict[str, float]] = [
    {"LR": 1.0, "UR": 1.001, "PV": 0.0}, {"LR": 1.001, "UR": 1.002, "PV": 0.0},
    {"LR": 1.002, "UR": 1.003, "PV": 0.001}, {"LR": 1.003, "UR": 1.004, "PV": 0.0015},
    {"LR": 1.004, "UR": 1.006, "PV": 0.002}, {"LR": 1.006, "UR": 1.008, "PV": 0.003},
    {"LR": 1.008, "UR": 1.01, "PV": 0.004}, {"LR": 1.01, "UR": 1.015, "PV": 0.005},
    {"LR": 1.015, "UR": 1.02, "PV": 0.007}, {"LR": 1.02, "UR": 1.025, "PV": 0.009},
    {"LR": 1.025, "UR": 1.03, "PV": 0.012}, {"LR": 1.03, "UR": 1.04, "PV": 0.014},
    {"LR": 1.04, "UR": 1.05, "PV": 0.017}, {"LR": 1.05, "UR": 1.06, "PV": 0.022},
    {"LR": 1.06, "UR": 1.08, "PV": 0.028}, {"LR": 1.08, "UR": 1.1, "PV": 0.035},
    {"LR": 1.1, "UR": 1.12, "PV": 0.035}, {"LR": 1.12, "UR": 1.15, "PV": 0.035},
    {"LR": 1.15, "UR": 1.2, "PV": 0.04}, {"LR": 1.2, "UR": 1.25, "PV": 0.04},
    {"LR": 1.25, "UR": 1.3, "PV": 0.04}, {"LR": 1.3, "UR": 1.35, "PV": 0.04},
    {"LR": 1.35, "UR": 1.4, "PV": 0.04}, {"LR": 1.4, "UR": 1.45, "PV": 0.04},
    {"LR": 1.45, "UR": 1.5, "PV": 0.04}, {"LR": 1.5, "UR": 1.55, "PV": 0.05},
    {"LR": 1.55, "UR": 1.6, "PV": 0.05}, {"LR": 1.6, "UR": 1.7, "PV": 0.05},
    {"LR": 1.7, "UR": 1.8, "PV": 0.05}, {"LR": 1.8, "UR": 1.9, "PV": 0.05},
    {"LR": 1.9, "UR": 2.0, "PV": 0.05}, {"LR": 2.0, "UR": 2.1, "PV": 0.05},
    {"LR": 2.1, "UR": 2.2, "PV": 0.06}, {"LR": 2.2, "UR": 2.3, "PV": 0.06},
    {"LR": 2.3, "UR": 2.4, "PV": 0.06}, {"LR": 2.4, "UR": 2.5, "PV": 0.06},
    {"LR": 2.5, "UR": 2.6, "PV": 0.07}, {"LR": 2.6, "UR": 2.7, "PV": 0.07},
    {"LR": 2.7, "UR": 2.8, "PV": 0.07}, {"LR": 2.8, "UR": 2.9, "PV": 0.08},
    {"LR": 2.9, "UR": 3.0, "PV": 0.08}, {"LR": 3.0, "UR": 3.2, "PV": 0.08},
    {"LR": 3.2, "UR": 3.4, "PV": 0.1}, {"LR": 3.4, "UR": 3.6, "PV": 0.1},
    {"LR": 3.6, "UR": 3.8, "PV": 0.1}, {"LR": 3.8, "UR": 4.0, "PV": 0.1},
    {"LR": 4.0, "UR": 4.5, "PV": 0.15}, {"LR": 4.5, "UR": 5.0, "PV": 0.15},
    {"LR": 5.0, "UR": 5.5, "PV": 0.2}, {"LR": 5.5, "UR": 6.0, "PV": 0.2},
    {"LR": 6.0, "UR": 6.5, "PV": 0.2}, {"LR": 6.5, "UR": 7.0, "PV": 0.25},
    {"LR": 7.0, "UR": 8.0, "PV": 0.3}, {"LR": 8.0, "UR": 9.0, "PV": 0.4},
    {"LR": 9.0, "UR": 11.0, "PV": 0.5}, {"LR": 11.0, "UR": 13.0, "PV": 1.0},
    {"LR": 13.0, "UR": 15.0, "PV": 1.5}, {"LR": 15.0, "UR": 17.0, "PV": 2.0},
    {"LR": 17.0, "UR": 19.0, "PV": 2.5}, {"LR": 19.0, "UR": 21.0, "PV": 3.0},
    {"LR": 21.0, "UR": 26.0, "PV": 3.5}, {"LR": 26.0, "UR": 31.0, "PV": 4.0},
    {"LR": 31.0, "UR": 41.0, "PV": 4.5}, {"LR": 41.0, "UR": 51.0, "PV": 5.0},
    {"LR": 51.0, "UR": 61.0, "PV": 5.0}, {"LR": 61.0, "UR": 71.0, "PV": 6.0},
    {"LR": 71.0, "UR": 81.0, "PV": 6.0}, {"LR": 81.0, "UR": 91.0, "PV": 7.0},
    {"LR": 91.0, "UR": 101.0, "PV": 8.0}, {"LR": 101.0, "UR": 121.0, "PV": 10.0},
    {"LR": 121.0, "UR": 151.0, "PV": 11.0}, {"LR": 151.0, "UR": 201.0, "PV": 12.0},
    {"LR": 201.0, "UR": 351.0, "PV": 14.0}, {"LR": 351.0, "UR": 501.0, "PV": 15.0},
    {"LR": 501.0, "UR": 751.0, "PV": 20.0}, {"LR": 751.0, "UR": 1001.0, "PV": 30.0},
    {"LR": 1001.0, "UR": 10001.0, "PV": 50.0},
]

_CHARTS_CACHE: Optional[Dict[str, List[Dict[str, float]]]] = None
_MARKET_MAP_CACHE: Optional[Dict[str, Any]] = None

_DISPLAY_ODD_RE = re.compile(r"\d+(?:[.,]\d+)?")


# ─────────────────────────────────────────────────────────────────────────────
# Chart / market-map loading
# ─────────────────────────────────────────────────────────────────────────────
def load_charts() -> Dict[str, List[Dict[str, float]]]:
    """Load the full PV chart registry (PV_CHARTS~1 .. PV_CHARTS~N)."""
    global _CHARTS_CACHE
    if _CHARTS_CACHE is not None:
        return _CHARTS_CACHE

    charts: Dict[str, List[Dict[str, float]]] = {}
    if os.path.exists(CHARTS_FILE):
        try:
            with open(CHARTS_FILE, "r", encoding="utf-8") as fh:
                charts = json.load(fh)
        except Exception:
            charts = {}

    if not isinstance(charts, dict):
        charts = {}

    # Guarantee the ANJ standard chart exists so the default path is never wrong.
    charts.setdefault(f"PV_CHARTS~{DEFAULT_CHART_ID}", _EMBEDDED_CHART_6)
    _CHARTS_CACHE = charts
    return charts


def load_market_map() -> Dict[str, Any]:
    """Load the (sport, market) -> chart-id map. Falls back to a sane default."""
    global _MARKET_MAP_CACHE
    if _MARKET_MAP_CACHE is not None:
        return _MARKET_MAP_CACHE

    cfg: Dict[str, Any] = {"default": DEFAULT_CHART_ID, "sports": {}, "markets": {}}
    if os.path.exists(MARKET_MAP_FILE):
        try:
            with open(MARKET_MAP_FILE, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass
    _MARKET_MAP_CACHE = cfg
    return cfg


def resolve_chart_id(sport: str = "", market: str = "") -> str:
    """Pick the chart id for a (sport, market) pair.

    Resolution order: exact market key -> sport default -> global default.
    Keys are matched case-insensitively against the stock market names the
    pipeline emits (e.g. "Match Result", "Both Teams to Score").
    """
    cfg = load_market_map()
    markets = cfg.get("markets") or {}
    sports = cfg.get("sports") or {}

    m_key = (market or "").strip().lower()
    if m_key and isinstance(markets, dict):
        for k, v in markets.items():
            if str(k).strip().lower() == m_key:
                return str(v)

    s_key = (sport or "").strip().lower()
    if s_key and isinstance(sports, dict):
        for k, v in sports.items():
            if str(k).strip().lower() == s_key:
                return str(v)

    return str(cfg.get("default", DEFAULT_CHART_ID))


# ─────────────────────────────────────────────────────────────────────────────
# Core adjustment maths (mirrors getAdjustmentValue)
# ─────────────────────────────────────────────────────────────────────────────
def get_pv_adjustment(raw_decimal: float, chart_id: str = DEFAULT_CHART_ID) -> Optional[float]:
    """Return the PV deduction for a raw odd, or None when no row applies.

    None mirrors the library's falsy return and means "do not adjust".
    """
    charts = load_charts()
    chart_key = f"PV_CHARTS~{chart_id}"
    chart = charts.get(chart_key)
    if chart is None:
        chart = charts.get(f"PV_CHARTS~{DEFAULT_CHART_ID}")
    if not chart:
        return None

    for row in chart:
        try:
            lr = float(row.get("LR", 0.0))
            ur = float(row.get("UR", 0.0))
            pv = float(row.get("PV", 0.0))
        except (TypeError, ValueError):
            continue
        if lr <= raw_decimal <= ur:
            return pv
    return None


def _round_screen(adjusted: float) -> float:
    """Bet365 display precision: 3dp below 1.10, 2dp otherwise."""
    if adjusted < 1.10:
        return round(adjusted, 3)
    return round(adjusted, 2)


def apply_bet365_pv(val: Any, chart_id: str = DEFAULT_CHART_ID) -> float:
    """Reconstruct the on-screen odd from a raw feed odd under one chart.

    Backward-compatible name kept for existing call sites.  When no chart row
    applies the raw odd is returned unchanged (falsy-return semantics).
    """
    try:
        raw_dec = float(str(val).replace(",", ".").strip())
    except (TypeError, ValueError):
        return MIN_SCREEN_ODD

    if raw_dec <= MIN_SCREEN_ODD:
        return MIN_SCREEN_ODD

    pv_adj = get_pv_adjustment(raw_dec, chart_id=chart_id)
    if pv_adj is None:
        return _round_screen(raw_dec)

    adjusted = max(MIN_SCREEN_ODD, raw_dec - pv_adj)
    return _round_screen(adjusted)


def screen_odd(val: Any, sport: str = "", market: str = "") -> float:
    """Reconstruct the on-screen odd using the chart resolved for (sport, market)."""
    chart_id = resolve_chart_id(sport, market)
    return apply_bet365_pv(val, chart_id=chart_id)


def format_french_odd(val: Any, chart_id: str = DEFAULT_CHART_ID) -> str:
    """Raw odd -> on-screen string ('2.82')."""
    adj = apply_bet365_pv(val, chart_id=chart_id)
    return f"{adj:.3f}" if adj < 1.10 else f"{adj:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# Ground-truth path: the number already rendered on screen
# ─────────────────────────────────────────────────────────────────────────────
def screen_odd_from_display(text: Any) -> Optional[str]:
    """Extract and normalise the on-screen decimal odd from a DOM string.

    This is the authoritative value: it already includes the ANJ deduction,
    any logged-in account adjustment, and any price boost, so it beats any
    reconstruction from the feed.  Returns None when no price is present
    (e.g. a suspended market rendered as '-', 'SP', or blank).
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s or s in {"-", "–", "—", "SP", "N/A", "NA", ""}:
        return None
    m = _DISPLAY_ODD_RE.search(s.replace(",", "."))
    if not m:
        return None
    try:
        f = float(m.group(0))
    except ValueError:
        return None
    if f <= 1.0:
        return None
    return f"{f:.3f}" if f < 1.10 else f"{f:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# Self-check + live calibration
# ─────────────────────────────────────────────────────────────────────────────
def verify_chart6() -> bool:
    """Assert the worked ANJ Chart 6 example: 2.90/3.50/2.35 -> 2.82/3.40/2.29."""
    return (
        apply_bet365_pv(2.90, "6") == 2.82
        and apply_bet365_pv(3.50, "6") == 3.40
        and apply_bet365_pv(2.35, "6") == 2.29
    )


_CALIBRATE_JS = r"""
() => {
    const out = { charts: {}, liveExample: null, keys: Object.keys(window).filter(k =>
        /price|pv|odds/i.test(k)) };
    const lib = window.PriceVarianceLib || window.ns_pricevariancelib ||
                window.ns_pricevariancelib_util;
    if (!lib) return out;
    const chartReg = lib.pvOdds && lib.pvOdds.PV_CHARTS ? lib.pvOdds.PV_CHARTS
                     : (lib.PV_CHARTS ? lib.PV_CHARTS : null);
    if (chartReg) {
        for (const key of Object.keys(chartReg)) {
            const rows = chartReg[key];
            if (Array.isArray(rows)) {
                out.charts[key] = rows.map(r => ({
                    LR: r.LR !== undefined ? r.LR : r.lr,
                    UR: r.UR !== undefined ? r.UR : r.ur,
                    PV: r.PV !== undefined ? r.PV : r.pv
                }));
            }
        }
    }
    if (lib.pvOdds && typeof lib.pvOdds.getAdjustmentValue === 'function') {
        out.liveExample = {
            '2.90': lib.pvOdds.getAdjustmentValue('2.9000', '1', '', '40', 'PV_CHARTS'),
            '3.50': lib.pvOdds.getAdjustmentValue('3.5000', '1', '', '40', 'PV_CHARTS'),
            '2.35': lib.pvOdds.getAdjustmentValue('2.3500', '1', '', '40', 'PV_CHARTS')
        };
    }
    return out;
}
"""


def calibrate_from_page(page) -> Dict[str, Any]:
    """Dump the live PriceVarianceLib charts off an open bet365.fr tab.

    `page` is a Playwright Page already sitting on bet365.fr.  Returns the raw
    calibration payload; use pv_calibrate.py for the CLI wrapper that writes
    bet365_pv_charts.json.
    """
    try:
        return page.evaluate(_CALIBRATE_JS)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "charts": {}, "liveExample": None}


if __name__ == "__main__":
    ok = verify_chart6()
    print(f"[PV] Chart 6 self-check: {'PASS' if ok else 'FAIL'}")
    print(f"     2.90 -> {apply_bet365_pv(2.90, '6')}")
    print(f"     3.50 -> {apply_bet365_pv(3.50, '6')}")
    print(f"     2.35 -> {apply_bet365_pv(2.35, '6')}")
    charts = load_charts()
    print(f"[PV] Charts loaded: {sorted(charts.keys())}")

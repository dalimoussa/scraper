"""
pv_calibrate.py  —  Live ANJ Price Variance calibrator for Bet365 France
========================================================================
Reads Bet365's *own* client-side Price Variance library straight out of an
open bet365.fr tab and (optionally) rewrites `bet365_pv_charts.json` with the
charts the French site is actually serving today.

Why this exists
---------------
The client saw odds on screen that did not match our feed->screen conversion.
The conversion is only ever as correct as the chart table it uses.  Rather than
trust a hand-copied table, this tool asks the site for the truth:

    window.PriceVarianceLib.pvOdds.getAdjustmentValue(...)
    window.PriceVarianceLib.pvOdds.PV_CHARTS

Usage
-----
    # Inspect only (no writes):
    python pv_calibrate.py

    # Calibrate and merge charts into bet365_pv_charts.json:
    python pv_calibrate.py --write

    # Attach to an already-running Chrome on the CDP port instead of launching:
    python pv_calibrate.py --connect --port 9222 --write

The script never invents data: if it cannot reach the library it says so and
exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from bet365_pv import (
    CHARTS_FILE,
    MARKET_MAP_FILE,
    apply_bet365_pv,
    calibrate_from_page,
    load_charts,
    verify_chart6,
)

DEFAULT_URL = "https://www.bet365.fr/#/AS/B1/"


def _merge_charts(existing: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    for key, rows in (fresh or {}).items():
        if isinstance(rows, list) and rows:
            merged[key] = rows
    return merged


def _probe_live(page) -> Dict[str, Any]:
    """Ask the page for its own adjustment on the worked ANJ example."""
    js = r"""
    () => {
        const lib = window.PriceVarianceLib || window.ns_pricevariancelib ||
                    window.ns_pricevariancelib_util;
        if (!lib || !lib.pvOdds || typeof lib.pvOdds.getAdjustmentValue !== 'function') {
            return {available: false};
        }
        const probe = (raw, marketId) => lib.pvOdds.getAdjustmentValue(
            Number(raw).toFixed(4), '1', '', String(marketId), 'PV_CHARTS');
        return {
            available: true,
            matchResult: {
                '2.90': probe('2.90', '40'),
                '3.50': probe('3.50', '40'),
                '2.35': probe('2.35', '40')
            }
        };
    }
    """
    try:
        return page.evaluate(js)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate Bet365 France ANJ PV charts from the live site.")
    parser.add_argument("--url", default=DEFAULT_URL, help="bet365.fr URL to open/calibrate from.")
    parser.add_argument("--connect", action="store_true", help="Attach to an existing Chrome on the CDP port.")
    parser.add_argument("--port", type=int, default=9222, help="CDP port (default 9222).")
    parser.add_argument("--write", action="store_true", help="Merge live charts into bet365_pv_charts.json.")
    args = parser.parse_args()

    print(f"[PV] Local chart self-check (Chart 6): {'PASS' if verify_chart6() else 'FAIL'}")
    print(f"     2.90 -> {apply_bet365_pv(2.90, '6')} | 3.50 -> {apply_bet365_pv(3.50, '6')} | 2.35 -> {apply_bet365_pv(2.35, '6')}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[PV] playwright is not installed; cannot calibrate live. pip install -r requirements.txt")
        return 2

    payload: Dict[str, Any] = {}
    probe: Dict[str, Any] = {}
    with sync_playwright() as pw:
        if args.connect:
            try:
                browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
            except Exception as exc:  # noqa: BLE001
                print(f"[PV] Could not connect over CDP on {args.port}: {exc}")
                return 3
        else:
            browser = pw.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(locale="fr-FR")
            page = context.new_page()

        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            payload = calibrate_from_page(page)
            probe = _probe_live(page)
        except Exception as exc:  # noqa: BLE001
            print(f"[PV] Calibration navigation error: {exc}")
            payload = {"charts": {}}
        finally:
            if not args.connect:
                browser.close()

    charts = payload.get("charts") or {}
    print(f"[PV] Live charts discovered: {sorted(charts.keys())}")
    if probe:
        print(f"[PV] Live library available: {probe.get('available')}")
        if probe.get("matchResult"):
            print(f"     live getAdjustmentValue(2.90/3.50/2.35, marketId=40) = {probe.get('matchResult')}")

    if not charts:
        print("[PV] No charts returned by the page. Nothing written.")
        return 1

    if args.write:
        existing = {}
        if os.path.exists(CHARTS_FILE):
            try:
                with open(CHARTS_FILE, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
            except Exception:
                existing = {}
        merged = _merge_charts(existing, charts)
        with open(CHARTS_FILE, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2)
        print(f"[PV] Wrote {len(merged)} charts to {CHARTS_FILE} at {datetime.now(timezone.utc).isoformat()}")
        print(f"[PV] Market map lives at {MARKET_MAP_FILE}")
    else:
        print("[PV] Dry run. Re-run with --write to persist.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

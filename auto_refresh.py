"""
Bet365 Auto-Refresh Daemon
==========================
Automatically re-scrapes all sports every 2 minutes and writes
all_matches.json atomically so the data is always fresh.

Usage:
    python auto_refresh.py
    python auto_refresh.py --interval 120       # seconds between refreshes (default: 120)
    python auto_refresh.py --out all_matches.json
    python auto_refresh.py --interval 60 --out all_matches.json

Stop: Ctrl+C
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# ── Import the scrape engine ───────────────────────────────────────────────────
try:
    from bet365_engine import scrape_all_sports, is_future_match
except ImportError as exc:
    print(f"[FATAL] Cannot import bet365_engine: {exc}")
    sys.exit(1)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def _count_matches(data) -> int:
    if not data:
        return 0
    return sum(len(s.get("matches", [])) for s in data)


def _write_atomic(data, out_path: str) -> None:
    """Write JSON atomically via a .tmp swap so the file is never half-written."""
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def _preserve_existing(out_path: str) -> None:
    """Purge arrived/expired matches from previous file if scrape returned 0 matches."""
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            cleaned = []
            for sp in existing:
                vm = [m for m in sp.get("matches", []) if is_future_match(m)]
                if vm:
                    cleaned.append({"sport": sp.get("sport"), "matches": vm})
            _write_atomic(cleaned, out_path)
            total = sum(len(s.get("matches", [])) for s in cleaned)
            print(f"  [Notice] Purged arrived/expired matches from previous file — {total} future matches active.")
            return
        except Exception:
            pass
        size_kb = os.path.getsize(out_path) / 1024
        print(f"  [Notice] Keeping previous file ({size_kb:.1f} KB) — scrape returned 0 matches.")


# ── Main loop ──────────────────────────────────────────────────────────────────

def run_loop(interval: int, out_path: str) -> None:
    cycle = 0
    print("=" * 62)
    print("  Bet365 Auto-Refresh Daemon")
    print(f"  Refresh interval : {interval}s  ({interval // 60}m {interval % 60}s)")
    print(f"  Output file      : {os.path.abspath(out_path)}")
    print(f"  Domain           : https://www.bet365.fr")
    print("  Stop             : Ctrl+C")
    print("=" * 62)

    while True:
        cycle += 1
        print(f"\n[{_now()}] ── Cycle #{cycle} starting ───────────────────────────────")

        try:
            data = scrape_all_sports()
            n = _count_matches(data)

            if n > 0:
                _write_atomic(data, out_path)
                sports = [s.get("sport", "?") for s in data]
                print(f"  ✓  Saved {n} matches across {len(data)} sports → {out_path}")
                print(f"     Sports: {', '.join(sports)}")
            else:
                _preserve_existing(out_path)

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # Never crash the loop — log and retry next cycle
            print(f"  [ERROR] Scrape cycle #{cycle} failed: {exc}")

        print(f"  Next refresh in {interval}s  ({_now()} + {interval // 60}m)…")

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            raise


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bet365 Auto-Refresh Daemon — keeps all_matches.json live."
    )
    parser.add_argument(
        "--interval", type=int, default=120,
        help="Seconds between scrape cycles (default: 120 = 2 minutes)"
    )
    parser.add_argument(
        "--out", default="all_matches.json",
        help="Output JSON path (default: all_matches.json)"
    )
    args = parser.parse_args()

    try:
        run_loop(interval=args.interval, out_path=args.out)
    except KeyboardInterrupt:
        print(f"\n\n[{_now()}] Auto-refresh daemon stopped. Goodbye!")


if __name__ == "__main__":
    main()

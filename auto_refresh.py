"""
Bet365 Pure CDP Auto-Refresh Daemon
====================================
Periodically re-scrapes target sports (Big 5 Soccer + UCL/UEL, Tennis, Basketball,
Handball, Cycling, Golf, F1) via Chrome DevTools Protocol and atomically updates
all_matches.json.

Usage:
    python auto_refresh.py
    python auto_refresh.py --interval 180       # seconds between refreshes (default: 180)
    python auto_refresh.py --out all_matches.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    from bet365_engine import scrape_all_sports
except ImportError as exc:
    print(f"[FATAL] Cannot import bet365_engine: {exc}")
    sys.exit(1)


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


def run_loop(interval: int, out_path: str) -> None:
    cycle = 0
    print("=" * 64)
    print("  Bet365 Pure CDP Auto-Refresh Daemon")
    print(f"  Refresh interval : {interval}s  ({interval // 60}m {interval % 60}s)")
    print(f"  Output file      : {os.path.abspath(out_path)}")
    print("  Target Sports    : Big 5 Soccer, Tennis, Basketball, Handball, Cycling, Golf, F1")
    print("  Stop             : Ctrl+C")
    print("=" * 64)

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
                if os.path.exists(out_path):
                    size_kb = os.path.getsize(out_path) / 1024
                    print(f"  [Notice] Keeping previous file ({size_kb:.1f} KB) — cycle returned 0 matches.")

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"  [ERROR] Scrape cycle #{cycle} failed: {exc}")

        print(f"  Next refresh in {interval}s  ({_now()} + {interval // 60}m)...")

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Bet365 Pure CDP Auto-Refresh Daemon"
    )
    parser.add_argument(
        "--interval", type=int, default=180,
        help="Seconds between scrape cycles (default: 180 = 3 minutes)"
    )
    parser.add_argument(
        "--out", default="all_matches.json",
        help="Output JSON path (default: all_matches.json)"
    )
    args = parser.parse_args()

    try:
        run_loop(interval=args.interval, out_path=args.out)
    except KeyboardInterrupt:
        print(f"\n\n[{_now()}] Auto-refresh daemon stopped.")


if __name__ == "__main__":
    main()

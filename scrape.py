"""
bet365.fr scraper  -  High-performance multi-market, in-play & parallel scraper.

Usage:
    python scrape.py                                    # All sports with parallel workers
    python scrape.py --sport Soccer                     # Soccer (deep + featured + live)
    python scrape.py --sport Tennis --live              # Live in-play Tennis matches only
    python scrape.py --concurrency 8 --out all.json     # Fast scrape with 8 parallel threads
    python scrape.py --sport Basketball --no-live       # Basketball pre-match only
"""

import argparse
import json
import sys
import time

from datetime import datetime

from bet365 import Bet365AndroidSession
from bet365.scraper import (
    clone_session,
    is_prematch_future,
    is_valid_prematch,
    load_config,
    scrape_all_parallel,
    scrape_sport,
)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape bet365.fr upcoming pre-matches and odds to JSON"
    )
    parser.add_argument(
        "--sport",
        default=None,
        help="Target sport name (default: all sports, e.g. 'Soccer', 'Tennis', 'Basketball')",
    )
    parser.add_argument(
        "--concurrency",
        "-j",
        type=int,
        default=5,
        help="Number of concurrent worker threads for parallel scraping (default: 5)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Scrape ONLY live in-play matches (overrides pre-match default)",
    )
    parser.add_argument(
        "--no-deep",
        action="store_true",
        default=False,
        help="Disable deep competition/league drill-down",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=0,
        help="Run continuously every N seconds (e.g. --interval 60). Default: 0 (single run)",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        default=0.15,
        help="Random timing variation (+/- fraction of interval, e.g. 0.15 for +/-15%%) to prevent robotic pattern blocks (default: 0.15)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Path to save JSON output (atomic update)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.json",
        help="Config file path (default: config.json)",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level (default: 2)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    session = Bet365AndroidSession(
        config["api_url"],
        config["api_key"],
        proxy=config.get("proxy") or None,
        verify=False,
        host=config.get("host", "www.bet365.fr"),
    )

    def _ensure_connected():
        print("[*] Connecting to bet365.fr & bootstrapping session ...", file=sys.stderr)
        session.go_homepage()

    _ensure_connected()

    print("[*] Fetching available sports ...", file=sys.stderr)
    all_sports = session.extract_available_sports()

    # Filter by sport if requested
    if args.sport:
        target = [s for s in all_sports if s.name.lower() == args.sport.lower()]
        if not target:
            available = [s.name for s in all_sports]
            print(
                f"[!] Sport '{args.sport}' not found. Available: {available}",
                file=sys.stderr,
            )
            sys.exit(1)
        sports_to_scrape = target
    else:
        # Filter out static banner pods
        sports_to_scrape = [s for s in all_sports if s.name not in ["Offers", "Upcoming"]]

    deep_mode = not args.no_deep
    live_mode = args.live
    prematch_mode = not args.live

    cycle = 0

    while True:
        cycle += 1
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        mode_label = "live in-play" if live_mode else "upcoming pre-matches"
        print(
            f"[{now_str}] [Cycle #{cycle}] Scraping {len(sports_to_scrape)} sport(s) ({mode_label}, concurrency={args.concurrency}, deep={deep_mode}) ...",
            file=sys.stderr,
        )

        t0 = time.time()
        try:
            if len(sports_to_scrape) == 1:
                sp = sports_to_scrape[0]
                data = scrape_sport(
                    session,
                    sp,
                    deep=deep_mode,
                    include_live=live_mode,
                    prematch_only=prematch_mode,
                )
                output = [data] if data["matches"] else []
            else:
                output = scrape_all_parallel(
                    session,
                    sports_to_scrape,
                    max_workers=args.concurrency,
                    deep=deep_mode,
                    include_live=live_mode,
                    prematch_only=prematch_mode,
                )
        except Exception as err:
            print(f"[!] Scrape error in cycle #{cycle}: {err}. Re-bootstrapping session ...", file=sys.stderr)
            try:
                _ensure_connected()
            except Exception as re_err:
                print(f"[!] Re-bootstrap failed: {re_err}", file=sys.stderr)
            output = []

        # Extra verification filter: purge any match that has already started as of current time
        if prematch_mode and output:
            filtered_output = []
            for sp_data in output:
                valid_matches = [
                    m for m in sp_data.get("matches", [])
                    if is_valid_prematch(m, now_dt)
                ]
                if valid_matches:
                    filtered_output.append({
                        "sport": sp_data["sport"],
                        "matches": valid_matches
                    })
            output = filtered_output

        t1 = time.time()
        total_matches = sum(len(s["matches"]) for s in output)
        print(
            f"[{now_str}] [Cycle #{cycle}] Done: {total_matches} valid {mode_label} across {len(output)} sports in {t1 - t0:.2f}s",
            file=sys.stderr,
        )

        # Synchronize and atomically write output
        result_json = json.dumps(output, ensure_ascii=False, indent=args.indent)
        if args.out:
            tmp_out = f"{args.out}.tmp"
            with open(tmp_out, "w", encoding="utf-8") as fh:
                fh.write(result_json)
            import os
            os.replace(tmp_out, args.out)
            print(f"[{now_str}] [Cycle #{cycle}] Synchronized to {args.out}", file=sys.stderr)
        else:
            print(result_json)

        # Exit if single-run mode
        if args.interval <= 0:
            break

        # Calculate jittered sleep time to avoid robotic anti-bot patterns
        jitter_delta = args.interval * args.jitter * (2 * (0.5 - (time.time() % 1)))
        sleep_secs = max(5.0, args.interval + jitter_delta)
        print(f"[*] Sleeping {sleep_secs:.1f}s until next sync (Ctrl+C to stop) ...\n", file=sys.stderr)
        try:
            time.sleep(sleep_secs)
        except KeyboardInterrupt:
            print("\n[*] Stopped by user. Exiting cleanly.", file=sys.stderr)
            break


if __name__ == "__main__":
    main()

"""
Bet365 France Multi-Sport Real-Time Automation Pipeline
=======================================================
Senior Python Automation Engineer Edition

Extracts verified, real-time sports data from Bet365 France via Chrome DevTools Protocol (CDP)
and exports validated data to all_matches.json.

Strict Data Constraints:
- Soccer: 1X2, O/U 2.5, BTTS, Double Chance, DNB
- Tennis: ATP Shanghai Match Winner
- Basketball: EuroLeague Point Spread, Total >= 100.0, Moneyline
- Handball: Starligue/EHF Handicap, Total <= 90.0, Match Result
- Cycling: Active race odds or empty list
- Formula 1: Race Winner, Podium
- Golf: Outright winner markets with player rosters (or empty list if suspended)
- Programmatic validation: Zero synthetic data guarantee & cross-sport contamination prevention.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

from scraper_engine import run_full_pipeline
from validation import validate_pipeline_dataset


def main():
    parser = argparse.ArgumentParser(description="Bet365 France Live Multi-Sport Scraper")
    parser.add_argument("--out", default="all_matches.json", help="Output file path (default: all_matches.json)")
    parser.add_argument("--verify-only", action="store_true", help="Only validate existing JSON file without scraping")
    args = parser.parse_args()

    if args.verify_only:
        if not os.path.exists(args.out):
            print(f"[ERROR] Target file {args.out} does not exist for verification.")
            sys.exit(1)
        with open(args.out, "r", encoding="utf-8") as f:
            data = json.load(f)
        ok, errors = validate_pipeline_dataset(data)
        if ok:
            print(f"[VERIFIED] {args.out} passed all data constraints and programmatic validation.")
            sys.exit(0)
        else:
            print(f"[FAILED] Validation errors found in {args.out}:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

    print("=" * 70)
    print("  STARTING BET365 AUTOMATION PIPELINE (LIVE CDP EXTRACTOR)")
    print("=" * 70)

    start_time = time.time()
    raw_dataset = run_full_pipeline()

    print("\n" + "=" * 70)
    print("  RUNNING PROGRAMMATIC VALIDATION ENGINE")
    print("=" * 70)

    is_valid, validation_errors = validate_pipeline_dataset(raw_dataset)

    if not is_valid:
        print("[CRITICAL] Dataset failed strict constraint validation:")
        for err in validation_errors:
            print(f"  [X] {err}")
        print("\nPipeline aborted to prevent invalid or contaminated output from being written.")
        sys.exit(1)

    print("[OK] Programmatic validation passed: ZERO synthetic data, ZERO cross-sport contamination.")

    # Atomic write to target file
    tmp_path = f"{args.out}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(raw_dataset, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, args.out)
    elapsed = time.time() - start_time

    # Summary report
    print("\n" + "=" * 70)
    print("  EXTRACTION & AUDIT REPORT SUMMARY")
    print("=" * 70)
    total_matches = 0
    for sport_group in raw_dataset:
        sp = sport_group["sport"]
        m_list = sport_group["matches"]
        total_matches += len(m_list)
        print(f"  * {sp:<12}: {len(m_list):>3} verified matches / outright events")

    print("-" * 70)
    print(f"  Total Verified Records : {total_matches}")
    print(f"  Execution Time         : {elapsed:.2f} seconds")
    print(f"  Destination Artifact   : {os.path.abspath(args.out)}")
    print("=" * 70)


if __name__ == "__main__":
    main()

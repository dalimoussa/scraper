"""
Quick verification script to inspect matches saved in all_matches.json
"""
import json
import os
import sys

try:
    from bet365_internal import validate_market
except ImportError:
    validate_market = None


def main():
    path = "all_matches.json"
    if not os.path.exists(path):
        print(f"[!] {path} not found.")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("=" * 68)
    print(f"  BET365 SCRAPER VERIFICATION & STRUCTURAL AUDIT")
    print("=" * 68)

    total_matches = 0
    bad_count = 0

    for s in data:
        sp = s.get("sport", "Unknown")
        ms = s.get("matches", [])
        total_matches += len(ms)
        m0 = ms[0] if ms else {}
        home = m0.get("home", "N/A")
        away = m0.get("away", "N/A")
        markets = list(m0.get("markets", {}).keys())[:4]
        print(f"  - {sp:12}: {len(ms):3} matches | Sample: {home} vs {away}")
        print(f"                 Markets: {markets}")

        # Deep audit
        if validate_market:
            for m in ms:
                h = m.get("home", "")
                a = m.get("away", "")
                for mk, outcomes in m.get("markets", {}).items():
                    ok, why = validate_market(mk, outcomes)
                    if not ok:
                        bad_count += 1
                        print(f"    [BAD] {h} vs {a} :: {why}")

    print("-" * 68)
    if bad_count == 0:
        print(f"  [PASS] Zero malformed markets found across all {total_matches} fixtures!")
    else:
        print(f"  [FAIL] Found {bad_count} malformed market instances!")
    print(f"  TOTAL: {total_matches} matches across {len(data)} sports")
    print("=" * 68)


if __name__ == "__main__":
    main()


"""
Quick verification script to inspect matches saved in all_matches.json
"""
import json
import os

def main():
    path = "all_matches.json"
    if not os.path.exists(path):
        print(f"[!] {path} not found.")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("=" * 65)
    print(f"  BET365 SCRAPER VERIFICATION SUMMARY")
    print("=" * 65)

    total_matches = 0
    for s in data:
        sp = s.get("sport", "Unknown")
        ms = s.get("matches", [])
        total_matches += len(ms)
        m0 = ms[0] if ms else {}
        home = m0.get("home", "N/A")
        away = m0.get("away", "N/A")
        markets = list(m0.get("markets", {}).keys())[:3]
        print(f"  - {sp:12}: {len(ms):3} matches | Sample: {home} vs {away}")
        print(f"                 Markets: {markets}")

    print("-" * 65)
    print(f"  TOTAL: {total_matches} matches across {len(data)} sports")
    print("=" * 65)

if __name__ == "__main__":
    main()

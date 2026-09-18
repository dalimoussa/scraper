"""
Bet365 Client Scraper Tool
==========================
Zero-dependency standalone client to fetch and trigger Bet365 odds
scraping from your remote RDP server.

Requirements:
    Python 3.7+ (No external pip packages required!)

Usage:
    # 1. First-time setup (set your RDP / VS Code forwarded URL):
    python client.py --set-url https://your-forwarded-url.app.github.dev

    # 2. Get latest matches (instant):
    python client.py

    # 3. Trigger a fresh live scrape on RDP:
    python client.py --scrape

    # 4. Scrape only specific sports:
    python client.py --scrape --sports Soccer,Tennis

    # 5. Check server status:
    python client.py --status

    # 6. Save to a custom output file:
    python client.py --out my_matches.json
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_config.json")
DEFAULT_URL = "http://localhost:8000"


def load_saved_url() -> str:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                url = cfg.get("server_url", "").strip()
                if url:
                    return url
        except Exception:
            pass
    return DEFAULT_URL


def save_url(url: str) -> None:
    clean_url = url.strip().rstrip("/")
    cfg = {"server_url": clean_url}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print(f"[OK] Server URL saved: {clean_url}")
        print("You can now run 'python client.py' without passing --url.")
    except Exception as e:
        print(f"[ERROR] Failed to save config: {e}")


def make_request(url: str, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Bet365Client/1.0", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            err_json = json.loads(body)
            err_msg = err_json.get("error", body)
        except Exception:
            err_msg = body
        print(f"[ERROR] Server HTTP {e.code}: {err_msg}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[ERROR] Cannot connect to server at {url}")
        print(f"Reason: {e.reason}")
        print("\nPlease verify:")
        print("  1. The RDP server script is running (server.py).")
        print("  2. In VS Code on the RDP, the forwarded port is set to 'Public'.")
        print("  3. Your server URL is correct.")
        sys.exit(1)


def display_matches(data: list, out_path: str = "matches.json") -> None:
    if not isinstance(data, list):
        print(f"[!] Unexpected response format from server: {type(data)}")
        return

    total_m = sum(len(s.get("matches", [])) for s in data)
    print("\n" + "=" * 66)
    print("  BET365 SCRAPED ODDS - RESULTS SUMMARY")
    print("=" * 66)

    for sport_group in data:
        sp = sport_group.get("sport", "Unknown")
        matches = sport_group.get("matches", [])
        m0 = matches[0] if matches else {}
        home = m0.get("home", "")
        away = m0.get("away", "")
        vs_str = f"{home} vs {away}" if home and away else (home or "Event")
        markets = list(m0.get("markets", {}).keys())[:3]

        print(f"  - {sp:12}: {len(matches):3} matches | Sample: {vs_str}")
        if markets:
            print(f"                 Markets: {markets}")

    print("-" * 66)
    print(f"  TOTAL: {total_m} matches collected across {len(data)} sports")
    print("=" * 66)

    # Save to file
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size_kb = os.path.getsize(out_path) / 1024
        print(f"\n[SUCCESS] Saved {total_m} matches to {os.path.abspath(out_path)} ({size_kb:.1f} KB)\n")
    except Exception as e:
        print(f"[ERROR] Failed to save {out_path}: {e}")


def main():
    saved_url = load_saved_url()

    parser = argparse.ArgumentParser(
        description="Bet365 Client Scraper Tool - Fetch & Trigger Remote Scraping"
    )
    parser.add_argument(
        "--url", default=saved_url,
        help=f"RDP / VS Code forwarded API URL (current: {saved_url})"
    )
    parser.add_argument(
        "--set-url", dest="set_url",
        help="Save default server URL to client_config.json and exit"
    )
    parser.add_argument(
        "--scrape", action="store_true",
        help="Trigger a fresh live scrape on the RDP server before downloading"
    )
    parser.add_argument(
        "--sport",
        help="Target single sport (e.g. Soccer, Tennis, Basketball, Handball, Cycling, Golf, F1)"
    )
    parser.add_argument(
        "--sports",
        help="Target multiple comma-separated sports (e.g. Soccer,Tennis,Basketball)"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Check server status and match availability without downloading full data"
    )
    parser.add_argument(
        "--out", default="matches.json",
        help="Local output JSON file path (default: matches.json)"
    )
    args = parser.parse_args()

    # Save URL option
    if args.set_url:
        save_url(args.set_url)
        return

    base_url = args.url.rstrip("/")

    # Check status
    if args.status:
        status_url = f"{base_url}/api/status"
        print(f"[*] Checking server status at: {status_url} ...")
        res = make_request(status_url, timeout=15)
        print("\n" + "=" * 50)
        print("  SERVER STATUS")
        print("=" * 50)
        print(f"  Status        : {res.get('status', 'unknown').upper()}")
        print(f"  Scraping Now  : {'YES' if res.get('is_scraping') else 'NO'}")
        print(f"  Last Scrape   : {res.get('last_scrape') or 'N/A'}")
        print(f"  Total Matches : {res.get('total_matches', 0)}")
        print("  Sports Breakdown:")
        for sp, cnt in res.get("sports", {}).items():
            print(f"    - {sp:12}: {cnt:3} matches")
        print("=" * 50 + "\n")
        return

    # Trigger fresh live scrape
    if args.scrape:
        print(f"[*] Connecting to Bet365 Scraper Server at {base_url} ...")
        sports = args.sports or args.sport
        params = {}
        if sports:
            params["sports"] = sports
        query = ("?" + urllib.parse.urlencode(params)) if params else ""
        scrape_url = f"{base_url}/api/scrape{query}"

        target_desc = sports if sports else "All 7 Sports"
        print(f"[*] Triggering live scrape for [{target_desc}] on RDP server...")
        print("[*] Please wait (this typically takes 30-90 seconds)...")

        t0 = time.time()
        # Generous timeout for full multi-sport scrape
        data = make_request(scrape_url, timeout=600)
        elapsed = time.time() - t0
        print(f"[*] Live scrape finished in {elapsed:.1f}s.")
        display_matches(data, out_path=args.out)
        return

    # Instant fetch (cached matches)
    print(f"[*] Fetching latest matches from {base_url} ...")
    sports = args.sports or args.sport
    params = {}
    if sports:
        params["sports"] = sports
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    matches_url = f"{base_url}/api/matches{query}"

    data = make_request(matches_url, timeout=30)
    display_matches(data, out_path=args.out)


if __name__ == "__main__":
    main()

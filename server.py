"""
Bet365 Scraper RDP API Server
=============================
Lightweight, zero-dependency HTTP server designed to run on RDP / cloud host.
Exposes REST endpoints to trigger scrapes and fetch live odds.

Endpoints:
    GET  /                - Server health and documentation
    GET  /api/status      - Current status, match counts, and last update time
    GET  /api/matches     - Return latest scraped matches (instant, cached)
    GET  /api/scrape      - Trigger live scrape & return fresh matches
    POST /api/scrape      - Trigger live scrape & return fresh matches

Usage:
    python server.py
    python server.py --port 8000
    python server.py --port 8000 --host 0.0.0.0
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

DATA_FILE = os.path.join(SCRIPT_DIR, "all_matches.json")
scrape_lock = threading.Lock()
is_scraping = False
last_scrape_time = None
last_scrape_stats = {}


def get_current_matches(sport_filter=None):
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if sport_filter:
            sf_lowers = [s.strip().lower() for s in sport_filter if s.strip()]
            data = [s for s in data if s.get("sport", "").lower() in sf_lowers]
        return data
    except Exception as e:
        print(f"[ERROR] Failed to read {DATA_FILE}: {e}")
        return []


def trigger_scrape(target_sports=None):
    global is_scraping, last_scrape_time, last_scrape_stats

    with scrape_lock:
        is_scraping = True
        try:
            from bet365_engine import scrape_all_sports

            print(f"\n[SERVER] Triggering scrape for: {target_sports or 'All Sports'}")
            raw_data = scrape_all_sports(target_sports=target_sports)

            # Merge with existing file if only specific sports were scraped
            if target_sports and os.path.exists(DATA_FILE):
                try:
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    t_lowers = [t.lower() for t in target_sports]
                    merged = [s for s in existing if s.get("sport", "").lower() not in t_lowers]
                    merged.extend(raw_data)
                    canonical = ["Soccer", "Tennis", "Basketball", "Handball", "Cycling", "Golf", "F1"]
                    merged.sort(key=lambda s: canonical.index(s["sport"]) if s.get("sport") in canonical else 99)
                    raw_data = merged
                except Exception:
                    pass

            total_m = sum(len(s.get("matches", [])) for s in raw_data)
            if total_m > 0:
                tmp = DATA_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, DATA_FILE)

            last_scrape_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            last_scrape_stats = {
                "sports": len(raw_data),
                "matches": total_m,
                "timestamp": last_scrape_time
            }
            return raw_data
        finally:
            is_scraping = False


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class ScraperAPIHandler(BaseHTTPRequestHandler):

    def _set_cors_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_cors_headers(204)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # 1. Root info / dashboard
        if path == "" or path == "/":
            data = get_current_matches()
            total_m = sum(len(s.get("matches", [])) for s in data)
            sports_list = [s.get("sport") for s in data]
            response = {
                "service": "Bet365 CDP Scraper API",
                "status": "online",
                "is_scraping": is_scraping,
                "last_scrape": last_scrape_time,
                "total_matches": total_m,
                "sports_available": sports_list,
                "endpoints": {
                    "GET /api/status": "Check server status and match counts",
                    "GET /api/matches": "Download latest matches (instant, ?sport=Soccer)",
                    "GET /api/scrape": "Trigger live scrape on RDP and return matches (?sports=Soccer,Tennis)"
                }
            }
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(response, indent=2).encode("utf-8"))
            return

        # 2. Status
        if path == "/api/status":
            data = get_current_matches()
            total_m = sum(len(s.get("matches", [])) for s in data)
            sports_breakdown = {s.get("sport"): len(s.get("matches", [])) for s in data}
            response = {
                "status": "online",
                "is_scraping": is_scraping,
                "last_scrape": last_scrape_time,
                "total_matches": total_m,
                "sports": sports_breakdown
            }
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(response, indent=2).encode("utf-8"))
            return

        # 3. Get matches (cached/instant)
        if path == "/api/matches":
            sport_arg = params.get("sport") or params.get("sports")
            sports = []
            if sport_arg:
                for item in sport_arg:
                    sports.extend([x.strip() for x in item.split(",") if x.strip()])
            matches = get_current_matches(sport_filter=sports if sports else None)
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(matches, ensure_ascii=False).encode("utf-8"))
            return

        # 4. Trigger live scrape
        if path == "/api/scrape":
            sport_arg = params.get("sport") or params.get("sports")
            target_sports = None
            if sport_arg:
                target_sports = []
                for item in sport_arg:
                    target_sports.extend([x.strip() for x in item.split(",") if x.strip()])

            if is_scraping:
                self._set_cors_headers(429)
                self.wfile.write(json.dumps({
                    "error": "A scrape is already in progress. Please wait a moment and check /api/matches."
                }).encode("utf-8"))
                return

            results = trigger_scrape(target_sports=target_sports)
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(results, ensure_ascii=False).encode("utf-8"))
            return

        # 404
        self._set_cors_headers(404)
        self.wfile.write(json.dumps({"error": f"Endpoint '{path}' not found."}).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/api/scrape":
            # Check body for sports
            content_len = int(self.headers.get("Content-Length", 0))
            body_sports = None
            if content_len > 0:
                try:
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                    body_sports = body.get("sports") or body.get("sport")
                    if isinstance(body_sports, str):
                        body_sports = [s.strip() for s in body_sports.split(",") if s.strip()]
                except Exception:
                    pass

            target_sports = body_sports
            if not target_sports:
                sport_arg = params.get("sport") or params.get("sports")
                if sport_arg:
                    target_sports = []
                    for item in sport_arg:
                        target_sports.extend([x.strip() for x in item.split(",") if x.strip()])

            if is_scraping:
                self._set_cors_headers(429)
                self.wfile.write(json.dumps({
                    "error": "A scrape is already in progress. Please wait a moment and check /api/matches."
                }).encode("utf-8"))
                return

            results = trigger_scrape(target_sports=target_sports)
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(results, ensure_ascii=False).encode("utf-8"))
            return

        self._set_cors_headers(404)
        self.wfile.write(json.dumps({"error": f"Endpoint '{path}' not found."}).encode("utf-8"))

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]} {args[2]}\n")


def main():
    parser = argparse.ArgumentParser(description="Bet365 Scraper RDP API Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    server = ThreadedHTTPServer((args.host, args.port), ScraperAPIHandler)
    print("=" * 64)
    print("  Bet365 Scraper RDP API Server")
    print(f"  Listening on : http://{args.host}:{args.port}")
    print(f"  Local access : http://localhost:{args.port}")
    print("  Endpoints:")
    print(f"    - Status   : http://localhost:{args.port}/api/status")
    print(f"    - Matches  : http://localhost:{args.port}/api/matches")
    print(f"    - Scrape   : http://localhost:{args.port}/api/scrape")
    print("=" * 64)
    print("[*] Server is running. Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server stopping...")
        server.shutdown()
        server.server_close()
        print("[*] Server stopped.")


if __name__ == "__main__":
    main()

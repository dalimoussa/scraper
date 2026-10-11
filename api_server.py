"""
Bet365 France Real-Time REST API & Web Dashboard Server
======================================================
Zero-Dependency HTTP Server (Python standard library http.server).
Serves RESTful endpoints for sports data & odds history alongside a modern,
glassmorphic dark-mode web dashboard.

Endpoints:
- GET /                         -> Sleek Dark-Mode Interactive Web Dashboard
- GET /api/matches              -> All scraped sports & matches JSON
- GET /api/matches?sport=<name> -> Filtered matches by sport (e.g. Soccer, Tennis)
- GET /api/history?match_id=<id>-> Chronological odds movement from SQLite
- GET /api/health               -> Server health, record count & freshness
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from history_tracker import get_odds_movement

DEFAULT_DATA_FILE = "all_matches.json"
DEFAULT_DB_FILE = "odds_history.db"


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bet365 Real-Time Intelligence Dashboard</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(18, 24, 38, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent: #00d26a;
      --accent-glow: rgba(0, 210, 106, 0.25);
      --live-red: #ff3366;
      --live-glow: rgba(255, 51, 102, 0.3);
      --text: #f0f4f8;
      --text-muted: #8a99ad;
      --odds-bg: #1c2438;
      --odds-hover: #26334f;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      background-image: radial-gradient(circle at 20% 15%, rgba(0, 210, 106, 0.08) 0%, transparent 40%),
                        radial-gradient(circle at 80% 85%, rgba(0, 150, 255, 0.06) 0%, transparent 50%);
      color: var(--text);
      min-height: 100vh;
      padding: 24px;
    }

    header {
      max-width: 1400px;
      margin: 0 auto 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .brand-badge {
      background: linear-gradient(135deg, #00d26a, #008744);
      color: #fff;
      font-weight: 800;
      font-size: 16px;
      padding: 6px 12px;
      border-radius: 8px;
      letter-spacing: 0.5px;
      box-shadow: 0 0 15px var(--accent-glow);
    }
    .brand-title {
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.5px;
    }
    .brand-subtitle {
      font-size: 13px;
      color: var(--text-muted);
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .btn {
      background: var(--card-bg);
      color: var(--text);
      border: 1px solid var(--card-border);
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .btn:hover {
      background: var(--odds-hover);
      border-color: rgba(255, 255, 255, 0.2);
    }
    .btn-primary {
      background: var(--accent);
      color: #0b0f19;
      border: none;
    }
    .btn-primary:hover {
      background: #05e677;
      box-shadow: 0 0 16px var(--accent-glow);
    }

    .filters {
      max-width: 1400px;
      margin: 0 auto 24px;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 8px;
    }
    .filter-chip {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.2s ease;
    }
    .filter-chip:hover { color: var(--text); border-color: rgba(255,255,255,0.2); }
    .filter-chip.active {
      background: rgba(0, 210, 106, 0.15);
      border-color: var(--accent);
      color: var(--accent);
    }

    .grid {
      max-width: 1400px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 20px;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(12px);
      border-radius: 14px;
      padding: 20px;
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .card:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
      border-color: rgba(255, 255, 255, 0.18);
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      color: var(--text-muted);
    }
    .badge-live {
      background: var(--live-red);
      color: #fff;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 6px;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      box-shadow: 0 0 10px var(--live-glow);
    }
    .badge-live::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #fff;
      animation: pulse 1s infinite alternate;
    }
    @keyframes pulse { from { opacity: 0.4; } to { opacity: 1; } }

    .badge-margin {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      padding: 2px 7px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 11px;
    }

    .match-teams {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .team-name {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: -0.3px;
    }

    .markets-box {
      background: rgba(0, 0, 0, 0.25);
      border-radius: 8px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .market-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .market-title {
      font-size: 12px;
      color: var(--text-muted);
      font-weight: 600;
    }
    .odds-group {
      display: flex;
      gap: 6px;
    }
    .odd-btn {
      background: var(--odds-bg);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .odd-btn:hover { background: var(--odds-hover); }
    .odd-btn .val {
      color: var(--accent);
      font-weight: 700;
      font-family: monospace;
    }

    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 11px;
      color: var(--text-muted);
      border-top: 1px solid rgba(255, 255, 255, 0.05);
      padding-top: 12px;
    }
    .history-link {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      cursor: pointer;
    }
    .history-link:hover { text-decoration: underline; }

    /* Modal for history */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(6px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 999;
      padding: 20px;
    }
    .modal-content {
      background: #141b2d;
      border: 1px solid var(--card-border);
      border-radius: 16px;
      max-width: 600px;
      width: 100%;
      max-height: 80vh;
      overflow-y: auto;
      padding: 24px;
      box-shadow: 0 20px 40px rgba(0,0,0,0.6);
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 12px;
    }
    .timeline-item {
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      font-size: 13px;
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-badge">BET365 LIVE</div>
      <div>
        <div class="brand-title">Multi-Sport Intelligence Hub</div>
        <div class="brand-subtitle">Real-Time Odds, Overrounds & Market Depth</div>
      </div>
    </div>
    <div class="controls">
      <button class="btn" id="btn-auto-toggle" onclick="toggleAutoRefresh()">Auto-Refresh: ON</button>
      <button class="btn btn-primary" onclick="loadData()">Refresh Now</button>
    </div>
  </header>

  <div class="filters" id="filters-container">
    <div class="filter-chip active" onclick="setSportFilter('ALL')">All Sports</div>
  </div>

  <main class="grid" id="matches-grid">
    <div style="color: var(--text-muted); padding: 40px; text-align: center; grid-column: 1/-1;">
      Loading verified sports intelligence...
    </div>
  </main>

  <!-- History Modal -->
  <div class="modal-backdrop" id="history-modal" onclick="closeModal(event)">
    <div class="modal-content" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 id="modal-match-title">Odds Fluctuation Timeline</h3>
        <button class="btn" onclick="closeModal()">Close</button>
      </div>
      <div id="modal-timeline-body">
        Loading historical movements...
      </div>
    </div>
  </div>

  <script>
    let activeSport = 'ALL';
    let fullDataset = [];
    let autoInterval = null;

    async function loadData() {
      try {
        const res = await fetch('/api/matches');
        fullDataset = await res.json();
        renderFilters();
        renderMatches();
      } catch (err) {
        console.error("Fetch error:", err);
      }
    }

    function renderFilters() {
      const container = document.getElementById('filters-container');
      const sports = [...new Set(fullDataset.map(g => g.sport))];
      let html = `<div class="filter-chip ${activeSport === 'ALL' ? 'active' : ''}" onclick="setSportFilter('ALL')">All Sports</div>`;
      for (const sp of sports) {
        const count = fullDataset.find(g => g.sport === sp)?.matches?.length || 0;
        html += `<div class="filter-chip ${activeSport === sp ? 'active' : ''}" onclick="setSportFilter('${sp}')">${sp} (${count})</div>`;
      }
      container.innerHTML = html;
    }

    function setSportFilter(sp) {
      activeSport = sp;
      renderFilters();
      renderMatches();
    }

    function renderMatches() {
      const grid = document.getElementById('matches-grid');
      let matches = [];

      for (const group of fullDataset) {
        if (activeSport === 'ALL' || activeSport === group.sport) {
          for (const m of (group.matches || [])) {
            matches.push({ ...m, sportName: group.sport });
          }
        }
      }

      if (matches.length === 0) {
        grid.innerHTML = `<div style="color: var(--text-muted); padding: 40px; text-align: center; grid-column: 1/-1;">No events available for this category.</div>`;
        return;
      }

      grid.innerHTML = matches.map(m => {
        const isLive = m.is_live;
        const liveInfo = m.live_status || {};
        const markets = m.markets || {};
        const margins = m.market_margins || {};

        let mrHtml = '';
        if (markets['Match Result']) {
          mrHtml = `<div class="market-row">
            <span class="market-title">1X2 Match Result</span>
            <div class="odds-group">
              <span class="odd-btn">1 <span class="val">${markets['Match Result']['1']}</span></span>
              <span class="odd-btn">X <span class="val">${markets['Match Result']['X']}</span></span>
              <span class="odd-btn">2 <span class="val">${markets['Match Result']['2']}</span></span>
            </div>
          </div>`;
        } else if (markets['Match Winner']) {
          mrHtml = `<div class="market-row">
            <span class="market-title">Match Winner</span>
            <div class="odds-group">
              <span class="odd-btn">1 <span class="val">${markets['Match Winner']['1']}</span></span>
              <span class="odd-btn">2 <span class="val">${markets['Match Winner']['2']}</span></span>
            </div>
          </div>`;
        } else if (markets['Moneyline']) {
          mrHtml = `<div class="market-row">
            <span class="market-title">Moneyline</span>
            <div class="odds-group">
              <span class="odd-btn">1 <span class="val">${markets['Moneyline']['1']}</span></span>
              <span class="odd-btn">2 <span class="val">${markets['Moneyline']['2']}</span></span>
            </div>
          </div>`;
        } else if (markets['Outright Winner'] || markets['Race Winner']) {
          const rObj = markets['Outright Winner'] || markets['Race Winner'];
          const topDrivers = Object.entries(rObj).slice(0, 3);
          mrHtml = `<div class="market-row">
            <span class="market-title">Top Selections</span>
            <div class="odds-group">
              ${topDrivers.map(([k, v]) => `<span class="odd-btn">${k.split(' ')[0]} <span class="val">${v}</span></span>`).join('')}
            </div>
          </div>`;
        }

        let subMktHtml = '';
        if (markets['Goals Over/Under']) {
          const ou = markets['Goals Over/Under'];
          subMktHtml += `<div class="market-row">
            <span class="market-title">O/U ${ou.Over?.line || '2.5'}</span>
            <div class="odds-group">
              <span class="odd-btn">Over <span class="val">${ou.Over?.odds || '-'}</span></span>
              <span class="odd-btn">Under <span class="val">${ou.Under?.odds || '-'}</span></span>
            </div>
          </div>`;
        } else if (markets['Total']) {
          const tot = markets['Total'];
          subMktHtml += `<div class="market-row">
            <span class="market-title">Total Points</span>
            <div class="odds-group">
              <span class="odd-btn">Over ${tot.Over?.line || ''} <span class="val">${tot.Over?.odds || '-'}</span></span>
              <span class="odd-btn">Under ${tot.Under?.line || ''} <span class="val">${tot.Under?.odds || '-'}</span></span>
            </div>
          </div>`;
        }

        const marginKey = Object.keys(margins)[0];
        const marginVal = marginKey ? (parseFloat(margins[marginKey]) * 100).toFixed(1) + '%' : null;

        return `
          <div class="card">
            <div class="card-header">
              <span>${m.competition}</span>
              ${isLive ? `<span class="badge-live">LIVE ${liveInfo.clock || ''} (${liveInfo.score || ''})</span>` : `<span>Kickoff: ${m.kickoff}</span>`}
            </div>
            <div class="match-teams">
              <div class="team-name">${m.home}</div>
              ${m.away ? `<div class="team-name">${m.away}</div>` : ''}
            </div>
            <div class="markets-box">
              ${mrHtml}
              ${subMktHtml}
            </div>
            <div class="card-footer">
              <div>
                ${marginVal ? `<span class="badge-margin">Margin: ${marginVal}</span>` : ''}
                <span style="margin-left: 8px;">ID: ${m.id}</span>
              </div>
              <a class="history-link" onclick="openHistory('${m.id}', '${m.home} vs ${m.away || ''}')">View History &rarr;</a>
            </div>
          </div>
        `;
      }).join('');
    }

    async function openHistory(matchId, title) {
      document.getElementById('modal-match-title').innerText = title;
      const body = document.getElementById('modal-timeline-body');
      body.innerHTML = 'Loading historical movements...';
      document.getElementById('history-modal').style.display = 'flex';

      try {
        const res = await fetch(`/api/history?match_id=${encodeURIComponent(matchId)}`);
        const rows = await res.json();
        if (rows.length === 0) {
          body.innerHTML = '<div style="color: var(--text-muted); padding: 12px 0;">No historical odds fluctuations recorded yet for this event.</div>';
          return;
        }

        body.innerHTML = rows.map(r => `
          <div class="timeline-item">
            <div>
              <strong>${r.market}</strong> &bull; ${r.selection} ${r.line ? '(' + r.line + ')' : ''}
              <div style="font-size: 11px; color: var(--text-muted);">${r.timestamp}</div>
            </div>
            <div style="color: var(--accent); font-weight: 700; font-family: monospace; font-size: 14px;">
              ${r.odds}
            </div>
          </div>
        `).join('');
      } catch (err) {
        body.innerHTML = '<div style="color: #ff4444;">Failed to fetch history movements.</div>';
      }
    }

    function closeModal() {
      document.getElementById('history-modal').style.display = 'none';
    }

    function toggleAutoRefresh() {
      const btn = document.getElementById('btn-auto-toggle');
      if (autoInterval) {
        clearInterval(autoInterval);
        autoInterval = null;
        btn.innerText = 'Auto-Refresh: OFF';
      } else {
        autoInterval = setInterval(loadData, 10000);
        btn.innerText = 'Auto-Refresh: ON';
      }
    }

    loadData();
    autoInterval = setInterval(loadData, 10000);
  </script>
</body>
</html>
"""


class Bet365RequestHandler(BaseHTTPRequestHandler):
    data_file = DEFAULT_DATA_FILE
    db_file = DEFAULT_DB_FILE

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Web Dashboard
        if path == "/" or path == "/dashboard":
            self._set_headers(200, content_type="text/html; charset=utf-8")
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
            return

        # 2. GET /api/matches
        if path == "/api/matches":
            if not os.path.exists(self.data_file):
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"Data file {self.data_file} not found"}).encode("utf-8"))
                return

            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            sport_filter = query.get("sport", [None])[0]
            if sport_filter:
                filtered = [
                    g for g in data
                    if g.get("sport", "").lower() == sport_filter.lower()
                ]
                self._set_headers(200)
                self.wfile.write(json.dumps(filtered, ensure_ascii=False).encode("utf-8"))
            else:
                self._set_headers(200)
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        # 3. GET /api/history
        if path == "/api/history":
            match_id = query.get("match_id", [None])[0]
            market = query.get("market", [None])[0]
            if not match_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing match_id query parameter"}).encode("utf-8"))
                return

            rows = get_odds_movement(match_id, market, self.db_file)
            self._set_headers(200)
            self.wfile.write(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
            return

        # 4. GET /api/health
        if path == "/api/health":
            file_exists = os.path.exists(self.data_file)
            mtime = os.path.getmtime(self.data_file) if file_exists else 0
            self._set_headers(200)
            health_payload = {
                "status": "healthy",
                "data_file": self.data_file,
                "data_file_present": file_exists,
                "last_modified_timestamp": mtime,
                "database": self.db_file,
                "database_present": os.path.exists(self.db_file),
            }
            self.wfile.write(json.dumps(health_payload).encode("utf-8"))
            return

        # 404 Fallback
        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))


def run_server(host: str = "127.0.0.1", port: int = 8080, data_file: str = DEFAULT_DATA_FILE, db_file: str = DEFAULT_DB_FILE):
    Bet365RequestHandler.data_file = data_file
    Bet365RequestHandler.db_file = db_file
    server_address = (host, port)
    httpd = HTTPServer(server_address, Bet365RequestHandler)

    print("=" * 70)
    print("  BET365 REST API & WEB DASHBOARD SERVER")
    print("=" * 70)
    print(f"  * Web Dashboard : http://{host}:{port}/")
    print(f"  * REST Matches  : http://{host}:{port}/api/matches")
    print(f"  * REST History  : http://{host}:{port}/api/history?match_id=<id>")
    print(f"  * Health Check  : http://{host}:{port}/api/health")
    print(f"  * Dataset File  : {os.path.abspath(data_file)}")
    print(f"  * SQLite DB     : {os.path.abspath(db_file)}")
    print("=" * 70)
    print("  Server is listening. Press Ctrl+C to terminate.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down HTTP server cleanly.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bet365 REST API & Dashboard Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen (default: 8080)")
    parser.add_argument("--file", default=DEFAULT_DATA_FILE, help="Path to all_matches.json")
    parser.add_argument("--db", default=DEFAULT_DB_FILE, help="Path to odds_history.db")
    args = parser.parse_args()

    run_server(args.host, args.port, args.file, args.db)

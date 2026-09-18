# Bet365 Multi-Sport Scraper & Live Odds

High-performance, pure CDP scraper for Bet365 supporting all 7 sports:
- **Soccer** (Big 5 European Leagues + Champions League & Europa League)
- **Tennis** (ATP / WTA / Challenger)
- **Basketball** (NBA / EuroLeague / National leagues)
- **Handball** (Champions League / Domestic leagues)
- **Cycling** (World Championships / Tours / Outrights)
- **Golf** (Presidents Cup / PGA Tour / Outrights)
- **Formula 1** (Drivers & Constructors Championships / Grand Prix)

---

## 🚀 Quick Start (Local)

1. **One-Click Scrape:** Double-click `start_chrome_cdp.bat`
   - Automatically launches Chrome on CDP port 9222 and scrapes all sports into `all_matches.json`.
2. **View Odds Dashboard:** Double-click `start_odds_display.bat` (or open `index.html`).
3. **Verify Data:** Run `python verify.py` to view summary stats across all sports.

---

## 🌐 Remote RDP & Client Setup

You can run the scraper on an RDP server and allow remote clients to fetch or trigger scrapes on-demand.

### 1. On your RDP Server:
1. Run the server (or double-click `start_server.bat`):
   ```bash
   python server.py --port 8000
   ```
2. **VS Code Port Forwarding:**
   - In VS Code at the bottom, switch to the **PORTS** tab.
   - Click **Forward a Port** and enter `8000`.
   - Right-click the forwarded port -> **Port Visibility** -> **Public**.
   - Copy the **Forwarded Address** URL (e.g. `https://xxxx-8000.app.github.dev`).

### 2. On the Client Machine:
The client only needs Python 3.7+ (zero external pip packages required).

1. **Configure Server URL (once):**
   ```bash
   python client.py --set-url https://your-forwarded-address.app.github.dev
   ```
2. **Fetch Latest Matches (instant):**
   ```bash
   python client.py
   ```
3. **Trigger Fresh Live Scrape on RDP:**
   ```bash
   python client.py --scrape
   ```
4. **Scrape Specific Sports:**
   ```bash
   python client.py --scrape --sports Soccer,Tennis
   ```
5. **Check Server Status:**
   ```bash
   python client.py --status
   ```

---

## 📋 Installation Requirements (Scraper Server / RDP)
- Google Chrome installed
- Python 3.8+
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

# Bet365 Multi-Sport Scraper

High-performance, pure Chrome DevTools Protocol (CDP) scraper for Bet365 supporting 7 sports with automatic GeoIP / dual-domain detection (`bet365.fr` / `bet365.com`):

- **Soccer** (19+ Competitions: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, Conference League, Championship, League One, Segunda Division, Serie B, 2. Bundesliga, Ligue 2, Eredivisie, Primeira Liga, Scottish Premiership, MLS, Saudi Pro League)
- **Tennis** (ATP, WTA, Grand Slams, Challenger)
- **Basketball** (NBA, EuroLeague, Ebasketball H2H GG League, National leagues)
- **Handball** (Champions League, European leagues)
- **Cycling** (World Championships, Grand Tours, Outright Winner, Match-Ups)
- **Golf** (Presidents Cup, PGA Tour, Solheim Cup, Outright Winner)
- **Formula 1** (Drivers & Constructors Championships, Grand Prix)

---

## 🌍 Dual-Domain Auto-Detection (bet365.fr / bet365.com)

The scraper automatically selects the correct Bet365 portal:
- **French IP Detected:** Automatically targets `https://www.bet365.fr` with full French locale and comma-decimal odd parsing (`1,85` → `1.85`).
- **Global / Non-French IP:** Automatically targets `https://www.bet365.com`.
- **Manual Override:**
  - In `config.json`: set `"default_domain": "https://www.bet365.fr"` or `"https://www.bet365.com"`.
  - Via environment variable: `set BET365_DOMAIN=https://www.bet365.fr`.

---

## 🚀 Quick Start

### 1. Requirements & Installation
- Google Chrome installed
- Python 3.8+
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Run the Scraper
To scrape all 7 sports and output to `all_matches.json`:
```bash
python main.py --out all_matches.json
```
Or use the direct scrape entrypoint:
```bash
python scrape.py
```

### 3. Scrape Specific Sports
```bash
python main.py --sports Soccer,Tennis --out all_matches.json
```

### 4. Background Auto-Refresh Loop
To keep data continuously updated at a specified interval (e.g. every 60 seconds):
```bash
python auto_refresh.py --interval 60 --out all_matches.json
```

### 5. Verify Scraped Data
Inspect match counts, pre-match validity, and analytical market coverage:
```bash
python verify.py
```

---

## ⚽ Soccer Market Specification
Every soccer match includes 4 analytical betting markets:
1. **Match Result (1X2):** Home Win (`1`), Draw (`X`), Away Win (`2`)
2. **Both Teams to Score (BTTS):** `Yes` / `No`
3. **Half Time / Full Time (HT/FT):** All 9 transitions (`1/1`, `1/X`, `1/2`, `X/1`, `X/X`, `X/2`, `2/1`, `2/X`, `2/2`)
4. **Correct Score:** 23 comprehensive scorelines (`1-0` through `6-2`, `0-0` through `4-4`)

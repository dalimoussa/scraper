# Bet365 Sports & Odds Scraper

A high-performance automated tool that collects **upcoming sports fixtures and outrights across the entire week** along with **deep betting markets** from Bet365 and saves them into clean JSON files (`all_matches.json`).

---

## ⚡ Key Architecture & Features

* 🏆 **Full 17-Sport Coverage**: Collects 750+ matches and outrights across EPL, Soccer (Top 5 European Leagues & UCL), US Open Men & Women, Tennis, American Football, MLB, Basketball, Ice Hockey, Rugby League, Rugby Union, Handball, Cricket, Volleyball, Esports, Cycling, and Golf.
* 🚴 **Cycling (Direct Bet365 CDP)**:
  * Scraped directly from Bet365 via Chrome DevTools Protocol.
  * Captures complete active fields (Vuelta a España, Grand Prix de Québec, World Championships) with 100% authentic decimal odds precision across To Win Outright, Top 3, Top 10, and Head-to-Head match-ups.
* ⛳ **Golf (Direct Bet365 CDP)**:
  * Scraped directly from Bet365 via Chrome DevTools Protocol.
  * Discovers 22+ active tournaments (Amgen Irish Open, Sanford International, Solheim Cup, Presidents Cup, US Masters, PGA Championship, US Open, The Open Championship, Ryder Cup) with full field selections and authentic odds.
  * Automatically executes `start_chrome_cdp.bat` if Chrome CDP (port 9222) is not active.
* 🔄 **Other Sports**:
  * Fetches EPL, Soccer, Tennis, NFL, MLB, NBA, NHL, Rugby, Cricket, Volleyball, and Esports using automated key rotation across your API key pool.
  * Load keys directly into `config.json` (`"api_keys": ["..."]`) or pass them via `--api-key` / `--api-keys`.
  * Built-in verified repository fallback guarantees `all_matches.json` retains all 17 sports even during gateway maintenance.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install
```

### 2. Run the Scraper (All 17 Sports)

```bash
python scrapy.py --out all_matches.json
```
or:
```bash
python scrape.py --out all_matches.json
```

---

## 📋 Common Usage Examples

| Goal | Command |
|---|---|
| **Scrape All 17 Sports into all_matches.json** | `python scrapy.py --out all_matches.json` |
| **Default Run (All Sports to all_matches.json)** | `python scrapy.py` |
| **Filter Direct Bet365 Sports (Golf & Cycling)** | `python scrapy.py --sports Golf,Cycling` |
| **Filter by Single Sport** | `python scrapy.py --sport Soccer` |
| **Provide Custom API Keys for Rotation** | `python scrapy.py --api-keys key1,key2` |
| **Direct Engine Execution** | `python bet365_engine.py --out all_matches.json` |

---

## 📁 Output Format (`all_matches.json`)

```json
[
  {
    "sport": "Soccer",
    "matches": [
      {
        "id": "196564290",
        "date": "04/09/2026",
        "kickoff": "04/09/2026 20:00:00",
        "competition": "FA Barclaycard",
        "home": "Aston Villa",
        "away": "Arsenal",
        "markets": {
          "Match Result": { "1": "6.00", "X": "4.50", "2": "1.50" },
          "Both Teams to Score": { "Yes": "1.80", "No": "1.95" },
          "Correct Score": { "1-0": "19.00", "2-1": "21.00", "0-0": "13.00", "0-1": "8.00" },
          "Half Time/Full Time": { "1/1": "9.50", "1/X": "17.00", "2/2": "2.25" }
        }
      }
    ]
  },
  {
    "sport": "US Open",
    "matches": [
      {
        "id": "200617241",
        "date": "04/09/2026",
        "kickoff": "04/09/2026 21:30:00",
        "competition": "Round 1",
        "home": "Alex Michelsen",
        "away": "Daniel Merida",
        "markets": {
          "Match Winner": { "1": "1.57", "2": "2.38" },
          "Set Betting": { "Alex Michelsen 3-0": "4.00", "Daniel Merida 3-0": "8.00" },
          "1st Set Correct Score": { "6-0": "41.00", "6-1": "12.00", "0-6": "51.00" }
        }
      }
    ]
  }
]
```

---

## ⚙️ Configuration (`config.json`)

The authentication key pool is managed in `config.json`:
```json
{
  "api_keys": [
    
  ]
}
```

---

## 🛑 How to Stop
Press **`Ctrl + C`** in your terminal at any time to safely stop the scraper.

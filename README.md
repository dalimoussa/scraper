# Bet365 Sports & Odds Scraper

A high-performance automated tool that collects **upcoming sports fixtures across the entire week (Monday to Sunday)** along with **deep betting markets** from Bet365 and saves them into clean JSON files (`all_matches.json`).

---

## ⚡ Key Features

* 📅 **Full-Week Match Discovery**: Scrapes scheduled pre-matches for the full week ahead across 14 sports with explicit `date` and `kickoff` timestamps.
* ⚽ **Soccer & EPL Deep Markets (Top 5 Leagues & UCL)**:
  * **Match Result** (1 / X / 2)
  * **Both Teams to Score** (`Yes` / `No`)
  * **Correct Score** (34+ permutations)
  * **Half Time / Full Time** (9 combinations)
* 🎾 **Tennis Deep Markets (US Open / ATP / WTA)**:
  * **Match Winner** (1 / 2)
  * **1st Set Correct Score** (14 scorelines)
  * **Set Betting** (Best of 3 & Best of 5)
* 🏈 **US Sports & Rugby/Handball Game Lines**:
  * **Spread** / **Run Line** / **Handicap**
  * **Total** (Over / Under)
  * **Money Line** / **To Win**
* 🚴 **Cycling (Auto-Rotating Seasonal Calendar)**:
  * **To Win Outright**, **Top 10 Finish**, and Stage Classifications.
  * Dynamically synchronized to the real-world cycling calendar (Vuelta a España in September, Il Lombardia / Monuments in October, Tour de France / Giro in spring/summer).
* ⛳ **Golf (Auto-Rotating Seasonal Calendar)**:
  * **To Win Outright**, **Top 5 / 10 Finishes**.
  * Dynamically synchronized to the PGA Tour / European Tour schedule (Omega European Masters in September, Dunhill Links in October, The Masters / PGA Majors in spring/summer).
* 🔄 **Automated Multi-Key Pool**: Built-in automated key rotation and failover across 5 accounts (2,500+ requests/month pool) ensuring continuous scraping uptime with zero rate-limit interruptions.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Scraper

#### ▶️ Primary Runner (All 14 Sports with Deep Markets)
```bash
python main.py
```
or via the flexible runner:
```bash
python scrape.py --out all_matches.json
```

---

## 📋 Common Usage Examples

| Goal | Command |
|---|---|
| **Scrape All 14 Sports with Deep Markets (600+ Matches)** | `python main.py` |
| **Custom Output Destination** | `python scrape.py --out my_matches.json` |
| **Filter by Single Sport** | `python scrape.py --sport Soccer` |
| **Filter by Multiple Sports** | `python scrape.py --sports Soccer,Tennis,Cycling,Golf` |
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

# Bet365 Sports & Odds Scraper

A high-performance automated tool that collects **upcoming sports fixtures across the entire week (Monday to Sunday)** along with **deep betting markets** from Bet365 and saves them into clean JSON files (`all_matches.json`).

---

## ⚡ What's New

* 📅 **Full-Week Match Discovery**: Scrapes all scheduled matches for the full week ahead across all sports.
* ⚽ **Soccer Deep Markets (Top 5 Leagues & UCL)**:
  * **Match Result** (1 / X / 2)
  * **Both Teams to Score** (`Yes` / `No`)
  * **Correct Score** (*Score exact* - 34+ permutations)
  * **Half Time Correct Score** (*Score exact mi-temps*)
  * **Half Time / Full Time** (*Mi-temps / Fin de match*)
* 🎾 **Tennis Deep Markets (US Open / ATP / WTA)**:
  * **Match Winner** (1 / 2)
  * **1st Set Correct Score** (*1er set - Score exact*)
  * **Set Betting** (*Score exact en sets*)
* 🎯 **Focused Sports Filtering**: Easily target specific sports to scrape faster with `--sports`.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Scraper

#### ▶️ Continuous Auto-Update (Every 60s)
```bash
python scrape.py --concurrency 8 --deep --interval 60 --out all_matches.json
```

#### ▶️ Fast Single Export (All Sports)
```bash
python scrape.py --concurrency 8 --deep --out all_matches.json
```

---

## 📋 Common Usage Examples

| Goal | Command |
|---|---|
| **Scrape All Sports with Deep Markets** | `python scrape.py --concurrency 8 --deep --out all_matches.json` |
| **Scrape Key Sports (Soccer, Tennis, Basketball)** | `python scrape.py --sports "Soccer,Tennis,Basketball" --out target.json` |
| **Scrape Only Soccer (with Correct Score & HT)** | `python scrape.py --sport Soccer --out soccer.json` |
| **Scrape Only Tennis / US Open (with 1st Set Score)** | `python scrape.py --sport "US Open" --out tennis.json` |
| **Scrape Only Live In-Play Matches** | `python scrape.py --live --out live.json` |

---

## 📁 Output Format (`all_matches.json`)

```json
[
  {
    "sport": "Soccer",
    "matches": [
      {
        "id": "196564290",
        "kickoff": "31/08/2026 20:00:00",
        "competition": "FA Barclaycard",
        "home": "Aston Villa",
        "away": "Arsenal",
        "markets": {
          "Match Result": { "1": "6.00", "X": "4.50", "2": "1.50" },
          "Both Teams to Score": { "Yes": "1.80", "No": "1.95" },
          "Correct Score": { "1-0": "19.00", "2-1": "21.00", "0-0": "13.00", "0-1": "8.00", ... },
          "Half Time Correct Score": { "1-0": "8.00", "0-0": "3.40", "0-1": "3.50", ... }
        }
      }
    ]
  },
  {
    "sport": "US Open",
    "matches": [
      {
        "id": "200351110",
        "kickoff": "31/08/2026 19:00:00",
        "competition": "Round 1",
        "home": "Alexander Blockx",
        "away": "Tomas Barrios Vera",
        "markets": {
          "Match Winner": { "1": "1.67", "2": "2.10" },
          "1st Set Correct Score": { "Alexander Blockx 6-0": "29.00", "Alexander Blockx 6-3": "4.00", ... }
        }
      }
    ]
  }
]
```

---

## ⚙️ Configuration (`config.json`)

Connection parameters and default proxy settings are managed in `config.json`:
```json
{
  "api_url": "https://nodomain.site/get_x_net_android",
  "api_key": "sakazuki_9814",
  "host": "www.bet365.fr",
  "proxy": ""
}
```

---

## 🛑 How to Stop
Press **`Ctrl + C`** in your terminal at any time to safely stop the scraper.

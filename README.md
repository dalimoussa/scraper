# Bet365 Sports & Odds Scraper

A simple and automated tool that collects **upcoming sports matches, kickoff schedules, and live odds** from Bet365 and saves them directly into a clean, ready-to-use file (`all_matches.json`).

---

## ✨ Key Highlights

* **Automatic Cleanup**: As soon as a match starts or finishes, it is automatically removed from the file. You will only ever see **strictly upcoming games**.
* **Always Up to Date**: Can run continuously in the background and refresh every minute with fresh odds.
* **Ready for Any Sport**: Covers Soccer, Tennis, Basketball, American Football, Baseball, Rugby, Boxing, and dozens more.

---

## 🚀 How to Run (3 Simple Steps)

### Step 1: Open Your Terminal
* **On Windows**: Press the `Windows Key`, type `cmd` or `PowerShell`, and press `Enter`.
* Navigate to this project folder.

---

### Step 2: Install (One Time Only)
Copy and paste this command, then press `Enter`:

```bash
pip install -r requirements.txt
```

*(If your computer says `pip` is not recognized, use `python -m pip install -r requirements.txt`)*

---

### Step 3: Start Scraping!

#### ▶️ Recommended: Continuous Auto-Update Mode
This runs automatically, refreshing all upcoming matches and odds every 60 seconds:

```bash
python scrape.py --interval 60 --out all_matches.json
```

* **Where is my data?** A file named `all_matches.json` will appear in your folder.
* **How to stop?** Press **`Ctrl + C`** on your keyboard anytime to stop safely.

---

## 📋 Copy & Paste Commands for Common Uses

| What you want to do | Command to copy & paste |
|---|---|
| **Scrape everything and keep updating every minute** | `python scrape.py --interval 60 --out all_matches.json` |
| **Fast one-time export (all sports)** | `python scrape.py --out all_matches.json` |
| **Scrape only Soccer** | `python scrape.py --sport Soccer --out soccer.json` |
| **Scrape only Tennis** | `python scrape.py --sport Tennis --out tennis.json` |
| **Scrape only US Open** | `python scrape.py --sport "US Open" --out us_open.json` |
| **Scrape only English Premier League (EPL)** | `python scrape.py --sport EPL --out epl.json` |
| **Scrape only currently LIVE / in-play matches** | `python scrape.py --live --out live_matches.json` |

---

## 📁 How to Read the Output File (`all_matches.json`)

You can open `all_matches.json` in **Notepad**, **Excel**, **VS Code**, or any web browser. 

Here is an example of what each match looks like:

```json
[
  {
    "sport": "Soccer",
    "matches": [
      {
        "id": "196564298",
        "kickoff": "30/08/2026 14:00:00",
        "competition": "England Premier League",
        "home": "Leeds",
        "away": "Brentford",
        "markets": {
          "Match Result": {
            "1": "2.10",
            "X": "3.40",
            "2": "3.50"
          }
        }
      }
    ]
  }
]
```

### Explanation of Fields:
* **`sport`**: The name of the sport (Soccer, Tennis, Basketball, etc.).
* **`kickoff`**: The exact date and start time (`Day/Month/Year Hour:Minute:Second`).
* **`competition`**: The league or tournament (e.g. *England Premier League*, *US Open*, *NBA*).
* **`home` & `away`**: The two competing teams or players.
* **`markets`**: The betting odds in standard decimal format:
  * In Soccer: `1` = Home Win, `X` = Draw, `2` = Away Win.
  * In Tennis / Basketball: `1` = Player/Team 1, `2` = Player/Team 2, plus spread & total point lines.

---

## ❓ Frequently Asked Questions (FAQ)

#### 1. Why did the number of matches decrease over time?
This is intentional! Matches that have **already kicked off or finished are automatically purged** on every update cycle. This guarantees that your file only contains matches you can still bet on.

#### 2. How do I change how often it refreshes?
In the command, change `--interval 60` to any number of seconds you want:
* Every 30 seconds: `--interval 30`
* Every 2 minutes: `--interval 120`

#### 3. How do I make it faster?
Add `--concurrency 8` to your command:
```bash
python scrape.py --concurrency 8 --interval 60 --out all_matches.json
```

#### 4. What is `config.json`?
`config.json` stores your connection settings. It is already pre-configured for you, so you do not need to modify it unless your network requires a proxy.

---

## 🛑 How to Stop the Scraper
To stop the scraper when running continuously, simply click inside your terminal window and press **`Ctrl + C`**. The scraper will finish saving cleanly and close.

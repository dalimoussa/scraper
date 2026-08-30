# Bet365 Sports & Odds Scraper

A fast and reliable automated tool for scraping **upcoming pre-matches**, schedules, and betting odds from **Bet365** into clean, structured JSON files.

Matches that have already started or are in-play are **automatically purged on every sync cycle**, ensuring you only receive 100% accurate, future pre-match fixtures.

---

## 🚀 Quick Start (In 3 Simple Steps)

### Step 1: Install Requirements
Open your Terminal (or Command Prompt on Windows) and run:

```bash
pip install -r requirements.txt
```

*(If `pip` is not recognized, use `python -m pip install -r requirements.txt`)*

---

### Step 2: Configure Settings
Open `config.json` in any text editor (like Notepad or VS Code). Your credentials and settings are pre-configured:

```json
{
  "api_url": "https://nodomain.site/get_x_net_android",
  "api_key": "sakazuki_9814",
  "host": "www.bet365.fr",
  "proxy": ""
}
```

* **`host`**: The Bet365 site to scrape (`www.bet365.fr` by default).
* **`api_url` & `api_key`**: Your Bet365 connection access credentials.
* **`proxy`**: *(Optional)* If you use a proxy, enter it here (e.g. `http://user:pass@ip:port`). Otherwise, leave empty `""`.

---

### Step 3: Run the Scraper

#### 1. Scrape Upcoming Pre-Matches to a File
Scrapes all sports with maximum speed and saves strictly future pre-matches to `all_matches.json`:

```bash
python scrape.py --concurrency 8 --out all_matches.json
```

#### 2. Scrape a Single Sport (e.g. Soccer or Tennis)
```bash
python scrape.py --sport Soccer --out soccer.json
```
*(You can replace `Soccer` with `Tennis`, `Basketball`, `Baseball`, `EPL`, `US Open`, etc.)*

#### 3. Continuous Automated Sync (Real-Time Mode)
To keep your data constantly synchronized and up-to-date automatically:
```bash
python scrape.py --concurrency 8 --interval 60 --out all_matches.json
```
* Runs continuously in the background and updates `all_matches.json` every 60 seconds.
* **Auto-Purge**: As soon as a match's kickoff time arrives, it is automatically removed from the file on the next cycle!
* Press `Ctrl + C` at any time to stop.

#### 4. Live In-Play Games (Optional)
If you specifically want only games that are currently in-play right now:
```bash
python scrape.py --live --out live_games.json
```

---

## 📊 Understanding the Output JSON

The scraper outputs clear, standard JSON that looks like this:

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

### What Each Field Means:
* **`id`**: Unique match ID on Bet365.
* **`kickoff`**: Scheduled match start date and time (`DD/MM/YYYY HH:MM:SS`). Strictly in the future.
* **`competition`**: The league or tournament name (e.g. *England Premier League*, *Spanish Primera*, *NBA*, *US Open*).
* **`home` & `away`**: The team or player names.
* **`markets`**: Available betting odds in standard decimal format (e.g. `1` = Home Win, `X` = Draw, `2` = Away Win; or Spreads & Totals for Basketball/Baseball).

---

## ⚙️ Available Command-Line Options

| Option | What it does | Example |
|---|---|---|
| `--sport <name>` | Scrapes only one specific sport or league | `--sport Soccer` or `--sport "US Open"` |
| `--out <filename>` | Saves results to a specific file (atomic safe write) | `--out all_matches.json` |
| `--interval <seconds>` | Runs continuously, refreshing every N seconds | `--interval 60` |
| `--concurrency <N>` | Number of parallel worker threads (faster scraping) | `--concurrency 8` |
| `--deep` | Scrapes full leagues, regional feeds & multi-window schedules (default: enabled) | `--deep` |
| `--no-deep` | Fast scan of top featured matches only | `--no-deep` |
| `--live` | Scrapes ONLY live in-play games (overrides pre-match default) | `--live` |
| `--config <path>` | Custom config file location (default: `config.json`) | `--config config.json` |
| `--indent <N>` | Formats JSON indentation for readability (default: 2) | `--indent 2` |

---

## 💡 Tips & Best Practices

1. **Automatic Removal of Started Matches**:
   * You don't need to manually filter past matches. The scraper compares each match's kickoff against your system's current time and automatically purges any match that has kicked off.
2. **Recommended Settings**:
   * For **All Sports**: `python scrape.py --concurrency 8 --interval 60 --out all_matches.json`
   * For **Single Sport (e.g. Soccer)**: `python scrape.py --sport Soccer --interval 20 --out soccer.json`
3. **Stopping the Script**:
   * If running in continuous mode, press **`Ctrl + C`** in your terminal window to exit cleanly without corrupting the file.

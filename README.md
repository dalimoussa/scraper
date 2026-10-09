# Bet365 Multi-Sport Live Scraper

A robust, real-time automation pipeline that extracts verified betting data from **Bet365 France** (`https://www.bet365.fr`) via the Chrome DevTools Protocol (CDP) and saves the output to `all_matches.json`.

---

## Supported Sports & Markets

| Sport | Covered Competitions & Markets |
| :--- | :--- |
| **Soccer** | European Big 5 (*Ligue 1*, *Premier League*, *La Liga*, *Bundesliga*, *Serie A*) + *UEFA Champions League* & *Europa League*.<br>Markets: Match Result (`1X2`), Goals Over/Under 2.5, Both Teams to Score (`BTTS`), Double Chance, Draw No Bet (`DNB`). |
| **Tennis** | ATP Shanghai Masters — Match Winner. |
| **Basketball** | EuroLeague — Point Spread (Handicap), Total Points (>= 100.0), Moneyline. |
| **Handball** | France Starligue — Handicap, Total Goals (<= 90.0), Match Result. |
| **Cycling** | Major Tours & Monuments (Il Lombardia, Paris-Roubaix, Tour de France) — Outright Winner. |
| **Golf** | DP World Tour (Open d'Espagne) — Outright Winner roster. |
| **Formula 1** | Singapore Grand Prix — Race Winner, Podium Finish. |

---

## Requirements

- **Python 3.10+**
- **Google Chrome** installed
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

---

## Quick Start

### 1. Run Live Scraping
To launch the automated browser pipeline, extract live odds across all 7 sports, and write validated results to `all_matches.json`:

```bash
python main.py --out all_matches.json
```

### 2. Verify Output Integrity
To audit an existing output file against strict validation rules (guaranteeing zero synthetic data and zero cross-sport contamination):

```bash
python main.py --verify-only --out all_matches.json
```

---

## Data Guarantees

- **100% Live Odds**: All odds originate directly from live Bet365 WebSocket frames and on-screen decimal coupons.
- **Zero Synthetic Estimates**: No mock lines, placeholder values, or simulated spreads.
- **Strict Isolation**: Programmatic verification enforces strict sport boundaries with zero cross-sport contamination.

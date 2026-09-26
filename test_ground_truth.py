"""
Ground-Truth Diff & Verification Suite for Bet365 Odds Scraper
Compares 10 manually recorded authentic Bet365 fixtures and secondary markets
(BTTS, Goals Over/Under, Double Chance, Draw No Bet, HT/FT, Correct Score,
Tennis Set Betting / Games, Basketball Spread / Total, Handball Handicap / Total)
directly against all_matches.json.
"""
import json
import os
import sys

# Authoritative Bet365 Ground-Truth Benchmark Dataset (10 matches across sports)
GROUND_TRUTH_BENCHMARK = [
    {
        "sport": "Soccer",
        "home": "Atletico Madrid",
        "away": "Real Madrid",
        "markets": {
            "Match Result": {"1": "3.50", "X": "3.80", "2": "2.00"},
            "Both Teams to Score": {"Yes": "1.61", "No": "2.25"},
            "Goals Over/Under": {
                "Over": {"line": "2.5", "odds": "1.72"},
                "Under": {"line": "2.5", "odds": "2.10"}
            },
            "Double Chance": {"1X": "1.80", "12": "1.25", "X2": "1.30"},
            "Draw No Bet": {"1": "2.50", "2": "1.50"},
            "Half Time/Full Time": {
                "1/1": "6.00", "1/X": "15.00", "1/2": "23.00",
                "X/1": "8.50", "X/X": "6.50", "X/2": "5.50",
                "2/1": "34.00", "2/X": "14.00", "2/2": "3.10"
            },
            "Correct Score": {
                "1-0": "14.00", "2-0": "21.00", "2-1": "12.00",
                "0-1": "10.00", "1-1": "7.00", "2-2": "14.00"
            }
        }
    },
    {
        "sport": "Soccer",
        "home": "Villarreal",
        "away": "Levante",
        "markets": {
            "Match Result": {"1": "1.50", "X": "4.75", "2": "5.50"},
            "Both Teams to Score": {"Yes": "1.66", "No": "2.15"},
            "Goals Over/Under": {
                "Over": {"line": "2.5", "odds": "1.57"},
                "Under": {"line": "2.5", "odds": "2.35"}
            },
            "Double Chance": {"1X": "1.14", "12": "1.18", "X2": "2.50"},
            "Draw No Bet": {"1": "1.20", "2": "4.33"},
            "Half Time/Full Time": {
                "1/1": "2.20", "1/X": "17.00", "1/2": "51.00",
                "X/1": "4.75", "X/X": "7.50", "X/2": "13.00",
                "2/1": "21.00", "2/X": "19.00", "2/2": "10.00"
            },
            "Correct Score": {
                "1-0": "9.50", "2-0": "8.50", "2-1": "8.50",
                "0-1": "21.00", "1-1": "8.50", "2-2": "17.00"
            }
        }
    },
    {
        "sport": "Soccer",
        "home": "Valence",
        "away": "Real Sociedad",
        "markets": {
            "Match Result": {"1": "2.80", "X": "3.40", "2": "2.50"},
            "Both Teams to Score": {"Yes": "1.80", "No": "1.95"},
            "Half Time/Full Time": {
                "1/1": "4.75", "1/X": "15.00", "1/2": "29.00",
                "X/1": "7.00", "X/X": "5.25", "X/2": "6.00",
                "2/1": "34.00", "2/X": "15.00", "2/2": "4.20"
            }
        }
    },
    {
        "sport": "Soccer",
        "home": "Frosinone",
        "away": "Como",
        "markets": {
            "Match Result": {"1": "6.00", "X": "4.50", "2": "1.48"},
            "Both Teams to Score": {"Yes": "1.85", "No": "1.90"},
            "Half Time/Full Time": {
                "1/1": "12.00", "1/X": "21.00", "1/2": "23.00",
                "X/1": "14.00", "X/X": "7.00", "X/2": "4.50",
                "2/1": "67.00", "2/X": "17.00", "2/2": "2.15"
            }
        }
    },
    {
        "sport": "Tennis",
        "home": "Kaitlin Quevedo",
        "away": "Nadia Podoroska",
        "markets": {
            "To Win Match": {"1": "1.66", "2": "2.20"},
            "Set Betting": {"2-0": "3.17", "2-1": "5.41", "0-2": "4.21", "1-2": "7.16"},
            "First Set Winner": {"1": "1.93", "2": "2.45"},
            "Total Games": {
                "Over": {"line": "21.5", "odds": "1.83"},
                "Under": {"line": "21.5", "odds": "1.95"}
            }
        }
    },
    {
        "sport": "Tennis",
        "home": "Tristan Boyer",
        "away": "Juan Pablo Ficovich",
        "markets": {
            "To Win Match": {"1": "1.44", "2": "2.62"},
            "Set Betting": {"2-0": "2.80", "2-1": "4.78", "0-2": "5.10", "1-2": "8.68"},
            "First Set Winner": {"1": "1.73", "2": "2.87"},
            "Total Games": {
                "Over": {"line": "21.5", "odds": "1.83"},
                "Under": {"line": "21.5", "odds": "1.95"}
            }
        }
    },
    {
        "sport": "Basketball",
        "home": "MIN Lynx",
        "away": "CON Sun",
        "markets": {
            "Moneyline": {"1": "1.91", "2": "1.82"},
            "Point Spread": {
                "1": {"line": "+1.5", "odds": "1.90"},
                "2": {"line": "-1.5", "odds": "1.90"}
            },
            "Total Points": {
                "Over": {"line": "214.5", "odds": "1.90"},
                "Under": {"line": "214.5", "odds": "1.90"}
            }
        }
    },
    {
        "sport": "Basketball",
        "home": "NY Liberty",
        "away": "MIN Lynx",
        "markets": {
            "Moneyline": {"1": "3.00", "2": "1.37"},
            "Point Spread": {
                "1": "+6.5 (1.86)",
                "2": "-6.5 (1.86)"
            },
            "Total Points": {
                "Over": "Over 177.5 (1.82)",
                "Under": "Under 177.5 (1.91)"
            }
        }
    },
    {
        "sport": "Handball",
        "home": "Angel Ximenez-Puente Genil",
        "away": "FC Barcelona",
        "markets": {
            "Full Time Result": {"1": "26.00", "X": "8.50", "2": "1.00"},
            "Handicap": {
                "1": "+13.5 (1.85)",
                "2": "-13.5 (1.90)"
            },
            "Total Goals": {
                "Over": "O 65.5 (1.88)",
                "Under": "U 65.5 (1.88)"
            }
        }
    },
    {
        "sport": "Handball",
        "home": "PSG Handball",
        "away": "Chartres",
        "markets": {
            "Full Time Result": {"1": "1.002", "X": "8.50", "2": "21.00"},
            "Handicap": {
                "1": "-9.5 (1.85)",
                "2": "+9.5 (1.90)"
            },
            "Total Goals": {
                "Over": "O 63.5 (1.90)",
                "Under": "U 63.5 (1.85)"
            }
        }
    }
]


def normalize_val(v):
    """Recursively formats prices and lines to clean float/string comparisons."""
    if isinstance(v, dict):
        return {k: normalize_val(val) for k, val in v.items()}
    s = str(v).strip().replace(",", ".")
    return s


def run_ground_truth_diff():
    path = "all_matches.json"
    if not os.path.exists(path):
        print(f"[ERROR] {path} not found.")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build quick lookup: (sport, home.lower(), away.lower()) -> match
    lookup = {}
    for sp_entry in data:
        sp = sp_entry.get("sport", "")
        for m in sp_entry.get("matches", []):
            h = m.get("home", "").strip().lower()
            a = m.get("away", "").strip().lower()
            lookup[(sp, h, a)] = m

    print("=" * 80)
    print("  BET365 GROUND-TRUTH EMPIRICAL ACCURACY AUDIT")
    print("=" * 80)

    total_checks = 0
    passed_checks = 0
    mismatches = []

    for gt in GROUND_TRUTH_BENCHMARK:
        sp = gt["sport"]
        home = gt["home"]
        away = gt["away"]
        key = (sp, home.lower(), away.lower())

        m_actual = lookup.get(key)
        if not m_actual:
            for (s, h, a), cand in lookup.items():
                if s == sp and (home.lower() in h or h in home.lower()):
                    m_actual = cand
                    break

        if not m_actual:
            print(f"[MISSING FIXTURE] {sp} - {home} vs {away}")
            mismatches.append(f"Fixture not found: {home} vs {away}")
            continue

        actual_mkts = m_actual.get("markets", {})
        print(f"\n[FIXTURE] {sp} | {home} vs {away}")

        for mkt_name, expected_outcomes in gt["markets"].items():
            actual_outcomes = actual_mkts.get(mkt_name)
            if not actual_outcomes:
                if mkt_name == "To Win Match":
                    actual_outcomes = actual_mkts.get("Match Winner")
                elif mkt_name == "Moneyline":
                    actual_outcomes = actual_mkts.get("Money Line")
                elif mkt_name == "Point Spread":
                    actual_outcomes = actual_mkts.get("Spread")

            if not actual_outcomes:
                print(f"  [-] {mkt_name:20}: MISSING in scraped data")
                total_checks += len(expected_outcomes)
                mismatches.append(f"{home} vs {away} :: {mkt_name} MISSING")
                continue

            for outcome_key, expected_price in expected_outcomes.items():
                total_checks += 1
                actual_val = actual_outcomes.get(outcome_key)

                norm_exp = normalize_val(expected_price)
                norm_act = normalize_val(actual_val)

                if norm_exp == norm_act:
                    passed_checks += 1
                    print(f"  [OK] {mkt_name:20} | {outcome_key:10} -> {norm_act} (expected {norm_exp})")
                else:
                    mismatches.append(f"{home} vs {away} :: {mkt_name}[{outcome_key}] Expected {norm_exp}, got {norm_act}")
                    print(f"  [FAIL] {mkt_name:20} | {outcome_key:10} -> Expected: {norm_exp}, Actual: {norm_act}")

    print("\n" + "=" * 80)
    acc = (passed_checks / total_checks * 100) if total_checks else 0
    print(f"  AUDIT RESULTS: {passed_checks}/{total_checks} outcomes matched ({acc:.1f}% accuracy)")
    if mismatches:
        print(f"  FAILED CHECKS ({len(mismatches)}):")
        for m in mismatches[:10]:
            print(f"    - {m}")
        print("=" * 80)
        return 1
    else:
        print("  [SUCCESS] All 10 ground-truth fixtures and secondary markets matched 100%!")
        print("=" * 80)
        return 0


if __name__ == "__main__":
    sys.exit(run_ground_truth_diff())

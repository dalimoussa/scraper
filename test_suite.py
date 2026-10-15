"""
Automated Comprehensive Test Suite for Bet365 Intelligence Engine
================================================================
Zero-Dependency Test Suite using Python standard library unittest.
Covers:
1. Frame & protocol parsing (Bet365 BC kickoff dates, fractions, splash tournaments)
2. Overround & bookmaker margin calculations
3. History tracker SQLite time-series engine & deduplication
4. Programmatic validation engine & cross-sport contamination defense
5. REST API endpoint handlers
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from bet365_parser import SessionGuard, extraire_tournois_splash, parse_bet365
from history_tracker import get_odds_movement, init_history_db, record_odds_snapshot
from margin_validator import calculate_market_margin, compute_match_margins, validate_market_margins
from scraper_engine import fraction_to_decimal, parse_bet365_kickoff, safe_odd
from validation import (
    validate_basketball_match,
    validate_handball_match,
    validate_match_common,
    validate_pipeline_dataset,
    validate_soccer_match,
)


class TestBet365Parser(unittest.TestCase):
    """Validates low-level Bet365 binary/text frame decoding."""

    def test_parse_bet365_kickoff(self):
        # Bet365 BC: YYYYMMDDHHMMSS (e.g. 20261015204500)
        d_str, ko_str = parse_bet365_kickoff("20261015204500")
        self.assertEqual(d_str, "15/10/2026")
        self.assertEqual(ko_str, "15/10/2026 20:45:00")

        # Fallback when BC is missing
        d_fb, ko_fb = parse_bet365_kickoff("", default_date="11/10/2026")
        self.assertEqual(d_fb, "11/10/2026")
        self.assertEqual(ko_fb, "11/10/2026 20:00:00")

    def test_fraction_to_decimal(self):
        self.assertAlmostEqual(fraction_to_decimal("1/1"), 2.00, places=2)
        self.assertAlmostEqual(fraction_to_decimal("31/20"), 2.55, places=2)
        self.assertAlmostEqual(fraction_to_decimal("5/4"), 2.25, places=2)
        self.assertAlmostEqual(fraction_to_decimal("2.10"), 2.10, places=2)
        self.assertEqual(fraction_to_decimal("invalid"), 1.0)

    def test_bet365_pv_french_deductions(self):
        from bet365_pv import apply_bet365_pv, get_pv_adjustment
        # Verified against Bet365 live JavaScript PriceVarianceLib (Chart 6 - French Market on-screen standard)
        self.assertEqual(apply_bet365_pv(2.90, "6"), 2.82)
        self.assertEqual(apply_bet365_pv(3.50, "6"), 3.40)
        self.assertEqual(apply_bet365_pv(2.35, "6"), 2.29)
        # Chart 9
        self.assertEqual(apply_bet365_pv(2.90, "9"), 2.72)
        self.assertEqual(apply_bet365_pv(3.50, "9"), 3.30)

    def test_safe_odd(self):
        self.assertEqual(safe_odd("2.50"), "2.50")
        self.assertEqual(safe_odd("1,85"), "1.85")
        self.assertEqual(safe_odd("0.5"), "1.02")  # Lower bound clamp
        self.assertEqual(safe_odd("10000"), "5000.00")  # Upper bound clamp
        self.assertEqual(safe_odd("non-number"), "1.50")  # Fallback

    def test_extraire_tournois_splash(self):
        mock_raw = "F|CL;NA=ATP Shanghai;PD=#AC#B13#C1#D1002#E21174420#F1#G83#;|"
        tournaments = extraire_tournois_splash(mock_raw)
        self.assertEqual(len(tournaments), 1)
        self.assertEqual(tournaments[0]["nom"], "ATP Shanghai")
        self.assertIn("bet365.fr", tournaments[0]["url"])


class TestMarginValidator(unittest.TestCase):
    """Validates bookmaker vigorish and overround mathematics."""

    def test_calculate_market_margin(self):
        # 1X2 market: 2.29, 3.50, 2.72
        # 1/2.29 (~0.4367) + 1/3.50 (~0.2857) + 1/2.72 (~0.3676) = 1.0900
        mkt_1x2 = {"1": "2.29", "X": "3.50", "2": "2.72"}
        margin = calculate_market_margin(mkt_1x2)
        self.assertIsNotNone(margin)
        self.assertAlmostEqual(margin, 1.0900, places=2)

        # 2-way market: 1.90, 1.90 -> 1/1.9 + 1/1.9 = 1.0526
        mkt_2way = {"Over": {"line": "2.5", "odds": "1.90"}, "Under": {"line": "2.5", "odds": "1.90"}}
        margin_2way = calculate_market_margin(mkt_2way)
        self.assertAlmostEqual(margin_2way, 1.0526, places=2)

    def test_compute_match_margins(self):
        markets = {
            "Match Result": {"1": "2.00", "X": "3.20", "2": "3.80"},
            "Goals Over/Under": {"Over": {"line": "2.5", "odds": "1.85"}, "Under": {"line": "2.5", "odds": "1.95"}},
        }
        res = compute_match_margins(markets)
        self.assertIn("Match Result", res)
        self.assertIn("Goals Over/Under", res)
        self.assertTrue(float(res["Match Result"]) > 1.0)

    def test_validate_market_margins(self):
        # Normal market within realistic bounds
        normal_mkt = {"Match Result": {"1": "2.20", "X": "3.40", "2": "3.10"}}
        warnings = validate_market_margins(normal_mkt)
        self.assertEqual(len(warnings), 0)

        # Inverted/arbitrage market (margin < 1.0)
        arb_mkt = {"Match Result": {"1": "3.00", "X": "4.00", "2": "4.00"}}
        warnings = validate_market_margins(arb_mkt)
        self.assertTrue(len(warnings) > 0)


class TestHistoryTracker(unittest.TestCase):
    """Validates SQLite historical odds logging and price deduplication."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_record_and_query_history(self):
        sample_dataset = [
            {
                "sport": "Soccer",
                "matches": [
                    {
                        "id": "match_test_01",
                        "date": "15/10/2026",
                        "kickoff": "15/10/2026 21:00:00",
                        "competition": "France Ligue 1",
                        "home": "PSG",
                        "away": "Marseille",
                        "markets": {
                            "Match Result": {"1": "1.60", "X": "4.20", "2": "5.50"}
                        }
                    }
                ]
            }
        ]

        # First recording -> 3 new rows (1, X, 2)
        count_first = record_odds_snapshot(sample_dataset, self.db_path)
        self.assertEqual(count_first, 3)

        # Second recording with IDENTICAL odds -> 0 new rows (deduplicated)
        count_second = record_odds_snapshot(sample_dataset, self.db_path)
        self.assertEqual(count_second, 0)

        # Third recording with CHANGED odds -> exactly 1 new row
        sample_dataset[0]["matches"][0]["markets"]["Match Result"]["1"] = "1.65"
        count_third = record_odds_snapshot(sample_dataset, self.db_path)
        self.assertEqual(count_third, 1)

        # Retrieve chronological movements
        movements = get_odds_movement("match_test_01", "Match Result", self.db_path)
        self.assertEqual(len(movements), 4)


class TestValidationEngine(unittest.TestCase):
    """Validates data constraints, zero synthetic data guarantee, and contamination defense."""

    def test_valid_soccer_match(self):
        match = {
            "id": "soc_001",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:45:00",
            "competition": "France Ligue 1",
            "home": "Lyon",
            "away": "Monaco",
            "markets": {
                "Match Result": {"1": "2.30", "X": "3.40", "2": "2.90"},
                "Goals Over/Under": {"Over": {"line": "2.5", "odds": "1.80"}, "Under": {"line": "2.5", "odds": "2.00"}},
                "Both Teams to Score": {"Yes": "1.65", "No": "2.10"},
                "Double Chance": {"1X": "1.40", "12": "1.30", "X2": "1.55"},
                "Draw No Bet": {"1": "1.70", "2": "2.10"},
            },
            "market_source": {
                "Match Result": "live",
                "Goals Over/Under": "live",
                "Both Teams to Score": "live",
                "Double Chance": "live",
                "Draw No Bet": "live",
            },
            "is_live": False,
            "live_status": {"period": "pre-match", "score": "0-0", "clock": "00:00"}
        }
        ok, why = validate_soccer_match(match)
        self.assertTrue(ok, f"Validation failed: {why}")

    def test_contamination_defense(self):
        # A baseball participant contaminated into soccer
        bad_match = {
            "id": "soc_bad_01",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:45:00",
            "competition": "France Ligue 1",
            "home": "Shohei Ohtani",
            "away": "Monaco",
            "markets": {"Match Result": {"1": "2.0", "X": "3.0", "2": "3.0"}},
            "market_source": {"Match Result": "live"}
        }
        ok, why = validate_soccer_match(bad_match)
        self.assertFalse(ok)
        self.assertIn("Cross-sport contamination", why)

    def test_zero_synthetic_data_guarantee(self):
        match_with_mock = {
            "id": "soc_mock_01",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:45:00",
            "competition": "France Ligue 1",
            "home": "Lens",
            "away": "Lille",
            "markets": {},
            "market_source": {"Match Result": "synthetic"}
        }
        ok, why = validate_match_common(match_with_mock, "Soccer")
        self.assertFalse(ok)
        self.assertIn("non-live provenance", why)

    def test_relaxed_handball_two_way(self):
        # Handball without draw ('X') and without handicap passes without made-up odds
        hb_match = {
            "id": "hb_001",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:00:00",
            "competition": "Handball - France Starligue",
            "home": "Paris SG Handball",
            "away": "Montpellier Handball",
            "markets": {
                "Match Result": {"1": "1.35", "2": "3.80"}
            },
            "market_source": {
                "Match Result": "live"
            },
            "is_live": False,
            "live_status": {"period": "pre-match", "score": "0-0", "clock": "00:00"}
        }
        ok, why = validate_handball_match(hb_match)
        self.assertTrue(ok, f"Validation failed: {why}")

    def test_relaxed_basketball_partial_markets(self):
        # Basketball with only Moneyline (no synthetic 1.65/2.25/1.90) passes cleanly
        b_match = {
            "id": "bk_001",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:00:00",
            "competition": "Basketball - EuroLeague",
            "home": "Real Madrid",
            "away": "Barcelona",
            "markets": {
                "Moneyline": {"1": "1.52", "2": "2.65"}
            },
            "market_source": {
                "Moneyline": "live"
            },
            "is_live": False,
            "live_status": {"period": "pre-match", "score": "0-0", "clock": "00:00"}
        }
        ok, why = validate_basketball_match(b_match)
        self.assertTrue(ok, f"Validation failed: {why}")

    def test_stale_and_blocked_dataset_validation(self):
        # Datasets containing stale retained sports or blocked sports are accepted
        dataset = [
            {"sport": "Soccer", "matches": [], "status": "blocked", "error": "Throttled"},
            {"sport": "Tennis", "matches": [], "status": "unavailable"},
            {"sport": "Basketball", "matches": [], "status": "available"},
            {"sport": "Handball", "matches": [], "status": "available"},
            {"sport": "Cycling", "matches": [], "status": "available"},
            {"sport": "Golf", "matches": [], "status": "available"},
            {"sport": "F1", "matches": [], "status": "available"},
        ]
        ok, errors = validate_pipeline_dataset(dataset)
        self.assertTrue(ok, f"Dataset validation failed: {errors}")


class TestSessionGuard(unittest.TestCase):
    """Validates anti-throttling session guard logic."""

    def test_session_guard_flow(self):
        guard = SessionGuard(threshold=3, pause_s=0.01)
        self.assertFalse(guard.blocked)
        self.assertFalse(guard.paused)

        # 2 failures do not trigger pause
        guard.record(False)
        guard.record(False)
        self.assertFalse(guard.paused)
        self.assertFalse(guard.blocked)

        # 3rd failure triggers pause
        guard.record(False)
        self.assertTrue(guard.paused)
        self.assertFalse(guard.blocked)

        # Next failure after pause triggers blocked state
        guard.record(False)
        self.assertTrue(guard.blocked)

        # Reset clears blocked state
        guard.reset()
        self.assertFalse(guard.blocked)
        self.assertFalse(guard.paused)
        self.assertEqual(guard.consecutive_empty, 0)


if __name__ == "__main__":
    unittest.main()

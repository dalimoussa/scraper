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
import unittest
from datetime import datetime

from bet365_parser import SessionGuard, extraire_tournois_splash, parse_bet365
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

    def test_contamination_audit(self):
        """Audits cross-sport contamination across thresholds, player tokens, and dataset validation:
        1. Basketball Total points line < 100.0 (e.g. 48.5 from handball/volleyball).
        2. Basketball participant token contamination (badminton/tennis players).
        3. Handball Total goals line > 90.0 (e.g. 165.5 from basketball).
        4. Handball participant token contamination.
        5. Pipeline dataset rejection on contaminated matches.
        """
        # 1. Basketball Total < 100.0 rejected
        bk_bad_line = {
            "id": "bk_bad_01",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:00:00",
            "competition": "Basketball - EuroLeague",
            "home": "Real Madrid",
            "away": "Barcelona",
            "markets": {
                "Total": {"Over": {"line": "48.5", "odds": "1.85"}, "Under": {"line": "48.5", "odds": "1.85"}}
            },
            "market_source": {"Total": "live"},
        }
        ok, why = validate_basketball_match(bk_bad_line)
        self.assertFalse(ok)
        self.assertIn("Cross-sport contamination", why)

        # 2. Basketball non-basketball participant token
        bk_bad_token = {
            "id": "bk_bad_02",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:00:00",
            "competition": "Basketball - EuroLeague",
            "home": "Alexander Zverev",
            "away": "Barcelona",
            "markets": {"Moneyline": {"1": "1.50", "2": "2.50"}},
            "market_source": {"Moneyline": "live"},
        }
        ok, why = validate_basketball_match(bk_bad_token)
        self.assertFalse(ok)
        self.assertIn("Cross-sport contamination", why)

        # 3. Handball Total > 90.0 rejected
        hb_bad_line = {
            "id": "hb_bad_01",
            "date": "15/10/2026",
            "kickoff": "15/10/2026 20:00:00",
            "competition": "Handball - France Starligue",
            "home": "Paris SG Handball",
            "away": "Montpellier Handball",
            "markets": {
                "Total": {"Over": {"line": "165.5", "odds": "1.85"}, "Under": {"line": "165.5", "odds": "1.85"}}
            },
            "market_source": {"Total": "live"},
        }
        ok, why = validate_handball_match(hb_bad_line)
        self.assertFalse(ok)
        self.assertIn("Cross-sport contamination", why)

        # 4. Pipeline dataset audit catches contaminated matches
        dataset = [
            {"sport": "Soccer", "matches": []},
            {"sport": "Tennis", "matches": []},
            {"sport": "Basketball", "matches": [bk_bad_line]},
            {"sport": "Handball", "matches": []},
            {"sport": "Cycling", "matches": []},
            {"sport": "Golf", "matches": []},
            {"sport": "F1", "matches": []},
        ]
        is_valid, errors = validate_pipeline_dataset(dataset)
        self.assertFalse(is_valid)
        self.assertTrue(any("Cross-sport contamination" in err for err in errors))

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


class TestAnjPriceVarianceAndLiveMarkets(unittest.TestCase):
    """Locks in the ANJ PV correctness and the no-synthetic-markets guarantee."""

    # The exact worked example from the client brief.
    RAW_1X2_FEED = (
        "MA;NA=Résultat du match;ID=M40;|"
        "PA;FI=123;OD=19/10;NA=1;|"   # 2.90
        "PA;FI=123;OD=5/2;NA=X;|"     # 3.50
        "PA;FI=123;OD=27/20;NA=2;|"   # 2.35
    )

    def test_chart6_worked_example(self):
        from bet365_pv import apply_bet365_pv, verify_chart6
        self.assertTrue(verify_chart6())
        self.assertEqual(apply_bet365_pv(2.90, "6"), 2.82)
        self.assertEqual(apply_bet365_pv(3.50, "6"), 3.40)
        self.assertEqual(apply_bet365_pv(2.35, "6"), 2.29)

    def test_screen_odd_from_display_reads_ground_truth(self):
        from bet365_pv import screen_odd_from_display
        self.assertEqual(screen_odd_from_display("2.82"), "2.82")
        self.assertEqual(screen_odd_from_display("2,82"), "2.82")
        self.assertEqual(screen_odd_from_display(" 10.50 "), "10.50")
        self.assertIsNone(screen_odd_from_display("-"))
        self.assertIsNone(screen_odd_from_display(""))
        self.assertIsNone(screen_odd_from_display("SP"))

    def test_feed_to_screen_matches_brief(self):
        from live_markets import build_soccer_markets, extract_market_rows, screen_rows
        rows = extract_market_rows(self.RAW_1X2_FEED)
        self.assertEqual(len(rows), 3)
        rows = screen_rows(None, rows, ki="1", l3="", sport="Soccer")
        markets, source, prov, raw = build_soccer_markets(rows, "Le Mans", "Toulouse")
        self.assertEqual(markets["Match Result"], {"1": "2.82", "X": "3.40", "2": "2.29"})
        self.assertEqual(raw["Match Result"], {"1": "2.90", "X": "3.50", "2": "2.35"})
        self.assertEqual(source["Match Result"], "live")
        self.assertEqual(prov["Match Result"], "chart")

    def test_no_fabricated_secondary_markets(self):
        from live_markets import build_soccer_markets, extract_market_rows, screen_rows
        # A feed that carries ONLY Match Result must yield ONLY Match Result.
        rows = screen_rows(None, extract_market_rows(self.RAW_1X2_FEED), sport="Soccer")
        markets, source, prov, _ = build_soccer_markets(rows, "Le Mans", "Toulouse")
        self.assertEqual(set(markets.keys()), {"Match Result"})
        for forbidden in ("Both Teams to Score", "Correct Score", "Half Time/Full Time",
                          "Double Chance", "Draw No Bet", "Goals Over/Under"):
            self.assertNotIn(forbidden, markets)

    def test_partial_market_is_omitted_not_invented(self):
        from live_markets import build_soccer_markets, extract_market_rows, screen_rows
        partial = "MA;NA=Résultat du match;ID=M40;|PA;FI=9;OD=19/10;NA=1;|PA;FI=9;OD=5/2;NA=X;|"
        rows = screen_rows(None, extract_market_rows(partial), sport="Soccer")
        markets, _, _, _ = build_soccer_markets(rows, "A", "B")
        self.assertNotIn("Match Result", markets)

    def test_pv_audit_catches_mismatch(self):
        from validation import audit_pv_consistency
        good = {
            "markets": {"Match Result": {"1": "2.82", "X": "3.40", "2": "2.29"}},
            "unadjusted_raw_markets": {"Match Result": {"1": "2.90", "X": "3.50", "2": "2.35"}},
            "market_provenance": {"Match Result": "chart"},
        }
        self.assertEqual(audit_pv_consistency(good, "Soccer"), [])

        bad = {
            "markets": {"Match Result": {"1": "2.90", "X": "3.50", "2": "2.35"}},  # raw shown as screen
            "unadjusted_raw_markets": {"Match Result": {"1": "2.90", "X": "3.50", "2": "2.35"}},
            "market_provenance": {"Match Result": "chart"},
        }
        self.assertTrue(audit_pv_consistency(bad, "Soccer"))

    def test_provenance_guard_rejects_bad_method(self):
        from validation import validate_match_common
        m = {
            "id": "x", "date": "15/10/2026", "kickoff": "15/10/2026 20:00:00",
            "competition": "France Ligue 1", "home": "Lyon", "away": "Monaco",
            "markets": {"Match Result": {"1": "2.30", "X": "3.40", "2": "2.90"}},
            "market_source": {"Match Result": "live"},
            "market_provenance": {"Match Result": "poisson"},
        }
        ok, why = validate_match_common(m, "Soccer")
        self.assertFalse(ok)
        self.assertIn("invalid capture method", why)

    def test_filter_synthetic_strips_non_live(self):
        from live_markets import filter_synthetic
        dataset = [{
            "sport": "Soccer",
            "matches": [{
                "id": "m1",
                "markets": {"Match Result": {"1": "2.0"}, "Correct Score": {"1-0": "9.0"}},
                "market_source": {"Match Result": "live", "Correct Score": "synthetic"},
            }],
        }]
        out = filter_synthetic(dataset)
        mkts = out[0]["matches"][0]["markets"]
        self.assertIn("Match Result", mkts)
        self.assertNotIn("Correct Score", mkts)

    def test_capture_evidence_audit_flags_unproven_markets(self):
        from validation import audit_capture_evidence, validate_pipeline_dataset
        # Legacy artefact: modelled secondary markets tagged "live" with no proof.
        legacy = {
            "id": "soc_leg", "date": "15/10/2026", "kickoff": "15/10/2026 20:45:00",
            "competition": "France Ligue 1", "home": "Le Mans", "away": "Toulouse",
            "markets": {"Match Result": {"1": "2.82", "X": "3.40", "2": "2.29"}, "Both Teams to Score": {"Yes": "1.52", "No": "2.19"}},
            "market_source": {"Match Result": "live", "Both Teams to Score": "live"},
        }
        self.assertTrue(audit_capture_evidence(legacy, "Soccer"))
        # New artefact: every market carries a capture method.
        proven = {
            "id": "soc_prov", "date": "15/10/2026", "kickoff": "15/10/2026 20:45:00",
            "competition": "France Ligue 1", "home": "Le Mans", "away": "Toulouse",
            "markets": {"Match Result": {"1": "2.82", "X": "3.40", "2": "2.29"}, "Both Teams to Score": {"Yes": "1.52", "No": "2.19"}},
            "market_source": {"Match Result": "live", "Both Teams to Score": "live"},
            "market_provenance": {"Match Result": "js", "Both Teams to Score": "dom"},
        }
        self.assertEqual(audit_capture_evidence(proven, "Soccer"), [])

        # Pipeline dataset validation flags the unproven legacy fixture
        bad_dataset = [
            {"sport": "Soccer", "matches": [legacy]},
            {"sport": "Tennis", "matches": []},
            {"sport": "Basketball", "matches": []},
            {"sport": "Handball", "matches": []},
            {"sport": "Cycling", "matches": []},
            {"sport": "Golf", "matches": []},
            {"sport": "F1", "matches": []},
        ]
        ok, errors = validate_pipeline_dataset(bad_dataset)
        self.assertFalse(ok)
        self.assertTrue(any("secondary markets present without capture evidence" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

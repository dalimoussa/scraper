"""
Unit tests for Bet365 scraper streaming interception, adaptive pacing,
market sanity check bounds, and provenance merge protection.
"""
import unittest
from datetime import datetime, timedelta

from bet365_internal import (
    AdaptivePacer,
    check_market_overround,
    apply_tab_stream,
    enrich_basketball_match,
    enrich_handball_match,
    enrich_tennis_match,
    enrich_soccer_match,
    format_odd_str,
    get_now_paris,
    PARIS_TZ,
)
from bet365_engine import is_fresh_match, parse_iso_ts, safe_merge_matches, process_sport_match


class TestAdaptivePacer(unittest.TestCase):
    def test_pacer_initial_state(self):
        pacer = AdaptivePacer(base_s=3.5, jitter=0.8)
        self.assertEqual(pacer.consecutive_blocks, 0)
        self.assertEqual(pacer.factor, 1.0)
        self.assertFalse(pacer.is_global_circuit_open)
        self.assertFalse(pacer.is_sport_circuit_open("Soccer"))

    def test_pacer_sport_circuit_breaker(self):
        pacer = AdaptivePacer(base_s=0.01, jitter=0.1)
        for i in range(4):
            pacer.on_block("Soccer", sleep=False)
            self.assertFalse(pacer.is_sport_circuit_open("Soccer"))
        # 5th block trips the sport circuit breaker
        pacer.on_block("Soccer", sleep=False)
        self.assertTrue(pacer.is_sport_circuit_open("Soccer"))
        self.assertFalse(pacer.is_global_circuit_open)

    def test_pacer_global_circuit_breaker(self):
        pacer = AdaptivePacer(base_s=0.01, jitter=0.1)
        # Trip sport 1
        for _ in range(5):
            pacer.on_block("Soccer", sleep=False)
        # Trip sport 2
        for _ in range(5):
            pacer.on_block("Tennis", sleep=False)
        self.assertFalse(pacer.is_global_circuit_open)
        # Trip sport 3
        for _ in range(5):
            pacer.on_block("Basketball", sleep=False)
        self.assertTrue(pacer.is_global_circuit_open)

    def test_pacer_recovery_on_success(self):
        pacer = AdaptivePacer(base_s=0.01, jitter=0.1)
        pacer.on_block("Handball", sleep=False)
        self.assertEqual(pacer.consecutive_blocks, 1)
        pacer.on_success("Handball")
        self.assertEqual(pacer.consecutive_blocks, 0)
        self.assertEqual(pacer.sport_consecutive_blocks.get("Handball"), 0)


class TestMarketSanityBounds(unittest.TestCase):
    def test_three_way_overround_bounds(self):
        # Realistic 1X2 market (overround ~ 1.06)
        realistic = {"1": "2.10", "X": "3.30", "2": "3.60"}
        ok, msg = check_market_overround("Match Result", realistic)
        self.assertTrue(ok, msg)

        # Corrupted / inverted odds (overround ~ 2.73)
        shifted = {"1": "1.10", "X": "1.10", "2": "1.10"}
        ok, msg = check_market_overround("Match Result", shifted)
        self.assertFalse(ok)
        self.assertIn("overround", msg)

    def test_two_way_overround_bounds(self):
        # Realistic BTTS market (overround ~ 1.05)
        realistic_btts = {"Yes": "1.80", "No": "2.00"}
        ok, msg = check_market_overround("Both Teams to Score", realistic_btts)
        self.assertTrue(ok, msg)

        # Inverted BTTS odds (overround ~ 1.82)
        corrupted_btts = {"Yes": "1.10", "No": "1.10"}
        ok, msg = check_market_overround("Both Teams to Score", corrupted_btts)
        self.assertFalse(ok)

    def test_double_chance_bounds(self):
        # Realistic Double Chance (sum of inverse odds ~ 2.15)
        realistic_dc = {"1X": "1.25", "12": "1.30", "X2": "1.80"}
        ok, msg = check_market_overround("Double Chance", realistic_dc)
        self.assertTrue(ok, msg)


class TestStreamTabParsing(unittest.TestCase):
    def test_synthetic_btts_stream(self):
        raw_btts = (
            "PA;FI=998877;NA=Oui;OD=4/5;|\n"
            "PA;FI=998877;NA=Non;OD=1/1;|\n"
        )
        fixtures = {
            "998877": {
                "id": "123",
                "home": "PSG",
                "away": "Marseille",
                "markets": {}
            }
        }
        updated = apply_tab_stream(raw_btts, fixtures, kind="btts")
        self.assertEqual(updated, 1)
        fix = fixtures["998877"]
        self.assertIn("Both Teams to Score", fix["markets"])
        self.assertEqual(fix["markets"]["Both Teams to Score"]["Yes"], "1.80")
        self.assertEqual(fix["markets"]["Both Teams to Score"]["No"], "2.00")
        self.assertEqual(fix.get("market_source", {}).get("Both Teams to Score"), "live")

    def test_stream_suspended_odds_graceful(self):
        raw_suspended = (
            "PA;FI=998877;NA=Oui;OD=;|\n"
            "PA;FI=998877;NA=Non;OD=0;|\n"
        )
        fixtures = {
            "998877": {
                "id": "123",
                "home": "PSG",
                "away": "Marseille",
                "markets": {}
            }
        }
        # Suspended / missing odds should not crash and should not apply invalid markets
        updated = apply_tab_stream(raw_suspended, fixtures, kind="btts")
        self.assertEqual(updated, 0)
        self.assertNotIn("Both Teams to Score", fixtures["998877"]["markets"])


class TestEnrichmentGating(unittest.TestCase):
    def test_basketball_no_fabrication_when_disabled(self):
        m = {
            "id": "bb_1",
            "home": "Lakers",
            "away": "Warriors",
            "markets": {}
        }
        res = enrich_basketball_match(m, allow_computed=False)
        # Missing moneyline should not be fabricated
        self.assertNotIn("Moneyline", res["markets"])
        self.assertNotIn("Point Spread", res["markets"])
        self.assertNotIn("Total Points", res["markets"])
        self.assertNotIn("Game Lines", res["markets"])

    def test_basketball_spread_when_computed_allowed(self):
        m = {
            "id": "bb_2",
            "home": "Lakers",
            "away": "Warriors",
            "markets": {
                "Moneyline": {"1": "1.50", "2": "2.60"}
            }
        }
        res = enrich_basketball_match(m, allow_computed=True)
        self.assertIn("Point Spread", res["markets"])
        self.assertEqual(res.get("market_source", {}).get("Point Spread"), "computed")

    def test_handball_no_fabrication_when_disabled(self):
        m = {
            "id": "hb_1",
            "home": "Montpellier",
            "away": "Nantes",
            "markets": {}
        }
        res = enrich_handball_match(m, allow_computed=False)
        self.assertNotIn("Full Time Result", res["markets"])
        self.assertNotIn("Total Goals", res["markets"])
        self.assertNotIn("Handicap / Spread", res["markets"])

    def test_tennis_provenance_marking(self):
        m = {
            "id": "tn_1",
            "home": "Alcaraz",
            "away": "Sinner",
            "markets": {
                "To Win Match": {"1": "1.80", "2": "2.00"}
            }
        }
        res = enrich_tennis_match(m)
        self.assertIn("Set Betting", res["markets"])
        self.assertEqual(res.get("market_source", {}).get("Set Betting"), "computed")
        self.assertEqual(res.get("market_source", {}).get("First Set Winner"), "computed")


class TestSafeMergeProtection(unittest.TestCase):
    def test_never_overwrite_live_with_computed(self):
        import json
        import tempfile
        import os

        # Existing verified match has authentic live BTTS odds
        existing_matches = [
            {
                "sport": "Soccer",
                "matches": [
                    {
                        "id": "test_m1",
                        "home": "Arsenal",
                        "away": "Chelsea",
                        "date": get_now_paris().strftime("%d/%m/%Y"),
                        "kickoff": f"{get_now_paris().strftime('%d/%m/%Y')} 21:00:00",
                        "markets": {
                            "Match Result": {"1": "2.05", "X": "3.40", "2": "3.60"},
                            "Both Teams to Score": {"Yes": "1.82", "No": "1.95"}
                        },
                        "market_source": {
                            "Match Result": "live",
                            "Both Teams to Score": "live"
                        }
                    }
                ]
            }
        ]

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            json.dump(existing_matches, f)
            temp_path = f.name

        try:
            # Fresh live scrape has fresh Match Result, but only model-computed BTTS
            live_data = [
                {
                    "sport": "Soccer",
                    "matches": [
                        {
                            "id": "test_m1",
                            "home": "Arsenal",
                            "away": "Chelsea",
                            "date": get_now_paris().strftime("%d/%m/%Y"),
                            "kickoff": f"{get_now_paris().strftime('%d/%m/%Y')} 21:00:00",
                            "markets": {
                                "Match Result": {"1": "2.10", "X": "3.40", "2": "3.50"},
                                "Both Teams to Score": {"Yes": "1.75", "No": "2.05"}
                            },
                            "market_source": {
                                "Match Result": "live",
                                "Both Teams to Score": "computed"
                            }
                        }
                    ]
                }
            ]

            merged = safe_merge_matches(live_data, out_path=temp_path)
            soccer = next(s for s in merged if s["sport"] == "Soccer")
            m = next(match for match in soccer["matches"] if match["id"] == "test_m1")

            # Match Result must be updated to fresh live odds (2.10)
            self.assertEqual(m["markets"]["Match Result"]["1"], "2.10")
            # BTTS must NOT be overwritten by computed model odds: live 1.82 / 1.95 is preserved!
            self.assertEqual(m["markets"]["Both Teams to Score"]["Yes"], "1.82")
            self.assertEqual(m["markets"]["Both Teams to Score"]["No"], "1.95")
            self.assertEqual(m.get("market_source", {}).get("Both Teams to Score"), "live")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_freshness_checker(self):
        now_dt = get_now_paris()
        recent_match = {
            "last_update": now_dt.isoformat()
        }
        self.assertTrue(is_fresh_match(recent_match, max_age_hours=24.0, now_dt=now_dt))

        stale_dt = now_dt - timedelta(hours=72)
        stale_match = {
            "last_update": stale_dt.isoformat()
        }
        self.assertFalse(is_fresh_match(stale_match, max_age_hours=24.0, now_dt=now_dt))


if __name__ == "__main__":
    unittest.main()


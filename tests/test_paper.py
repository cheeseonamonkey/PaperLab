import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yeno
import research

class PaperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = patch.object(yeno, "LEDGER", Path(temporary.name) / "ledger.json")
        override.start()
        self.addCleanup(override.stop)
        self.obs = {
            "slug": "btc-updown-15m-1794637800", "ends": 1794638700,
            "observed_at": "2026-11-14 00:00:00 UTC",
            "features": {"ret5": .002, "ret15": .001},
            "quotes": {"Up": {"price": .50, "size": 1000}, "Down": {"price": .49, "size": 1000}},
            "outcome": None,
        }
        self.params = yeno.validate(json.loads(yeno.STRATEGY.read_text()))

    def test_no_real_order_endpoints_or_exchange_credentials(self):
        # No signing or actual trade submission is present in the paper engine.
        source = Path(yeno.__file__).read_text()
        self.assertNotIn("api_key", source.lower())
        self.assertNotIn("private_key", source.lower())
        self.assertNotIn("Request(url, data=", source)

    def test_model_uses_quoted_ask_and_fees(self):
        pick = yeno.choose(self.obs, self.params)
        self.assertEqual(pick["side"], "Up")
        self.assertGreater(pick["price"], .50)
        state = yeno.load()
        self.assertIn("Paper BUY", yeno.enter(state, self.obs, self.params))
        self.assertEqual(state["cash"], 99)
        self.assertLess(state["trades"][0]["shares"], 2)

    def test_trade_never_exceeds_quoted_liquidity(self):
        self.obs["quotes"]["Up"]["size"] = .01
        state = yeno.load()
        self.assertIn("liquidity", yeno.enter(state, self.obs, self.params))
        self.assertEqual(state["cash"], 100)
        self.assertEqual(state["trades"], [])

    def test_no_duplicate_trade(self):
        state = yeno.load()
        yeno.enter(state, self.obs, self.params)
        self.assertIn("Duplicate", yeno.enter(state, self.obs, self.params))
        self.assertEqual(len(state["trades"]), 1)

    def test_settlement_official_only(self):
        self.assertIsNone(yeno.winner({"closed": True, "outcomePrices": '["1","0"]'}))
        self.assertEqual(yeno.winner({"closed": True, "umaResolutionStatus": "resolved", "outcomePrices": '["1","0"]'}), "Up")
        state = yeno.load()
        yeno.enter(state, self.obs, self.params)
        state["observations"].append(self.obs)
        with patch.object(yeno, "market", return_value={"closed": True, "umaResolutionStatus": "resolved", "outcomePrices": '["1","0"]'}):
            self.assertEqual(yeno.settle(state, self.obs["ends"] + 300), 1)
        self.assertEqual(state["trades"][0]["status"], "settled")
        self.assertGreater(state["cash"], 100)
        self.assertEqual(state["observations"][0]["outcome"], "Up")

    def test_unresolved_market_never_settles(self):
        state = yeno.load()
        self.obs["outcome"] = None
        state["observations"].append(self.obs)
        with patch.object(yeno, "market", return_value={"closed": True, "umaResolutionStatus": "disputed", "outcomePrices": '["1","0"]'}):
            self.assertEqual(yeno.settle(state, self.obs["ends"]+300), 0)
        self.assertIsNone(state["observations"][0]["outcome"])

    def test_invalid_params(self):
        for bad in ({"w5": float("nan"), **{k:v for k,v in self.params.items() if k!="w5"}}, {**self.params, "max_price": 1}, {**self.params, "extra": 1}):
            with self.assertRaises(ValueError):
                yeno.validate(bad)

    def test_research_matches_paper_execution(self):
        pick = yeno.choose(self.obs, self.params)
        self.obs["outcome"] = pick["side"]
        result = research.simulate([self.obs], self.params)
        self.assertEqual(result["trades"], 1)
        self.assertGreater(result["profit"], 0)

if __name__ == "__main__":
    unittest.main()

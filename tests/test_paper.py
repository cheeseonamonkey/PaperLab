import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import feeds
import predictors
import yeno

class PaperTests(unittest.TestCase):
    def setUp(self):
        self.now = 1794643205
        self.slug = feeds.window_slug(self.now//900*900)
        self.obs = {
            "venue": "polymarket_us", "slug": self.slug,
            "start": self.now//900*900, "ends": self.now//900*900+900,
            "observed_at": self.now,
            "quotes": {
                "Up": {"bid": .47, "ask": .49, "bid_size": 100, "ask_size": 100,
                       "bid_depth": 300, "ask_depth": 200},
                "Down": {"bid": .51, "ask": .53, "bid_size": 100, "ask_size": 100,
                         "bid_depth": 200, "ask_depth": 300},
            },
            "features": {"strike_distance":.0003,"brti_close":67000,"price_to_beat":66980,
                "btc_r5":.002,"btc_vol15":.001,"btc_r15":.001,
                "eth_r5":.002,"sol_r5":.002,"xrp_r5":.002,
                "yes_book_imbalance":.2},
            "display_history":[], "brti_history":[]
        }
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for name in ("STATE","REPORT"):
            value=Path(self.dir.name)/("state.json" if name=="STATE" else "REPORT.md")
            override=patch.object(yeno,name,value)
            override.start()
            self.addCleanup(override.stop)
        over=patch.object(yeno,"OBS_DIR",Path(self.dir.name)/"obs")
        over.start()
        self.addCleanup(over.stop)

    def test_12_independent_paper_accounts(self):
        s=yeno.initial()
        self.assertEqual(len(s["accounts"]),12)
        self.assertTrue(all(a["cash"]==100 for a in s["accounts"].values()))
        self.assertNotIn("polymarket.com",feeds.API)
        self.assertEqual(s["venue"],"polymarket_us")
        self.assertEqual(s["mode"],"paper")

    def test_yes_and_no_us_book_complements(self):
        out=feeds.quotes({"bids":[{"px":{"value":".47"},"qty":"90"}],
                "offers":[{"px":{"value":".49"},"qty":"80"}]})
        self.assertEqual(out["Down"]["ask"],.53)
        self.assertEqual(out["Down"]["bid"],.51)
        self.assertEqual(out["Down"]["ask_size"],90)

    def test_maker_limit_reserves_but_does_not_fill_same_tick(self):
        acct=yeno.initial()["accounts"]["lstm"]
        order=yeno.maybe_order(acct,self.obs,.9,"limit",self.now)
        self.assertEqual(order,"LIMIT Up")
        self.assertEqual(len(acct["orders"]),1)
        self.assertEqual(acct["cash"],100)
        self.assertLess(yeno.available(acct),100)
        yeno.evaluate_limits(acct,self.obs,self.now)
        self.assertEqual(acct["orders"][0]["status"],"open")
        self.assertEqual(len(acct["trades"]),0)

    def test_limit_requires_later_ask_cross_and_depth(self):
        acct=yeno.initial()["accounts"]["lstm"]
        yeno.maybe_order(acct,self.obs,.9,"limit",self.now)
        updated=copy.deepcopy(self.obs)
        updated["quotes"]["Up"]["ask"]=.47
        updated["quotes"]["Up"]["ask_size"]=.1
        yeno.evaluate_limits(acct,updated,self.now+15)
        self.assertEqual(acct["orders"][0]["status"],"open")
        updated["quotes"]["Up"]["ask_size"]=100
        yeno.evaluate_limits(acct,updated,self.now+30)
        self.assertEqual(acct["orders"][0]["status"],"filled")
        self.assertEqual(acct["trades"][0]["type"],"limit_cross")
        self.assertLess(acct["cash"],100)

    def test_unfilled_limit_expiration_and_released_cash(self):
        acct=yeno.initial()["accounts"]["lstm"]
        yeno.maybe_order(acct,self.obs,.9,"limit",self.now)
        yeno.evaluate_limits(acct,self.obs,self.obs["ends"]+5)
        self.assertEqual(acct["orders"][0]["status"],"expired")
        self.assertEqual(yeno.available(acct),100)

    def test_marketable_entry_respects_liquidity_and_min_shares(self):
        acct=yeno.initial()["accounts"]["conv_gru"]
        updated=copy.deepcopy(self.obs)
        updated["quotes"]["Up"]["ask_size"]=1
        self.assertIn("no-fill",yeno.maybe_order(acct,updated,.9,"market",self.now))
        self.assertEqual(acct["cash"],100)
        self.assertFalse(acct["trades"])
        self.assertEqual(yeno.maybe_order(acct,self.obs,.9,"market",self.now),"PAPER MARKET Up")
        self.assertEqual(acct["trades"][0]["status"],"open")

    def test_isolated_duplicate_and_risk_budget(self):
        state=yeno.initial()
        yeno.process_snapshot(state,self.obs,{"lstm":.9,"conv_gru":.9})
        self.assertEqual(len(state["accounts"]["lstm"]["orders"]),1)
        self.assertEqual(len(state["accounts"]["conv_gru"]["orders"]),1)
        original=state["accounts"]["lstm"]["orders"][0]["reserved"]
        yeno.process_snapshot(state,self.obs,{"lstm":.9,"conv_gru":.9})
        self.assertEqual(len(state["accounts"]["lstm"]["orders"]),1)
        self.assertEqual(original,state["accounts"]["lstm"]["orders"][0]["reserved"])
        self.assertEqual(len(state["accounts"]["conv_gru"]["orders"]),1)

    def test_five_minute_limit_opportunities_and_size(self):
        acct=yeno.initial()["accounts"]["brti_distance"]
        self.assertEqual(yeno.maybe_order(acct,self.obs,.9,"limit",self.now),"LIMIT Up")
        self.assertGreater(acct["orders"][0]["cost"],5)
        self.assertLessEqual(acct["orders"][0]["cost"],15)
        self.assertIsNone(yeno.maybe_order(acct,self.obs,.9,"limit",self.now+1))
        self.assertEqual(yeno.maybe_order(acct,self.obs,.9,"limit",self.now+300),"LIMIT Up")
        self.assertEqual(len(acct["orders"]),2)
        self.assertTrue(all(mode in ("limit","hold") for mode in yeno.POLICIES.values()))

    def test_resolution_only_official_us_api_and_cash(self):
        state=yeno.initial()
        acct=state["accounts"]["conv_gru"]
        yeno.maybe_order(acct,self.obs,.9,"market",self.now)
        state["markets"][self.slug]={"ends":self.obs["ends"],"outcome":None,"checked_at":0}
        with patch.object(yeno,"settlement",return_value=None):
            yeno.reconcile(state,self.obs["ends"]+61)
        self.assertEqual(acct["trades"][0]["status"],"open")
        with patch.object(yeno,"settlement",return_value="Up"):
            yeno.reconcile(state,self.obs["ends"]+123)
        self.assertEqual(acct["trades"][0]["status"],"settled")
        self.assertGreater(acct["cash"],100)
        self.assertEqual(state["markets"][self.slug]["outcome"],"Up")

    def test_reject_other_venue_state(self):
        state=yeno.initial();state["venue"]="polymarket_international"
        yeno.STATE.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            yeno.load()

    def test_public_observation_archives_are_recoverable(self):
        yeno.append_observation(self.obs)
        import gzip
        only=list(yeno.OBS_DIR.glob("*.gz"))
        self.assertEqual(len(only),1)
        with gzip.open(only[0],"rt") as handle:
            row=json.loads(handle.readline())
        self.assertEqual(row["slug"],self.slug)
        self.assertEqual(row["venue"],"polymarket_us")

    def test_checkpoint_dimensions(self):
        self.assertEqual(len(predictors.SCALES["x_mean"]),24)
        self.assertEqual(len(predictors.SCALES["c_mean"]),64)
        self.assertEqual(len(predictors.MODELS),5)

if __name__=="__main__":
    unittest.main()

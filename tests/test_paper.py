import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import feeds
import predictors
import paper

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
            override=patch.object(paper,name,value)
            override.start()
            self.addCleanup(override.stop)
        over=patch.object(paper,"OBS_DIR",Path(self.dir.name)/"obs")
        over.start()
        self.addCleanup(over.stop)

    def test_13_independent_paper_accounts(self):
        s=paper.initial()
        self.assertEqual(len(s["accounts"]),13)
        self.assertTrue(all(a["cash"]==100 for a in s["accounts"].values()))
        self.assertIn("research_linear",s["accounts"])
        self.assertNotIn("polymarket.com",feeds.API)
        self.assertEqual(s["venue"],"polymarket_us")
        self.assertEqual(s["mode"],"paper")

    def test_v2_state_migrates_without_losing_history(self):
        state=paper.initial()
        state["version"]=2
        state["accounts"].pop("research_linear")
        state["forecast_metrics"].pop("research_linear")
        state["accounts"]["lstm"].update(cash=73.5,orders=[{"slug":"old","status":"filled"}],signals=4)
        paper.STATE.write_text(json.dumps(state))
        migrated=paper.load()
        self.assertEqual(migrated["version"],paper.STATE_VERSION)
        self.assertEqual(migrated["accounts"]["lstm"]["cash"],73.5)
        self.assertEqual(migrated["accounts"]["lstm"]["orders"],[{"slug":"old","status":"filled"}])
        self.assertEqual(migrated["accounts"]["lstm"]["signals"],4)
        self.assertEqual(migrated["accounts"]["research_linear"]["cash"],paper.START)
        self.assertIn("research_linear",migrated["forecast_metrics"])

    def test_yes_and_no_us_book_complements(self):
        out=feeds.quotes({"bids":[{"px":{"value":".47"},"qty":"90"}],
                "offers":[{"px":{"value":".49"},"qty":"80"}]})
        self.assertEqual(out["Down"]["ask"],.53)
        self.assertEqual(out["Down"]["bid"],.51)
        self.assertEqual(out["Down"]["ask_size"],90)

    def test_maker_limit_reserves_but_does_not_fill_same_tick(self):
        acct=paper.initial()["accounts"]["lstm"]
        order=paper.maybe_order(acct,self.obs,.9,"limit",self.now)
        self.assertEqual(order,"LIMIT Up")
        self.assertEqual(len(acct["orders"]),1)
        self.assertEqual(acct["cash"],100)
        self.assertLess(paper.available(acct),100)
        paper.evaluate_limits(acct,self.obs,self.now)
        self.assertEqual(acct["orders"][0]["status"],"open")
        self.assertEqual(len(acct["trades"]),0)

    def test_limit_requires_later_ask_cross_and_depth(self):
        acct=paper.initial()["accounts"]["lstm"]
        paper.maybe_order(acct,self.obs,.9,"limit",self.now)
        updated=copy.deepcopy(self.obs)
        updated["quotes"]["Up"]["ask"]=.47
        updated["quotes"]["Up"]["ask_size"]=.1
        paper.evaluate_limits(acct,updated,self.now+15)
        self.assertEqual(acct["orders"][0]["status"],"open")
        updated["quotes"]["Up"]["ask_size"]=100
        paper.evaluate_limits(acct,updated,self.now+30)
        self.assertEqual(acct["orders"][0]["status"],"filled")
        self.assertEqual(acct["trades"][0]["type"],"limit_cross")
        self.assertLess(acct["cash"],100)

    def test_unfilled_limit_expiration_and_released_cash(self):
        acct=paper.initial()["accounts"]["lstm"]
        paper.maybe_order(acct,self.obs,.9,"limit",self.now)
        paper.evaluate_limits(acct,self.obs,self.obs["ends"]+5)
        self.assertEqual(acct["orders"][0]["status"],"expired")
        self.assertEqual(paper.available(acct),100)

    def test_marketable_entry_respects_liquidity_and_min_shares(self):
        acct=paper.initial()["accounts"]["conv_gru"]
        updated=copy.deepcopy(self.obs)
        updated["quotes"]["Up"]["ask_size"]=1
        self.assertIn("no-fill",paper.maybe_order(acct,updated,.9,"market",self.now))
        self.assertEqual(acct["cash"],100)
        self.assertFalse(acct["trades"])
        self.assertEqual(paper.maybe_order(acct,self.obs,.9,"market",self.now),"PAPER MARKET Up")
        self.assertEqual(acct["trades"][0]["status"],"open")

    def test_isolated_duplicate_and_risk_budget(self):
        state=paper.initial()
        paper.process_snapshot(state,self.obs,{"lstm":.9,"conv_gru":.9})
        self.assertEqual(len(state["accounts"]["lstm"]["orders"]),1)
        self.assertEqual(len(state["accounts"]["conv_gru"]["orders"]),1)
        original=state["accounts"]["lstm"]["orders"][0]["reserved"]
        paper.process_snapshot(state,self.obs,{"lstm":.9,"conv_gru":.9})
        self.assertEqual(len(state["accounts"]["lstm"]["orders"]),1)
        self.assertEqual(original,state["accounts"]["lstm"]["orders"][0]["reserved"])
        self.assertEqual(len(state["accounts"]["conv_gru"]["orders"]),1)

    def test_three_concurrent_markets_share_one_exposure_budget(self):
        acct = paper.initial()["accounts"]["brti_distance"]
        self.assertEqual(paper.MAX_ORDER_EQUITY_FRACTION, .10)
        self.assertEqual(paper.MAX_EXPOSURE_EQUITY_FRACTION, .30)
        for i in range(3):
            obs = copy.deepcopy(self.obs)
            obs["slug"] = "concurrent-" + str(i)
            self.assertEqual(paper.maybe_order(acct, obs, .9, "limit", self.now), "LIMIT Up")
        self.assertEqual(len([o for o in acct["orders"] if o["status"] == "open"]), 3)
        self.assertGreater(paper.committed_exposure(acct), 29.9)
        self.assertLessEqual(paper.committed_exposure(acct), 30)
        extra = copy.deepcopy(self.obs)
        extra["slug"] = "concurrent-overflow"
        self.assertIsNone(paper.maybe_order(acct, extra, .9, "limit", self.now))

    def test_one_minute_limit_opportunities_and_size(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        self.assertEqual(paper.maybe_order(acct,self.obs,.9,"limit",self.now),"LIMIT Up")
        self.assertGreater(acct["orders"][0]["cost"],0)
        self.assertLessEqual(acct["orders"][0]["cost"],paper.MAX_ORDER_EQUITY_FRACTION*paper.START)
        self.assertIsNone(paper.maybe_order(acct,self.obs,.9,"limit",self.now+1))
        self.assertEqual(paper.maybe_order(acct,self.obs,.9,"limit",self.now+60),"LIMIT Up")
        self.assertEqual(len(acct["orders"]),2)
        self.assertTrue(all(mode in ("limit","hold") for mode in paper.POLICIES.values()))

    def test_size_varies_with_estimated_edge(self):
        small=paper.initial()["accounts"]["brti_distance"]
        large=paper.initial()["accounts"]["brti_distance"]
        paper.maybe_order(small,self.obs,.54,"limit",self.now)
        paper.maybe_order(large,self.obs,.90,"limit",self.now)
        self.assertGreater(small["orders"][0]["cost"],0)
        self.assertLess(small["orders"][0]["cost"],large["orders"][0]["cost"])
        self.assertLessEqual(large["orders"][0]["cost"],paper.MAX_ORDER_EQUITY_FRACTION*paper.START)

    def test_order_cap_scales_with_account_equity(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        acct["cash"]=40
        paper.maybe_order(acct,self.obs,.9,"limit",self.now)
        self.assertLessEqual(acct["orders"][0]["cost"],4)

    def test_committed_exposure_caps_open_positions_and_orders(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        acct["cash"]=84
        acct["trades"].append({"slug":"prior","status":"open","cost":16})
        self.assertEqual(paper.equity(acct),100)
        self.assertEqual(paper.committed_exposure(acct),16)
        paper.maybe_order(acct,self.obs,.9,"limit",self.now)
        self.assertLessEqual(acct["orders"][0]["reserved"],10)
        self.assertLessEqual(paper.committed_exposure(acct),30)

    def test_total_exposure_never_exceeds_equity_cap(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        for bucket in range(4):
            paper.maybe_order(acct,self.obs,.9,"limit",self.now+bucket*60)
        self.assertLessEqual(paper.committed_exposure(acct),paper.MAX_EXPOSURE_EQUITY_FRACTION*paper.equity(acct))
        self.assertIsNone(paper.maybe_order(acct,self.obs,.9,"limit",self.now+4*60))

    def test_existing_passive_sell_requires_later_cross(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        trade={"slug":self.slug,"side":"Up","status":"open","placed_at":self.now-60,"shares":10,"cost":5}
        acct["trades"].append(trade)
        order={"slug":self.slug,"side":"Up","type":"limit_sell","status":"open",
               "placed_at":self.now,"price":.7,"shares":10,"reserved":0,"trade_placed_at":trade["placed_at"]}
        acct["orders"].append(order)
        paper.evaluate_limits(acct,self.obs,self.now)
        self.assertEqual(order["status"],"open")
        obs=copy.deepcopy(self.obs)
        obs["quotes"]["Up"].update(bid=.7,bid_size=100)
        paper.evaluate_limits(acct,obs,self.now+15)
        self.assertEqual(trade["close_reason"],"limit_sell")

    def test_urgent_exit_charges_taker_fee(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        trade={"slug":self.slug,"side":"Up","type":"limit_cross","status":"open",
               "placed_at":self.now-60,"shares":10,"cost":5}
        acct["trades"].append(trade)
        obs=copy.deepcopy(self.obs)
        obs["quotes"]["Up"]["bid_size"]=100
        self.assertEqual(paper.maybe_exit(acct,obs,.1,self.now),"IOC SELL Up")
        price=obs["quotes"]["Up"]["bid"]
        self.assertAlmostEqual(trade["payout"],10*price-paper.TAKER_COEFFICIENT*10*price*(1-price))
        self.assertEqual(trade["close_reason"],"ioc_sell")

    def test_urgent_exit_leaves_position_if_depth_insufficient(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        trade={"slug":self.slug,"side":"Up","status":"open","placed_at":self.now-60,"shares":10,"cost":5}
        acct["trades"].append(trade)
        obs=copy.deepcopy(self.obs)
        obs["quotes"]["Up"]["bid_size"]=0
        paper.maybe_exit(acct,obs,.1,self.now)
        self.assertEqual(trade["status"],"open")

    def test_maker_fee_is_zero(self):
        acct=paper.initial()["accounts"]["brti_distance"]
        paper.maybe_order(acct,self.obs,.9,"limit",self.now)
        order=acct["orders"][0]
        self.assertAlmostEqual(order["cost"],order["shares"]*order["price"],places=7)

    def test_resolution_only_official_us_api_and_cash(self):
        state=paper.initial()
        acct=state["accounts"]["conv_gru"]
        paper.maybe_order(acct,self.obs,.9,"market",self.now)
        state["markets"][self.slug]={"ends":self.obs["ends"],"outcome":None,"checked_at":0}
        with patch.object(paper,"settlement",return_value=None):
            paper.reconcile(state,self.obs["ends"]+61)
        self.assertEqual(acct["trades"][0]["status"],"open")
        with patch.object(paper,"settlement",return_value="Up"):
            paper.reconcile(state,self.obs["ends"]+123)
        self.assertEqual(acct["trades"][0]["status"],"settled")
        self.assertGreater(acct["cash"],100)
        self.assertEqual(state["markets"][self.slug]["outcome"],"Up")

    def test_reject_other_venue_state(self):
        state=paper.initial();state["venue"]="polymarket_international"
        paper.STATE.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            paper.load()

    def test_public_observation_archives_are_recoverable(self):
        paper.append_observation(self.obs)
        import gzip
        only=list(paper.OBS_DIR.glob("*.gz"))
        self.assertEqual(len(only),1)
        with gzip.open(only[0],"rt") as handle:
            row=json.loads(handle.readline())
        self.assertEqual(row["slug"],self.slug)
        self.assertEqual(row["venue"],"polymarket_us")

    def test_checkpoint_dimensions(self):
        self.assertEqual(len(predictors.SCALES["x_mean"]),24)
        self.assertEqual(len(predictors.SCALES["c_mean"]),64)
        self.assertEqual(len(predictors.MODELS),5)

    def test_calibration_learns_per_account_only_on_settlement(self):
        state = paper.initial()
        market = {"forecasts": [
            {"at": self.now, "market": .5, "probabilities": {"btc_momentum": .6}},
            {"at": self.now + 15, "market": .5, "probabilities": {"btc_momentum": .8}},
        ]}
        paper.score_market_forecasts(state, market, "Up")
        learner = state["accounts"]["btc_momentum"]["learning"]
        self.assertEqual(learner["markets"], 1)
        self.assertAlmostEqual(learner["logit_offset"], .015)
        self.assertNotIn("learning", state["accounts"]["btc_reversion"])
        self.assertEqual(paper.calibrate(.6, state["accounts"]["btc_momentum"]), .6)
        learner["markets"] = paper.CALIBRATION_WARMUP
        self.assertGreater(paper.calibrate(.6, state["accounts"]["btc_momentum"]), .6)

if __name__=="__main__":
    unittest.main()

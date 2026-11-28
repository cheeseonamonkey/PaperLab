import unittest
import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import train_research
from datetime import datetime, timedelta, timezone

from train_research import candle_returns, chronological_split, market_window


def ts(value):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


class ResearchChecks(unittest.TestCase):
    def test_corrupt_archive_hour_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Path(root)/"data"/"backfill"/"hours"/"2026-11-14"
            archive.mkdir(parents=True)
            (archive/"10.json.gz").write_bytes(b"not a valid gzip")
            with patch.object(train_research,"ROOT",Path(root)):
                self.assertEqual(train_research.examples(),[])

    def test_bootstrap_joins_normal_observations_with_official_labels(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            observations=root/"data"/"observations"
            labels=root/"data"/"bootstrap"/"labels"
            observations.mkdir(parents=True)
            labels.mkdir(parents=True)
            name="cpc-btc-updown-15m-2026-11-14-1000z"
            (labels/"one.json").write_text(json.dumps({name:"Up"}))
            row={"source":"bootstrap","slug":name,"observed_at":ts("2026-11-14 10:05"),
                 "display_up":.6,"features":{"btc_r1":.001}}
            with gzip.open(observations/"bootstrap-one.jsonl.gz","wt") as stream:
                stream.write(json.dumps(row)+"\n")
            with patch.object(train_research,"ROOT",root):
                result=train_research.examples()
            self.assertEqual(len(result),1)
            self.assertEqual(result[0][3:],(1,"bootstrap"))

    def test_historical_price_proxy_is_trained_only_after_official_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slug = "cpc-btc-updown-15m-2026-11-14-1000z"
            at = ts("2026-11-14 10:05")
            path = root / "data" / "observations" / "hour.jsonl.gz"
            path.parent.mkdir(parents=True)
            with gzip.open(path, "wt") as stream:
                stream.write(json.dumps({
                    "source":"historical_price_proxy","slug":slug,"observed_at":at,
                    "display_up":.65,"features":{"btc_r1":.001},
                    "feature_available_at":{"btc_r1":at}}) + "\n")
            state = root / "data" / "state.json"
            state.write_text(json.dumps({"markets":{slug:{"outcome":None}}}))
            with patch.object(train_research,"ROOT",root):
                self.assertEqual(train_research.examples(), [])
                state.write_text(json.dumps({"markets":{slug:{"outcome":"Up"}}}))
                result = train_research.examples()
            self.assertEqual(len(result),1)
            self.assertEqual(result[0][4],"historical_price_proxy")
            self.assertEqual(result[0][3],1)

    def test_grouped_scores_and_market_only_ablation(self):
        import math
        m15 = "cpc-btc-updown-15m-2026-11-14-1000z"
        m1 = "cpc-btc-updown-1h-2026-11-14-1000z"
        f = train_research.features(.6, "15m", {"BTC": .001})
        rows = [(ts("2026-11-14 10:05"),m15,f,1,"bootstrap"),
                (ts("2026-11-14 10:05"),m1,f,0,"live")]
        model = train_research.fit(rows, epochs=0, kind="market_only")
        groups = train_research.grouped_scores(rows, model)
        self.assertEqual(set(groups), {"15m:bootstrap", "1h:live"})
        self.assertEqual(train_research.transform(f, "market_only")[2:], [0.0]*(len(f)-2))
        self.assertAlmostEqual(groups["15m:bootstrap"]["brier"], .16)
        self.assertAlmostEqual(groups["15m:bootstrap"]["log_loss"], -math.log(.6))
        self.assertAlmostEqual(groups["1h:live"]["market_brier"], .36)
        self.assertEqual(groups["1h:live"]["markets"], 1)

    def test_candles_are_not_used_until_closed(self):
        candles = {"BTC": [[ts("2026-11-14 10:00"), 0, 0, 0, 100, 1],
                           [ts("2026-11-14 10:01"), 0, 0, 0, 101, 1]]}
        self.assertNotIn("BTC", candle_returns(candles, ts("2026-11-14 10:02")))
        self.assertIn("BTC", candle_returns(candles, ts("2026-11-14 10:03")))

    def test_split_keeps_overlapping_markets_out(self):
        m15 = "cpc-btc-updown-15m-2026-11-14-1145z"
        m1 = "cpc-btc-updown-1h-2026-11-14-1200z"
        rows = [(ts("2026-11-14 11:50"),m15,[],1,"history"),
                (ts("2026-11-14 12:10"),m1,[],0,"history")]
        train, valid, cutoff, _ = chronological_split(rows)
        self.assertEqual(cutoff, ts("2026-11-14 12:00"))
        self.assertEqual([x[1] for x in train], [m15])
        self.assertEqual([x[1] for x in valid], [m1])
        self.assertLessEqual(market_window(train[0][1])[1], cutoff)
        self.assertGreaterEqual(market_window(valid[0][1])[0], cutoff)

    def test_examples_drop_post_market_rows_and_unavailable_sp500(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations = root / "data" / "observations"
            observations.mkdir(parents=True)
            slug = "cpc-btc-updown-15m-2026-11-14-1000z"
            start = ts("2026-11-14 10:00")
            rows = [
                {"source":"live","slug":slug,"observed_at":start+60,
                 "quotes":{"Up":{"bid":.49,"ask":.51}},
                 "features":{"sp500_r1":.02},
                 "feature_available_at":{"sp500_r1":start+120}},
                {"source":"live","slug":slug,"observed_at":start+901,
                 "quotes":{"Up":{"bid":.49,"ask":.51}},"features":{"btc_r1":.001}},
            ]
            with gzip.open(observations / "observed.jsonl.gz", "wt") as stream:
                stream.write("".join(json.dumps(row)+"\n" for row in rows))
            state = root / "data" / "state.json"
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(json.dumps({"markets":{slug:{"outcome":"Up"}}}))
            with patch.object(train_research, "ROOT", root):
                examples = train_research.examples()
            self.assertEqual(len(examples), 1)
            self.assertEqual(examples[0][2][-2:], [0.0, 1.0])

    def test_candidate_expansions_append_causal_terms(self):
        f = train_research.features(.6, "1h", {"BTC": .001, "ETH": -.002})
        self.assertEqual(len(train_research.transform(f, "linear")), len(f))
        self.assertEqual(len(train_research.transform(f, "interactions")), len(f)+8)
        self.assertEqual(len(train_research.transform(f, "horizon_split")), len(f)+8)
        self.assertEqual(len(train_research.transform(f, "squares")), len(f)+4)
        self.assertEqual(len(train_research.transform(f, "market_only")), len(f))
        model = train_research.fit([(ts("2026-11-14 10:05"), "m", f, 1, "live")],
                                   epochs=0, kind="interactions")
        self.assertEqual(len(model["mean"]), len(f)+8)

    def test_fork_requires_streak_margin_and_respects_caps(self):
        def exp(name, brier, market=.110, markets=10):
            return {"name": name, "validation": {"brier": brier, "market_brier": market,
                                                 "markets": markets}}
        experiments = [exp("linear", .100), exp("interactions", .090)]
        state, winner = train_research.evaluate_fork(experiments, {}, 0)
        self.assertIsNone(winner)
        self.assertEqual(state["streak"], 1)
        state, winner = train_research.evaluate_fork(experiments, state, 0)
        self.assertIsNone(winner)
        state, winner = train_research.evaluate_fork(experiments, state, 0)
        self.assertEqual(winner["name"], "interactions")
        self.assertEqual(state["forked"], ["interactions"])
        # Already forked, at cap, thin sample, and sub-margin wins never fork.
        state, winner = train_research.evaluate_fork(
            experiments, {"candidate": "interactions", "streak": 9, "forked": ["interactions"]}, 0)
        self.assertIsNone(winner)
        state, winner = train_research.evaluate_fork(
            [exp("linear", .100), exp("squares", .090)],
            {"candidate": "squares", "streak": 9, "forked": []}, train_research.FORK_MAX_FORKS)
        self.assertIsNone(winner)
        state, winner = train_research.evaluate_fork(
            [exp("linear", .100), exp("squares", .090, markets=2)],
            {"candidate": "squares", "streak": 9, "forked": []}, 0)
        self.assertIsNone(winner)
        self.assertEqual(state["streak"], 0)
        state, winner = train_research.evaluate_fork(
            [exp("linear", .100), exp("squares", .109)],
            {"candidate": "squares", "streak": 9, "forked": []}, 0)
        self.assertIsNone(winner)

    def test_forward_predict_requires_prior_settlement_and_causal_features(self):
        slug = "cpc-btc-updown-15m-2026-11-14-1000z"
        start = ts("2026-11-14 10:00")
        raw = train_research.features(.5, "15m", {})
        model = train_research.fit([(start+60, slug, raw, 1, "live")], epochs=0)
        model["trained_through"] = start
        obs = {"venue":"polymarket_us","slug":slug,"start":start,"ends":start+900,
               "observed_at":start+300,"quotes":{"Up":{"bid":.49,"ask":.51}},
               "features":{"sp500_r1":.02},
               "feature_available_at":{"sp500_r1":start+301}}
        probability = train_research.predict(obs, model)
        self.assertIsNotNone(probability)
        self.assertGreater(probability, 0)
        self.assertLess(probability, 1)
        model["trained_through"] = start+1
        self.assertIsNone(train_research.predict(obs, model))


class PhaseTwoTests(unittest.TestCase):
    def test_feature_vector_v2_layout(self):
        f = train_research.features(.6, "15m", {"BTC": .001, "BTC_R5": .002,
                                                "TIME_LEFT": .5, "STRIKE_DISTANCE": .0004})
        self.assertEqual(len(f), 20)
        self.assertEqual(len(f), len(train_research.FEATURE_NAMES))
        self.assertAlmostEqual(f[10], .002)          # btc_r5 slot
        self.assertAlmostEqual(f[16], .5)            # time_left slot
        self.assertAlmostEqual(f[17], .0004)         # strike_distance slot
        self.assertEqual(f[-2:], [0.0, 1.0])         # SP500 pair stays last

    def test_candidate_sweep_grid(self):
        names = [c[0] for c in train_research.CANDIDATES]
        self.assertEqual(names[0], "linear")
        self.assertEqual(names[1], "market_only")
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 20)
        self.assertTrue(all(len(c) == 4 for c in train_research.CANDIDATES))

    def test_archive_hour_becomes_labeled_examples(self):
        start = 1763164800  # 2025-11-15T08:00:00Z
        slug = "btc-up-or-down-15m-1763164800"
        candles = [[start - 1200 + 60 * i, 100, 100, 100, 100 + (i % 3), 2.0] for i in range(40)]
        hour = {"hour_start": start,
                "markets": [{"slug": slug, "start": start,
                             "display": [[start + 30, .6, .4], [start + 90, .61, .39],
                                         [start + 150, .59, .41], [start + 210, .62, .38],
                                         [start + 270, .6, .4], [start + 330, .6, .4]],
                             "settlement": {"settlement": 1}}],
                "exogenous_coinbase_1m": {"BTC": candles, "ETH": candles,
                                          "SOL": candles, "XRP": candles}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "data" / "backfill" / "hours" / "2025-11-15"
            target.mkdir(parents=True)
            with gzip.open(target / "08.json.gz", "wt", encoding="utf-8") as stream:
                json.dump(hour, stream)
            (root / "data" / "state.json").write_text(json.dumps({"markets": {}}))
            with patch.object(train_research, "ROOT", root):
                rows = train_research.examples()
        archive = [r for r in rows if r[4] == "archive"]
        self.assertTrue(archive)
        self.assertTrue(all(r[1] == slug and r[3] == 1 for r in archive))
        self.assertEqual(len(archive[0][2]), 20)

    def test_retire_losing_forks(self):
        created = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        trades = [{"status": "settled", "pnl": -1.0} for _ in range(25)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "strategies").mkdir(parents=True)
            (root / "strategies" / "roster.json").write_text(json.dumps({"forks": [
                {"name": "fork_x_01", "candidate": "x", "status": "active", "created_at": created},
                {"name": "fork_y_02", "candidate": "y", "status": "active", "created_at": created}]}))
            (root / "data").mkdir()
            (root / "data" / "state.json").write_text(json.dumps({"accounts": {
                "fork_x_01": {"trades": trades},
                "fork_y_02": {"trades": [{"status": "settled", "pnl": 1.0}] * 25}}}))
            with patch.object(train_research, "ROOT", root):
                retired = train_research.retire_losing_forks()
                roster = json.loads((root / "strategies" / "roster.json").read_text())
        self.assertEqual(retired, ["fork_x_01"])
        by_name = {e["name"]: e for e in roster["forks"]}
        self.assertEqual(by_name["fork_x_01"]["status"], "retired")
        self.assertEqual(by_name["fork_y_02"].get("status", "active"), "active")


if __name__ == "__main__":
    unittest.main()

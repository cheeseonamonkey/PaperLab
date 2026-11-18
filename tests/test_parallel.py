import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper
import parallel
import test_paper


class ParallelTests(unittest.TestCase):
    def test_shard_rejects_missing_or_non_integer_index(self):
        for index in (None, "0", True, -1, len(parallel.SHARDS)):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "Invalid shard"):
                parallel.shard(index)

    def test_collect_fetches_one_closed_hour_and_skips_processed_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "hour.json.gz"
            with gzip.open(archive, "wt") as stream:
                json.dump({"markets":[],"exogenous_coinbase_1m":{}}, stream)
            state = paper.initial()
            obs = {"venue":"polymarket_us","source":"historical_price_proxy",
                   "slug":"historical","start":3600,"ends":4500,
                   "observed_at":3660,"display_up":.55,"quotes":{},"features":{},
                   "display_history":[],"brti_history":[]}
            with patch.object(parallel,"BATCH",root/"batch"), \
                 patch.object(parallel.paper,"load",return_value=state), \
                 patch.object(parallel.paper,"append_observation") as append, \
                 patch.object(parallel.backfill,"latest_closed_hour",return_value=(3600,7200)), \
                 patch.object(parallel.backfill,"collect_hour",
                              return_value=(archive,0,5)) as fetch, \
                 patch.object(parallel.backfill,"observations",return_value=[obs]), \
                 patch.object(parallel,"get",return_value={"series":[{"candles":[]}]}):
                parallel.collect()
            fetch.assert_called_once_with(3600,7200,require_settlement=False)
            append.assert_called_once_with(obs)
            manifest = parallel.read(root/"batch"/"collection.json")
            self.assertEqual(manifest["hour_end"],7200)
            self.assertEqual(manifest["batch"]["observations"],1)
            with gzip.open(root/"batch"/"events.jsonl.gz","rt") as stream:
                events = [json.loads(line) for line in stream]
            self.assertEqual([e["kind"] for e in events], ["observation","reconcile"])
            state["last_processed_hour_end"] = 7200
            with patch.object(parallel,"BATCH",root/"batch"), \
                 patch.object(parallel.paper,"load",return_value=state), \
                 patch.object(parallel.backfill,"latest_closed_hour",return_value=(3600,7200)), \
                 patch.object(parallel.backfill,"collect_hour",
                              side_effect=AssertionError("Duplicate fetch")):
                parallel.collect()
            with gzip.open(root/"batch"/"events.jsonl.gz","rt") as stream:
                self.assertEqual([json.loads(line)["kind"] for line in stream], ["reconcile"])

    def test_historical_replay_allows_repeated_signals_without_book_data(self):
        state = paper.initial()
        at = 1794636000
        obs = {"venue":"polymarket_us","source":"historical_price_proxy",
               "slug":"historical-market","start":at,"ends":at+900,
               "observed_at":at+120,"display_up":.5,"quotes":{},
               "features":{"btc_r5":.01},"feature_available_at":{}}
        second = {**obs,"observed_at":at+180,"display_up":.49}
        parallel.replay_events(state, [
            {"kind":"observation","observation":obs},
            {"kind":"observation","observation":second},
        ], ("btc_momentum","book_imbalance"), None)
        account = state["accounts"]["btc_momentum"]
        self.assertGreaterEqual(len(account["orders"]), 2)
        self.assertEqual(len(account["trades"]), 1)
        self.assertEqual(account["trades"][0]["type"], "historical_price_proxy")
        self.assertFalse(state["accounts"]["book_imbalance"]["orders"])

    def test_shards_match_single_engine_and_require_all_outputs(self):
        fixture = test_paper.PaperTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as directory:
            old = os.getcwd()
            os.chdir(directory)
            self.addCleanup(os.chdir, old)
            state = paper.initial()
            obs = fixture.obs
            state["markets"]["historical"] = {
                "ends": obs["ends"] + 1200, "outcome": None, "checked_at": 0,
                "forecasts": [{"at": obs["observed_at"] - 1, "market": .5,
                               "probabilities": {"lstm": .6}}],
            }
            parallel.write(parallel.BATCH / "base.json", state)
            active = {**obs, "slug": "active-market", "ends": obs["ends"] + 1200,
                      "observed_at": obs["ends"] + 31}
            events = [
                {"kind":"observation","observation":obs},
                {"kind":"reconcile","at":obs["ends"]+31,"outcomes":{obs["slug"]:"Up"}},
                {"kind":"observation","observation":active},
            ]
            with gzip.open(parallel.BATCH / "events.jsonl.gz","wt") as stream:
                for event in events:
                    stream.write(json.dumps(event)+"\n")
            manifest={"polling":state["polling"],"last_run":None,
                      "base_hash":parallel.digest(parallel.BATCH / "base.json"),
                      "events_hash":parallel.digest(parallel.BATCH / "events.jsonl.gz")}
            parallel.write(parallel.BATCH / "collection.json",manifest)
            paper.process_snapshot(state,obs,{})
            with patch.object(paper,"settlement",return_value="Up"):
                paper.reconcile(state,obs["ends"]+31)
            paper.process_snapshot(state,active,{})
            for index in range(len(parallel.SHARDS)-1):
                parallel.shard(index)
            with self.assertRaises(FileNotFoundError):
                parallel.merge()
            parallel.shard(len(parallel.SHARDS)-1)
            parallel.merge()
            self.assertEqual(json.loads(paper.STATE.read_text()),state)

            result_path = Path("shard-results/0.json")
            result = parallel.read(result_path)
            result["state"]["markets"][active["slug"]]["forecasts"][0]["probabilities"]["lstm"] = .5
            parallel.write(result_path, result)
            with self.assertRaisesRegex(ValueError, "foreign strategy"):
                parallel.merge()


if __name__ == "__main__":
    unittest.main()

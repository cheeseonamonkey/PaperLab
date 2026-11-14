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

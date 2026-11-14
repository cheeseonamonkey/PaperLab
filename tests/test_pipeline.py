import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap
import backfill
import paper
import reports
import train_research


class PipelineTests(unittest.TestCase):
    def test_observation_persists_input_availability_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            at = 1794632340
            obs = {"venue":"polymarket_us", "slug":"test", "start":at, "ends":at+900,
                   "observed_at":at, "quotes":{}, "features":{"sp500_r1":.01},
                   "feature_available_at":{"sp500_r1":at}, "book_top5":{},
                   "display_history":[], "brti_history":[]}
            with patch.object(paper, "OBS_DIR", Path(directory)):
                paper.append_observation(obs)
            path = next(Path(directory).glob("*.jsonl.gz"))
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                stored = json.loads(stream.readline())
            self.assertEqual(stored["feature_available_at"], {"sp500_r1":at})

    def test_bootstrap_persists_in_training_location_without_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            data=root/"data"
            state=data/"bootstrap"/"state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"next_end":1794654000,"hours_saved":0,"target_hours":1,"done":False}))
            def contract(start,horizon,period):
                name=backfill.slug(start,horizon)
                return {"slug":name,"horizon":horizon,"status":"collected",
                        "settlement":{"settlement":1},
                        "display_history":{"history":[{"timestamp":start+300,"longPrice":0.6}]}}
            with patch.object(bootstrap,"ROOT",data), patch.object(bootstrap,"STATE",state), \
                 patch.object(bootstrap,"market",side_effect=contract), \
                 patch.object(bootstrap,"exogenous",return_value={}):
                bootstrap.main()
            self.assertTrue(json.loads(state.read_text())["done"])
            self.assertEqual(len(list((data/"observations").glob("bootstrap-*.gz"))),1)
            self.assertFalse((data/"backfill").exists())
            with patch.object(train_research,"ROOT",root):
                self.assertEqual(len(train_research.examples()),5)

    def test_export_writes_bot_ledgers_and_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            state=paper.initial()
            state["accounts"]["book_imbalance"]["orders"].append({
                "slug":"market","status":"open","type":"limit","reserved":1,"placed_at":1})
            with patch.object(reports,"LEDGERS",root/"data"/"ledgers"), \
                 patch.object(reports,"PAGES",root/"docs"/"bots"):
                reports.export(state)
            path=root/"data"/"ledgers"/"book_imbalance-orders.csv"
            with path.open(newline="") as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(rows[0]["slug"],"market")
            self.assertTrue((root/"docs"/"bots"/"book_imbalance.md").exists())


if __name__ == "__main__":
    unittest.main()

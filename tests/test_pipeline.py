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
    def test_latest_closed_hour_boundaries(self):
        self.assertEqual(backfill.latest_closed_hour(7200), (3600, 7200))
        self.assertEqual(backfill.latest_closed_hour(7199), (0, 3600))

    def test_full_archive_reuses_existing_hours_and_stops_at_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "hours" / "1970-01-01" / "01.json.gz"
            existing.parent.mkdir(parents=True)
            with gzip.open(existing, "wt") as stream:
                json.dump({"start":3600,"end":7200,"markets":[
                    {"status":"collected"}],"exogenous_coinbase_1m":{}},stream)

            def download(start, end, require_settlement):
                self.assertFalse(require_settlement)
                target = backfill.hour_path(start)
                target.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(target,"wt") as stream:
                    json.dump({"start":start,"end":end,"markets":[
                        {"status":"collected"}],"exogenous_coinbase_1m":{}},stream)
                return target,0,1

            with patch.object(backfill,"ROOT",root), \
                 patch.object(backfill,"STATE",root/"state.json"), \
                 patch.object(backfill,"FIRST_HOUR",3600), \
                 patch.object(backfill,"HOURS_PER_RUN",2), \
                 patch.object(backfill,"latest_closed_hour",return_value=(7200,10800)), \
                 patch.object(backfill,"collect_hour",side_effect=download) as fetch, \
                 patch.object(backfill.time,"sleep"):
                backfill.main()
                state = json.loads((root/"state.json").read_text())
                self.assertTrue(state["done"])
                self.assertEqual(state["processed_hours"],2)
                self.assertEqual(state["downloaded_hours"],1)
                self.assertEqual(state["reused_hours"],1)
                self.assertEqual(state["next_end"],3600)
                fetch.assert_called_once_with(7200,10800,require_settlement=False)
                backfill.main()
                self.assertEqual(fetch.call_count,1)

    def test_archive_pauses_without_advancing_past_source_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(backfill,"ROOT",root), \
                 patch.object(backfill,"STATE",root/"state.json"), \
                 patch.object(backfill,"FIRST_HOUR",3600), \
                 patch.object(backfill,"HOURS_PER_RUN",2), \
                 patch.object(backfill,"latest_closed_hour",return_value=(7200,10800)), \
                 patch.object(backfill,"collect_hour",side_effect=OSError("temporary outage")):
                backfill.main()
            state=json.loads((root/"state.json").read_text())
            self.assertFalse(state["done"])
            self.assertEqual(state["next_end"],10800)
            self.assertEqual(state["processed_hours"],0)
            self.assertIn("temporary outage",state["last_error"]["reason"])

    def test_historical_observations_use_only_closed_input_candles(self):
        start = 1794636000
        slug = backfill.slug(start, "15m")
        hour = {"start":start,"end":start+3600,
                "markets":[{"slug":slug,"horizon":"15m","start":start,"ends":start+900,
                            "status":"collected",
                            "metadata":{"market":{"assetPriceTerms":{"priceToBeat":100}}},
                            "display_history":{"history":[
                                {"timestamp":start+120,"longPrice":.55},
                                {"timestamp":start+180,"longPrice":.56}]}}],
                "exogenous_coinbase_1m":{"BTC":[
                    [t,0,0,0,100+i,1] for i,t in enumerate(range(start-1200,start+180,60))]}}
        reference = [{"timestamp":t,"close":100+i}
                     for i,t in enumerate(range(start-1200,start+180,60))]
        rows = backfill.observations(hour, reference)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["observed_at"] for r in rows], [start+120,start+180])
        self.assertTrue(all(r["source"]=="historical_price_proxy" and not r["quotes"] for r in rows))
        self.assertTrue(all(all(t <= r["observed_at"]
                                for t in r["feature_available_at"].values()) for r in rows))

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

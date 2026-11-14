import unittest
import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import train_research
from datetime import datetime, timezone

from train_research import candle_returns, chronological_split, market_window


def ts(value):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


class ResearchChecks(unittest.TestCase):
    def test_archived_backfill_is_never_a_training_input(self):
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
        self.assertEqual(train_research.transform(f, "market_only")[2:], [0.0]*8)
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


if __name__ == "__main__":
    unittest.main()

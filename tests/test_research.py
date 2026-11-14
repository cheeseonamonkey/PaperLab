import unittest
from datetime import datetime, timezone

from train_research import candle_returns, chronological_split, market_window


def ts(value):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


class ResearchChecks(unittest.TestCase):
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

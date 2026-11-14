import unittest
from unittest.mock import patch

import feeds


class ExogenousFeedTests(unittest.TestCase):
    def test_sp500_uses_only_fred_closes_past_conservative_availability(self):
        payload = b"observation_date,SP500\n2026-11-11,7000\n2026-11-12,7070\n2026-11-13,7140\n"
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return payload

        observed = int(feeds.dt.datetime(2026, 11, 14, 4, 59, tzinfo=feeds.dt.timezone.utc).timestamp())
        with patch.object(feeds, "urlopen", return_value=Response()), patch.object(feeds.time, "time", return_value=observed):
            result = feeds._sp500_context(observed)
        self.assertIsNotNone(result)
        self.assertEqual(result["available_at"], observed)
        self.assertAlmostEqual(result["r1"], __import__("math").log(7070/7000))

    def test_sp500_is_missing_before_first_available_observation(self):
        payload = b"observation_date,SP500\n2026-11-13,7140\n"
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return payload

        observed = int(feeds.dt.datetime(2026, 11, 14, 4, 59, tzinfo=feeds.dt.timezone.utc).timestamp())
        with patch.object(feeds, "urlopen", return_value=Response()), patch.object(feeds.time, "time", return_value=observed):
            self.assertIsNone(feeds._sp500_context(observed))

    def test_coinbase_context_carries_close_availability(self):
        now = 1_800_000_000
        rows = [[now - 1200 + i * 60, 0, 0, 0, 100 + i, 1] for i in range(20)]
        result = feeds._momentum(rows, now)
        self.assertEqual(result["available_at"], now - 57)
        self.assertLessEqual(result["available_at"], now)


if __name__ == "__main__":
    unittest.main()

import pandas as pd

from market_us.train_sweep import normalize_reference


def test_subminute_reference_rows_aggregate_to_minute_bars():
    rows = []
    for minute in (1_700_000_040, 1_700_000_100):
        for offset, (open_, high, low, close, ticks) in enumerate(
            [(10.0, 12.0, 9.0, 11.0, 3),
             (11.0, 13.0, 10.0, 12.0, 4),
             (12.0, 12.5, 8.0, 9.0, 5),
             (9.0, 9.5, 7.0, 8.0, 6)]
        ):
            rows.append({"sample_at": minute + offset * 15, "open": open_,
                         "high": high, "low": low, "close": close,
                         "tick_count": ticks, "bucket_sec": 15})
    out = normalize_reference(pd.DataFrame(rows)).sort_values("sample_at")
    assert list(out.sample_at) == [1_700_000_040, 1_700_000_100]
    first = out.iloc[0]
    assert first.open == 10.0 and first.close == 8.0
    assert first.high == 13.0 and first.low == 7.0
    assert first.tick_count == 18
    assert set(out.bucket_sec) == {60}


def test_native_minute_rows_take_precedence_over_aggregates():
    frame = pd.DataFrame([
        {"sample_at": 1_700_000_040, "open": 1.0, "high": 2.0, "low": 1.0,
         "close": 2.0, "tick_count": 10, "bucket_sec": 60},
        {"sample_at": 1_700_000_040, "open": 5.0, "high": 6.0, "low": 5.0,
         "close": 6.0, "tick_count": 1, "bucket_sec": 15},
    ])
    out = normalize_reference(frame)
    assert len(out) == 1
    assert out.iloc[0].close == 2.0
    assert out.iloc[0].tick_count == 10


def test_legacy_sixty_second_frames_pass_through_deduplicated():
    frame = pd.DataFrame([
        {"sample_at": 60, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
         "tick_count": 1, "bucket_sec": 60},
        {"sample_at": 60, "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0,
         "tick_count": 9, "bucket_sec": 60},
    ])
    out = normalize_reference(frame)
    assert len(out) == 1
    assert out.iloc[0].close == 1.0

"""Timestamp and missing-data regression tests for US auxiliary features."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from market_us.exogenous import FRED, ETFS, build_features, feature_frame, make_daily, store_file


def test_equity_daily_not_known_at_market_open():
    bar = make_daily(pd.Series(["2026-11-05"]), pd.Series([600]), ETFS["SPY"])
    assert bar.loc[0, "known_at"] == pd.Timestamp("2026-11-06T00:00:00Z")


def test_macro_lags_and_vintage_exclusion(tmp_path):
    f = FRED["DGS2"]
    data = make_daily(pd.Series(["2026-10-10"]), pd.Series([3.8]), f)
    store_file(f.name, data, tmp_path)
    cpi = FRED["CPIAUCSL"]
    store_file(cpi.name, make_daily(pd.Series(["2026-08-01"]),
                                    pd.Series([320]), cpi), tmp_path)
    anchors = pd.Series(["2026-10-11T23:59:59Z", "2026-10-12T00:00:01Z"])
    panel = build_features(tmp_path, anchors)
    assert pd.isna(panel.loc[0, "yield_2y__value"])
    assert panel.loc[1, "yield_2y__value"] == 3.8
    assert "cpi__value" not in panel
    assert "yield_2y__missing" in panel
    unsafe = build_features(tmp_path, anchors, include_revised=True)
    assert "cpi__value" in unsafe


def test_minute_features_never_use_unfinished_bar(tmp_path):
    observed = pd.date_range("2026-11-01T00:00Z", periods=17, freq="min")
    bars = pd.DataFrame({"observed_at": observed, "known_at": observed + pd.Timedelta(seconds=63),
                         "value": np.arange(100, 117, dtype=float), "volume": np.ones(17)})
    store_file("btc_spot", bars, tmp_path)
    panel = build_features(tmp_path, pd.Series(["2026-11-01T00:01:02Z", "2026-11-01T00:01:04Z",
                                                "2026-11-01T00:16:10Z"]))
    assert pd.isna(panel.loc[0, "btc_spot__value"])
    assert panel.loc[1, "btc_spot__value"] == 100
    assert np.isclose(panel.loc[2, "btc_spot__ret_15m"], np.log(115 / 100))
    assert panel.loc[2, "btc_spot__age_seconds"] >= 0


def test_gap_and_expired_values(tmp_path):
    store_file("btc_spot", pd.DataFrame({
        "observed_at": pd.to_datetime(["2026-10-01T00:00Z"], utc=True),
        "known_at": pd.to_datetime(["2026-10-01T00:01:03Z"], utc=True),
        "value": [90.0], "volume": [3.0],
    }), tmp_path)
    result = build_features(tmp_path, pd.Series(["2026-10-01T00:05Z", "2026-10-01T00:20Z"]))
    assert result.loc[0, "btc_spot__value"] == 90
    assert result.loc[1, "btc_spot__missing"] == 1
    assert pd.isna(result.loc[1, "btc_spot__value"])


def test_ret_sign_and_no_forward_join():
    observed = pd.date_range("2026-11-01T00:00Z", periods=6, freq="D")
    df = pd.DataFrame({"known_at": observed, "value": [100, 102, 105, 104, 103, 107]})
    result = feature_frame("sp500_spy", df, "price")
    assert np.isclose(result.loc[1, "sp500_spy__change_1"], 0.02)
    assert pd.isna(result.loc[0, "sp500_spy__change_1"])

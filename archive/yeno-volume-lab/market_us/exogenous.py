"""Read-only, point-in-time-aware auxiliary market data for Polymarket US research.

This data is NEVER a substitute for executable US contract books or BRTI settlement.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/research/polymarket_us/exogenous"
LOG = logging.getLogger("yeno.us.exogenous")

# Lag is conservative availability, NOT the reference observation date.
# Revision-sensitive releases remain excluded from model features by default.
@dataclass(frozen=True)
class Feed:
    name: str
    source: str
    delay_days: int
    max_age_days: int
    revised: bool = False
    kind: str = "level"


FRED = {
    "DGS2": Feed("yield_2y", "FRED", 2, 7),
    "DGS10": Feed("yield_10y", "FRED", 2, 7),
    "DFF": Feed("fed_effective", "FRED", 2, 7),
    "DFEDTARU": Feed("fed_target_upper", "FRED", 2, 14),
    "DTWEXBGS": Feed("usd_trade_weighted", "FRED", 3, 12),
    "DCOILWTICO": Feed("wti_oil", "FRED", 2, 7),
    "CPIAUCSL": Feed("cpi", "FRED", 60, 110, True),
    "PAYEMS": Feed("payrolls", "FRED", 60, 110, True),
    "UNRATE": Feed("unemployment", "FRED", 60, 110, True),
    "GDPC1": Feed("real_gdp", "FRED", 120, 210, True),
    "ICSA": Feed("initial_claims", "FRED", 21, 50, True),
}

ETFS = {
    "SPY": Feed("sp500_spy", "Yahoo", 1, 5, kind="price"),
    "QQQ": Feed("nasdaq_qqq", "Yahoo", 1, 5, kind="price"),
    "GLD": Feed("gold_gld", "Yahoo", 1, 5, kind="price"),
    "USO": Feed("oil_uso", "Yahoo", 1, 5, kind="price"),
    "UUP": Feed("usd_uup", "Yahoo", 1, 5, kind="price"),
}
VIX = Feed("vix", "Cboe", 1, 5)
COINS = ("BTC", "ETH", "SOL", "XRP")
YAHOO_LIMIT_NOTE = "Unofficial research-only Yahoo chart endpoint; not a licensed production feed."


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "YeNoResearch/0.1 (read-only, noncommercial)"})
    retries = Retry(total=3, connect=3, read=2, backoff_factor=0.7,
                    status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def get(s: requests.Session, url: str, **params) -> requests.Response:
    r = s.get(url, params=params or None, timeout=20)
    r.raise_for_status()
    return r


def make_daily(dates: pd.Series, values: pd.Series, feed: Feed) -> pd.DataFrame:
    d = pd.to_datetime(dates, utc=True).dt.normalize()
    v = pd.to_numeric(values, errors="coerce")
    result = pd.DataFrame({"observed_at": d, "known_at": d + pd.Timedelta(days=feed.delay_days),
                           "value": v}).dropna().sort_values("observed_at")
    return result.drop_duplicates("observed_at", keep="last").reset_index(drop=True)


def fred(s: requests.Session, code: str, feed: Feed) -> pd.DataFrame:
    r = get(s, "https://fred.stlouisfed.org/graph/fredgraph.csv", id=code)
    df = pd.read_csv(io.BytesIO(r.content))
    if len(df.columns) != 2 or code not in df:
        raise ValueError(f"Unexpected FRED schema for {code}: {list(df.columns)}")
    return make_daily(df.iloc[:, 0], df[code], feed)


def yahoo(s: requests.Session, ticker: str, feed: Feed, years: int) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
    data = get(s, url, interval="1d", range=f"{years}y").json()
    item = (data.get("chart", {}).get("result") or [None])[0]
    if not item:
        raise ValueError(f"No Yahoo chart data for {ticker}")
    times = pd.to_datetime(item["timestamp"], unit="s", utc=True)
    # Yahoo's daily bar timestamp is NOT the time of its last included trade.
    # Make the entire daily bar available only at next midnight UTC.
    close = item["indicators"]["quote"][0]["close"]
    return make_daily(pd.Series(times), pd.Series(close), feed)


def cboe_vix(s: requests.Session) -> pd.DataFrame:
    r = get(s, "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
    df = pd.read_csv(io.BytesIO(r.content))
    if not {"DATE", "CLOSE"}.issubset(df.columns):
        raise ValueError(f"Unexpected Cboe columns: {list(df.columns)}")
    return make_daily(df["DATE"], df["CLOSE"], VIX)


def coinbase(s: requests.Session, asset: str, days: int, now=None) -> pd.DataFrame:
    end = pd.Timestamp(now or datetime.now(timezone.utc)).floor("min")
    start = end - pd.Timedelta(days=days)
    blocks = []
    cursor = end
    while cursor > start:
        begin = max(start, cursor - pd.Timedelta(minutes=299))
        url = f"https://api.exchange.coinbase.com/products/{asset}-USD/candles"
        data = get(s, url, granularity=60, start=begin.isoformat(),
                   end=cursor.isoformat()).json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Coinbase response for {asset}")
        blocks.extend(row for row in data if isinstance(row, list) and len(row) >= 6)
        cursor = begin
        time.sleep(0.12)
    if not blocks:
        return pd.DataFrame(columns=["observed_at", "known_at", "value", "volume"])
    raw = pd.DataFrame(blocks, columns=["timestamp", "low", "high", "open", "close", "volume"])
    raw["observed_at"] = pd.to_datetime(raw["timestamp"], unit="s", utc=True)
    # A minute's close/volume cannot enter a prediction during that minute.
    raw["known_at"] = raw["observed_at"] + pd.Timedelta(seconds=63)
    raw["value"] = pd.to_numeric(raw["close"], errors="coerce")
    raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce")
    return (raw[["observed_at", "known_at", "value", "volume"]]
            .dropna(subset=["value"])
            .drop_duplicates("observed_at", keep="last")
            .sort_values("observed_at").reset_index(drop=True))


def store_file(name: str, frame: pd.DataFrame, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{name}.parquet"
    if dest.exists():
        old = pd.read_parquet(dest)
        frame = pd.concat([old, frame], ignore_index=True)
    frame = (frame.drop_duplicates("observed_at", keep="last")
             .sort_values("observed_at").reset_index(drop=True))
    tmp = dest.with_suffix(".tmp.parquet")
    frame.to_parquet(tmp, index=False)
    tmp.replace(dest)
    return {"rows": int(len(frame)),
            "first": str(frame["observed_at"].min()) if len(frame) else None,
            "last": str(frame["observed_at"].max()) if len(frame) else None,
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}


def collect(directory: Path, crypto_days: int = 3, etf_years: int = 10,
            only: set[str] | None = None) -> dict:
    feeds = {}
    source_urls = {}
    s = session()

    def run(name: str, feed: Feed, url: str, fn):
        if only and name not in only:
            return
        try:
            info = store_file(name, fn(), directory)
            feeds[name] = {"status": "ok", "source": feed.source, "url": url,
                           "assumed_lag_days": feed.delay_days,
                           "revision_sensitive": feed.revised, **info}
            LOG.info("%s: %s rows", name, info["rows"])
        except Exception as exc:
            feeds[name] = {"status": "error", "source": feed.source,
                           "error": f"{type(exc).__name__}: {exc}"}
            LOG.warning("%s: %s", name, exc)

    for code, feed in FRED.items():
        run(feed.name, feed, f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}",
            lambda code=code, feed=feed: fred(s, code, feed))
    for ticker, feed in ETFS.items():
        run(feed.name, feed, "https://query1.finance.yahoo.com/v8/finance/chart/",
            lambda ticker=ticker, feed=feed: yahoo(s, ticker, feed, etf_years))
    run(VIX.name, VIX, "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        lambda: cboe_vix(s))
    if crypto_days > 0:
        for asset in COINS:
            name = f"{asset.lower()}_spot"
            feed = Feed(name, "Coinbase Exchange", 0, 1, kind="price")
            run(name, feed, f"https://api.exchange.coinbase.com/products/{asset}-USD/candles",
                lambda asset=asset: coinbase(s, asset, crypto_days))

    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(),
                "venue_target": "Polymarket US (NOT Polymarket International)",
                "purpose": "auxiliary features, not settlement or executable prices",
                "revision_policy": "exclude revision-sensitive FRED by default",
                "yahoo_caveat": YAHOO_LIMIT_NOTE,
                "feeds": feeds}
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def feature_frame(name: str, df: pd.DataFrame, kind: str) -> pd.DataFrame:
    df = df.sort_values("known_at").drop_duplicates("known_at").copy()
    v = df["value"].astype(float)
    result = pd.DataFrame({"known_at": df["known_at"], f"{name}__value": v})
    if name in {f"{coin.lower()}_spot" for coin in COINS}:
        for n in (1, 5, 15, 60, 240, 1440):
            result[f"{name}__ret_{n}m"] = np.log(v / v.shift(n)).replace([np.inf, -np.inf], np.nan)
        minute_ret = np.log(v / v.shift(1)).replace([np.inf, -np.inf], np.nan)
        for n in (15, 60, 240):
            result[f"{name}__vol_{n}m"] = minute_ret.rolling(n, min_periods=n).std()
        if "volume" in df:
            result[f"{name}__volume_15m"] = df["volume"].rolling(15, min_periods=15).sum()
            result[f"{name}__volume_1h"] = df["volume"].rolling(60, min_periods=60).sum()
    else:
        for n in (1, 5, 20):
            if kind == "price":
                result[f"{name}__change_{n}"] = v.pct_change(n, fill_method=None)
            else:
                result[f"{name}__change_{n}"] = v.diff(n)
    return result


def build_features(directory: Path, decision_times: pd.Series, *, include_revised=False) -> pd.DataFrame:
    # pandas 3 preserves input datetime resolution: merge_asof requires
    # identical resolution on both timestamp keys (s/us/ns).
    timestamps = pd.to_datetime(decision_times, utc=True, errors="raise").astype("datetime64[ns, UTC]")
    anchors = pd.DataFrame({"decision_at": timestamps}).sort_values("decision_at").reset_index(drop=True)
    if anchors["decision_at"].isna().any():
        raise ValueError("Null decision timestamp")
    if not len(anchors):
        raise ValueError("No decision timestamps")

    feed_info = {x.name: x for x in (*FRED.values(), *ETFS.values(), VIX)}
    feed_info.update({f"{asset.lower()}_spot": Feed(f"{asset.lower()}_spot", "Coinbase Exchange", 0, 1, kind="price") for asset in COINS})
    for name, feed in feed_info.items():
        path = directory / f"{name}.parquet"
        if not path.exists() or (feed.revised and not include_revised):
            continue
        frame = pd.read_parquet(path)
        if frame.empty:
            continue
        frame["known_at"] = pd.to_datetime(frame["known_at"], utc=True).astype("datetime64[ns, UTC]")
        frame = frame[frame["known_at"] <= anchors["decision_at"].max()]
        if frame.empty:
            continue
        right = feature_frame(name, frame, feed.kind)
        anchors = pd.merge_asof(
            anchors, right, left_on="decision_at", right_on="known_at",
            direction="backward",
            tolerance=pd.Timedelta(minutes=10) if name.endswith("_spot")
                      else pd.Timedelta(days=feed.max_age_days),
        )
        anchors[f"{name}__age_seconds"] = (anchors["decision_at"] - anchors["known_at"]).dt.total_seconds()
        anchors[f"{name}__missing"] = anchors[f"{name}__value"].isna().astype("int8")
        anchors = anchors.drop(columns=["known_at"])
    if {"yield_2y__value", "yield_10y__value"} <= set(anchors):
        anchors["yield_curve_10y_minus_2y"] = anchors["yield_10y__value"] - anchors["yield_2y__value"]
    if {"btc_spot__ret_15m", "eth_spot__ret_15m"} <= set(anchors):
        for asset in ("eth", "sol", "xrp"):
            col = f"{asset}_spot__ret_15m"
            if col in anchors:
                anchors[f"{asset}_vs_btc__ret_15m"] = anchors[col] - anchors["btc_spot__ret_15m"]
    return anchors


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect/read-only cross-asset, macro and crypto features for Polymarket US.")
    parser.add_argument("action", choices=("collect", "build", "status"))
    parser.add_argument("--directory", type=Path, default=STORE)
    parser.add_argument("--crypto-days", type=int, default=3)
    parser.add_argument("--etf-years", type=int, default=10)
    parser.add_argument("--only", nargs="*", help="Feed names to fetch; others untouched")
    parser.add_argument("--anchors", type=Path, help="CSV/Parquet with a decision_at UTC column")
    parser.add_argument("--output", type=Path, help="Output parquet for build")
    parser.add_argument("--include-revised", action="store_true",
                        help="Research only: historical FRED revisions can leak future values")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.action == "status":
        print((args.directory / "manifest.json").read_text() if (args.directory / "manifest.json").exists() else "Not collected yet")
    elif args.action == "collect":
        if not 0 <= args.crypto_days <= 365 or not 1 <= args.etf_years <= 30:
            parser.error("Unsupported data range")
        print(json.dumps(collect(args.directory, args.crypto_days, args.etf_years,
                                 only=set(args.only) if args.only else None), indent=2))
    else:
        if not args.anchors or not args.output:
            parser.error("build requires --anchors and --output")
        anchors = (pd.read_parquet(args.anchors) if args.anchors.suffix == ".parquet"
                   else pd.read_csv(args.anchors))
        if "decision_at" not in anchors.columns:
            parser.error("anchors require decision_at")
        result = build_features(args.directory, anchors["decision_at"],
                                include_revised=args.include_revised)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(args.output, index=False)
        print(json.dumps({"rows": len(result), "features": len(result.columns) - 1,
                          "output": str(args.output), "first": str(result.decision_at.min()),
                          "last": str(result.decision_at.max())}, indent=2))


if __name__ == "__main__":
    main()

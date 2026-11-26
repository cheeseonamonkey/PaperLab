"""Resumable, integrity-checked Binance Vision 1m spot archive for YeNo context.

Independent of Polymarket US prices/books/settlement. Retains verified source ZIPs
and point-in-time-safe OHLCV Parquet; never fabricates missing candles.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/research/polymarket_us/spot_archive"
BASE = "https://data.binance.vision/data/spot"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FIELDS = ("ts", "open", "high", "low", "close", "volume", "close_ts",
          "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore")
LOG = logging.getLogger("yeno.spot.archive")


def first_of_next_month(day: dt.date) -> dt.date:
    return (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def sources(start: dt.date, end: dt.date):
    month = start.replace(day=1)
    while month <= end:
        next_month = first_of_next_month(month)
        if next_month <= dt.datetime.now(dt.timezone.utc).date().replace(day=1):
            yield "monthly", month.strftime("%Y-%m"), month, next_month
        else:
            for offset in range((min(end + dt.timedelta(days=1), next_month) - max(month, start)).days):
                day = max(month, start) + dt.timedelta(days=offset)
                yield "daily", day.isoformat(), day, day + dt.timedelta(days=1)
        month = next_month


def request_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "YeNoUSResearch/0.1 (public archive only)"
    retry = Retry(total=4, connect=4, read=4, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504),
                  respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_file(s: requests.Session, url: str, dest: Path) -> str:
    expected = s.get(url + ".CHECKSUM", timeout=30)
    expected.raise_for_status()
    checksum = expected.text.split()[0].lower()
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ValueError(f"Invalid source checksum: {url}")
    if dest.exists() and sha256_file(dest) == checksum:
        return checksum
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".download-", suffix=".zip", delete=False) as f:
        tmp = Path(f.name)
    try:
        with s.get(url, timeout=(15, 120), stream=True) as response:
            response.raise_for_status()
            with tmp.open("wb") as out:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        out.write(chunk)
        if sha256_file(tmp) != checksum:
            raise ValueError(f"Checksum mismatch: {url}")
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                raise ValueError(f"Invalid ZIP archive: {url}")
        tmp.replace(dest)
        return checksum
    finally:
        tmp.unlink(missing_ok=True)


def convert(raw: Path, start: dt.date, end: dt.date) -> pd.DataFrame:
    with zipfile.ZipFile(raw) as z:
        members = [i for i in z.infolist() if i.filename.endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in {raw}: {len(members)}")
        with z.open(members[0]) as f:
            df = pd.read_csv(f, header=None, names=FIELDS, usecols=list(range(12)))
    if df.empty:
        raise ValueError(f"Empty archive: {raw}")
    ts = pd.to_numeric(df.pop("ts"), errors="raise").astype("int64")
    unit = "us" if ts.iloc[0] >= 10**15 else "ms"
    observed = pd.to_datetime(ts, unit=unit, utc=True)
    if not observed.dt.second.eq(0).all() or not observed.dt.microsecond.eq(0).all():
        raise ValueError(f"Unexpected non-minute timestamps in {raw}")
    df = df.drop(columns=["close_ts", "ignore"])
    for col in df:
        df[col] = pd.to_numeric(df[col], errors="raise")
    df.insert(0, "observed_at", observed)
    df.insert(1, "known_at", observed + pd.Timedelta(seconds=63))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    df = df[(df.observed_at >= start_ts) & (df.observed_at < end_ts)]
    if df.empty or df.observed_at.duplicated().any() or not df.observed_at.is_monotonic_increasing:
        raise ValueError(f"Missing, duplicate, or unordered archive rows: {raw}")
    if (df[["open", "high", "low", "close"]] <= 0).any().any() or (df["volume"] < 0).any():
        raise ValueError(f"Invalid OHLCV values: {raw}")
    return df.reset_index(drop=True)


def collect(s: requests.Session, symbol: str, kind: str, key: str, begin: dt.date,
            finish: dt.date, start: dt.date, end: dt.date, store: Path) -> dict:
    stem = f"{symbol}-1m-{key}"
    url = f"{BASE}/{kind}/klines/{symbol}/1m/{stem}.zip"
    archive = store / "raw" / symbol / f"{stem}.zip"
    output = store / "parquet" / symbol / f"{stem}.parquet"
    metadata = output.with_suffix(".json")
    if output.exists() and metadata.exists():
        previous = json.loads(metadata.read_text())
        if previous.get("requested_start") == start.isoformat() and previous.get("requested_end") == end.isoformat():
            return {"state": "skipped", "rows": previous["rows"], "file": str(output)}
        # Previously valid complete archives are safe to reuse for a narrower date window.
        if (previous.get("first") and previous.get("last")
                and previous.get("period_start") == begin.isoformat()
                and previous.get("period_end") == finish.isoformat()):
            return {"state": "skipped", "rows": previous["rows"], "file": str(output)}
    checksum = archive_file(s, url, archive)
    frame = convert(archive, max(begin, start), min(finish, end + dt.timedelta(days=1)))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".part-", suffix=".parquet", delete=False) as f:
        tmp = Path(f.name)
    try:
        frame.to_parquet(tmp, index=False, compression="zstd")
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    metadata.write_text(json.dumps({
        "source": url, "source_sha256": checksum, "rows": len(frame),
        "period_start": begin.isoformat(), "period_end": finish.isoformat(),
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "first": str(frame.observed_at.iloc[0]), "last": str(frame.observed_at.iloc[-1]),
        "expected_minutes": int((min(finish, end + dt.timedelta(days=1)) - max(begin, start)).total_seconds() / 60),
        "note": "Binance spot data only; NOT Polymarket US settlement/book prices.",
    }, indent=2) + "\n")
    return {"state": "collected", "rows": len(frame), "file": str(output)}


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=dt.date.fromisoformat, default=today - dt.timedelta(days=730))
    ap.add_argument("--end", type=dt.date.fromisoformat, default=today - dt.timedelta(days=1))
    ap.add_argument("--symbols", nargs="+", choices=SYMBOLS, default=list(SYMBOLS))
    ap.add_argument("--store", type=Path, default=STORE)
    ap.add_argument("--limit", type=int, default=0, help="Optional smoke-test limit on archive files")
    args = ap.parse_args()
    if args.end < args.start or args.end >= today:
        ap.error("Dates must be ordered, with end before today UTC")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    failures, ok = [], 0
    with request_session() as s:
        for symbol in args.symbols:
            for kind, key, begin, finish in sources(args.start, args.end):
                if args.limit and ok >= args.limit:
                    break
                try:
                    result = collect(s, symbol, kind, key, begin, finish,
                                     args.start, args.end, args.store)
                    ok += 1
                    LOG.info("%s %s %s %s rows=%s", symbol, key, kind,
                             result["state"], result["rows"])
                except Exception as e:
                    failures.append(f"{symbol} {key}: {type(e).__name__}: {e}")
                    LOG.error(failures[-1])
            if args.limit and ok >= args.limit:
                break
    LOG.info("finished archives=%d errors=%d", ok, len(failures))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

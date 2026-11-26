"""Sparse, read-only Polymarket US BTC market collector.

30s live snapshots; decisions may be evaluated every 60s.
Past market display prices != executable historic order-book depth.
All market URLs target gateway.polymarket.us (not polymarket.com).
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/research/polymarket_us/market.sqlite3"
API = "https://gateway.polymarket.us"
UTC = dt.timezone.utc
LOG = logging.getLogger("yeno.us.collect")
PAUSE = 0.20


def client() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "YeNoUSResearch/0.1 (public read-only collection)"
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.7,
                  status_forcelist=(429, 500, 502, 503, 504),
                  respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=2))
    return s


def get(s: requests.Session, endpoint: str, params=None) -> dict | None:
    r = s.get(API + endpoint, params=params, timeout=18)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    obj = r.json()
    if not isinstance(obj, dict):
        raise ValueError(f"Unexpected payload from {endpoint}")
    return obj


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=40)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=40000")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS markets(
        slug TEXT PRIMARY KEY, horizon_min INTEGER NOT NULL,
        window_start INTEGER NOT NULL, window_end INTEGER NOT NULL,
        market_id TEXT, question TEXT, rules TEXT, created_at TEXT,
        captured_at INTEGER NOT NULL, settlement TEXT);
      CREATE TABLE IF NOT EXISTS historical_prices(
        slug TEXT NOT NULL, sample_at INTEGER NOT NULL,
        up_display REAL, down_display REAL,
        PRIMARY KEY(slug,sample_at));
      CREATE TABLE IF NOT EXISTS market_snapshots(
        slug TEXT NOT NULL, captured_at INTEGER NOT NULL,
        window_start INTEGER NOT NULL, window_end INTEGER NOT NULL,
        best_bid REAL, best_ask REAL, bid_qty REAL, ask_qty REAL,
        bid_depth REAL, ask_depth REAL, shares_traded REAL,
        notional_traded REAL, open_interest REAL, last_trade REAL,
        bids_top5 TEXT, asks_top5 TEXT,
        state TEXT, source_updated_at TEXT,
        PRIMARY KEY(slug,captured_at));
      CREATE TABLE IF NOT EXISTS btc_reference(
        sample_at INTEGER PRIMARY KEY, observed_at INTEGER NOT NULL,
        open REAL, high REAL, low REAL, close REAL, tick_count INTEGER,
        bucket_sec INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS fetch_state(
        scope TEXT NOT NULL, key TEXT NOT NULL,
        checked_at INTEGER NOT NULL, status TEXT NOT NULL,
        rows INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,key));
      CREATE TABLE IF NOT EXISTS paper_fills(
        fill_id TEXT PRIMARY KEY, filled_at INTEGER NOT NULL,
        slug TEXT NOT NULL, side TEXT NOT NULL,
        quantity REAL NOT NULL, price REAL NOT NULL, fee_usd REAL NOT NULL);
      CREATE INDEX IF NOT EXISTS idx_snapshots_time ON market_snapshots(captured_at);
      CREATE INDEX IF NOT EXISTS idx_prices_time ON historical_prices(sample_at);
      CREATE INDEX IF NOT EXISTS idx_fills_market ON paper_fills(slug,filled_at);
    """)
    db.commit()
    return db


def marked(db, scope, key) -> bool:
    return db.execute("SELECT 1 FROM fetch_state WHERE scope=? AND key=?", (scope, key)).fetchone() is not None


def mark(db, scope, key, status, rows=0):
    db.execute("INSERT OR REPLACE INTO fetch_state VALUES(?,?,?,?,?)",
               (scope, key, int(time.time()), status, rows))


def windows(day: dt.date):
    midnight = dt.datetime.combine(day, dt.time(), UTC)
    for minutes in (15, 60):
        horizon = "15m" if minutes == 15 else "1h"
        for offset in range(0, 1440, minutes):
            start = midnight + dt.timedelta(minutes=offset)
            yield (f"cpc-btc-updown-{horizon}-{start:%Y-%m-%d-%H%M}z",
                   minutes, int(start.timestamp()))


def expected_windows(at: dt.datetime):
    epoch = int(at.timestamp())
    for minutes in (15, 60):
        period = minutes * 60
        start = epoch // period * period
        start_dt = dt.datetime.fromtimestamp(start, UTC)
        horizon = "15m" if minutes == 15 else "1h"
        yield (f"cpc-btc-updown-{horizon}-{start_dt:%Y-%m-%d-%H%M}z",
               minutes, start)


def save_market(db, market: dict, slug: str, horizon: int, start: int):
    with db:
        db.execute("""INSERT INTO markets VALUES(?,?,?,?,?,?,?,?,?,NULL)
          ON CONFLICT(slug) DO UPDATE SET
            market_id=excluded.market_id, question=excluded.question,
            rules=excluded.rules, captured_at=excluded.captured_at""",
          (slug, horizon, start, start + 60 * horizon, market.get("id"),
           market.get("question"), market.get("description"),
           market.get("createdAt"), int(time.time())))


def archive_market(db, s, slug, horizon, start, throttle=PAUSE) -> int:
    if marked(db, "history", slug):
        return 0
    market = get(s, "/v1/market/slug/" + slug)
    if market is None or not market.get("market"):
        with db:
            mark(db, "history", slug, "not_found")
        return 0
    save_market(db, market["market"], slug, horizon, start)
    # Explicit epoch window avoids ALL-time history sampling outside the window.
    p = {"symbol": slug, "fidelity": 1, "timestamp.startTimestamp": start,
         "timestamp.endTimestamp": start + horizon * 60 + 60}
    history = get(s, "/v1/price-history", p)
    if history is None:
        raise ValueError(f"Missing price-history endpoint for {slug}")
    values = []
    for row in history.get("history", []):
        ts = int(row["timestamp"])
        if start <= ts < start + horizon * 60:
            values.append((slug, ts, row.get("longPrice"), row.get("shortPrice")))
    with db:
        db.executemany("INSERT OR REPLACE INTO historical_prices VALUES(?,?,?,?)", values)
        # Missing/empty histories are recorded as absence, never fabricated.
        mark(db, "history", slug, "ok" if values else "empty", len(values))
    time.sleep(throttle)
    return len(values)


def archive_settlement(db, s, slug, throttle=PAUSE):
    if marked(db, "settlement", slug):
        return
    result = get(s, f"/v1/markets/{slug}/settlement")
    if result is None:
        return
    value = result.get("settlement")
    with db:
        if value is not None:
            db.execute("UPDATE markets SET settlement=? WHERE slug=?",
                       (json.dumps(value), slug))
        mark(db, "settlement", slug, "ok" if value is not None else "missing", int(value is not None))
    time.sleep(throttle)


def archive_reference_day(db, s, day, throttle=PAUSE):
    key = str(day)
    if marked(db, "btc_day", key):
        return 0
    start = int(dt.datetime.combine(day, dt.time(), UTC).timestamp())
    payload = get(s, "/v1/asset-prices/history",
                  {"assets": "crypto:btc", "from": start,
                   "to": start + 86400, "bucket": "ASSET_PRICE_BUCKET_1M"})
    if payload is None:
        return 0
    candles = []
    for series in payload.get("series", []):
        for item in series.get("candles", []):
            timestamp = int(item["timestamp"])
            if start <= timestamp < start + 86400:
                candles.append((timestamp, int(time.time()), item.get("open"),
                                item.get("high"), item.get("low"), item.get("close"),
                                item.get("tickCount"), 60))
    with db:
        db.executemany("""INSERT INTO btc_reference VALUES(?,?,?,?,?,?,?,?)
                          ON CONFLICT(sample_at) DO NOTHING""", candles)
        mark(db, "btc_day", key, "ok" if candles else "empty", len(candles))
    time.sleep(throttle)
    return len(candles)


def num(v):
    if isinstance(v, dict):
        v = v.get("value")
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def top(levels):
    selected = []
    for row in levels[:5]:
        price, qty = num(row.get("px")), num(row.get("qty"))
        if price is not None and qty is not None:
            selected.append([price, qty])
    return selected


def live_book(db, s, slug, horizon, start, at=None):
    payload = get(s, f"/v1/markets/{slug}/book")
    if payload is None:
        return False
    book = payload.get("marketData") or {}
    if not book or book.get("state") not in ("MARKET_STATE_OPEN", "MARKET_STATE_SUSPENDED"):
        return False
    # Capture time AFTER receiving the response; never backdate the information.
    observed = int(at if at is not None else time.time())
    bids, asks = top(book.get("bids") or []), top(book.get("offers") or [])
    stats = book.get("stats") or {}
    bid, ask = (bids[0] if bids else (None, None)), (asks[0] if asks else (None, None))
    row = (slug, observed, start, start + horizon * 60,
           bid[0], ask[0], bid[1], ask[1],
           sum(q for _, q in bids), sum(q for _, q in asks),
           num(stats.get("sharesTraded")), num(stats.get("notionalTraded")),
           num(stats.get("openInterest")), num(stats.get("lastTradePx")),
           json.dumps(bids, separators=(",", ":")), json.dumps(asks, separators=(",", ":")),
           book.get("state"), book.get("transactTime"))
    with db:
        db.execute("""INSERT OR REPLACE INTO market_snapshots
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
    return True


def live_reference(db, s):
    now = int(time.time())
    payload = get(s, "/v1/asset-prices/history",
                  {"assets": "crypto:btc", "from": now - 100, "to": now - 15,
                   "bucket": "ASSET_PRICE_BUCKET_15S"})
    if payload is None:
        return 0
    candles = []
    for series in payload.get("series", []):
        for c in series.get("candles", []):
            ts = int(c["timestamp"])
            # The candle must have closed before it is observed.
            if ts + 15 <= now:
                candles.append((ts, now, c.get("open"), c.get("high"),
                                c.get("low"), c.get("close"), c.get("tickCount"), 15))
    with db:
        db.executemany("""INSERT OR IGNORE INTO btc_reference VALUES(?,?,?,?,?,?,?,?)""", candles)
    return len(candles)


def backfill(db, s, start: dt.date, end: dt.date, max_markets=None):
    n, rows = 0, 0
    day = start
    while day <= end and (max_markets is None or n < max_markets):
        for slug, horizon, opened in windows(day):
            if max_markets is not None and n >= max_markets:
                break
            if marked(db, "history", slug) and marked(db, "settlement", slug):
                continue
            try:
                if not marked(db, "history", slug):
                    rows += archive_market(db, s, slug, horizon, opened)
                if db.execute("SELECT 1 FROM markets WHERE slug=?", (slug,)).fetchone():
                    archive_settlement(db, s, slug)
                n += 1
                if n % 40 == 0:
                    LOG.info("backfill date=%s markets=%d price_rows=%d", day, n, rows)
            except (requests.RequestException, ValueError, sqlite3.Error) as exc:
                LOG.warning("market=%s error=%s", slug, exc)
                time.sleep(2)
        try:
            archive_reference_day(db, s, day)
        except (requests.RequestException, ValueError, sqlite3.Error) as exc:
            LOG.warning("btc day=%s error=%s", day, exc)
        day += dt.timedelta(days=1)
    LOG.info("backfill finished checked=%d price_rows=%d end=%s", n, rows, day)
    return n


def live(db, s, seconds=30, stop_after=0):
    started = time.monotonic()
    count = 0
    while not stop_after or time.monotonic() - started < stop_after:
        now = dt.datetime.now(UTC)
        for slug, horizon, start in expected_windows(now):
            try:
                if not db.execute("SELECT 1 FROM markets WHERE slug=?", (slug,)).fetchone():
                    market = get(s, "/v1/market/slug/" + slug)
                    if market and market.get("market"):
                        save_market(db, market["market"], slug, horizon, start)
                if live_book(db, s, slug, horizon, start):
                    count += 1
            except (requests.RequestException, ValueError, sqlite3.Error) as exc:
                LOG.warning("live book=%s error=%s", slug, exc)
        try:
            live_reference(db, s)
        except (requests.RequestException, ValueError, sqlite3.Error) as exc:
            LOG.warning("live BTC reference error=%s", exc)
        if count and count % 120 == 0:
            LOG.info("live snapshots=%d", count)
        # Align to 30s grid; no overlapping requests or busy looping.
        time.sleep(max(1, seconds - time.time() % seconds))


def status(db):
    tables = ("markets", "historical_prices", "market_snapshots",
              "btc_reference", "paper_fills", "fetch_state")
    print(json.dumps({
        "path": str(DB),
        "bytes": DB.stat().st_size if DB.exists() else 0,
        "rows": {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables},
        "horizons": dict(db.execute("SELECT horizon_min, COUNT(*) FROM markets GROUP BY horizon_min")),
        "recent_snapshots": db.execute("SELECT slug,captured_at FROM market_snapshots ORDER BY captured_at DESC LIMIT 4").fetchall(),
        "last_reference": db.execute("SELECT MAX(sample_at) FROM btc_reference").fetchone()[0],
        "fetch_status": dict(db.execute("SELECT scope,COUNT(*) FROM fetch_state GROUP BY scope")),
    }, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backfill", "live", "status"))
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2026, 9, 22))
    parser.add_argument("--end", type=dt.date.fromisoformat,
                        default=dt.datetime.now(UTC).date() - dt.timedelta(days=1))
    parser.add_argument("--max-markets", type=int)
    parser.add_argument("--seconds", type=int, choices=(30, 60), default=30)
    parser.add_argument("--stop-after", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock_path = args.db.with_suffix(f".{args.mode}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        if args.mode != "status":
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit("Collector already running in this mode")
        with connect(args.db) as db, client() as s:
            if args.mode == "status":
                status(db)
            elif args.mode == "backfill":
                if args.end < args.start:
                    parser.error("--end must be >= --start")
                backfill(db, s, args.start, args.end, args.max_markets)
            else:
                live(db, s, args.seconds, args.stop_after)


if __name__ == "__main__":
    main()

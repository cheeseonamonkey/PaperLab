"""Paced, resumable archival of public Polymarket US BTC market history.

Historical display prices are not executable order books. This collector
only stores source responses; it does not trade, train or infer fills.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from feeds import _momentum, get, value, window_slug

ROOT = Path(__file__).resolve().parent / "data" / "backfill"
STATE = ROOT / "state.json"
HOUR = 3600
HORIZONS = (("15m", 900), ("1h", HOUR))
HOURS_PER_RUN = 3


def latest_closed_hour(now=None):
    """UTC boundaries of the last fully closed hour."""
    end = int(time.time() if now is None else now) // HOUR * HOUR
    return end - HOUR, end


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def slug(start, horizon):
    """Compatibility wrapper; market identifiers come from the canonical feed helper."""
    return window_slug(start, horizon)


def market(start, horizon, period, require_settlement=True):
    symbol = slug(start, horizon)
    meta = get("/v1/market/slug/" + symbol, missing_ok=True)
    if meta is None:
        return {"slug": symbol, "horizon": horizon, "status": "not_found"}
    contract = meta.get("market") or {}
    terms = contract.get("assetPriceTerms") or {}
    if terms.get("indexSymbol") != "BRTI" or terms.get("horizon") != horizon:
        raise ValueError("Unexpected market metadata for " + symbol)
    history = get("/v1/price-history", {
        "symbol": symbol, "fidelity": 1,
        "timestamp.startTimestamp": start,
        "timestamp.endTimestamp": start + period,
    }, missing_ok=not require_settlement)
    if history is None and not require_settlement:
        return {"slug": symbol, "horizon": horizon, "status": "history_unavailable"}
    if not isinstance(history.get("history"), list):
        raise ValueError("Invalid price history for " + symbol)
    try:
        result = get("/v1/markets/" + symbol + "/settlement", missing_ok=True)
    except OSError:
        if require_settlement:
            raise
        result = None
    if result is not None and (result.get("slug") != symbol or result.get("settlement") not in (0, 1)):
        if require_settlement:
            raise ValueError("Invalid official settlement for " + symbol)
        result = None
    if require_settlement and result is None:
        raise ValueError("Official settlement unavailable for " + symbol)
    return {"slug": symbol, "horizon": horizon, "start": start, "ends": start + period,
            "status": "collected", "metadata": meta, "display_history": history,
            "settlement": result}


def exogenous(start, end):
    """Minute OHLCV for context; candles become available only after closing."""
    candles = {}
    for asset in ("BTC", "ETH", "SOL", "XRP"):
        params = urlencode({"granularity": 60,
                            "start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                            "end": datetime.fromtimestamp(end, timezone.utc).isoformat()})
        url = "https://api.exchange.coinbase.com/products/" + asset + "-USD/candles?" + params
        try:
            with urlopen(Request(url, headers={"User-Agent": "PaperLab/1.0"}), timeout=15) as response:
                rows = json.load(response)
            if not isinstance(rows, list):
                raise ValueError("Invalid exogenous candle response for " + asset)
            candles[asset] = sorted((row for row in rows if len(row) >= 6 and start <= int(row[0]) < end),
                                    key=lambda row: row[0])
        except (OSError, ValueError, KeyError) as error:
            print("Optional", asset, "history unavailable:", error, flush=True)
            candles[asset] = []
    return candles


def collect_hour(start, end, require_settlement=True):
    at = datetime.fromtimestamp(start, timezone.utc)
    path = ROOT / "hours" / at.strftime("%Y-%m-%d") / (at.strftime("%H") + ".json.gz")
    markets = [market(t, horizon, period, require_settlement=require_settlement)
               for horizon, period in HORIZONS
               for t in range(start, end, period)]
    item = {"venue": "polymarket_us", "start": start, "end": end,
            "kind": "historical_display_not_order_book", "markets": markets,
            "exogenous_coinbase_1m": exogenous(start - 20 * 60, end)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out:
            out.write((json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode())
    os.replace(tmp, path)
    missing = sum(m["status"] != "collected" for m in markets)
    return path, missing, len(markets)


def observations(hour, reference):
    """Causal historical display-price observations; no synthetic order-book depth."""
    candles = hour["exogenous_coinbase_1m"]
    reference = sorted((c for c in reference if value(c.get("close")) is not None),
                       key=lambda c: int(c["timestamp"]))
    records = []
    for contract in hour["markets"]:
        if contract["status"] != "collected":
            continue
        terms = (contract["metadata"].get("market") or {}).get("assetPriceTerms") or {}
        strike = value(terms.get("priceToBeat"))
        if strike is None or strike <= 0:
            continue
        start, end = contract["start"], contract["ends"]
        for row in contract["display_history"]["history"]:
            at, price = int(row["timestamp"]), value(row.get("longPrice"))
            if not start <= at < end or price is None or not .01 < price < .99:
                continue
            features, available_at = {}, {}
            for asset, series in candles.items():
                momentum = _momentum([c for c in series if int(c[0]) + 63 <= at], at)
                if momentum:
                    for key in ("r1", "r5", "r15", "vol15", "volume15"):
                        name = asset.lower() + "_" + key
                        features[name] = momentum[key]
                        available_at[name] = momentum["available_at"]
            known = [c for c in reference if int(c["timestamp"]) + 60 <= at]
            close = value(known[-1]["close"]) if known else None
            recent = known[-16:]
            continuous = len(recent) == 16 and all(
                int(b["timestamp"])-int(a["timestamp"]) == 60
                for a,b in zip(recent, recent[1:]))
            returns = ([math.log(value(b["close"])/value(a["close"]))
                        for a,b in zip(recent, recent[1:])] if continuous else [])
            if known:
                available_at["brti_close"] = int(known[-1]["timestamp"]) + 60
            features.update(price_to_beat=strike, brti_close=close,
                            strike_distance=close / strike - 1 if close else None,
                            btc_vol15=statistics.pstdev(returns) if len(returns) == 15 else None,
                            time_left=(end - at) / (end - start))
            records.append({"venue": "polymarket_us", "source": "historical_price_proxy",
                            "slug": contract["slug"], "start": start, "ends": end,
                            "observed_at": at, "display_up": price, "features": features,
                            "feature_available_at": available_at, "quotes": {},
                            "display_history": [{"timestamp": at, "up": price, "down": 1 - price}],
                            "brti_history": []})
    unique = {(row["slug"], row["observed_at"]): row for row in records}
    return sorted(unique.values(), key=lambda row: (row["observed_at"], row["slug"]))


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    # Leave the most recently closed hour for settlements to become available.
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "next_end": int(time.time()) // HOUR * HOUR - HOUR,
        "hours_saved": 0, "missing_markets": 0, "empty_hours": 0,
    }
    # Backfill the latest closed hour as well, covering live-run gaps.
    recent_start, recent_end = latest_closed_hour()
    recent_at = datetime.fromtimestamp(recent_start, timezone.utc)
    recent_path = ROOT / "hours" / recent_at.strftime("%Y-%m-%d") / (recent_at.strftime("%H") + ".json.gz")
    if not recent_path.exists():
        try:
            collect_hour(recent_start, recent_end)
            state["recent_hours_saved"] = state.get("recent_hours_saved", 0) + 1
            state.pop("recent_error", None)
        except (OSError, ValueError) as exc:
            state["recent_error"] = str(exc)[:200]
            print("Latest hour deferred:", exc, flush=True)
        write_json(STATE, state)
    for _ in range(HOURS_PER_RUN):
        if state.get("done"):
            break
        end = state["next_end"]
        start = end - HOUR
        path, missing, total = collect_hour(start, end)
        state["next_end"] = start
        state["hours_saved"] += 1
        state["missing_markets"] += missing
        state["empty_hours"] = state.get("empty_hours", 0) + 1 if missing == total else 0
        # Record the 404s; stop after a full day without either horizon.
        state["done"] = state["empty_hours"] >= 24
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(STATE, state)
        print("Saved", path, "missing", missing, "next_end", start, flush=True)


if __name__ == "__main__":
    main()

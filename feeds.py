"""Read-only Polymarket US market, BRTI reference, and optional cross-asset feeds."""
from __future__ import annotations

import datetime as dt
import csv
import io
import json
import math
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://gateway.polymarket.us"
ASSETS = ("BTC", "ETH", "SOL", "XRP")
PERIOD = 900

def get(path, params=None, missing_ok=False):
    # Explicit host allowlist: no order, signing, account or auth endpoints.
    if not path.startswith(("/v1/market/slug/", "/v1/markets/", "/v1/asset-prices/history", "/v1/price-history")):
        raise ValueError("Unexpected US public read endpoint: " + path)
    url = API + path + ("?" + urlencode(params) if params else "")
    try:
        with urlopen(Request(url, headers={"User-Agent": "PaperLab/1.0", "Accept": "application/json"}), timeout=12) as response:
            value = json.load(response)
    except HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise
    if not isinstance(value, dict):
        raise ValueError("Unexpected US public API JSON")
    return value

def value(x):
    if isinstance(x, dict):
        x = x.get("value")
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None

def window_slug(start, horizon="15m"):
    at = dt.datetime.fromtimestamp(start, dt.timezone.utc)
    return "cpc-btc-updown-" + horizon + "-" + at.strftime("%Y-%m-%d-%H%M") + "z"

def levels(book, key):
    entries = []
    for row in (book.get(key) or []):
        price, quantity = value(row.get("px")), value(row.get("qty"))
        if price is not None and quantity is not None and 0 < price < 1 and quantity > 0:
            entries.append((price, quantity))
    return sorted(entries, reverse=key == "bids")[:5]

def quotes(book):
    bids, asks = levels(book, "bids"), levels(book, "offers")
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        raise ValueError("Missing or crossed US best bid/ask")
    # Polymarket US book is YES-centric; NO is the binary complement.
    up = {"bid": bids[0][0], "ask": asks[0][0], "bid_size": bids[0][1], "ask_size": asks[0][1],
          "bid_depth": sum(x[1] for x in bids), "ask_depth": sum(x[1] for x in asks)}
    down = {"bid": round(1-asks[0][0], 6), "ask": round(1-bids[0][0], 6),
            "bid_size": asks[0][1], "ask_size": bids[0][1],
            "bid_depth": up["ask_depth"], "ask_depth": up["bid_depth"]}
    return {"Up": up, "Down": down}

def _momentum(rows, now):
    recent = {int(x[0]): x for x in rows if int(x[0]) + 63 <= now}
    candles = [recent[k] for k in sorted(recent)]
    if len(candles) < 16:
        return None
    close = [float(x[4]) for x in candles]
    if not all(x > 0 and math.isfinite(x) for x in close):
        return None
    returns = [math.log(close[i]/close[i-1]) for i in range(1, len(close))]
    mean = sum(returns[-15:])/15
    return {"r1": returns[-1], "r5": math.log(close[-1]/close[-6]),
            "r15": math.log(close[-1]/close[-16]),
            "vol15": math.sqrt(sum((r-mean)**2 for r in returns[-15:])/15),
            "volume15": sum(float(x[5]) for x in candles[-15:]),
            "available_at": candles[-1][0] + 63}


def _sp500_context(now):
    """FRED daily close return, usable only after a conservative next-day cutoff."""
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    start = today - dt.timedelta(days=14)
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode({
        "id": "SP500", "cosd": start.isoformat(), "coed": today.isoformat()})
    with urlopen(Request(url, headers={"User-Agent": "PaperLab/1.0", "Accept": "text/csv"}), timeout=8) as response:
        text = response.read().decode("utf-8-sig")
    retrieved_at = int(time.time())
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = dt.date.fromisoformat(row.get("observation_date", row.get("DATE", "")))
            close = float(row["SP500"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(close) and close > 0:
            # FRED publishes the daily close after market close; waiting until
            # 05:00 UTC the next day is conservative across EST/EDT and holidays.
            available = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(5), dt.timezone.utc).timestamp())
            if available <= retrieved_at:
                rows.append((day, close, retrieved_at))
    if len(rows) < 2 or (today - rows[-1][0]) > dt.timedelta(days=4):
        return None
    return {"r1": math.log(rows[-1][1] / rows[-2][1]), "available_at": rows[-1][2]}

def settlement(slug):
    data = get("/v1/markets/"+slug+"/settlement", missing_ok=True)
    if data is None or data.get("slug") != slug:
        return None
    # Confirmed US endpoint outcome: 1 = Up (YES), 0 = Down (NO).
    result = data.get("settlement")
    if type(result) not in (int, float) or result not in (0, 1):
        return None
    return "Up" if result == 1 else "Down"

class USFeed:
    def __init__(self, horizon="15m"):
        if horizon not in ("15m", "1h"):
            raise ValueError("Unsupported US market horizon")
        self.horizon = horizon
        self.period = 900 if horizon == "15m" else 3600
        self.slug = None
        self.metadata = None
        self.cached_reference = []
        self.cached_display = []
        self.cached_exogenous = {}
        self.cached_sp500 = None
        self.sp500_at = 0
        self.reference_at = self.display_at = self.exogenous_at = 0

    def _reference(self, now):
        if self.cached_reference and now-self.reference_at < 58:
            return self.cached_reference
        data = get("/v1/asset-prices/history", {
            "assets": "crypto:btc", "from": now - 140*60, "to": now - 60,
            "bucket": "ASSET_PRICE_BUCKET_1M",
        })
        series = data.get("series", [])
        if len(series) != 1:
            raise ValueError("Unexpected BRTI reference series")
        candles = {int(c["timestamp"]): c for c in series[0].get("candles", []) if int(c["timestamp"]) + 60 <= now}
        self.cached_reference = [candles[k] for k in sorted(candles)]
        self.reference_at = now
        return self.cached_reference

    def _display(self, now, start):
        if now-self.display_at < 58:
            return self.cached_display
        data = get("/v1/price-history", {
            "symbol": self.slug, "fidelity": 1,
            "timestamp.startTimestamp": start, "timestamp.endTimestamp": now,
        })
        self.cached_display = [
            {"timestamp": int(row["timestamp"]), "up": value(row.get("longPrice")), "down": value(row.get("shortPrice"))}
            for row in data.get("history", []) if start <= int(row["timestamp"]) <= now
        ]
        self.display_at = now
        return self.cached_display

    def _exogenous(self, now):
        if now-self.exogenous_at < 116:
            return self.cached_exogenous
        # Cross-asset context is observational only. Each missing feed stays missing.
        # Coinbase prices do NOT replace the official BRTI event reference.
        from urllib.parse import urlencode
        context = {}
        for asset in ASSETS:
            try:
                url = "https://api.exchange.coinbase.com/products/"+asset+"-USD/candles?" + urlencode(
                    {"granularity": 60, "start": now-22*60, "end": now-60})
                with urlopen(Request(url, headers={"User-Agent": "PaperLab/1.0"}), timeout=8) as response:
                    series = json.load(response)
                fields = _momentum(series, now)
                if fields:
                    fields["available_at"] = max(fields["available_at"], int(time.time()))
                context[asset.lower()] = fields
            except (OSError, ValueError, KeyError) as error:
                print("Optional %s context unavailable: %s" % (asset, error), flush=True)
                context[asset.lower()] = None
        if now-self.sp500_at >= 3600:
            try:
                self.cached_sp500 = _sp500_context(now)
            except (OSError, ValueError, KeyError) as error:
                print("Optional S&P 500 context unavailable: %s" % error, flush=True)
                self.cached_sp500 = None
            self.sp500_at = now
        context["sp500"] = self.cached_sp500
        self.cached_exogenous = context
        self.exogenous_at = now
        return context

    def observe(self, now=None):
        now = int(time.time() if now is None else now)
        start = (now//self.period)*self.period
        slug = window_slug(start, self.horizon)
        if slug != self.slug:
            self.slug, self.metadata = slug, None
            self.cached_display, self.display_at = [], 0
        if self.metadata is None:
            item = get("/v1/market/slug/"+slug)
            self.metadata = item.get("market")
        m = self.metadata or {}
        terms = m.get("assetPriceTerms") or {}
        if m.get("status") != "MARKET_STATUS_OPEN" or terms.get("indexSymbol") != "BRTI" or terms.get("horizon") != self.horizon:
            raise ValueError("Expected open Polymarket US " + self.horizon + " BRTI market")
        strike = value(terms.get("priceToBeat"))
        if strike is None or strike <= 0:
            raise ValueError("US price-to-beat unavailable")
        # Fetch slow inputs BEFORE the order book: decisions use a fresh book
        # and only already-known reference/spot observations.
        reference = self._reference(now)
        display = self._display(now, start)
        exogenous = self._exogenous(now)
        result = get("/v1/markets/"+slug+"/book")["marketData"]
        if result.get("state") != "MARKET_STATE_OPEN" or result.get("marketSlug") != slug:
            raise ValueError("US order book not OPEN or wrong slug")
        quote = quotes(result)
        # Capture timestamp AFTER fetching book; never backdate stale data.
        received = int(time.time())
        if received >= start+self.period:
            raise ValueError("Expired during book acquisition")
        recent_book = result.get("transactTime")
        if recent_book:
            try:
                updated = dt.datetime.fromisoformat(recent_book.replace("Z", "+00:00")).timestamp()
                if received - updated > 15 or updated - received > 10:
                    raise ValueError("US book timestamp stale/in future")
            except (TypeError, AttributeError) as error:
                raise ValueError("Invalid US book timestamp") from error
        # Extra inputs are logged for future retraining even if older checkpoints
        # cannot use them without invalidating their feature contracts.
        last = reference[-1] if reference else {}
        current_brti = value(last.get("close"))
        numeric = {
            "time_left": (start+self.period-received)/self.period, "price_to_beat": strike,
            "brti_close": current_brti,
            "strike_distance": (current_brti/strike-1) if current_brti else None,
            "yes_spread": quote["Up"]["ask"]-quote["Up"]["bid"],
            "yes_bid_depth": quote["Up"]["bid_depth"],
            "yes_ask_depth": quote["Up"]["ask_depth"],
            "yes_book_imbalance": ((quote["Up"]["bid_depth"]-quote["Up"]["ask_depth"]) /
                (quote["Up"]["bid_depth"]+quote["Up"]["ask_depth"])),
        }
        feature_available_at = {}
        for asset, fields in exogenous.items():
            keys = ("r1",) if asset == "sp500" else ("r1", "r5", "r15", "vol15", "volume15")
            for key in keys:
                feature = asset+"_"+key
                numeric[feature] = fields.get(key) if fields else None
                if numeric[feature] is not None:
                    feature_available_at[feature] = fields["available_at"]
        return {"venue":"polymarket_us", "slug": slug, "start": start, "ends": start+self.period,
                "observed_at": received, "quotes":quote, "features": numeric,
                "feature_available_at": feature_available_at,
                "book_top5": {"bids":levels(result,"bids"), "asks":levels(result,"offers")},
                "display_history":display, "brti_history":reference,
                "is_live_book":True}

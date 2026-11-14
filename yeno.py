"""Public-data-only BTC 15-minute binary-market paper trader; no order API."""
from __future__ import annotations
import json, math, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "data/ledger.json"
STRATEGY = ROOT / "strategies/champion.json"
REPORT = ROOT / "REPORT.md"
FEE = 0.02                  # Modeled buffer, not a quote of actual fees
SLIPPAGE = 0.005           # USD per outcome share
START = 100.0
WINDOW = 900

def utc(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def request(url):
    req = Request(url, headers={"User-Agent": "YeNoPaperLab/0.1", "Accept": "application/json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)

def arr(value):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list):
        raise ValueError("Expected list in market metadata")
    return result

def market(slug):
    item = request("https://gamma-api.polymarket.com/events/slug/" + slug)
    if not isinstance(item, dict) or item.get("slug") != slug or len(item.get("markets", [])) != 1:
        raise ValueError("Missing/invalid market " + slug)
    result = item["markets"][0]
    if arr(result["outcomes"]) != ["Up", "Down"]:
        raise ValueError("Unexpected market outcomes")
    return result

def winner(item):
    if not item.get("closed") or item.get("umaResolutionStatus") != "resolved":
        return None
    prices = [float(x) for x in arr(item["outcomePrices"])]
    return "Up" if prices == [1.0, 0.0] else "Down" if prices == [0.0, 1.0] else None

def best_ask(token):
    data = request("https://clob.polymarket.com/book?token_id=" + token)
    asks = sorted(({"price": float(x["price"]), "size": float(x["size"])} for x in data.get("asks", [])), key=lambda x: x["price"])
    return next((x for x in asks if .01 <= x["price"] < 1 and x["size"] > 0), None)

def features():
    now = int(time.time())
    rows = request("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60&start=" + str(now-1500) + "&end=" + str(now))
    prices = {int(r[0]): float(r[4]) for r in rows if int(r[0]) < now // 60 * 60}
    values = [prices[t] for t in sorted(prices)]
    if len(values) < 16 or not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError("Insufficient valid spot candles")
    return {"ret5": values[-1]/values[-6]-1, "ret15": values[-1]/values[-16]-1}

def validate(params):
    limits = {"w5": (-80, 80), "w15": (-80, 80), "min_edge": (0, .25), "max_price": (.55, .95)}
    if set(params) != set(limits):
        raise ValueError("Unexpected strategy parameters")
    for key, (low, high) in limits.items():
        value = params[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("Invalid parameter " + key)
    return params

def choose(obs, params):
    """Pure strategy; backtests and paper execution use this same function."""
    p = min(.95, max(.05, .5 + params["w5"]*obs["features"]["ret5"] + params["w15"]*obs["features"]["ret15"]))
    candidates = []
    for side, probability in (("Up", p), ("Down", 1-p)):
        quote = obs["quotes"].get(side)
        if not quote:
            continue
        price = quote["price"] + SLIPPAGE
        if .05 <= price <= params["max_price"]:
            edge = probability - price*(1+FEE)
            candidates.append({"side": side, "price": price, "edge": edge, "probability": probability})
    if not candidates:
        return None
    pick = max(candidates, key=lambda x: x["edge"])
    if pick["edge"] >= params["min_edge"]:
        return {**pick, "stake": 5.0, "reason": "modeled_edge"}
    if pick["price"] <= .75 and pick["probability"] >= .32:
        return {**pick, "stake": 1.0, "reason": "exploration"}
    return None

def load():
    if LEDGER.exists():
        state = json.loads(LEDGER.read_text())
        if state.get("mode") != "paper" or state.get("starting_cash") != START:
            raise ValueError("Ledger not paper-only or incorrect initial bankroll")
        return state
    return {"mode": "paper", "starting_cash": START, "cash": START, "observations": [], "trades": [], "last_run": None}

def save(state):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    temp = LEDGER.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(temp, LEDGER)

def settle(state, now):
    count = 0
    trades = {t["slug"]: t for t in state["trades"]}
    for obs in state["observations"]:
        if obs["outcome"] is not None or now < obs["ends"] + 120:
            continue
        side = winner(market(obs["slug"]))
        if side is None:
            continue  # Never infer outcome from a third-party spot proxy.
        obs["outcome"] = side
        trade = trades.get(obs["slug"])
        if trade and trade["status"] == "open":
            payout = trade["shares"] if trade["side"] == side else 0.0
            trade.update(status="settled", payout=round(payout, 8), pnl=round(payout-trade["stake"], 8), winner=side, settled_at=utc(now))
            state["cash"] = round(state["cash"]+payout, 8)
        count += 1
    return count

def observe(now):
    start = now//WINDOW*WINDOW
    if start+WINDOW-now < 360:
        start += WINDOW
    slug = "btc-updown-15m-" + str(start)
    item = market(slug)
    if item.get("closed") or not item.get("acceptingOrders") or not item.get("enableOrderBook"):
        raise ValueError("Market not accepting orders: " + slug)
    tokens = arr(item["clobTokenIds"])
    if len(tokens) != 2:
        raise ValueError("Expected two outcome tokens")
    return {"slug": slug, "ends": start+WINDOW, "observed_at": utc(now), "features": features(), "quotes": {"Up": best_ask(str(tokens[0])), "Down": best_ask(str(tokens[1]))}, "outcome": None}

def enter(state, obs, params):
    chosen = choose(obs, params)
    if not chosen:
        return "No qualifying paper trade"
    stake = min(chosen["stake"], state["cash"])
    if stake < .99:
        return "Not enough paper cash"
    shares = stake / (chosen["price"] * (1+FEE))
    if shares > obs["quotes"][chosen["side"]]["size"]:
        return "Insufficient best-ask liquidity"
    if any(t["slug"] == obs["slug"] for t in state["trades"]):
        return "Duplicate entry blocked"
    state["trades"].append({"slug": obs["slug"], "side": chosen["side"], "stake": round(stake,8), "shares": round(shares,8), "price": round(chosen["price"],6), "modeled_edge": round(chosen["edge"],6), "reason": chosen["reason"], "opened_at": obs["observed_at"], "status": "open"})
    state["cash"] = round(state["cash"]-stake, 8)
    return "Paper BUY %s for $%.2f at %.3f (%s)" % (chosen["side"],stake,chosen["price"],chosen["reason"])

def report(state):
    trades = state["trades"]
    done = [t for t in trades if t["status"] == "settled"]
    opened = [t for t in trades if t["status"] == "open"]
    pnl = sum(t["pnl"] for t in done)
    wins = sum(t["pnl"] > 0 for t in done)
    rows = ["# YeNo Paper Lab — Results", "", "Last run: **%s**" % (state["last_run"] or "Not yet run"), "", "| Metric | Value |", "|---|---:|", "| Starting cash | $100.00 |", "| Available paper cash | $%.2f |" % state["cash"], "| Open cost basis (not marked-to-market) | $%.2f |" % sum(t["stake"] for t in opened), "| Realized P&L | $%+.2f |" % pnl, "| Settled trades | %d |" % len(done), "| Win rate | %s |" % ("%.1f%%" % (100*wins/len(done)) if done else "N/A"), "| Open positions | %d |" % len(opened), "| Recorded observations | %d |" % len(state["observations"]), "", "## Latest trades", "", "| Market | Side | Stake | Status | P&L |", "|---|---|---:|---|---:|"]
    for t in reversed(trades[-25:]):
        rows.append("| [%s](https://polymarket.com/event/%s) | %s | $%.2f | %s | %s |" % (t["slug"], t["slug"], t["side"], t["stake"], t["status"], "$%+.2f" % t["pnl"] if "pnl" in t else "—"))
    if not trades:
        rows.append("| No trades | — | — | — | — |")
    rows += ["", "## Assumptions", "", "Observed Polymarket 15-minute BTC Up/Down order-book asks; settlement uses only Gamma officially resolved outcomes.", "Execution is hypothetical: quoted best ask + $0.005/share and 2% modeled entry fees (not a real fee quote). A real order might not fill at this price.", "The baseline strategy is experimental and not calibrated. No leverage, no orders, no wallet, no signing, no exchange keys.", ""]
    return "\n".join(rows)

def run():
    state = load()
    now = int(time.time())
    resolved = settle(state, now)
    obs = observe(now)
    if not any(x["slug"] == obs["slug"] for x in state["observations"]):
        state["observations"].append(obs)
        action = enter(state, obs, validate(json.loads(STRATEGY.read_text())))
    else:
        action = "Already observed; duplicate prevented"
    state["last_run"] = utc(now)
    save(state)
    REPORT.write_text(report(state))
    print("%s | resolved=%d | %s | cash=$%.2f" % (state["last_run"], resolved, action, state["cash"]))

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "run"
    if action == "run":
        run()
    elif action == "report":
        REPORT.write_text(report(load()))
        print(REPORT.read_text())
    else:
        sys.exit("Usage: python yeno.py [run|report]")

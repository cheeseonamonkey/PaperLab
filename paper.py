"""Thirteen isolated $100 Polymarket US paper accounts; simulated market/limit orders.

All actions are LOCAL JSON state transitions. No authenticated API, wallets,
signed requests, order submission, or exchange-key support exists.
"""
from __future__ import annotations
import argparse
import gzip
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from feeds import USFeed, settlement
from predictors import MODELS, Predictions
from train_research import load_fork_models, load_model as load_research_model, predict as predict_research

ROOT = Path(__file__).resolve().parent
STATE = ROOT/"data/state.json"
REPORT = ROOT/"REPORT.md"
OBS_DIR = ROOT/"data/observations"
START = 100.0
TAKER_COEFFICIENT = .0695  # US straight-contract fee; maker fee is zero
SLIPPAGE = .005       # Marketable-entry execution penalty per share
STATE_VERSION = 3
KELLY_SCALE = .25
MAX_ORDER_EQUITY_FRACTION = .10
MAX_EXPOSURE_EQUITY_FRACTION = .30
MIN_ORDER_COST = .01
DECISION_INTERVAL = 60
MIN_EDGE = .045
STRATEGY_MIN_EDGE = {}  # Optional per-account overrides.
CALIBRATION_WARMUP = 20
CALIBRATION_RATE = .05
CALIBRATION_MAX_LOGIT = .15
BASE_POLICIES = {
    "stacked_rnn": "limit",
    "skip_gru_2": "limit",
    "depthwise_tcn": "limit",
    "lstm": "limit",
    "conv_gru": "limit",
    "market_implied": "hold",
    "brti_distance": "limit",
    "brti_distance_limit": "limit",
    "btc_momentum": "limit",
    "btc_reversion": "limit",
    "cross_asset_momentum": "limit",
    "book_imbalance": "limit",
    "research_linear": "limit",
}
ROSTER = ROOT/"strategies/roster.json"

def fork_policies():
    """Fork accounts from the checked-in roster (train_research owns it):
    active forks trade with the limit policy; retired forks (periodic reset)
    stay on the books in hold mode — history preserved, no new trades."""
    try:
        entries = json.loads(ROSTER.read_text()).get("forks", [])
    except (OSError, ValueError):
        return {}
    return {entry["name"]: ("hold" if entry.get("status") == "retired" else "limit")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)}

POLICIES = {**BASE_POLICIES, **fork_policies()}
# Accounts whose probability comes from a fitted model file rather than a rule.
MODEL_ACCOUNTS = {"research_linear"} | set(fork_policies())

def stamp(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).isoformat(timespec="seconds")

def empty_forecast_metric():
    return {"markets":0,"forecasts":0,"brier_sum":0.0,"market_brier_sum":0.0,
            "logloss_sum":0.0,"market_logloss_sum":0.0}

def initial():
    return {"version":STATE_VERSION, "venue":"polymarket_us", "mode":"paper",
            "cash_per_strategy":START, "last_run":None, "last_processed_hour_end":0,
            "last_batch":None, "markets":{},
            "forecast_metrics":{name:empty_forecast_metric() for name in POLICIES},
            "polling":{"attempts":0,"observed":0,"skipped":0,"last_attempt":None,"last_error":None},
            "accounts":{name:{"cash":START,"orders":[],"trades":[],"signals":0} for name in POLICIES}}

def load():
    if not STATE.exists():
        return initial()
    data=json.loads(STATE.read_text())
    if (data.get("mode"),data.get("venue"),data.get("cash_per_strategy")) != ("paper","polymarket_us",START):
        raise ValueError("Non-US or non-paper account state rejected")
    legacy_names = set(BASE_POLICIES) - {"research_linear"}
    if data.get("version") == 2 and set(data.get("accounts",{})) == legacy_names:
        data["accounts"]["research_linear"] = {"cash":START,"orders":[],"trades":[],"signals":0}
        data["version"] = STATE_VERSION
    elif data.get("version") != STATE_VERSION or not set(data.get("accounts",{})) <= set(POLICIES):
        raise ValueError("Strategy account set mismatch")
    # Roster accounts (research_linear, auto-forks) join with a fresh isolated
    # $100 account the first time a state predating them is loaded; existing
    # accounts and their history are never touched by this migration.
    for name in POLICIES:
        data["accounts"].setdefault(name, {"cash":START,"orders":[],"trades":[],"signals":0})
    data.setdefault("last_processed_hour_end", 0)
    data.setdefault("last_batch", None)
    data.setdefault("forecast_metrics",{})
    for name in POLICIES:
        data["forecast_metrics"].setdefault(name,empty_forecast_metric())
    for market in data.get("markets",{}).values():
        market.setdefault("forecasts",[])
    return data

def save(state):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n")
    os.replace(tmp,STATE)

def append_observation(obs):
    OBS_DIR.mkdir(parents=True,exist_ok=True)
    path=OBS_DIR/(datetime.fromtimestamp(obs["observed_at"],timezone.utc).strftime("%Y-%m-%d")+".jsonl.gz")
    # Shared quote/data record, not one duplicate per strategy.
    record={k:obs[k] for k in ("venue","slug","start","ends","observed_at","quotes","features")}
    if "feature_available_at" in obs:
        record["feature_available_at"] = obs["feature_available_at"]
    if "source" in obs:
        record["source"] = obs["source"]
    if "display_up" in obs:
        record["display_up"] = obs["display_up"]
    record["book_top5"] = obs.get("book_top5", {})
    record["latest_display"]=obs["display_history"][-1] if obs["display_history"] else None
    record["latest_reference"]=obs["brti_history"][-1] if obs["brti_history"] else None
    with gzip.open(path,"at",encoding="utf-8") as file:
        file.write(json.dumps(record,separators=(",",":"),sort_keys=True)+"\n")

def cap(x,lo=.01,hi=.99):
    return max(lo,min(hi,x))

def implied_probability(obs):
    if obs.get("source") == "historical_price_proxy":
        return cap(obs["display_up"])
    book = obs["quotes"]["Up"]
    return cap((book["bid"] + book["ask"]) / 2)


def fair_probability(strategy,obs,models):
    if strategy in MODELS or strategy in MODEL_ACCOUNTS:
        return models.get(strategy)
    f=obs["features"]
    implied=implied_probability(obs)
    if strategy=="market_implied":
        return None # Explicit hold / do-nothing benchmark.
    if strategy.startswith("brti_distance"):
        distance=f.get("strike_distance")
        volatility=f.get("btc_vol15")
        if distance is None or volatility is None or volatility <= 0:
            return None
        remaining=max(15,(obs["ends"]-obs["observed_at"]))/60
        z=distance/max(volatility*math.sqrt(remaining/15),.0002)
        return cap(.5*(1+math.erf(z/math.sqrt(2))))
    if strategy=="book_imbalance":
        if obs.get("source") == "historical_price_proxy":
            return None
        imbalance = f.get("yes_book_imbalance")
        return cap(implied + .10*imbalance) if imbalance is not None else None
    btc=f.get("btc_r5")
    if btc is None:
        return None
    if strategy=="btc_momentum":
        shift=80*btc
    elif strategy=="btc_reversion":
        shift=-80*btc
    elif strategy=="cross_asset_momentum":
        basket=[f.get(a+"_r5") for a in ("btc","eth","sol","xrp")]
        known=[x for x in basket if x is not None]
        if len(known)<3:
            return None
        shift=60*sum(known)/len(known)
    else:
        raise ValueError("Unexpected policy "+strategy)
    logit=math.log(cap(implied)/(1-cap(implied)))
    return cap(1/(1+math.exp(-max(-30,min(30,logit+shift)))))

def available(account):
    return account["cash"]-sum(o["reserved"] for o in account["orders"] if o["status"]=="open")

def equity(account):
    """Cash plus cost basis of open positions; reservations remain in cash."""
    return max(0.0,account["cash"]+sum(t.get("cost",0) for t in account["trades"] if t["status"]=="open"))

def committed_exposure(account):
    positions=sum(t.get("cost",0) for t in account["trades"] if t["status"]=="open")
    reservations=sum(o.get("reserved",0) for o in account["orders"] if o["status"]=="open")
    return positions+reservations

def maybe_order(account,obs,probability,mode,now,min_edge=MIN_EDGE):
    if probability is None or mode=="hold" or not .01 < probability < .99:
        return None
    slug=obs["slug"]
    bucket=now//DECISION_INTERVAL
    if any(o["slug"]==slug and o["placed_at"]//DECISION_INTERVAL==bucket for o in account["orders"]) or any(
            t["slug"]==slug and t["placed_at"]//DECISION_INTERVAL==bucket for t in account["trades"]):
        return None
    if available(account)<=0:
        return None
    historical = obs.get("source") == "historical_price_proxy"
    candidates=[]
    for side,prob in (("Up",probability),("Down",1-probability)):
        book = None if historical else obs["quotes"][side]
        if historical:
            price = (obs["display_up"] if side == "Up" else 1-obs["display_up"]) + SLIPPAGE
        elif mode=="limit":
            price = book["bid"]
        else:
            price = book["ask"]+SLIPPAGE
        if not .05 <= price <= .95:
            continue
        unit_fee = 0 if mode=="limit" and not historical else TAKER_COEFFICIENT*price*(1-price)
        modeled_edge = prob-price-unit_fee
        if modeled_edge>=min_edge:
            candidates.append((modeled_edge,side,price,book,unit_fee))
    if not candidates:
        return None
    edge,side,price,book,unit_fee=max(candidates,key=lambda x:x[0])
    unit_cost=price+unit_fee
    account_equity=equity(account)
    kelly_fraction=KELLY_SCALE*edge/(1-unit_cost) if unit_cost<1 else 0
    exposure_room=max(0,account_equity*MAX_EXPOSURE_EQUITY_FRACTION-committed_exposure(account))
    allocation=min(available(account),account_equity*MAX_ORDER_EQUITY_FRACTION,
                   account_equity*kelly_fraction,exposure_room)
    if allocation < max(MIN_ORDER_COST,unit_cost/10000):
        return None
    shares=math.floor(allocation/(price+unit_fee)*10000)/10000
    if shares<=0:
        return None
    cost=round(shares*(price+unit_fee),8)
    if cost>available(account)+1e-8:
        return None
    entry={"slug":slug,"side":side,"price":round(price,6),
           "shares":shares,"cost":cost,"edge":round(edge,6),"placed_at":now}
    account["signals"]+=1
    if historical or mode=="limit":
        order={**entry,"reserved":cost,"status":"open",
               "type":"historical_buy" if historical else "limit"}
        account["orders"].append(order)
        return ("PROXY BUY " if historical else "LIMIT ")+side
    if shares>book["ask_size"]:
        return "MARKET no-fill: insufficient displayed top-ask depth"
    account["cash"]=round(account["cash"]-cost,8)
    account["trades"].append({**entry,"status":"open","type":"market","filled_at":now})
    return "PAPER MARKET "+side

def maybe_exit(account, obs, probability, now):
    historical = obs.get("source") == "historical_price_proxy"
    depth = ({side: obs["quotes"][side]["bid_size"] for side in ("Up", "Down")}
             if not historical else None)
    exited, insufficient = [], False
    for trade in account["trades"]:
        if trade["status"] != "open" or trade["slug"] != obs["slug"]:
            continue
        side = trade["side"]
        price = ((obs["display_up"] if side == "Up" else 1-obs["display_up"]) - SLIPPAGE
                 if historical else obs["quotes"][side]["bid"])
        side_probability = (probability if side == "Up" else 1-probability) if probability is not None else None
        urgent = now >= obs["ends"] - 60 or (side_probability is not None and side_probability <= price)
        if not urgent:
            continue
        if price <= 0 or (not historical and depth[side] < trade["shares"]):
            insufficient = True
            continue
        for order in account["orders"]:
            if (order.get("type") == "limit_sell" and order["slug"] == trade["slug"]
                    and order.get("trade_placed_at") == trade["placed_at"]
                    and order["status"] == "open"):
                order.update(status="cancelled", cancelled_at=now)
        if not historical:
            depth[side] -= trade["shares"]
        fee = TAKER_COEFFICIENT*trade["shares"]*price*(1-price)
        proceeds = round(price*trade["shares"]-fee,8)
        pnl = round(proceeds-trade["cost"],8)
        order_type = "historical_sell" if historical else "ioc_sell"
        account["orders"].append({"slug":trade["slug"],"side":side,"type":order_type,
                                  "status":"filled","placed_at":now,"filled_at":now,"price":price,
                                  "shares":trade["shares"],"reserved":0,"fee":round(fee,8),
                                  "trade_placed_at":trade["placed_at"]})
        trade.update(status="settled",settled_at=now,close_reason=order_type,
                     exit_price=price,payout=proceeds,pnl=pnl,won=pnl>0)
        account["cash"] = round(account["cash"]+proceeds,8)
        exited.append(side)
    if exited:
        return "IOC SELL "+exited[0] if len(exited)==1 else "IOC SELL %d positions" % len(exited)
    return "IOC SELL no-fill: insufficient displayed depth" if insufficient else None

def evaluate_limits(account,obs,now,markets=None):
    markets=markets if markets is not None else {obs["slug"]:{"ends":obs["ends"]}}
    historical = obs.get("source") == "historical_price_proxy"
    ask_left = ({side:obs["quotes"][side]["ask_size"] for side in ("Up", "Down")}
                if not historical else None)
    bid_left = ({side:obs["quotes"][side]["bid_size"] for side in ("Up", "Down")}
                if not historical else None)
    for order in account["orders"]:
        if order["status"]!="open":
            continue
        market=markets.get(order["slug"],{})
        ends=market.get("ends")
        if ends is not None and now>=ends:
            # Expired orders are not assumed filled; reservations are released.
            order["status"]="expired"
            order["cancelled_at"]=now
            continue
        if order["slug"]!=obs["slug"]:
            continue
        if now<=order["placed_at"]:
            continue # Never fill against same snapshot used for placement.
        if historical:
            if order.get("type") != "historical_buy":
                continue
            price = (obs["display_up"] if order["side"] == "Up" else 1-obs["display_up"]) + SLIPPAGE
            fee = TAKER_COEFFICIENT*price*(1-price) if 0 < price < 1 else 0
            cost = round(order["shares"]*(price+fee),8)
            if not 0 < price < 1 or cost > order["reserved"]+1e-8:
                order.update(status="cancelled",cancelled_at=now)
                continue
            order.update(status="filled",filled_at=now,fill_price=round(price,6),
                         fee=round(order["shares"]*fee,8))
            account["cash"] = round(account["cash"]-cost,8)
            account["trades"].append({k:v for k,v in order.items()
                                     if k not in ("reserved","status","type")} |
                                    {"status":"open","type":"historical_price_proxy",
                                     "price":round(price,6),"cost":cost,"filled_at":now})
            continue
        if order.get("type") == "historical_buy":
            continue
        book=obs["quotes"][order["side"]]
        if order.get("type")=="limit_sell":
            trade=next((t for t in account["trades"] if t["slug"]==order["slug"] and
                        t["placed_at"]==order["trade_placed_at"] and t["status"]=="open"),None)
            if trade is None:
                order.update(status="cancelled",cancelled_at=now)
            elif book["bid"]>=order["price"] and bid_left[order["side"]]>=order["shares"]:
                proceeds=round(order["price"]*order["shares"],8)
                pnl=round(proceeds-trade["cost"],8)
                order.update(status="filled",filled_at=now)
                bid_left[order["side"]] -= order["shares"]
                trade.update(status="settled",settled_at=now,close_reason="limit_sell",
                             exit_price=order["price"],payout=proceeds,pnl=pnl,won=pnl>0)
                account["cash"]=round(account["cash"]+proceeds,8)
            continue
        if book["ask"] <= order["price"] and ask_left[order["side"]] >= order["shares"]:
            # Cross observed on a later poll: *hypothetical* fill at original
            # limit price. No maker rebate claimed, no guarantee of actual fill.
            order["status"]="filled"
            order["filled_at"]=now
            ask_left[order["side"]] -= order["shares"]
            account["cash"]=round(account["cash"]-order["cost"],8)
            account["trades"].append({k:v for k,v in order.items() if k not in ("reserved","status","type")} |
                                    {"status":"open","type":"limit_cross","filled_at":now})

def calibrate(probability, account):
    """Apply bounded online correction after enough settled market forecasts."""
    learning = account.get("learning", {})
    if probability is None or learning.get("markets", 0) < CALIBRATION_WARMUP:
        return probability
    p = min(.999, max(.001, probability))
    logit = math.log(p/(1-p)) + learning.get("logit_offset", 0.0)
    return 1/(1+math.exp(-max(-30, min(30, logit))))


def process_snapshot(state,obs,predictions,names=None):
    now=obs["observed_at"]
    market=state["markets"].setdefault(obs["slug"],{"ends":obs["ends"],"outcome":None,"checked_at":0})
    market.setdefault("forecasts",[])
    market_probability=implied_probability(obs)
    forecast={"at":now,"market":market_probability,"probabilities":{}}
    decisions=[]
    for name,mode in POLICIES.items():
        if names is not None and name not in names:
            continue
        account=state["accounts"][name]
        evaluate_limits(account,obs,now,state["markets"])
        p=market_probability if name=="market_implied" else fair_probability(name,obs,predictions)
        if p is not None and math.isfinite(p) and 0<=p<=1:
            if mode != "hold":
                p = calibrate(p, account)
            forecast["probabilities"][name]=p
        bucket=now//DECISION_INTERVAL
        last=account.setdefault("last_decision",{})
        if mode!="hold" and last.get(obs["slug"])!=bucket:
            last[obs["slug"]]=bucket
            for message in (maybe_exit(account,obs,p,now),
                            maybe_order(account,obs,p,mode,now,STRATEGY_MIN_EDGE.get(name,MIN_EDGE))):
                if message:
                    decisions.append(name+":"+message)
    market["forecasts"].append(forecast)
    return decisions

def forecast_losses(probability,actual):
    p=min(1-1e-12,max(1e-12,probability))
    return (probability-actual)**2, -(actual*math.log(p)+(1-actual)*math.log(1-p))

def score_market_forecasts(state,market,outcome):
    actual=1.0 if outcome=="Up" else 0.0
    paired={}
    for row in market.pop("forecasts",[]):
        benchmark=row.get("market")
        if benchmark is None:
            continue
        for name,probability in row.get("probabilities",{}).items():
            paired.setdefault(name,[]).append((probability,benchmark))
    for name,pairs in paired.items():
        losses=[forecast_losses(p,actual) for p,_ in pairs]
        baseline=[forecast_losses(q,actual) for _,q in pairs]
        metric=state["forecast_metrics"].setdefault(name,empty_forecast_metric())
        metric["markets"]+=1
        metric["forecasts"]+=len(pairs)
        metric["brier_sum"]+=sum(x[0] for x in losses)/len(losses)
        metric["logloss_sum"]+=sum(x[1] for x in losses)/len(losses)
        metric["market_brier_sum"]+=sum(x[0] for x in baseline)/len(baseline)
        metric["market_logloss_sum"]+=sum(x[1] for x in baseline)/len(baseline)
        if name in state["accounts"] and POLICIES.get(name) != "hold":
            # One update per resolved market, regardless of snapshot count.
            learning = state["accounts"][name].setdefault("learning", {"markets":0,"logit_offset":0.0})
            error = actual - sum(p for p,_ in pairs)/len(pairs)
            learning["markets"] += 1
            learning["logit_offset"] = max(-CALIBRATION_MAX_LOGIT, min(
                CALIBRATION_MAX_LOGIT, learning["logit_offset"] + CALIBRATION_RATE*error))

def reconcile(state,now):
    due={slug:m for slug,m in state["markets"].items()
         if m["outcome"] is None and now>=m["ends"]+30 and now-m["checked_at"]>=60}
    for slug,info in due.items():
        info["checked_at"]=now
        outcome=settlement(slug)
        if outcome is None:
            continue
        info["outcome"]=outcome
        info["resolved_at"]=now
        score_market_forecasts(state,info,outcome)
        for account in state["accounts"].values():
            for order in account["orders"]:
                if order["slug"]==slug and order["status"]=="open":
                    order["status"]="expired"
                    order["cancelled_at"]=now
            for trade in account["trades"]:
                if trade["slug"]!=slug or trade["status"]!="open":
                    continue
                payout=trade["shares"] if trade["side"]==outcome else 0.0
                trade.update(status="settled",won=trade["side"]==outcome,
                             payout=round(payout,8),pnl=round(payout-trade["cost"],8),
                             settled_at=now)
                account["cash"]=round(account["cash"]+payout,8)

def render(state):
    stats = state.get("polling", {})
    batch = state.get("last_batch")
    poll_label = "Previous live polling" if batch else "Polls"
    settled_markets=sum(m.get("outcome") is not None for m in state.get("markets",{}).values())
    settled_positions=sum(t["status"]=="settled" for a in state["accounts"].values() for t in a["trades"])
    header=["# Paper Lab — Polymarket US", "", "Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.",
            "Accounts: **%d independent $%.0f bankrolls**, not a shared pool. Latest successful observation: **%s**." %
            (len(state["accounts"]),START,stamp(state["last_run"]) if state["last_run"] else "Not yet run"), "",
            "Research sample: **%d markets tracked / %d officially settled / %d settled strategy positions**." %
            (len(state.get("markets",{})),settled_markets,settled_positions), "",
            "%s: **%s attempts / %s recorded / %s skipped**. Last error: %s." %
            (poll_label, stats.get("attempts",0),stats.get("observed",0),
             stats.get("skipped",0),stats.get("last_error") or "None"),"",
            "| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    if batch:
        header[-2:-2] = ["Last hourly replay: **%s–%s UTC**, %d historical price observations from %d markets (%d unavailable)." %
                   (stamp(batch["start"]),stamp(batch["end"]),batch["observations"],
                    batch["markets"],batch["missing_markets"]),""]
    for name,account in state["accounts"].items():
        settled=[t for t in account["trades"] if t["status"]=="settled"]
        pending=[o for o in account["orders"] if o["status"]=="open"]
        opening=[t for t in account["trades"] if t["status"]=="open"]
        wins=sum(bool(t.get("won")) for t in settled)
        pnl=sum(t["pnl"] for t in settled)
        metric=state.get("forecast_metrics",{}).get(name,empty_forecast_metric())
        n=metric["markets"]
        brier=metric["brier_sum"]/n if n else None
        gain=(metric["market_brier_sum"]-metric["brier_sum"])/n if n else None
        winrate="%d/%d (%.1f%%)" % (wins,len(settled),100*wins/len(settled)) if settled else "—"
        brier_text="%.3f (n=%d)" % (brier,n) if brier is not None else "— (n=0)"
        gain_text="%+.3f" % gain if gain is not None else "—"
        header.append("| [%s](docs/bots/%s.md) | $%.2f | $%+.2f | %s | %s | %s | %d | %d | %d |" %
                      (name,name,account["cash"],pnl,winrate,brier_text,gain_text,
                       len(settled),len(opening),len(pending)))
    baseline=state.get("forecast_metrics",{}).get("market_implied",empty_forecast_metric())
    if baseline["markets"]:
        header += ["", "Market-midpoint benchmark: Brier %.3f / log loss %.3f across %d settled markets." %
                   (baseline["brier_sum"]/baseline["markets"],
                    baseline["logloss_sum"]/baseline["markets"],baseline["markets"])]
    else:
        header += ["", "Market-midpoint benchmark: awaiting first officially settled market."]
    header += ["", "Win rate is settled simulated fills only. Forecasts estimate Up probability; Brier and log loss use the official outcome.",
                "Forecast losses average snapshots within each market, then average markets. Positive ΔBrier means improvement over the paired market midpoint; lower Brier/log loss is better.",
                "Realized profit is **not** total equity: active positions are not marked to market.",
                "Historical batches use archived display prices, not executable order books. Buy and sell fills are delayed fee-adjusted price proxies; actual liquidity and slippage are unknown.",
                "Legacy live-book limit fills used a later book crossing and displayed size, never proven queue priority. Historic orders retain their original fee assumptions.",
                "Five legacy checkpoint accounts abstain in this fresh-start run; the repository-trained research candidate is evaluated separately.",
                "The remaining seven strategies are explicit deterministic baselines, including a no-trade account.",
                "No authentication, private APIs, real orders, funds or wallets.", ""]
    return "\n".join(header)

README_START="<!-- PAPER_STATUS_START -->"
README_END="<!-- PAPER_STATUS_END -->"

def write_outputs(state):
    report=render(state)
    REPORT.write_text(report)
    readme_path=ROOT/"README.md"
    readme=readme_path.read_text()
    if readme.count(README_START)!=1 or readme.count(README_END)!=1:
        raise ValueError("README status markers missing or duplicated")
    report_lines=report.splitlines()
    table_start=report_lines.index("| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |")
    table_end=next(i for i in range(table_start+2,len(report_lines)) if not report_lines[i].startswith("|"))
    benchmark_line=next(line for line in report_lines[table_end+1:] if line.startswith("Market-midpoint benchmark:"))
    status=[README_START,"## Current research status","",*report_lines[2:table_end],"",
            benchmark_line,"",
            "Win rate uses settled simulated fills. Forecast Brier averages snapshots within each market, then averages markets; n is the number of settled markets. Positive ΔBrier means better than the paired market-midpoint forecast; lower Brier is better.",
            "",
            "Full caveats and the audit trail are in [REPORT.md](REPORT.md).",README_END]
    start=readme.index(README_START)
    end=readme.index(README_END)+len(README_END)
    readme_path.write_text(readme[:start]+"\n".join(status)+readme[end:])

def cycle(state,feed,models,now=None):
    now=int(time.time() if now is None else now)
    reconcile(state,now)
    observation=feed.observe(now)
    # Legacy checkpoints abstain; the causal research candidate runs separately.
    candidate=load_research_model()
    probabilities={"research_linear":predict_research(observation,candidate)} if candidate else {}
    for fork_name,fork_model in load_fork_models().items():
        probabilities[fork_name]=predict_research(observation,fork_model)
    # The source quote must still be recent when the decision is made.
    if time.time()-observation["observed_at"] > 12:
        raise ValueError("Stale quote after model inference; no paper orders")
    decisions=process_snapshot(state,observation,probabilities)
    append_observation(observation)
    state["last_run"]=observation["observed_at"]
    state["polling"]["observed"]+=1
    state["polling"]["last_error"]=None
    save(state)
    write_outputs(state)
    print(stamp(now),"US",observation["slug"],"signals",len(decisions),
          "decisions",", ".join(decisions[:5]) or "none",flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=("run","report","check"),nargs="?",default="run")
    ap.add_argument("--duration",type=int,default=0,help="Seconds of 15s polling (0 = one observation)")
    opts=ap.parse_args()
    state=load()
    state.setdefault("polling",{"attempts":0,"observed":0,"skipped":0,"last_attempt":None,"last_error":None})
    if opts.command=="report":
        write_outputs(state)
        from reports import export
        export(state)
        print(REPORT.read_text())
        return
    if opts.command=="check":
        from predictors import SCALES
        assert len(SCALES["x_mean"])==24 and len(SCALES["c_mean"])==64
        print("Paper engine configured; inactive legacy models:",", ".join(MODELS))
        return
    feeds,models=[USFeed("15m"),USFeed("1h")],Predictions()
    deadline=time.monotonic()+opts.duration
    while True:
        started=time.monotonic()
        for feed in feeds:
            state["polling"]["attempts"]+=1
            state["polling"]["last_attempt"]=int(time.time())
            try:
                cycle(state,feed,models)
            except Exception as exc:
                print(stamp(),"US",feed.horizon,"feed/model cycle failed; NO speculative trade:",str(exc),flush=True)
                state["polling"]["skipped"]+=1
                state["polling"]["last_error"]=type(exc).__name__+": "+str(exc)[:160]
                save(state)
                write_outputs(state)
                if not opts.duration:
                    raise
        if not opts.duration:
            return
        remaining=deadline-time.monotonic()
        if remaining<=0:
            return
        time.sleep(min(remaining,max(0,15-(time.monotonic()-started))))

if __name__=="__main__":
    main()

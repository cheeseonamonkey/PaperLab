"""Twelve isolated $100 Polymarket US paper accounts; simulated market/limit orders.

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

ROOT = Path(__file__).resolve().parent
STATE = ROOT/"data/state.json"
REPORT = ROOT/"REPORT.md"
OBS_DIR = ROOT/"data/observations"
START = 100.0
FEE = .02             # Conservative simulation buffer, not US actual venue fee
SLIPPAGE = .005       # Marketable-entry execution penalty per share
MAX_STAKE = 5.0
MIN_SHARES = 5.0
MAX_OPEN_COST = 15.0
POLICIES = {
    "stacked_rnn": "limit",
    "skip_gru_2": "limit",
    "depthwise_tcn": "market",
    "lstm": "limit",
    "conv_gru": "market",
    "market_implied": "hold",
    "brti_distance": "market",
    "brti_distance_limit": "limit",
    "btc_momentum": "market",
    "btc_reversion": "limit",
    "cross_asset_momentum": "limit",
    "book_imbalance": "limit",
}

def stamp(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).isoformat(timespec="seconds")

def empty_forecast_metric():
    return {"markets":0,"forecasts":0,"brier_sum":0.0,"market_brier_sum":0.0,
            "logloss_sum":0.0,"market_logloss_sum":0.0}

def initial():
    return {"version":2, "venue":"polymarket_us", "mode":"paper",
            "cash_per_strategy":START, "last_run":None, "markets":{},
            "forecast_metrics":{name:empty_forecast_metric() for name in POLICIES},
            "polling":{"attempts":0,"observed":0,"skipped":0,"last_attempt":None,"last_error":None},
            "accounts":{name:{"cash":START,"orders":[],"trades":[],"signals":0} for name in POLICIES}}

def load():
    if not STATE.exists():
        return initial()
    data=json.loads(STATE.read_text())
    if (data.get("mode"),data.get("venue"),data.get("cash_per_strategy"),data.get("version")) != ("paper","polymarket_us",START,2):
        raise ValueError("Non-US or non-paper account state rejected")
    if set(data.get("accounts",{})) != set(POLICIES):
        raise ValueError("Strategy account set mismatch")
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
    # Shared quote/data record, NOT 12 duplicated per-strategy observations.
    record={k:obs[k] for k in ("venue","slug","start","ends","observed_at","quotes","features")}
    record["book_top5"] = obs.get("book_top5", {})
    record["latest_display"]=obs["display_history"][-1] if obs["display_history"] else None
    record["latest_reference"]=obs["brti_history"][-1] if obs["brti_history"] else None
    with gzip.open(path,"at",encoding="utf-8") as file:
        file.write(json.dumps(record,separators=(",",":"),sort_keys=True)+"\n")

def cap(x,lo=.01,hi=.99):
    return max(lo,min(hi,x))

def fair_probability(strategy,obs,models):
    if strategy in MODELS:
        return models.get(strategy)
    f=obs["features"]
    quote=obs["quotes"]["Up"]
    implied=(quote["bid"]+quote["ask"])/2
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
        return cap(implied+.10*f.get("yes_book_imbalance",0))
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

def risk_exposure(account):
    return sum(t["cost"] for t in account["trades"] if t["status"]=="open")

def available(account):
    return account["cash"]-sum(o["reserved"] for o in account["orders"] if o["status"]=="open")

def maybe_order(account,obs,probability,mode,now):
    if probability is None or mode=="hold" or not .01 < probability < .99:
        return None
    slug=obs["slug"]
    if any(o["slug"]==slug for o in account["orders"]) or any(t["slug"]==slug for t in account["trades"]):
        return None
    if risk_exposure(account)>=MAX_OPEN_COST or available(account)<1:
        return None
    candidates=[]
    for side,prob in (("Up",probability),("Down",1-probability)):
        book=obs["quotes"][side]
        # Ask is executable for a marketable paper buy; resting bid for a limit.
        if mode=="limit":
            price=book["bid"]
            if price<.05 or price>.95:
                continue
            # Even maker-style paper orders require positive modeled edge.
            modeled_edge=prob-price*(1+FEE)
        else:
            price=book["ask"]+SLIPPAGE
            if price<.05 or price>.95:
                continue
            modeled_edge=prob-price*(1+FEE)
        if modeled_edge>=.05:
            candidates.append((modeled_edge,side,price,book))
    if not candidates:
        return None
    edge,side,price,book=max(candidates,key=lambda x:x[0])
    allocation=min(MAX_STAKE,available(account),MAX_OPEN_COST-risk_exposure(account))
    shares=math.floor(allocation/(price*(1+FEE))*10000)/10000
    if shares<MIN_SHARES:
        return None
    cost=round(shares*price*(1+FEE),8)
    if cost>available(account)+1e-8:
        return None
    entry={"slug":slug,"side":side,"price":round(price,6),
           "shares":shares,"cost":cost,"edge":round(edge,6),"placed_at":now}
    account["signals"]+=1
    if mode=="limit":
        order={**entry,"reserved":cost,"status":"open","type":"limit"}
        account["orders"].append(order)
        return "LIMIT "+side
    if shares>book["ask_size"]:
        return "MARKET no-fill: insufficient displayed top-ask depth"
    account["cash"]=round(account["cash"]-cost,8)
    account["trades"].append({**entry,"status":"open","type":"market","filled_at":now})
    return "PAPER MARKET "+side

def evaluate_limits(account,obs,now,markets):
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
        book=obs["quotes"][order["side"]]
        if book["ask"] <= order["price"] and book["ask_size"] >= order["shares"]:
            # Cross observed on a later poll: *hypothetical* fill at original
            # limit price. No maker rebate claimed, no guarantee of actual fill.
            order["status"]="filled"
            order["filled_at"]=now
            account["cash"]=round(account["cash"]-order["cost"],8)
            account["trades"].append({k:v for k,v in order.items() if k not in ("reserved","status","type")} |
                                    {"status":"open","type":"limit_cross","filled_at":now})

def process_snapshot(state,obs,predictions):
    now=obs["observed_at"]
    market=state["markets"].setdefault(obs["slug"],{"ends":obs["ends"],"outcome":None,"checked_at":0})
    market.setdefault("forecasts",[])
    up=obs["quotes"]["Up"]
    market_probability=cap((up["bid"]+up["ask"])/2)
    forecast={"at":now,"market":market_probability,"probabilities":{}}
    decisions=[]
    for name,mode in POLICIES.items():
        account=state["accounts"][name]
        evaluate_limits(account,obs,now,state["markets"])
        p=market_probability if name=="market_implied" else fair_probability(name,obs,predictions)
        if p is not None and math.isfinite(p) and 0<=p<=1:
            forecast["probabilities"][name]=p
        message=maybe_order(account,obs,p,mode,now)
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
    settled_markets=sum(m.get("outcome") is not None for m in state.get("markets",{}).values())
    settled_positions=sum(t["status"]=="settled" for a in state["accounts"].values() for t in a["trades"])
    header=["# YeNo Paper Lab — Polymarket US", "", "Venue: **Polymarket US**, BTC 15m BRTI Up/Down. All orders **simulated**.",
            "Accounts: **12 independent $100 bankrolls**, not a shared pool. Latest successful observation: **%s**." %
            (stamp(state["last_run"]) if state["last_run"] else "Not yet run"), "",
            "Research sample: **%d markets tracked / %d officially settled / %d settled strategy positions**." %
            (len(state.get("markets",{})),settled_markets,settled_positions), "",
            "Polls: **%s attempts / %s recorded / %s skipped**. Last error: %s." %
            (stats.get("attempts",0),stats.get("observed",0),stats.get("skipped",0),stats.get("last_error") or "None"),"",
            "| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
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
        header.append("| %s | $%.2f | $%+.2f | %s | %s | %s | %d | %d | %d |" %
                      (name,account["cash"],pnl,winrate,brier_text,gain_text,
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
                "US YES book is the market source; NO quotes are complement-derived.",
                "Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.",
                "Entry cost uses an assumed 2% fee buffer; marketable buys additionally add $0.005/share slippage. No actual fee or rebate schedule is inferred.",
                "Five frozen 250K checkpoints use trained BRTI/display histories; 52 slow macro context fields are mean-imputed (not the original live feature distribution). Results are exploratory and uncalibrated.",
                "The remaining seven strategies are explicit deterministic baselines, including a no-trade account.",
                "No authentication, private APIs, real orders, funds or wallets.", ""]
    return "\n".join(header)

README_START="<!-- YENO_STATUS_START -->"
README_END="<!-- YENO_STATUS_END -->"

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
    probabilities=models.all(observation)
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
        print(REPORT.read_text())
        return
    if opts.command=="check":
        from predictors import SCALES
        assert len(SCALES["x_mean"])==24 and len(SCALES["c_mean"])==64
        print("US paper engine configured; models:",", ".join(MODELS))
        return
    feed,models=USFeed(),Predictions()
    deadline=time.monotonic()+opts.duration
    while True:
        started=time.monotonic()
        state["polling"]["attempts"]+=1
        state["polling"]["last_attempt"]=int(time.time())
        try:
            cycle(state,feed,models)
        except Exception as exc:
            print(stamp(),"US feed/model cycle failed; NO speculative trade:",str(exc),flush=True)
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

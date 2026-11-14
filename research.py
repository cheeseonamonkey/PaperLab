"""Read-only research summaries. Pi proposes experiments, never executable orders."""
from __future__ import annotations
import argparse
import json
import re
import time
from pathlib import Path
from yeno import ROOT, load

PROPOSALS = ROOT/"research/proposals"

def sample_count(state):
    return sum(m["outcome"] is not None for m in state["markets"].values())

def prompt():
    state=load()
    count=sample_count(state)
    if count < 40:
        raise RuntimeError(f"Need >=40 officially settled US markets (got {count})")
    accounts=[]
    for name,account in state["accounts"].items():
        settled=[t for t in account["trades"] if t["status"]=="settled"]
        accounts.append({"name":name,"realized_pnl":round(sum(t["pnl"] for t in settled),4),
            "settled_trades":len(settled),"open_trades":sum(t["status"]=="open" for t in account["trades"]),
            "limit_orders_filled":sum(o["status"]=="filled" for o in account["orders"]),
            "limit_orders_expired":sum(o["status"]=="expired" for o in account["orders"])})
    return {
        "goal":"Research PAPER trading improvements only. No real-money trading.",
        "venue":"polymarket_us",
        "sample_scope":"Prospective but early and correlated 15-minute BTC markets; not a sealed holdout.",
        "important_caveats":[
            "All execution hypothetical; limit cross may not mean actual queue fill.",
            "Five neural models use mean-imputed 52 auxiliary inputs, an unverified distribution shift.",
            "No evidence any strategy is profitable or statistically significant.",
            "No strategy can be automatically deployed by this review.",
        ],
        "settled_market_count":count, "strategies":accounts,
        "required_output":"Output ONE JSON object: title (<=100 chars), hypothesis (<=500 chars), evaluation (<=700 chars), risks (<=500 chars). No markdown. Recommend one safe experiment with chronological evaluation and realistic fees.",
    }

def propose(text):
    match=re.search(r"\{[^{}]*\}",text,re.S)
    if not match:
        raise ValueError("Agent response did not contain a single JSON object")
    item=json.loads(match.group(0))
    limits={"title":100,"hypothesis":500,"evaluation":700,"risks":500}
    if set(item)!=set(limits) or not all(isinstance(item[k],str) and 5<=len(item[k])<=maxlen for k,maxlen in limits.items()):
        raise ValueError("Proposal does not match bounded review schema")
    PROPOSALS.mkdir(exist_ok=True,parents=True)
    path=PROPOSALS/(time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+".json")
    path.write_text(json.dumps({"status":"review_only","venue":"polymarket_us","proposal":item},indent=2)+"\n")
    print("Stored review-only proposal",path)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=("ready","prompt","evaluate"))
    ap.add_argument("file",nargs="?")
    args=ap.parse_args()
    if args.command=="ready":
        print("ready" if sample_count(load())>=40 else "collecting")
    elif args.command=="prompt":
        print(json.dumps(prompt(),indent=2))
    elif args.command=="evaluate":
        if not args.file:
            ap.error("evaluate requires the Pi output file")
        propose(Path(args.file).read_text())

if __name__=="__main__":
    main()

"""One-time, resumable two-day bootstrap using public data, independent of backfill."""
from __future__ import annotations
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from backfill import HORIZONS, HOUR, market, exogenous, write_json
from feeds import value
from train_research import candle_returns, market_window

ROOT = Path(__file__).resolve().parent / "data"
STATE = ROOT / "bootstrap" / "state.json"


def main():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "next_end": int(time.time()) // HOUR * HOUR - HOUR,
        "hours_saved": 0, "target_hours": 48, "done": False}
    while state["hours_saved"] < state["target_hours"]:
        end = state["next_end"]
        start = end - HOUR
        candles = exogenous(start, end)
        contracts = [market(t, horizon, period) for horizon, period in HORIZONS
                     for t in range(start, end, period)]
        observations, outcomes = [], {}
        for contract in contracts:
            if contract.get("status") != "collected":
                continue
            name = contract["slug"]
            result = contract["settlement"]["settlement"]
            outcomes[name] = "Up" if result == 1 else "Down"
            for q in contract["display_history"]["history"]:
                at = int(q["timestamp"])
                probability = value(q.get("longPrice"))
                if probability is None or not 0 < probability < 1:
                    continue
                market_start, market_end = market_window(name)
                if not market_start <= at < market_end:
                    continue
                context = {k.lower()+"_r1": v for k,v in candle_returns(candles, at).items()}
                observations.append({"source":"bootstrap","slug":name,"observed_at":at,
                                     "display_up":probability,"features":context})
        collected = sum(c.get("status") == "collected" for c in contracts)
        if not collected or not observations:
            raise ValueError("Bootstrap hour has no usable settled observations: " + str(start))
        state["markets_collected"] = state.get("markets_collected", 0) + collected
        state["missing_markets"] = state.get("missing_markets", 0) + len(contracts) - collected
        state["observations_saved"] = state.get("observations_saved", 0) + len(observations)
        at = datetime.fromtimestamp(start, timezone.utc)
        label = at.strftime("%Y-%m-%d-%H")
        directory = ROOT / "observations"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("bootstrap-" + label + ".jsonl.gz")
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as output:
                for row in observations:
                    output.write((json.dumps(row, sort_keys=True) + "\n").encode())
        os.replace(tmp, path)
        write_json(ROOT / "bootstrap" / "labels" / (label + ".json"), outcomes)
        state["next_end"] = start
        state["hours_saved"] += 1
        state["done"] = state["hours_saved"] >= state["target_hours"]
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(STATE, state)
        print("Bootstrap hour", label, "rows", len(observations), flush=True)


if __name__ == "__main__":
    main()

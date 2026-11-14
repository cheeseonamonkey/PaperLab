"""Bounded parameter research. Proposals never replace the production paper strategy."""
from __future__ import annotations
import json, re, sys, time
from pathlib import Path
from yeno import START, FEE, choose, load, validate, STRATEGY as CHAMPION

ROOT = Path(__file__).resolve().parent
PROPOSALS = ROOT / "research/proposals"
MIN_RESOLVED = 40

def history():
    return sorted((x for x in load()["observations"] if x["outcome"] in ("Up", "Down")), key=lambda x: x["ends"])

def split():
    data = history()
    cut = int(len(data) * .7)
    return data[:cut], data[cut:]

def simulate(items, strategy):
    capital, peak, worst = START, START, 0.0
    bets, wins = 0, 0
    for obs in items:
        pick = choose(obs, strategy)
        if pick is None:
            continue
        stake = min(capital, pick["stake"])
        quote = obs["quotes"][pick["side"]]
        if stake < .99 or stake/(pick["price"]*(1+FEE)) > quote["size"]:
            continue
        payout = stake/(pick["price"]*(1+FEE)) if pick["side"] == obs["outcome"] else 0.0
        capital += payout - stake
        peak = max(peak, capital)
        worst = max(worst, peak-capital)
        bets += 1
        wins += pick["side"] == obs["outcome"]
    return {"profit": round(capital-START, 4), "max_drawdown": round(worst, 4), "trades": bets, "wins": wins}

def ready():
    train, test = split()
    return len(history()) >= MIN_RESOLVED and len(train) >= 24 and len(test) >= 12

def input_data():
    train, test = split()
    if not ready():
        raise RuntimeError("Need at least 40 officially resolved snapshots for walk-forward evaluation")
    champion = validate(json.loads(CHAMPION.read_text()))
    return {
        "task": "Propose one parameter mutation to maximize net paper PnL without excessive drawdown. Output ONE JSON object containing only w5, w15, min_edge, max_price. No markdown.",
        "constraints": "w5/w15 each -80..80; min_edge 0..0.25; max_price 0.55..0.95; all numeric. Data is only historical, don't claim predictive edge.",
        "champion": champion,
        "training_score": simulate(train, champion),
        "observations": [{"ret5": x["features"]["ret5"], "ret15": x["features"]["ret15"], "up_ask": x["quotes"]["Up"]["price"] if x["quotes"]["Up"] else None, "down_ask": x["quotes"]["Down"]["price"] if x["quotes"]["Down"] else None, "winner": x["outcome"]} for x in train],
        "held_out_count": len(test),
    }

def propose(raw):
    match = re.search(r"\{[^{}]+\}", raw, flags=re.S)
    if not match:
        raise ValueError("Agent did not output a JSON object")
    config = validate(json.loads(match.group(0)))
    train, test = split()
    if not ready():
        raise ValueError("Not enough resolved observations")
    old = validate(json.loads(CHAMPION.read_text()))
    baseline = simulate(test, old)
    proposed = simulate(test, config)
    print(json.dumps({"champion": baseline, "candidate": proposed}, indent=2))
    # No candidates without a meaningful held-out improvement and enough actual paper trades.
    if proposed["trades"] < 6 or proposed["profit"] < max(0.5, baseline["profit"] + 0.5):
        print("Rejected: insufficient held-out profit/trade coverage")
        return False
    if proposed["max_drawdown"] > max(2.0, baseline["max_drawdown"] + 1.0):
        print("Rejected: excess held-out drawdown")
        return False
    if config == old:
        print("Rejected: identical to current champion")
        return False
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json"
    record = {"status": "review_only", "candidate": config, "baseline_heldout": baseline, "candidate_heldout": proposed, "train_n": len(train), "test_n": len(test)}
    (PROPOSALS / name).write_text(json.dumps(record, indent=2) + "\n")
    print("Saved review-only proposal: " + name)
    return True

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ready"
    if cmd == "ready":
        print("ready" if ready() else "collecting")
    elif cmd == "input":
        print(json.dumps(input_data(), indent=2))
    elif cmd == "evaluate":
        if len(sys.argv) != 3:
            sys.exit("Usage: python research.py evaluate path/to/agent_output.txt")
        propose(Path(sys.argv[2]).read_text())
    else:
        sys.exit("Usage: python research.py [ready|input|evaluate]")

if __name__ == "__main__":
    main()

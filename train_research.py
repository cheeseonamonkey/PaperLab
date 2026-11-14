"""Fit a market-relative model using settled live observations only."""
from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backfill import write_json
from feeds import value

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "training"
ASSETS = ("BTC", "ETH", "SOL", "XRP")


def features(probability, horizon, returns):
    p = min(.999, max(.001, probability))
    vals = [returns.get(asset) for asset in ASSETS]
    return [math.log(p / (1-p)), float(horizon == "1h")] + [
        0.0 if v is None else max(-.1, min(.1, v)) for v in vals
    ] + [float(v is None) for v in vals]


def candle_returns(candles, timestamp):
    result = {}
    for asset in ASSETS:
        rows = [r for r in candles.get(asset, []) if len(r) >= 6
                and int(r[0]) + 63 <= timestamp and value(r[4]) is not None]
        rows.sort(key=lambda r: r[0])
        if len(rows) >= 2 and int(rows[-1][0])-int(rows[-2][0]) == 60:
            a, b = value(rows[-2][4]), value(rows[-1][4])
            result[asset] = math.log(b/a) if a and b and a > 0 and b > 0 else None
    return result


def market_window(name):
    start = int(datetime.strptime(name[-16:], "%Y-%m-%d-%H%Mz").replace(tzinfo=timezone.utc).timestamp())
    return start, start + (3600 if "-1h-" in name else 900)


def chronological_split(rows):
    latest = max(r[0] for r in rows)
    days = {datetime.fromtimestamp(r[0], timezone.utc).strftime("%Y-%m-%d") for r in rows}
    if len(days) >= 2:
        at = datetime.fromtimestamp(latest, timezone.utc)
        cutoff = int(at.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        label = "latest UTC day"
    else:
        cutoff = latest // 3600 * 3600
        label = "latest UTC hour (early sample)"
    train = [r for r in rows if market_window(r[1])[1] <= cutoff]
    validation = [r for r in rows if market_window(r[1])[0] >= cutoff]
    return train, validation, cutoff, label


def examples():
    # Only observations collected prospectively by the live paper loop are training inputs.
    rows = {}
    state_path = ROOT / "data" / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    for path in sorted((ROOT / "data" / "observations").glob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                obs = json.loads(line)
                name = obs.get("slug")
                outcome = state.get("markets", {}).get(name, {}).get("outcome")
                if outcome not in ("Up", "Down"):
                    continue
                quote = obs["quotes"]["Up"]
                p = (float(quote["bid"])+float(quote["ask"]))/2
                at = int(obs["observed_at"])
                context = obs.get("features", {})
                returns = {asset: value(context.get(asset.lower()+"_r1")) for asset in ASSETS}
                horizon = "1h" if "-1h-" in name else "15m"
                rows[(name, at)] = (at, name, features(p, horizon, returns), int(outcome == "Up"), "live")
    return sorted(rows.values(), key=lambda x: (x[0], x[1]))


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


def fit(rows, epochs=25, rate=.08, regularization=.01):
    counts = Counter(r[1] for r in rows)
    weights = [1/counts[r[1]] for r in rows]
    total = sum(weights)
    nfeatures = len(rows[0][2])
    means = [sum(w*r[2][j] for r,w in zip(rows,weights))/total for j in range(nfeatures)]
    scales = [max(1e-6, math.sqrt(sum(w*(r[2][j]-means[j])**2 for r,w in zip(rows,weights))/total))
              for j in range(nfeatures)]
    beta = [0.0]*(nfeatures+1)
    for _ in range(epochs):
        grad = [0.0]*len(beta)
        for row, weight in zip(rows, weights):
            x = [(v-m)/s for v,m,s in zip(row[2],means,scales)]
            # Offset by the contemporaneous market probability.
            error = sigmoid(row[2][0] + beta[0] + sum(b*v for b,v in zip(beta[1:],x))) - row[3]
            grad[0] += weight*error
            for j,v in enumerate(x):
                grad[j+1] += weight*error*v
        beta[0] -= rate*grad[0]/total
        for j in range(1,len(beta)):
            beta[j] -= rate*(grad[j]/total + regularization*beta[j])
    return {"mean":means,"scale":scales,"weights":beta,"epochs":epochs}


def score(rows, model):
    counts = Counter(r[1] for r in rows)
    sums = [0.0, 0.0]
    total = 0.0
    for at,name,raw,y,source in rows:
        z = [(v-m)/s for v,m,s in zip(raw,model["mean"],model["scale"])]
        pred = sigmoid(raw[0]+model["weights"][0]+sum(b*v for b,v in zip(model["weights"][1:],z)))
        w = 1/counts[name]
        sums[0] += w*(pred-y)**2
        sums[1] += w*(sigmoid(raw[0])-y)**2
        total += w
    return {"brier":sums[0]/total,"market_brier":sums[1]/total,
            "markets":len(counts),"rows":len(rows)}


def main():
    rows = examples()
    days = sorted({datetime.fromtimestamp(r[0],timezone.utc).strftime("%Y-%m-%d") for r in rows})
    manifest = {"status":"waiting", "rows":len(rows), "markets":len({r[1] for r in rows}),
                "days":days, "updated_at":datetime.now(timezone.utc).isoformat(),
                "sources":dict(Counter(r[4] for r in rows)),
                "features":["market_logit","one_hour","btc_r1","eth_r1","sol_r1","xrp_r1",
                            "btc_missing","eth_missing","sol_missing","xrp_missing"]}
    if len(rows) >= 50:
        train, validation, cutoff, label = chronological_split(rows)
        if train and validation:
            trial = fit(train)
            manifest.update(status="trained", validation_window=label, validation_cutoff_utc=cutoff,
                            training_markets=len({r[1] for r in train}), validation=score(validation,trial),
                            final_fit="all available settled rows; validation included after scoring")
            write_json(OUTPUT / "model.json", fit(rows))
    if manifest["status"] != "trained":
        (OUTPUT / "model.json").unlink(missing_ok=True)
    write_json(OUTPUT / "status.json", manifest)
    print(json.dumps(manifest, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

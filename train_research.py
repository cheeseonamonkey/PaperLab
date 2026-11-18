"""Fit a market-relative model using one bootstrap plus settled live observations."""
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
    ] + [float(v is None) for v in vals] + [
        0.0 if returns.get("SP500") is None else max(-.1, min(.1, returns["SP500"])),
        float(returns.get("SP500") is None),
    ]


def known_value(context, available_at, name, observed_at, require_timestamp=False):
    result = value(context.get(name))
    if result is None:
        return None
    timestamp = available_at.get(name)
    if timestamp is None:
        return None if require_timestamp else result
    try:
        return result if int(timestamp) <= observed_at else None
    except (TypeError, ValueError):
        return None


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
    # Bootstrap and prospective observations share this directory; the separate archive is never scanned.
    rows = {}
    labels = {}
    for label_path in sorted((ROOT / "data" / "bootstrap" / "labels").glob("*.json")):
        labels.update(json.loads(label_path.read_text()))
    state_path = ROOT / "data" / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    for path in sorted((ROOT / "data" / "observations").glob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                obs = json.loads(line)
                name = obs.get("slug")
                source = obs.get("source", "live")
                outcome = labels.get(name) if source == "bootstrap" else state.get("markets", {}).get(name, {}).get("outcome")
                if outcome not in ("Up", "Down"):
                    continue
                at = int(obs["observed_at"])
                # A market outcome may label only observations made before that
                # market ended. Post-settlement snapshots are never examples.
                if at >= market_window(name)[1]:
                    continue
                if source in ("bootstrap", "historical_price_proxy"):
                    p = float(obs["display_up"])
                else:
                    quote = obs["quotes"]["Up"]
                    p = (float(quote["bid"])+float(quote["ask"]))/2
                context = obs.get("features", {})
                available_at = obs.get("feature_available_at", {})
                returns = {asset: known_value(context, available_at, asset.lower()+"_r1", at)
                           for asset in ASSETS}
                returns["SP500"] = known_value(context, available_at, "sp500_r1", at, True)
                horizon = "1h" if "-1h-" in name else "15m"
                if source != "bootstrap" or (name, at) not in rows:
                    rows[(name, at)] = (at, name, features(p, horizon, returns), int(outcome == "Up"), source)
    return sorted(rows.values(), key=lambda x: (x[0], x[1]))


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


def transform(raw, kind):
    result=list(raw)
    if kind=="market_only":
        result[2:] = [0.0] * (len(result)-2)
    if kind=="tanh_returns":
        for j in (*range(2,6), 10):
            result[j]=math.tanh(result[j]*1000)
    return result


def fit(rows, epochs=25, rate=.08, regularization=.01, kind="linear"):
    counts = Counter(r[1] for r in rows)
    weights = [1/counts[r[1]] for r in rows]
    total = sum(weights)
    inputs=[transform(r[2],kind) for r in rows]
    nfeatures = len(inputs[0])
    means = [sum(w*x[j] for x,w in zip(inputs,weights))/total for j in range(nfeatures)]
    scales = [max(1e-6, math.sqrt(sum(w*(x[j]-means[j])**2 for x,w in zip(inputs,weights))/total))
              for j in range(nfeatures)]
    beta = [0.0]*(nfeatures+1)
    for _ in range(epochs):
        grad = [0.0]*len(beta)
        for row, raw, weight in zip(rows, inputs, weights):
            x = [(v-m)/s for v,m,s in zip(raw,means,scales)]
            # Offset by the contemporaneous market probability.
            error = sigmoid(row[2][0] + beta[0] + sum(b*v for b,v in zip(beta[1:],x))) - row[3]
            grad[0] += weight*error
            for j,v in enumerate(x):
                grad[j+1] += weight*error*v
        beta[0] -= rate*grad[0]/total
        for j in range(1,len(beta)):
            beta[j] -= rate*(grad[j]/total + regularization*beta[j])
    return {"mean":means,"scale":scales,"weights":beta,"epochs":epochs,"transform":kind,"regularization":regularization}


def score(rows, model):
    counts = Counter(r[1] for r in rows)
    sums = [0.0, 0.0, 0.0, 0.0]
    total = 0.0
    for at,name,raw,y,source in rows:
        z = [(v-m)/s for v,m,s in zip(transform(raw,model.get("transform","linear")),model["mean"],model["scale"])]
        pred = sigmoid(raw[0]+model["weights"][0]+sum(b*v for b,v in zip(model["weights"][1:],z)))
        w = 1/counts[name]
        sums[0] += w*(pred-y)**2
        market = sigmoid(raw[0])
        sums[1] += w*(market-y)**2
        pred = min(1-1e-12, max(1e-12, pred))
        market = min(1-1e-12, max(1e-12, market))
        sums[2] -= w*(y*math.log(pred)+(1-y)*math.log1p(-pred))
        sums[3] -= w*(y*math.log(market)+(1-y)*math.log1p(-market))
        total += w
    return {"brier":sums[0]/total,"market_brier":sums[1]/total,
            "log_loss":sums[2]/total,"market_log_loss":sums[3]/total,
            "markets":len(counts),"rows":len(rows)}


def predict(observation, model):
    """Causal probability for a live US observation; reject stale/future models."""
    if observation.get("venue") != "polymarket_us":
        return None
    try:
        start = int(observation["start"])
        at = int(observation["observed_at"])
        trained_through = int(model["trained_through"])
    except (KeyError, TypeError, ValueError):
        return None
    if at < start or at >= int(observation.get("ends", 0)) or trained_through > start:
        return None
    quotes = observation.get("quotes", {}).get("Up", {})
    try:
        probability = (float(observation["display_up"])
                       if observation.get("source") == "historical_price_proxy"
                       else (float(quotes["bid"]) + float(quotes["ask"])) / 2)
    except (KeyError, TypeError, ValueError):
        return None
    if not 0 < probability < 1:
        return None
    context = observation.get("features", {})
    available_at = observation.get("feature_available_at", {})
    returns = {asset: known_value(context, available_at, asset.lower()+"_r1", at)
               for asset in ASSETS}
    returns["SP500"] = known_value(context, available_at, "sp500_r1", at, True)
    raw = features(probability, "1h" if "-1h-" in observation.get("slug", "") else "15m", returns)
    transformed = transform(raw, model.get("transform", "linear"))
    if len(transformed) != len(model.get("mean", [])) or len(transformed) != len(model.get("scale", [])):
        return None
    z = [(v-m)/s for v,m,s in zip(transformed, model["mean"], model["scale"])]
    if len(z) != len(model["weights"]) - 1:
        return None
    return sigmoid(raw[0] + model["weights"][0] + sum(b*v for b,v in zip(model["weights"][1:], z)))


def load_model(path=None):
    path = Path(path) if path is not None else OUTPUT / "model.json"
    return json.loads(path.read_text()) if path.exists() else None


def grouped_scores(rows, model):
    groups = {}
    for horizon in ("15m", "1h"):
        for source in ("bootstrap", "live", "historical_price_proxy"):
            subset = [r for r in rows if ("-1h-" in r[1]) == (horizon == "1h") and r[4] == source]
            if subset:
                groups[horizon + ":" + source] = score(subset, model)
    return groups


def main():
    rows = examples()
    days = sorted({datetime.fromtimestamp(r[0],timezone.utc).strftime("%Y-%m-%d") for r in rows})
    manifest = {"status":"waiting", "rows":len(rows), "markets":len({r[1] for r in rows}),
                "days":days, "updated_at":datetime.now(timezone.utc).isoformat(),
                "sources":dict(Counter(r[4] for r in rows)),
                "features":["market_logit","one_hour","btc_r1","eth_r1","sol_r1","xrp_r1",
                            "btc_missing","eth_missing","sol_missing","xrp_missing","sp500_r1","sp500_missing"]}
    if len(rows) >= 50:
        train, validation, cutoff, label = chronological_split(rows)
        if train and validation:
            experiments=[]
            for name,kind,penalty in (("linear","linear",.01),("market_only","market_only",.01),("regularized","linear",.10),
                                      ("tanh_returns","tanh_returns",.01)):
                trial=fit(train,regularization=penalty,kind=kind)
                experiments.append({"name":name,"transform":kind,"regularization":penalty,
                                    "validation":score(validation,trial),
                                    "validation_groups":grouped_scores(validation,trial)})
            manifest.update(status="trained", validation_window=label, validation_cutoff_utc=cutoff,
                            training_markets=len({r[1] for r in train}), validation=experiments[0]["validation"],
                            experiments=experiments,
                            final_fit="baseline refit on all available settled rows after validation; no automatic promotion")
            final_model = fit(rows)
            final_model.update(trained_through=max(market_window(r[1])[1] for r in rows),
                               training_markets=len({r[1] for r in rows}),
                               trained_at=datetime.now(timezone.utc).isoformat())
            write_json(OUTPUT / "model.json", final_model)
    if manifest["status"] != "trained":
        (OUTPUT / "model.json").unlink(missing_ok=True)
    write_json(OUTPUT / "status.json", manifest)
    run_id = __import__("os").environ.get("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(OUTPUT / "runs" / (run_id + ".json"), manifest)
    page = ROOT / "docs" / "research" / "latest.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Research experiments", "", "Status: **%s**. Markets: %d. Rows: %d." %
             (manifest["status"],manifest["markets"],manifest["rows"]), "",
             "Archive backfill is excluded. Bootstrap and live sources: %s." % manifest["sources"], "",
             "Candidates are evaluated chronologically and are not automatically promoted.", ""]
    if manifest.get("experiments"):
        lines += ["| Candidate | Brier | Market Brier | Validation markets |",
                  "|---|---:|---:|---:|"]
        for experiment in manifest["experiments"]:
            v=experiment["validation"]
            lines.append("| %s | %.4f | %.4f | %d |" %
                         (experiment["name"],v["brier"],v["market_brier"],v["markets"]))
    if manifest.get("experiments"):
        lines += ["", "## Baseline by horizon and source", "",
                  "| Horizon / source | Markets | Brier | Market Brier | Log loss | Market log loss |",
                  "|---|---:|---:|---:|---:|---:|"]
        for name, v in manifest["experiments"][0]["validation_groups"].items():
            lines.append("| %s | %d | %.4f | %.4f | %.4f | %.4f |" %
                         (name, v["markets"], v["brier"], v["market_brier"], v["log_loss"], v["market_log_loss"]))
        lines += ["", "Validation is repeatedly reused; small groups are descriptive and do not establish an edge."]
    page.write_text("\n".join(lines)+"\n")
    print(json.dumps(manifest, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

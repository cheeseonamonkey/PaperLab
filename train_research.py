"""Fit a market-relative model using one bootstrap plus settled live observations."""
from __future__ import annotations

import gzip
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import backfill
from backfill import write_json
from feeds import value

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "training"
ASSETS = ("BTC", "ETH", "SOL", "XRP")


def _clip(value, bound):
    return 0.0 if value is None else max(-bound, min(bound, value))


def features(probability, horizon, returns):
    """Feature vector v2 (20 slots). Layout: market logit, horizon flag,
    1-minute returns + missing flags, then the extended inputs (5-minute
    returns, BTC 15-minute return and volatility, time left, strike
    distance), and the SP500 pair last. One builder serves training and
    forward prediction, so the two can never drift apart."""
    p = min(.999, max(.001, probability))
    vals = [returns.get(asset) for asset in ASSETS]
    return [math.log(p / (1-p)), float(horizon == "1h")] + [
        0.0 if v is None else max(-.1, min(.1, v)) for v in vals
    ] + [float(v is None) for v in vals] + [
        _clip(returns.get(asset + "_R5"), .2) for asset in ASSETS
    ] + [
        _clip(returns.get("BTC_R15"), .2),
        _clip(returns.get("BTC_VOL15"), .05),
        0.0 if returns.get("TIME_LEFT") is None else max(0.0, min(1.0, returns["TIME_LEFT"])),
        _clip(returns.get("STRIKE_DISTANCE"), .01),
        0.0 if returns.get("SP500") is None else max(-.1, min(.1, returns["SP500"])),
        float(returns.get("SP500") is None),
    ]


FEATURE_NAMES = ["market_logit", "one_hour", "btc_r1", "eth_r1", "sol_r1", "xrp_r1",
                 "btc_missing", "eth_missing", "sol_missing", "xrp_missing",
                 "btc_r5", "eth_r5", "sol_r5", "xrp_r5", "btc_r15", "btc_vol15",
                 "time_left", "strike_distance", "sp500_r1", "sp500_missing"]


def feature_values(context, available_at, at):
    """Pull every model input from an observation's causal feature map."""
    values = {asset: known_value(context, available_at, asset.lower()+"_r1", at)
              for asset in ASSETS}
    for asset in ASSETS:
        values[asset + "_R5"] = known_value(context, available_at, asset.lower()+"_r5", at)
    values["BTC_R15"] = known_value(context, available_at, "btc_r15", at)
    values["BTC_VOL15"] = known_value(context, available_at, "btc_vol15", at)
    values["TIME_LEFT"] = known_value(context, available_at, "time_left", at)
    values["STRIKE_DISTANCE"] = known_value(context, available_at, "strike_distance", at)
    values["SP500"] = known_value(context, available_at, "sp500_r1", at, True)
    return values


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
    # Bootstrap and prospective observations share this directory; the backfill
    # archive joins below as its own labeled source (see archive_examples).
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
                returns = feature_values(context, available_at, at)
                horizon = "1h" if "-1h-" in name else "15m"
                if source != "bootstrap" or (name, at) not in rows:
                    rows[(name, at)] = (at, name, features(p, horizon, returns), int(outcome == "Up"), source)
    rows.update(archive_examples(rows))
    return sorted(rows.values(), key=lambda x: (x[0], x[1]))


DEEP = os.environ.get("PAPERLAB_DEEP") == "1"
ARCHIVE_STRIDE = 2 if DEEP else 5  # every Nth display point per archived market


def archive_examples(existing):
    """Labeled rows from the downloaded backfill archive (owner-approved
    2026-11-28: back-train on everything we have). Settlements embedded in
    each archived contract are the labels; the archive stores no BRTI
    reference series, so strike/vol inputs are missing for these rows and
    the model treats them through the same missing-value path as live data.
    Existing live/bootstrap rows win on (slug, timestamp) overlap."""
    rows = {}
    base = ROOT / "data" / "backfill" / "hours"
    if not base.exists():
        return rows
    for path in sorted(base.glob("*/*.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                hour = json.load(stream)
        except (OSError, ValueError, EOFError):
            continue  # A corrupt hour is skipped, never fatal to training.
        labels = {}
        for contract in hour.get("markets", []):
            settled = (contract.get("settlement") or {}).get("settlement")
            if settled in (0, 1):
                labels[contract["slug"]] = "Up" if settled == 1 else "Down"
        if not labels:
            continue
        per_market = {}
        for obs in backfill.observations(hour, []):
            per_market.setdefault(obs["slug"], []).append(obs)
        for slug, group in per_market.items():
            if slug not in labels:
                continue
            for obs in group[::ARCHIVE_STRIDE]:
                at = int(obs["observed_at"])
                if at >= market_window(slug)[1] or (slug, at) in existing or (slug, at) in rows:
                    continue
                returns = feature_values(obs.get("features", {}),
                                         obs.get("feature_available_at", {}), at)
                horizon = "1h" if "-1h-" in slug else "15m"
                rows[(slug, at)] = (at, slug, features(float(obs["display_up"]), horizon, returns),
                                    int(labels[slug] == "Up"), "archive")
    return rows


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


RETURN_SLOTS = (2, 3, 4, 5)  # btc/eth/sol/xrp 1-minute returns in features()


def expansion(raw, kind):
    """Extra feature-architecture terms appended by candidate transforms.

    Every expansion is a deterministic function of the causal raw features,
    so the same code path serves fit, score and forward predict.
    """
    if kind == "interactions":
        return [raw[0]*raw[j] for j in RETURN_SLOTS] + [raw[1]*raw[j] for j in RETURN_SLOTS]
    if kind == "horizon_split":
        return [raw[j]*raw[1] for j in RETURN_SLOTS] + [raw[j]*(1-raw[1]) for j in RETURN_SLOTS]
    if kind == "squares":
        return [raw[j]*raw[j]*100 for j in RETURN_SLOTS]
    return []


def transform(raw, kind):
    result=list(raw)
    if kind=="market_only":
        result[2:] = [0.0] * (len(result)-2)
    if kind=="tanh_returns":
        for j in (*range(2,6), 10):
            result[j]=math.tanh(result[j]*1000)
    return result + expansion(result, kind)


# Candidate sweep: (name, transform, regularization, epochs). The first entry
# is the frozen baseline that research_linear refits; the rest are a
# systematic grid over feature architectures, regularization and fit length,
# all evaluated on the identical chronological split. The weekly deep pass
# (PAPERLAB_DEEP=1) fits longer.
def build_candidates():
    epochs = (75, 150) if DEEP else (25, 75)
    grid = [("linear", "linear", .01, 25), ("market_only", "market_only", .01, 25)]
    for kind in ("linear", "tanh_returns", "interactions", "horizon_split", "squares"):
        for penalty in (.01, .10):
            for length in epochs:
                grid.append(("%s_p%d_e%d" % (kind, int(penalty*100), length), kind, penalty, length))
    return tuple(grid)


CANDIDATES = build_candidates()

# Auto-fork policy (owner-approved 2026-11-28): a non-baseline candidate that
# keeps winning chronologically earns its own isolated $100 paper account.
# Predeclared bars, so a fork is never one lucky validation window.
FORK_BASE_ACCOUNTS = 13
FORK_MAX_FORKS = 40
FORK_MAX_ACCOUNTS = 50
FORK_MIN_VALIDATION_MARKETS = 5
FORK_MARGIN = 0.003        # Brier improvement required over the market itself
FORK_STREAK = 3            # consecutive trained runs the same candidate must win
FORK_ELIGIBLE_EXCLUDES = ("linear", "market_only")


def evaluate_fork(experiments, fork_state, fork_count):
    """Pure fork decision. Returns (new_fork_state, winning_experiment_or_None).

    A candidate qualifies when, on the chronological validation split, it
    beats the market Brier by FORK_MARGIN, beats the linear baseline, and
    covers at least FORK_MIN_VALIDATION_MARKETS markets. The same candidate
    must qualify FORK_STREAK runs in a row, must not already have a fork,
    and the roster caps (FORK_MAX_FORKS / FORK_MAX_ACCOUNTS) must allow it.
    """
    state = {"candidate": fork_state.get("candidate"), "streak": int(fork_state.get("streak", 0)),
             "forked": list(fork_state.get("forked", []))}
    if not experiments:
        return state, None
    baseline = experiments[0]["validation"]["brier"]
    qualifying = [e for e in experiments
                  if e["name"] not in FORK_ELIGIBLE_EXCLUDES
                  and e["validation"]["markets"] >= FORK_MIN_VALIDATION_MARKETS
                  and e["validation"]["brier"] <= e["validation"]["market_brier"] - FORK_MARGIN
                  and e["validation"]["brier"] < baseline]
    if not qualifying:
        state.update(candidate=None, streak=0)
        return state, None
    best = min(qualifying, key=lambda e: e["validation"]["brier"])
    if state["candidate"] == best["name"]:
        state["streak"] += 1
    else:
        state.update(candidate=best["name"], streak=1)
    if state["streak"] < FORK_STREAK or best["name"] in state["forked"]:
        return state, None
    if fork_count >= FORK_MAX_FORKS or FORK_BASE_ACCOUNTS + fork_count >= FORK_MAX_ACCOUNTS:
        return state, None
    state["forked"].append(best["name"])
    state.update(candidate=None, streak=0)
    return state, best


def roster_path():
    return ROOT / "strategies" / "roster.json"


def load_roster():
    path = roster_path()
    if not path.exists():
        return {"forks": []}
    data = json.loads(path.read_text())
    return {"forks": [e for e in data.get("forks", []) if isinstance(e, dict) and e.get("name")]}


def load_fork_models():
    """Frozen per-fork models, keyed by paper account name."""
    models = {}
    for entry in load_roster()["forks"]:
        if entry.get("status", "active") != "active":
            continue
        model = load_model(ROOT / entry.get("model", ""))
        if model is not None:
            models[entry["name"]] = model
    return models


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
    returns = feature_values(context, available_at, at)
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


def apply_fork(rows, experiments):
    """Run one fork-policy step; on a win, freeze the candidate as a new account.

    The fork gets a frozen refit on all settled rows, a roster entry, and —
    from the next scheduled run — its own isolated $100 paper account with
    identical risk controls (paper.load initializes missing roster accounts).
    Fork history is never deleted; the caps are a hard stop, not a rotation.
    """
    roster = load_roster()
    forks = [e for e in roster["forks"] if e.get("status", "active") == "active"]
    state_path = OUTPUT / "fork_state.json"
    fork_state = json.loads(state_path.read_text()) if state_path.exists() else {}
    # A retired fork's candidate may earn a fork again: the already-forked
    # list tracks only candidates with a currently active fork.
    active_candidates = {e["candidate"] for e in forks}
    fork_state["forked"] = [c for c in fork_state.get("forked", []) if c in active_candidates]
    fork_state, winner = evaluate_fork(experiments, fork_state, len(forks))
    write_json(state_path, fork_state)
    if winner is None:
        return {"status": "no_fork", "streak_candidate": fork_state.get("candidate"),
                "streak": fork_state.get("streak", 0), "forks": len(forks)}
    name = "fork_%s_%02d" % (winner["name"], len(forks) + 1)
    model = fit(rows, epochs=winner.get("epochs", 25),
                regularization=winner["regularization"], kind=winner["transform"])
    model.update(trained_through=max(market_window(r[1])[1] for r in rows),
                 training_markets=len({r[1] for r in rows}),
                 trained_at=datetime.now(timezone.utc).isoformat(),
                 fork_candidate=winner["name"], fork_validation=winner["validation"])
    relative = "data/training/forks/%s.json" % name
    write_json(ROOT / relative, model)
    roster["forks"].append({"name": name, "candidate": winner["name"],
                            "transform": winner["transform"], "regularization": winner["regularization"],
                            "parent": "research_linear", "model": relative, "status": "active",
                            "created_at": datetime.now(timezone.utc).isoformat()})
    write_json(roster_path(), roster)
    return {"status": "forked", "account": name, "candidate": winner["name"],
            "validation": winner["validation"], "forks": len(roster["forks"])}


def grouped_scores(rows, model):
    groups = {}
    for horizon in ("15m", "1h"):
        for source in ("bootstrap", "live", "historical_price_proxy", "archive"):
            subset = [r for r in rows if ("-1h-" in r[1]) == (horizon == "1h") and r[4] == source]
            if subset:
                groups[horizon + ":" + source] = score(subset, model)
    return groups


WINDOW_DAYS = 45  # Rolling training window: stale-regime rows age out (periodic reset).


def retire_losing_forks():
    """Periodic reset for fork accounts: an old, well-sampled, losing fork is
    retired to hold-only. Its history stays in state and in the roster; only
    its trading stops, and its roster slot frees up for a future fork."""
    roster = load_roster()
    state_path = ROOT / "data" / "state.json"
    if not state_path.exists():
        return []
    accounts = json.loads(state_path.read_text()).get("accounts", {})
    now = datetime.now(timezone.utc)
    retired = []
    for entry in roster["forks"]:
        if entry.get("status", "active") != "active":
            continue
        account = accounts.get(entry["name"])
        if not account or not entry.get("created_at"):
            continue
        try:
            age_days = (now - datetime.fromisoformat(entry["created_at"])).days
        except ValueError:
            continue
        settled = [t for t in account.get("trades", []) if t.get("status") == "settled"]
        pnl = sum(t.get("pnl", 0) for t in settled)
        if age_days >= 21 and len(settled) >= 20 and pnl <= -15.0:
            entry.update(status="retired", retired_at=now.isoformat(),
                         retire_reason="age %dd, %d settled, realized P&L $%.2f" % (age_days, len(settled), pnl))
            retired.append(entry["name"])
    if retired:
        write_json(roster_path(), roster)
    return retired


def main():
    retired = retire_losing_forks()
    all_rows = examples()
    rows = all_rows
    if all_rows:
        window_start = max(r[0] for r in all_rows) - WINDOW_DAYS * 86400
        windowed = [r for r in all_rows if r[0] >= window_start]
        if len(windowed) >= 50:
            rows = windowed
    days = sorted({datetime.fromtimestamp(r[0],timezone.utc).strftime("%Y-%m-%d") for r in rows})
    manifest = {"status":"waiting", "rows":len(rows), "rows_before_window":len(all_rows),
                "window_days":WINDOW_DAYS, "deep":DEEP, "retired_forks":retired,
                "markets":len({r[1] for r in rows}),
                "days":days, "updated_at":datetime.now(timezone.utc).isoformat(),
                "sources":dict(Counter(r[4] for r in rows)),
                "features":FEATURE_NAMES}
    if len(rows) >= 50:
        train, validation, cutoff, label = chronological_split(rows)
        if train and validation:
            experiments=[]
            for name,kind,penalty,length in CANDIDATES:
                trial=fit(train,epochs=length,regularization=penalty,kind=kind)
                experiments.append({"name":name,"transform":kind,"regularization":penalty,"epochs":length,
                                    "validation":score(validation,trial),
                                    "validation_groups":grouped_scores(validation,trial)})
            manifest.update(status="trained", validation_window=label, validation_cutoff_utc=cutoff,
                            training_markets=len({r[1] for r in train}), validation=experiments[0]["validation"],
                            experiments=experiments,
                            final_fit="baseline refit on all available settled rows after validation; "
                                      "non-baseline candidates may auto-fork under the predeclared fork policy")
            final_model = fit(rows)
            final_model.update(trained_through=max(market_window(r[1])[1] for r in rows),
                               training_markets=len({r[1] for r in rows}),
                               trained_at=datetime.now(timezone.utc).isoformat())
            write_json(OUTPUT / "model.json", final_model)
            manifest["fork"] = apply_fork(rows, experiments)
    if manifest["status"] != "trained":
        (OUTPUT / "model.json").unlink(missing_ok=True)
    write_json(OUTPUT / "status.json", manifest)
    run_id = os.environ.get("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(OUTPUT / "runs" / (run_id + ".json"), manifest)
    page = ROOT / "docs" / "research" / "latest.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Research experiments", "", "Status: **%s**. Markets: %d. Rows: %d." %
             (manifest["status"],manifest["markets"],manifest["rows"]), "",
             "Training sources (archive backfill included as its own labeled source, "
             "45-day rolling window): %s." % manifest["sources"], "",
             "Candidates are evaluated chronologically. The baseline is never auto-promoted; a non-baseline "
             "candidate that clears the predeclared fork policy (margin, sample, 3-run streak, roster caps) "
             "spawns a frozen fork paper account — see the fork status in data/training/status.json.", ""]
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

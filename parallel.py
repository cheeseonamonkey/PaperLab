"""Collect one historical hour, replay isolated accounts, then merge."""
import argparse
import copy
import gzip
import hashlib
import json
import time
from pathlib import Path

import backfill
import paper
from feeds import get, settlement
from train_research import load_model, predict

BATCH = Path("batch")
SHARDS = (
    ("stacked_rnn", "skip_gru_2"), ("depthwise_tcn", "lstm"),
    ("conv_gru", "market_implied"), ("brti_distance", "brti_distance_limit"),
    ("btc_momentum", "btc_reversion"), ("cross_asset_momentum", "book_imbalance", "research_linear"),
)


def write(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(item, sort_keys=True))
    tmp.replace(path)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect():
    """Fetch the previous closed UTC hour once; no live polling."""
    BATCH.mkdir(exist_ok=True)
    state = paper.load()
    write(BATCH / "base.json", state)
    start, end = backfill.latest_closed_hour()
    already_processed = end <= state.get("last_processed_hour_end", 0)
    observations, hour = [], None
    if not already_processed:
        path, missing, total = backfill.collect_hour(start, end, require_settlement=False)
        with gzip.open(path, "rt", encoding="utf-8") as source:
            hour = json.load(source)
        try:
            reference = get("/v1/asset-prices/history", {
                "assets": "crypto:btc", "from": start-140*60, "to": end-60,
                "bucket": "ASSET_PRICE_BUCKET_1M",
            }).get("series", [])
            if len(reference) != 1:
                raise ValueError("Expected one official BTC reference series")
            candles = reference[0].get("candles", [])
        except (OSError, ValueError) as error:
            print("Official BRTI reference unavailable:", error, flush=True)
            candles = []
        observations = backfill.observations(hour, candles)
        if not observations:
            raise ValueError("Closed hour has no usable historical price observations")
        observations = [row for row in observations
                        if row["observed_at"] > (state.get("last_run") or 0)]
        for row in observations:
            paper.append_observation(row)
        batch = {"source": "historical_price_proxy", "start": start, "end": end,
                 "observations": len(observations), "markets": total-missing,
                 "missing_markets": missing}
    else:
        batch = state.get("last_batch")
    outcomes = {}
    for slug, market in state["markets"].items():
        if market["outcome"] is None and market["ends"]+30 <= time.time():
            try:
                outcomes[slug] = settlement(slug)
            except (OSError, ValueError) as error:
                print("Settlement check failed:", slug, error, flush=True)
                outcomes[slug] = None
    if hour is not None:
        for contract in hour["markets"]:
            source = contract.get("settlement") or {}
            if source.get("settlement") in (0, 1):
                outcomes[contract["slug"]] = "Up" if source["settlement"] == 1 else "Down"
    with gzip.open(BATCH / "events.jsonl.gz", "wt", encoding="utf-8") as events:
        for row in observations:
            events.write(json.dumps({"kind":"observation","observation":row}) + "\n")
        events.write(json.dumps({"kind":"reconcile","at":int(time.time()),
                                 "outcomes":outcomes}) + "\n")
    write(BATCH / "collection.json", {
        "polling":state["polling"],
        "last_run":max(state.get("last_run") or 0,
                       max((row["observed_at"] for row in observations), default=0)),
        "hour_end":end if not already_processed else state.get("last_processed_hour_end",0),
        "batch":batch,
        "base_hash":digest(BATCH / "base.json"),
        "events_hash":digest(BATCH / "events.jsonl.gz"),
    })
    print("Historical hour", start, end, "observations", len(observations),
          "already processed", already_processed, flush=True)


def replay_events(state, events, names, candidate):
    """Replay the canonical ordered event stream for the selected accounts."""
    for event in events:
        if event["kind"] == "reconcile":
            original = paper.settlement
            paper.settlement = lambda slug: event["outcomes"].get(slug)
            try:
                paper.reconcile(state, event["at"])
            finally:
                paper.settlement = original
        elif event["kind"] == "observation":
            obs = event["observation"]
            probabilities = {"research_linear":predict(obs, candidate)} if candidate else {}
            paper.process_snapshot(state, obs, probabilities, names=names)
        else:
            raise ValueError("Unknown event")


def shard(index):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(SHARDS):
        raise ValueError("Invalid shard")
    state = read(BATCH / "base.json")
    candidate = load_model()
    manifest = read(BATCH / "collection.json")
    if manifest["base_hash"] != digest(BATCH / "base.json") or manifest["events_hash"] != digest(BATCH / "events.jsonl.gz"):
        raise ValueError("Batch checksum mismatch")
    with gzip.open(BATCH / "events.jsonl.gz", "rt") as stream:
        replay_events(state, (json.loads(line) for line in stream), SHARDS[index], candidate)
    write(Path("shard-results") / (str(index) + ".json"),
          {"index":index,"names":list(SHARDS[index]),"manifest":manifest,"state":state})


def merge():
    manifest = read(BATCH / "collection.json")
    if manifest["base_hash"] != digest(BATCH / "base.json") or manifest["events_hash"] != digest(BATCH / "events.jsonl.gz"):
        raise ValueError("Batch checksum mismatch")
    results = [read(Path("shard-results") / (str(i)+".json")) for i in range(len(SHARDS))]
    base = read(BATCH / "base.json")
    if set(base["accounts"]) != {n for group in SHARDS for n in group}:
        raise ValueError("Shard roster differs from state")
    state = copy.deepcopy(results[0]["state"])
    for i, result in enumerate(results):
        if result["index"] != i or result["names"] != list(SHARDS[i]) or result["manifest"] != manifest:
            raise ValueError("Shard identity or batch mismatch")
        shard_state = result["state"]
        owned = set(SHARDS[i])
        for slug, market in shard_state["markets"].items():
            previous = base["markets"].get(slug, {}).get("forecasts", [])
            for forecast in market.get("forecasts", []):
                if set(forecast.get("probabilities", {})) - owned and forecast not in previous:
                    raise ValueError("Shard forecast contains a foreign strategy")
        if set(shard_state["markets"]) != set(state["markets"]):
            raise ValueError("Shard market mismatch")
        for slug, market in state["markets"].items():
            other = shard_state["markets"][slug]
            if {k:v for k,v in market.items() if k != "forecasts"} != {k:v for k,v in other.items() if k != "forecasts"}:
                raise ValueError("Shard settlement mismatch")
            forecasts, theirs = market.get("forecasts", []), other.get("forecasts", [])
            if len(forecasts) != len(theirs):
                raise ValueError("Forecast count mismatch")
            for left,right in zip(forecasts,theirs):
                if (left["at"],left["market"]) != (right["at"],right["market"]):
                    raise ValueError("Forecast alignment mismatch")
                left["probabilities"].update(right["probabilities"])
        for name in SHARDS[i]:
            state["accounts"][name] = shard_state["accounts"][name]
            state["forecast_metrics"][name] = shard_state["forecast_metrics"][name]
    state["polling"] = manifest["polling"]
    state["last_run"] = manifest["last_run"]
    if manifest.get("hour_end"):
        state["last_processed_hour_end"] = manifest["hour_end"]
    if manifest.get("batch") is not None:
        state["last_batch"] = manifest["batch"]
    paper.save(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect","shard","merge"))
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    if args.command == "collect":
        collect()
    elif args.command == "shard":
        shard(args.index)
    else:
        merge()

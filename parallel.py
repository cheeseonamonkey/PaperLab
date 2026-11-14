"""Record one shared live batch, replay isolated accounts, then merge."""
import argparse
import copy
import gzip
import hashlib
import json
import time
from pathlib import Path

import paper
from feeds import USFeed
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


def collect(duration):
    BATCH.mkdir(exist_ok=True)
    state = paper.load()
    write(BATCH / "base.json", state)
    collector = copy.deepcopy(state)
    feeds = [USFeed("15m"), USFeed("1h")]
    deadline = time.monotonic() + duration
    with gzip.open(BATCH / "events.jsonl.gz", "wt") as events:
        while True:
            started = time.monotonic()
            for feed in feeds:
                now = int(time.time())
                polling = collector["polling"]
                polling["attempts"] += 1
                polling["last_attempt"] = now
                outcomes = {}
                original = paper.settlement
                def record(slug):
                    try:
                        result = original(slug)
                    except Exception as exc:
                        print('Settlement check failed:', slug, str(exc), flush=True)
                        result = None
                    outcomes[slug] = result
                    return result
                paper.settlement = record
                try:
                    paper.reconcile(collector, now)
                    events.write(json.dumps({"kind":"reconcile","at":now,"outcomes":outcomes}) + "\n")
                    obs = feed.observe(now)
                    if time.time() - obs["observed_at"] > 12:
                        raise ValueError("Stale observation")
                    collector["markets"].setdefault(obs["slug"], {"ends":obs["ends"],"outcome":None,"checked_at":0})
                    events.write(json.dumps({"kind":"observation","observation":obs}) + "\n")
                    paper.append_observation(obs)
                    collector["last_run"] = obs["observed_at"]
                    polling["observed"] += 1
                    polling["last_error"] = None
                except Exception as exc:
                    polling["skipped"] += 1
                    polling["last_error"] = type(exc).__name__ + ": " + str(exc)[:160]
                    print("Collection error:", polling["last_error"], flush=True)
                finally:
                    paper.settlement = original
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, max(0,15-(time.monotonic()-started))))
    write(BATCH / "collection.json", {"polling":collector["polling"],"last_run":collector["last_run"],
                                      "base_hash":digest(BATCH / "base.json"),
                                      "events_hash":digest(BATCH / "events.jsonl.gz")})


def shard(index):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(SHARDS):
        raise ValueError("Invalid shard")
    state = read(BATCH / "base.json")
    candidate = load_model()
    manifest = read(BATCH / "collection.json")
    if manifest["base_hash"] != digest(BATCH / "base.json") or manifest["events_hash"] != digest(BATCH / "events.jsonl.gz"):
        raise ValueError("Batch checksum mismatch")
    with gzip.open(BATCH / "events.jsonl.gz", "rt") as stream:
        for line in stream:
            event = json.loads(line)
            if event["kind"] == "reconcile":
                original = paper.settlement
                paper.settlement = lambda slug: event["outcomes"].get(slug)
                try:
                    paper.reconcile(state, event["at"])
                finally:
                    paper.settlement = original
            elif event["kind"] == "observation":
                obs = event["observation"]
                probabilities = {"research_linear":predict(obs,candidate)} if candidate else {}
                paper.process_snapshot(state,obs,probabilities,names=SHARDS[index])
            else:
                raise ValueError("Unknown event")
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
    paper.save(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect","shard","merge"))
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    if args.command == "collect":
        if not 60 <= args.duration <= 3600:
            raise ValueError("Duration must be 60 to 3600 seconds")
        collect(args.duration)
    elif args.command == "shard":
        shard(args.index)
    else:
        merge()

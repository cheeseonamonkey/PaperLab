"""40-model one-epoch US probability-correction screening, on dated market history.

Historical display prices are probability inputs, NOT executable quotes.
All training uses prior calendar dates; development ranks candidates; the later
day is evaluated exactly once after candidate rankings are frozen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from market_us.collector import DB
from market_us.models import FEATURES, HISTORY, CONTEXT, parameters
from market_us.models_experimental import ALL_40, match_budget_40
from market_us.train_sweep import query, build, split, standardize, metrics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/results/us-40-200k-oneepoch"
LOG = logging.getLogger("yeno.us.sweep40")

# Deliberate group ablations: zeroing standardized features is an OOD
# perturbation, so importance is descriptive rather than causal.
GROUPS = {
    "market_price_and_momentum": {"x": [12, 13, 14, 15], "c": [5, 6]},
    "btc_short_horizon": {"x": [0, 1, 6, 7], "c": []},
    "btc_long_horizon": {"x": [2, 3, 4, 5, 9], "c": [4, 7, 8]},
    "market_horizon_and_phase": {"x": [10, 11, 19], "c": [0, 1, 2, 3]},
    "time_of_day": {"x": [20, 21], "c": [9, 10]},
    "observation_and_gap_masks": {"x": [16, 17, 18, 22, 23], "c": [11]},
}


FEATURE_NAMES = (
    "btc_return_1m", "btc_return_5m", "btc_return_15m", "btc_return_60m",
    "btc_volatility_15m", "btc_volatility_60m", "btc_candle_range",
    "btc_tick_density", "unused_log_btc", "btc_delta_from_market_open",
    "time_remaining", "time_elapsed", "up_display", "down_display",
    "up_price_momentum", "display_overround", "has_market_display",
    "has_btc_reference", "market_active", "hourly_market",
    "time_of_day_sin", "time_of_day_cos", "missing_volume", "sample_gap",
)
CONTEXT_NAMES = (
    "is_15m", "is_hourly", "time_remaining", "time_elapsed",
    "btc_delta_from_market_open", "up_display", "down_display",
    "btc_volatility_15m", "btc_volatility_60m", "time_of_day_sin",
    "time_of_day_cos", "has_market_display",
)


class MarketCorrection(nn.Module):
    def __init__(self, kind: str, width: int, dropout: float, target_params=200_000):
        super().__init__()
        self.kind = kind
        self.core, self.drop = match_budget_40(kind, target_params)[0], dropout
        # Preserve the exact width audited by the parameter matcher.
        if self.core.width != width:
            raise ValueError("Inconsistent audited width")
        self.core.head.add_module("dropout", nn.Dropout(dropout))
        # Baseline-identical initial predictions; avoid initially destroying
        # an already strong, interpretable market-implied probability.
        nn.init.zeros_(self.core.binary.weight)
        nn.init.zeros_(self.core.binary.bias)

    def forward(self, x, c, p, head):
        if self.training and self.drop:
            # Channel dropout shared through time; preserve masks/gap.
            numeric = F.dropout1d(x[:, :, :16].transpose(1, 2),
                                  p=self.drop, training=True).transpose(1, 2)
            x = torch.cat((numeric, x[:, :, 16:]), -1)
            c = torch.cat((c[:, :2], F.dropout(c[:, 2:11], p=self.drop,
                                                 training=True), c[:, 11:]), -1)
        out = self.core(x, c)
        delta = out["binary_logits"].gather(1, head[:, None]).squeeze(1)
        anchor = torch.logit(p.clamp(1e-4, 1 - 1e-4))
        return anchor + delta, delta, out["next_features"]


def sample_tensors(data):
    return {k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in data.items()
            if k in ("x", "c", "next", "y", "h", "display")}


def evaluate(model, tensors, idx, batch_size=512, masked=None, single=None):
    model.eval()
    preds = []
    with torch.inference_mode():
        for start in range(0, len(idx), batch_size):
            ids = torch.as_tensor(idx[start:start + batch_size], dtype=torch.long)
            x, c = tensors["x"][ids], tensors["c"][ids]
            if masked is not None or single is not None:
                x, c = x.clone(), c.clone()
                if masked is not None:
                    x[:, :, GROUPS[masked]["x"]] = 0
                    if GROUPS[masked]["c"]:
                        c[:, GROUPS[masked]["c"]] = 0
                if single is not None:
                    family, col = single
                    if family == "x":
                        x[:, :, col] = 0
                    else:
                        c[:, col] = 0
                # A continuous-time gate interprets the gap channel as
                # physical time; never replace its constant 1 with 0.
                x[:, :, -1] = 1
            logits, _, _ = model(x, c, tensors["display"][ids], tensors["h"][ids])
            preds.append(torch.sigmoid(logits).cpu().numpy())
    pred = np.concatenate(preds)
    return metrics(pred, tensors["y"][idx].numpy(), tensors["h"][idx].numpy())


def weights_by_market(data, train):
    # Adjacent samples share the same outcome; independent unit = market.
    ids, counts = np.unique(data["slugs"][train], return_counts=True)
    factors = dict(zip(ids, counts))
    weight = np.zeros(len(data["y"]), dtype="float32")
    weight[train] = np.array([1.0 / factors[s] for s in data["slugs"][train]],
                             dtype="float32")
    weight[train] /= weight[train].mean()
    return torch.from_numpy(weight)


def train_one(kind, config, tensors, train, dev, weights):
    torch.manual_seed(config.seed)
    model, audit = match_budget_40(kind, config.target_params)
    model = MarketCorrection(kind, audit["width"], config.dropout, config.target_params)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.lr,
                                  weight_decay=config.weight_decay)
    rng = torch.Generator().manual_seed(config.seed)
    shuffled = torch.as_tensor(train, dtype=torch.long)[
        torch.randperm(len(train), generator=rng)]
    model.train()
    total, count, begun = 0., 0, time.monotonic()
    for ids in shuffled.split(config.batch_size):
        optimizer.zero_grad(set_to_none=True)
        logits, delta, aux = model(tensors["x"][ids], tensors["c"][ids],
                                   tensors["display"][ids], tensors["h"][ids])
        bce = F.binary_cross_entropy_with_logits(
            logits, tensors["y"][ids], reduction="none")
        loss = (bce * weights[ids]).mean()
        loss = loss + config.correction_penalty * (delta.square() * weights[ids]).mean()
        # Same weak auxiliary objective for all architectures.
        ix = [0, 1, 4, 6, 9, 12, 14]
        loss = loss + config.aux_weight * F.smooth_l1_loss(
            aux[:, ix], tensors["next"][ids][:, ix])
        if not torch.isfinite(loss):
            raise RuntimeError(f"Nonfinite loss in {kind}")
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total += loss.item() * len(ids)
        count += len(ids)
    dev_result = evaluate(model, tensors, dev)
    # FP16 checkpoint serialization only. Computation/training remain FP32:
    # CPU half-precision kernels are not assumed to be faster.
    weights16 = {k: v.detach().cpu().half() if torch.is_floating_point(v)
                 else v.detach().cpu() for k, v in model.state_dict().items()}
    return model, audit | {
        "dropout": config.dropout,
        "epoch_count": 1,
        "train_loss": total / count,
        "dev": dev_result,
        "seconds": round(time.monotonic() - begun, 2),
        "checkpoint": kind + ".pt",
    }, weights16


def write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str) + "\n")
    tmp.replace(path)


def importance(model, tensors, idx):
    base = evaluate(model, tensors, idx)["overall"]["logloss"]
    return {name: round(evaluate(model, tensors, idx, masked=name)
                        ["overall"]["logloss"] - base, 7) for name in GROUPS}


def individual_importance(model, tensors, idx):
    base = evaluate(model, tensors, idx)["overall"]["logloss"]
    # Constant and absent channels cannot convey information.
    ignore = {8, 22, 23}
    candidates = ([("x", i, name) for i, name in enumerate(FEATURE_NAMES)
                   if i not in ignore] +
                  [("c", i, name) for i, name in enumerate(CONTEXT_NAMES)])
    scores = []
    for family, col, name in candidates:
        delta = evaluate(model, tensors, idx, single=(family, col))
        scores.append({"family": family, "input": name,
                       "delta_logloss": round(delta["overall"]["logloss"] - base, 7)})
    return sorted(scores, key=lambda row: -row["delta_logloss"])


def smoke(target, dropout):
    assert len(ALL_40) == len(set(ALL_40)) == 40
    torch.set_num_threads(2)
    print("Architecture audit: 40 distinct models")
    for name in ALL_40:
        model, record = match_budget_40(name, target)
        assert abs(record["deviation_pct"]) < 8, record
        wrapped = MarketCorrection(name, record["width"], dropout, target)
        x = torch.randn(2, HISTORY, FEATURES)
        x[:, :, -1] = 1
        context = torch.randn(2, CONTEXT)
        price = torch.tensor([0.25, 0.75])
        logits, delta, aux = wrapped.eval()(x, context, price,
                                             torch.tensor([0, 1]))
        assert logits.shape == delta.shape == (2,)
        assert aux.shape == (2, FEATURES)
        assert torch.allclose(torch.sigmoid(logits), price, atol=1e-6)
        logits.sum().backward()
        assert all(p.grad is None or torch.isfinite(p.grad).all()
                   for p in wrapped.parameters())
        print(f'{name:<23} {record["params"]:>7} ({record["deviation_pct"]:+.2f}%)',
              flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--target-params", type=int, default=200_000)
    parser.add_argument("--batch-size", type=int, default=192)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.20)
    parser.add_argument("--weight-decay", type=float, default=0.02)
    parser.add_argument("--correction-penalty", type=float, default=0.03)
    parser.add_argument("--aux-weight", type=float, default=0.005)
    parser.add_argument("--lr", type=float, default=0.0003)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-hours", type=float, default=2.9)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        smoke(args.target_params, args.dropout)
        return
    if not 0 <= args.dropout < 1 or args.target_params < 10_000:
        parser.error("Invalid dropout or parameter target")
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "progress.json").exists():
        parser.error("Output exists; refusing to overwrite a prior sweep")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    begun = time.monotonic()
    markets, history, spot = query(args.db)
    data, info = build(markets, history, spot)
    (train, dev, sealed), dates = split(data)
    # Explicitly exclude all former development/sealed days from headline claims:
    # this is an exploratory sweep; never tune on today's sealed day afterward.
    info.update({"source": "official_Polymarket_US", "splits": dates,
                 "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "objective": "market_logit_plus_regularized_learned_correction",
                 "checkpoint_dtype": "float16_storage_fp32_training",
                 "models": list(ALL_40),
                 "parameter_target": args.target_params,
                 "notes": "Historical DISPLAY prices, not executable quotes; market-weighted rows",
                 "args": vars(args) | {"db": str(args.db), "output": str(args.output)}})
    write_json(args.output / "manifest.json", info)
    scalers = standardize(data, train)
    write_json(args.output / "scalers.json", scalers)
    baseline = {
        "dev_market": metrics(data["display"][dev], data["y"][dev], data["h"][dev]),
        "constant_dev": metrics(
            np.full(len(dev), data["y"][train].mean()), data["y"][dev], data["h"][dev]),
        "sealed_market": None,
    }
    write_json(args.output / "baselines.json", baseline)
    tensors, weights = sample_tensors(data), weights_by_market(data, train)
    LOG.info("ready: samples=%d dates=%d splits=%s market_dev=%.5f",
             len(data["y"]), len(set(data["dates"])), dates["rows"],
             baseline["dev_market"]["overall"]["logloss"])
    rows = []
    for i, kind in enumerate(ALL_40, 1):
        if time.monotonic() - begun > args.max_hours * 3600:
            LOG.warning("time budget exceeded at %d/40", len(rows))
            break
        LOG.info("START %d/40 %s", i, kind)
        model, row, state = train_one(kind, args, tensors, train, dev, weights)
        torch.save({"kind": kind, "width": row["width"],
                    "target_params": args.target_params,
                    "dropout": args.dropout, "state_dict": state,
                    "training": "fp32", "checkpoint_storage": "fp16",
                    "anchor": "historical_market_display_price"},
                   args.output / row["checkpoint"])
        rows.append(row)
        write_json(args.output / "progress.json",
                   {"complete_models": len(rows), "target_models": 40,
                    "rows": rows})
        LOG.info("DONE %d/40 %s dev_logloss=%.5f baseline=%.5f seconds=%.1f",
                 i, kind, row["dev"]["overall"]["logloss"],
                 baseline["dev_market"]["overall"]["logloss"], row["seconds"])
        del model, state
    if len(rows) != 40:
        LOG.error("incomplete %d/40; sealed untouched", len(rows))
        return
    # Freeze ranking by development data BEFORE touching sealed day.
    rows.sort(key=lambda r: r["dev"]["overall"]["logloss"])
    write_json(args.output / "dev_ranking_frozen.json",
               {"ranking": [r["kind"] for r in rows],
                "date": dates["dev_date"], "baseline": baseline["dev_market"]})
    # Only top 5 models receive group occlusion analysis on development day.
    attribution_ids = dev[::max(1, len(dev) // 2048)]
    for row in rows:
        bundle = torch.load(args.output / row["checkpoint"],
                            map_location="cpu", weights_only=True)
        model = MarketCorrection(bundle["kind"], bundle["width"], bundle["dropout"],
                                 bundle["target_params"])
        model.load_state_dict(bundle["state_dict"])
        row["sealed"] = evaluate(model, tensors, sealed)
        if row in rows[:5]:
            row["group_ablation_delta_logloss"] = importance(
                model, tensors, attribution_ids)
        if row in rows[:3]:
            row["individual_ablation_delta_logloss"] = individual_importance(
                model, tensors, attribution_ids)
    baseline["sealed_market"] = metrics(data["display"][sealed],
                                         data["y"][sealed], data["h"][sealed])
    write_json(args.output / "baselines.json", baseline)
    write_json(args.output / "results.json",
               {"completed": True, "models": rows, "baselines": baseline,
                "dev_ranking_frozen": True,
                "importance": "positive delta = useful group under mean occlusion; not causal",
                "elapsed_seconds": round(time.monotonic() - begun, 1)})
    LOG.info("COMPLETE 40/40 winner=%s dev=%.5f sealed=%.5f baseline=%.5f",
             rows[0]["kind"], rows[0]["dev"]["overall"]["logloss"],
             rows[0]["sealed"]["overall"]["logloss"],
             baseline["sealed_market"]["overall"]["logloss"])


if __name__ == "__main__":
    main()

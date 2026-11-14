"""Reproduce frozen 250K-model input layout without inventing future data.

Source: YeNoVolumeLab market_us/train_sweep.py build()/standardize() and
market_us/train250.py MarketResidual. Context's 52 macro fields are imputed
to training means (all standardized zeros) because the new live collector
does not yet reproduce its vintage-aware historical macro feeds. Outputs are
EXPERIMENTAL PAPER signals, not validated production probabilities.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import stdev

MODELS = ("stacked_rnn", "skip_gru_2", "depthwise_tcn", "lstm", "conv_gru")
ROOT = Path(__file__).resolve().parent
SCALES = json.loads((ROOT/"models/scalers.json").read_text())

def _valid(x):
    try:
        result = float(x)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None

def features_for_checkpoint(obs):
    """Return original (120x24,64) or None if causal source coverage fails."""
    candles = {}
    for c in obs["brti_history"]:
        at = int(c["timestamp"])
        if at+60 <= obs["observed_at"]:
            vals = [_valid(c.get(k)) for k in ("open", "high", "low", "close", "tickCount")]
            if all(v is not None and v > 0 for v in vals[:4]):
                candles[at+60] = vals
    # Derive each completed BRTI minute's features in timestamp order.
    timestamps = sorted(candles)
    series = {}
    for i, at in enumerate(timestamps):
        if i < 60 or at != timestamps[i-1] + 60:
            continue
        # Missing older bars are never bridged by returns across timestamps.
        if any(timestamps[j] - timestamps[j-1] != 60 for j in range(i-59, i+1)):
            continue
        close = [candles[t][3] for t in timestamps]
        rets = [math.log(close[j]/close[j-1])*1000 for j in range(i-59, i+1)]
        h, l, tick = candles[at][1], candles[at][2], candles[at][4]
        row = [
            rets[-1],
            math.log(close[i]/close[i-5])*1000,
            math.log(close[i]/close[i-15])*1000,
            math.log(close[i]/close[i-60])*1000,
            stdev(rets[-15:]),
            stdev(rets[-60:]),
            math.log(h/l)*1000,
            tick/60,
            math.log(close[i]),
        ]
        series[at] = row
    start, now = obs["start"], obs["observed_at"]//60*60
    initial = series.get(start)
    if initial is None:
        return None
    quotes = {int(q["timestamp"])+60: q for q in obs["display_history"] if q["up"] is not None and q["down"] is not None and int(q["timestamp"])+60 <= now}
    steps = []
    previous = None
    for t in range(now-119*60, now+60, 60):
        row = [0.0]*24
        ref = series.get(t)
        if ref is not None:
            row[:8] = ref[:8]
            row[9] = (ref[8]-initial[8])*1000
            row[17] = 1.0
        active = start <= t < obs["ends"]
        if active:
            row[10] = max(0.0, (obs["ends"]-t)/900)
            row[11] = (t-start)/900
            row[18] = 1.0
            q = quotes.get(t)
            if q:
                up, down = q["up"], q["down"]
                row[12:14] = [up, down]
                row[14] = up-previous if previous is not None else 0.0
                row[15] = up+down-1
                row[16] = 1.0
                previous = up
        phase = 2*math.pi*(t%86400)/86400
        row[20], row[21] = math.sin(phase), math.cos(phase)
        row[23] = 1.0
        steps.append(row)
    last = steps[-1]
    if not last[16] or not last[17] or sum(r[17] for r in steps) < 60:
        return None
    c = [1.0, 0.0, last[10], last[11], last[9], last[12], last[13],
         last[4], last[5], last[20], last[21], last[16]]
    # 52 macro/ETF context entries: explicitly imputed training means.
    c.extend(SCALES["c_mean"][12:])
    x = [[min(8.0,max(-8.0,(v-m)/s)) for v,m,s in zip(row,SCALES["x_mean"],SCALES["x_std"])] for row in steps]
    for row in x:
        row[-1] = 1.0
    context = [min(8.0,max(-8.0,(v-m)/s)) for v,m,s in zip(c,SCALES["c_mean"],SCALES["c_std"])]
    return x, context, last[12]

class FrozenResidual:
    def __init__(self, model_name):
        import torch
        from torch import nn
        from legacy_us.models_experimental import match_budget_40
        torch.set_num_threads(2)
        checkpoint = torch.load(ROOT/"models/checkpoints"/(model_name+".pt"), map_location="cpu", weights_only=True)
        if checkpoint["kind"] != model_name or checkpoint["context_dim"] != 64:
            raise ValueError("Checkpoint metadata mismatch: "+model_name)
        core, _ = match_budget_40(model_name, checkpoint["target"], context_dim=64)
        core.head.add_module("dropout", nn.Dropout(checkpoint["dropout"]))
        class Model(nn.Module):
            def __init__(self, core):
                super().__init__()
                self.core = core
            def forward(self, x, c):
                return self.core(x, c)
        self.torch = torch
        self.model = Model(core)
        self.model.load_state_dict(checkpoint["state_dict"], strict=True)
        self.model.eval()
        self.name = model_name

    def __call__(self, tensors):
        x, context, displayed_up = tensors
        if not 0 < displayed_up < 1:
            return None
        t = self.torch
        with t.inference_mode():
            output = self.model(t.tensor([x], dtype=t.float32), t.tensor([context],dtype=t.float32))
            residual = output["binary_logits"][0, 0].item()
        value = math.log(max(1e-4,min(1-1e-4,displayed_up))/(1-max(1e-4,min(1-1e-4,displayed_up))))
        return 1/(1+math.exp(-max(-50, min(50, value+0.45*residual))))

class Predictions:
    def __init__(self):
        self.models = None

    def all(self, obs):
        x = features_for_checkpoint(obs)
        if x is None:
            return {name:None for name in MODELS}
        if self.models is None:
            self.models = {name:FrozenResidual(name) for name in MODELS}
        out = {}
        for name, model in self.models.items():
            try:
                out[name] = model(x)
            except (ValueError, RuntimeError) as error:
                print("Model "+name+" unavailable: "+str(error),flush=True)
                out[name] = None
        return out

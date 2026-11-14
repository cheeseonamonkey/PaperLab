"""Experimental ~200k CPU encoders; frozen 20-run models remain untouched.

All operations use observations no later than the decision timestamp.
Architecture diversity is for screening, not evidence of a trading edge.
"""
from __future__ import annotations
import math

import torch
from torch import nn
from torch.nn import functional as F

from .models import (
    CONTEXT, FEATURES, HISTORY, KINDS, USMarketModel, parameters,
)

EXTRA = (
    "simple_rnn", "stacked_rnn", "bidirectional_gru", "bidirectional_lstm",
    "skip_gru_2", "skip_gru_4", "skip_gru_8", "attentive_gru",
    "projected_gru", "conv_lstm", "tcn_gru", "multiscale_gru",
    "lowrank_mlp", "random_fourier", "wavelet_mlp", "lag_gated_mlp",
    "crossnet", "random_reservoir", "multidecay_ssm", "spectral_gate",
)
ALL_40 = KINDS + EXTRA


class ExperimentalEncoder(nn.Module):
    def __init__(self, kind: str, width: int, features=FEATURES, steps=HISTORY):
        super().__init__()
        self.kind, self.width = kind, width
        if kind in ("simple_rnn", "stacked_rnn", "bidirectional_gru",
                    "bidirectional_lstm", "skip_gru_2", "skip_gru_4",
                    "skip_gru_8", "attentive_gru", "projected_gru",
                    "conv_lstm", "tcn_gru"):
            is_bi = kind.startswith("bidirectional_")
            is_lstm = kind in ("bidirectional_lstm", "conv_lstm")
            is_rnn = kind in ("simple_rnn", "stacked_rnn")
            cell = nn.LSTM if is_lstm else (nn.RNN if is_rnn else nn.GRU)
            self.stem = nn.Identity()
            in_dim = features
            if kind == "projected_gru":
                low = max(8, min(width // 4, 48))
                self.stem = nn.Sequential(nn.Linear(features, low), nn.Tanh(),
                                          nn.Linear(low, width))
                in_dim = width
            elif kind in ("conv_lstm", "tcn_gru"):
                self.conv = nn.Conv1d(features, features, 5, groups=features)
                self.stem = nn.Linear(features, width)
                in_dim = width
            hidden = width // 2 if is_bi else width
            self.rnn = cell(in_dim, hidden, batch_first=True, bidirectional=is_bi,
                            num_layers=2 if kind == "stacked_rnn" else 1)
            if kind == "attentive_gru":
                self.attn = nn.Linear(width, 1)
        elif kind == "multiscale_gru":
            w = max(8, width // 4)
            self.rnns = nn.ModuleList([nn.GRU(features, w, batch_first=True)
                                       for _ in range(3)])
            self.project = nn.Linear(3 * w, width)
        elif kind in ("lowrank_mlp", "random_fourier", "wavelet_mlp",
                      "lag_gated_mlp", "crossnet", "spectral_gate"):
            dims = {
                "lowrank_mlp": features * 24,
                "random_fourier": features * 16,
                "wavelet_mlp": features * 10,
                "lag_gated_mlp": features * 5,
                "crossnet": features * 3,
                "spectral_gate": features * 6,
            }
            if kind == "random_fourier":
                gen = torch.Generator().manual_seed(20261105)
                self.register_buffer("omega", torch.randn(dims[kind], width, generator=gen)
                                     / math.sqrt(dims[kind]))
                self.project = nn.Linear(width * 2, width)
            else:
                self.project = nn.Linear(dims[kind], width)
            if kind == "crossnet":
                rank = max(8, width // 4)
                self.left = nn.Linear(width, rank)
                self.right = nn.Linear(width, rank)
                self.expand = nn.Linear(rank, width)
            if kind == "lag_gated_mlp":
                self.gate = nn.Linear(width, width)
            self.mlp = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width * 2),
                                     nn.GELU(), nn.Linear(width * 2, width))
        elif kind == "random_reservoir":
            gen = torch.Generator().manual_seed(20261105)
            self.register_buffer("input_matrix",
                                 torch.randn(features, width, generator=gen) / math.sqrt(features))
            self.register_buffer("recurrent_matrix",
                                 0.6 * torch.randn(width, width, generator=gen) / math.sqrt(width))
            self.readout = nn.Sequential(nn.Linear(width, width), nn.GELU(),
                                         nn.Linear(width, width))
        elif kind == "multidecay_ssm":
            self.stem = nn.Linear(features, width)
            self.logits = nn.Parameter(torch.tensor([-3.0, -1.0, 1.0, 3.0]))
            self.mix = nn.Sequential(nn.Linear(width * 4, width), nn.GELU(),
                                     nn.Linear(width, width))
        else:
            raise ValueError(kind)
        self.norm = nn.LayerNorm(width)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        k = self.kind
        if hasattr(self, "rnn"):
            if k.startswith("skip_gru_"):
                stride = int(k.rsplit("_", 1)[1])
                x = x[:, (x.shape[1] - 1) % stride::stride]
            if k in ("conv_lstm", "tcn_gru"):
                z = F.pad(x.transpose(1, 2), (4, 0))
                x = F.gelu(self.conv(z)).transpose(1, 2)
            x = self.stem(x)
            y, _ = self.rnn(x)
            if k == "attentive_gru":
                a = torch.softmax(self.attn(y).squeeze(-1), dim=1)
                z = (a.unsqueeze(-1) * y).sum(1)
            elif k.startswith("bidirectional_"):
                z = torch.cat((y[:, -1, :self.width // 2],
                               y[:, 0, self.width // 2:]), dim=-1)
            else:
                z = y[:, -1]
            return self.norm(z)
        if k == "multiscale_gru":
            states = []
            for stride, cell in zip((1, 4, 16), self.rnns):
                z = x[:, (x.shape[1] - 1) % stride::stride]
                states.append(cell(z)[0][:, -1])
            return self.norm(self.project(torch.cat(states, dim=-1)))
        if k == "random_reservoir":
            h = x.new_zeros(x.shape[0], self.width)
            projected = x @ self.input_matrix
            for t in range(x.shape[1]):
                h = torch.tanh(projected[:, t] + h @ self.recurrent_matrix)
            return self.norm(self.readout(h))
        if k == "multidecay_ssm":
            z = self.stem(x)
            t = torch.arange(x.shape[1] - 1, -1, -1, device=x.device, dtype=z.dtype)
            rate = torch.sigmoid(self.logits)
            weights = torch.softmax(-t[:, None] * rate[None], dim=0)
            summary = torch.einsum("btw,ts->bsw", z, weights)
            return self.norm(self.mix(summary.flatten(1)) + z[:, -1])
        if k == "lowrank_mlp":
            flat = F.adaptive_avg_pool1d(x.transpose(1, 2), 24).flatten(1)
        elif k == "random_fourier":
            pooled = F.adaptive_avg_pool1d(x.transpose(1, 2), 16).flatten(1)
            phase = pooled @ self.omega
            flat = torch.cat((torch.sin(phase), torch.cos(phase)), dim=-1)
        elif k == "wavelet_mlp":
            # Relative scales and signed scale transitions, all from past windows.
            pools = [x[:, -n:].mean(1) for n in (1, 2, 4, 8, 16, 32)]
            flat = torch.cat(pools + [pools[i] - pools[i + 1] for i in range(4)], dim=-1)
        elif k == "lag_gated_mlp":
            flat = torch.cat((x[:, -1], x[:, -4], x[:, -16], x[:, -64], x.mean(1)), dim=-1)
        elif k == "crossnet":
            flat = torch.cat((x[:, -1], x[:, -16:].mean(1), x.mean(1)), dim=-1)
        elif k == "spectral_gate":
            spectrum = torch.fft.rfft(x.float(), dim=1).abs()
            groups = [spectrum[:, s:e].mean(1) for s, e in
                      ((1, 3), (3, 8), (8, 16), (16, 32))]
            flat = torch.cat((x[:, -1], x.mean(1), *groups), dim=-1)
        else:
            raise ValueError(k)
        z = self.project(flat)
        if k == "crossnet":
            z = z + self.expand(torch.tanh(self.left(z)) * self.right(z))
        if k == "lag_gated_mlp":
            z = z * torch.sigmoid(self.gate(z))
        if k == "random_fourier":
            return self.norm(z)
        return self.norm(z + self.mlp(z))


def make_model(kind: str, width: int, context_dim=CONTEXT) -> USMarketModel:
    if kind in KINDS:
        return USMarketModel(kind, width, context=context_dim)
    if kind not in EXTRA:
        raise ValueError(kind)
    model = USMarketModel("gru", width, context=context_dim)
    model.encoder = ExperimentalEncoder(kind, width)
    model.kind = kind
    return model


def match_budget_40(kind: str, target=200_000, context_dim=CONTEXT):
    if kind not in ALL_40:
        raise ValueError(kind)
    lo, hi, best = 4, 96, None
    while lo <= hi:
        mid = (lo + hi) // 2
        width = mid * 4
        size = parameters(make_model(kind, width, context_dim))
        if best is None or abs(size - target) < abs(best[1] - target):
            best = width, size
        if size < target:
            lo = mid + 1
        else:
            hi = mid - 1
    assert best is not None
    for width in (max(16, best[0] - 4), best[0] + 4):
        size = parameters(make_model(kind, width, context_dim))
        if abs(size - target) < abs(best[1] - target):
            best = width, size
    width, size = best
    return make_model(kind, width, context_dim), {"kind": kind, "width": width,
                                     "params": size, "target": target,
                                     "deviation_pct": round(100 * (size / target - 1), 3)}

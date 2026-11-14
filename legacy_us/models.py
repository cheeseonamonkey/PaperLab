"""CPU-oriented architecture zoo for YeNo US.

Twenty distinct ~120k-parameter candidates. This file defines models and
a parameter-budget audit only; it does not train or claim trading performance.

Inputs:
    history: [batch, 120, 24] past numeric market observations, 30s spacing
    context: [batch, 12] known-at-decision public market/slow context
Outputs:
    binary_logits: [batch, 2] 15m and hourly US Up probabilities (supervised)
    next_features: [batch, 24] next observed feature vector (SSL only)

All observations, including input timestamps/gaps, must be causal.
Own inventory, fill volume and pending limit orders are separate execution-policy state.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from typing import Callable

import torch
from torch import nn
from torch.nn import functional as F

HISTORY = 120
FEATURES = 24
CONTEXT = 12
TARGET_PARAMS = 150_000

KINDS = (
    "gru", "stacked_gru", "lstm", "attention_gru",
    "tcn", "depthwise_tcn", "wavenet", "conv_gru",
    "transformer", "patch_transformer", "itransformer",
    "tsmixer", "multiscale_mixer", "tide",
    "fourier_mixer", "diagonal_ssm", "cfc",
    "kan_mixer", "regime_moe", "dlinear_residual",
)


def feedforward(width: int, multiplier: int = 2) -> nn.Sequential:
    return nn.Sequential(nn.Linear(width, width * multiplier), nn.GELU(),
                         nn.Linear(width * multiplier, width))


class Recurrent(nn.Module):
    def __init__(self, features: int, width: int, kind: str):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.rnn = (nn.LSTM if kind == "lstm" else nn.GRU)(
            width, width, num_layers=2 if kind == "stacked_gru" else 1,
            batch_first=True)
        self.attention = nn.Linear(width, 1) if kind == "attention_gru" else None
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        seq, _ = self.rnn(self.input(x))
        if self.attention is not None:
            weights = torch.softmax(self.attention(seq).squeeze(-1), dim=1)
            return self.norm((seq * weights.unsqueeze(-1)).sum(dim=1))
        return self.norm(seq[:, -1])


class ConvGRU(nn.Module):
    def __init__(self, features, width):
        super().__init__()
        self.conv1 = nn.Conv1d(features, width, 5)
        self.conv2 = nn.Conv1d(width, width, 3)
        self.rnn = nn.GRU(width, width, batch_first=True)
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        # Left padding only: output at time t never sees t+1.
        z = F.gelu(self.conv1(F.pad(x.transpose(1, 2), (4, 0))))
        z = self.conv2(F.pad(z, (2, 0)))
        y, _ = self.rnn(z.transpose(1, 2))
        return self.norm(y[:, -1])


class ConvBlock(nn.Module):
    def __init__(self, width, dilation, depthwise=False, gated=False):
        super().__init__()
        self.pad = dilation * 2
        self.gated = gated
        self.conv = nn.Conv1d(width, width * (2 if gated else 1),
                              kernel_size=3, dilation=dilation,
                              groups=width if depthwise and not gated else 1)
        self.pointwise = nn.Conv1d(width, width, 1)
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        z = self.conv(F.pad(x.transpose(1, 2), (self.pad, 0)))
        if self.gated:
            a, b = z.chunk(2, dim=1)
            z = torch.tanh(a) * torch.sigmoid(b)
        else:
            z = F.gelu(z)
        z = self.pointwise(z).transpose(1, 2)
        return self.norm(x + z)


class Convolutional(nn.Module):
    def __init__(self, features, width, kind):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.blocks = nn.Sequential(*[
            ConvBlock(width, dilation, kind == "depthwise_tcn", kind == "wavenet")
            for dilation in (1, 2, 4, 8)
        ])
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        y = self.blocks(self.input(x))
        return self.norm(y[:, -1] + y.mean(dim=1))


class Attention(nn.Module):
    def __init__(self, features, width, kind, steps):
        super().__init__()
        self.kind = kind
        self.steps = steps
        if kind == "patch_transformer":
            self.patch = 8
            self.input = nn.Linear(features * self.patch, width)
            self.n_tokens = math.ceil(steps / self.patch)
        elif kind == "itransformer":
            self.input = nn.Linear(steps, width)
            self.n_tokens = features
        else:
            self.input = nn.Linear(features, width)
            self.n_tokens = steps
        self.position = nn.Parameter(torch.zeros(1, self.n_tokens, width))
        layer = nn.TransformerEncoderLayer(
            width, nhead=4, dim_feedforward=width * 2,
            dropout=0.0, activation="gelu", batch_first=True,
            norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, num_layers=2,
                                              enable_nested_tensor=False)
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        if self.kind == "patch_transformer":
            count = math.ceil(x.shape[1] / self.patch)
            if count * self.patch != x.shape[1]:
                x = F.pad(x.transpose(1, 2), (0, count * self.patch - x.shape[1])).transpose(1, 2)
            x = x.reshape(x.shape[0], count, -1)
        elif self.kind == "itransformer":
            x = x.transpose(1, 2)
        z = self.input(x) + self.position
        y = self.encoder(z)
        return self.norm(y[:, -1] if self.kind == "transformer" else y.mean(dim=1))


class MixerBlock(nn.Module):
    def __init__(self, steps, width):
        super().__init__()
        self.time_norm = nn.LayerNorm(width)
        self.time = nn.Linear(steps, steps)
        self.feature_norm = nn.LayerNorm(width)
        self.feature = feedforward(width)

    def forward(self, x):
        z = self.time_norm(x).transpose(1, 2)
        x = x + self.time(z).transpose(1, 2)
        return x + self.feature(self.feature_norm(x))


class TSMixer(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.blocks = nn.Sequential(*(MixerBlock(steps, width) for _ in range(3)))
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        y = self.blocks(self.input(x))
        return self.norm(y.mean(dim=1) + y[:, -1])


class MultiScaleMixer(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.stems = nn.ModuleList([nn.Linear(features, width) for _ in (1, 4, 16)])
        self.mixers = nn.ModuleList([MixerBlock(math.ceil(steps / k), width)
                                     for k in (1, 4, 16)])
        self.gate = nn.Linear(width * 3, 3)
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        reps = []
        for k, stem, mixer in zip((1, 4, 16), self.stems, self.mixers):
            z = x if k == 1 else F.avg_pool1d(x.transpose(1, 2), k, k, ceil_mode=True).transpose(1, 2)
            y = mixer(stem(z))
            reps.append(y.mean(dim=1) + y[:, -1])
        joined = torch.cat(reps, dim=-1)
        weights = torch.softmax(self.gate(joined), dim=-1)
        return self.norm(sum(reps[i] * weights[:, i, None] for i in range(3)))


class TiDE(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.input = nn.Linear(features * 24, width)
        self.blocks = nn.ModuleList([feedforward(width) for _ in range(3)])
        self.norms = nn.ModuleList([nn.LayerNorm(width) for _ in range(3)])

    def forward(self, x):
        z = F.adaptive_avg_pool1d(x.transpose(1, 2), 24).flatten(1)
        z = self.input(z)
        for block, norm in zip(self.blocks, self.norms):
            z = norm(z + block(z))
        return z


class FourierMixer(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.real = nn.Parameter(torch.ones(steps // 2 + 1, features))
        self.imag = nn.Parameter(torch.zeros(steps // 2 + 1, features))
        self.input = nn.Linear(features, width)
        self.block = nn.Sequential(MixerBlock(steps, width), MixerBlock(steps, width))
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        spectral = torch.fft.rfft(x.float(), dim=1, norm="ortho")
        factor = torch.complex(self.real, self.imag)[None]
        restored = torch.fft.irfft(spectral * factor, n=x.shape[1], dim=1, norm="ortho")
        y = self.block(self.input(restored.to(x.dtype)))
        return self.norm(y[:, -1] + y.mean(dim=1))


class DiagonalSSM(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.logit_decay = nn.Parameter(torch.zeros(width))
        self.mix = nn.Sequential(feedforward(width), nn.LayerNorm(width), feedforward(width))
        self.norm = nn.LayerNorm(width)
        self.steps = steps

    def forward(self, x):
        z = self.input(x)
        decay = torch.sigmoid(self.logit_decay).clamp(max=0.999)
        t = torch.arange(x.shape[1], device=x.device, dtype=z.dtype)
        # Strict causal exponentially weighted recurrence computed as FFT convolution.
        kernel = torch.pow(decay[None], t[:, None]) * (1 - decay)[None]
        n = 1 << (2 * x.shape[1] - 1).bit_length()
        y = torch.fft.irfft(torch.fft.rfft(z.float(), n=n, dim=1)
                             * torch.fft.rfft(kernel.float(), n=n, dim=0)[None],
                             n=n, dim=1)[:, :x.shape[1]]
        y = self.mix(y[:, -1].to(z.dtype))
        return self.norm(y + z[:, -1])


class ContinuousGate(nn.Module):
    """Small continuous-time decaying recurrent cell, CfC-*inspired*, not official CfC."""
    def __init__(self, features, width):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.core = nn.Linear(width * 2, width * 3)
        self.out = nn.Sequential(feedforward(width), nn.LayerNorm(width))
        self.width = width

    def forward(self, x):
        z = self.input(x)
        h = z.new_zeros(z.shape[0], self.width)
        # x[-1] is a normalized nonnegative sample-gap feature.
        for i in range(x.shape[1]):
            eq, rate, gate = self.core(torch.cat([z[:, i], h], dim=-1)).chunk(3, -1)
            dt = x[:, i, -1:].clamp(0, 4) + 1e-2
            alpha = (-torch.expm1(-F.softplus(rate) * dt)).clamp(0, 1)
            proposal = torch.tanh(eq)
            h = h + alpha * torch.sigmoid(gate) * (proposal - h)
        return self.out(h)


class RBFKAN(nn.Module):
    """Efficient fixed-basis KAN-inspired nonlinearity; not an exact spline KAN."""
    def __init__(self, width):
        super().__init__()
        self.centers = nn.Parameter(torch.linspace(-2, 2, 7), requires_grad=False)
        self.log_width = nn.Parameter(torch.tensor(0.0))
        self.projection = nn.Linear(width * 7, width)

    def forward(self, x):
        basis = torch.exp(-torch.exp(self.log_width) *
                          (x.unsqueeze(-1) - self.centers).square())
        return self.projection(basis.flatten(-2))


class KANMixer(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.mix = nn.Linear(steps, steps)
        self.kan = RBFKAN(width)
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        y = self.input(x)
        z = y + self.mix(y.transpose(1, 2)).transpose(1, 2)
        return self.norm(self.kan(z.mean(dim=1)) + z[:, -1])


class RegimeMoE(nn.Module):
    def __init__(self, features, width, context):
        super().__init__()
        self.input = nn.Linear(features, width)
        self.conv = nn.Conv1d(width, width, 5)
        self.gate = nn.Linear(width * 2 + context, 4)
        self.experts = nn.ModuleList([feedforward(width) for _ in range(4)])
        self.norm = nn.LayerNorm(width)

    def forward(self, x, context):
        y = self.input(x)
        z = F.gelu(self.conv(F.pad(y.transpose(1, 2), (4, 0)))).transpose(1, 2)
        state = z[:, -1] + z.mean(dim=1)
        weights = torch.softmax(self.gate(torch.cat([state, y[:, -1], context], dim=-1)), -1)
        return self.norm(sum(weights[:, i, None] * f(state)
                             for i, f in enumerate(self.experts)) + state)


class DLinearResidual(nn.Module):
    def __init__(self, features, width, steps):
        super().__init__()
        self.trend = nn.Linear(features * 24, width)
        self.season = nn.Linear(features * 24, width)
        self.residual = nn.Sequential(feedforward(width), feedforward(width))
        self.norm = nn.LayerNorm(width)

    def forward(self, x):
        # Moving-average trend + seasonal residual, both causal within history.
        trend = F.avg_pool1d(F.pad(x.transpose(1, 2), (8, 0), mode="replicate"),
                              9, stride=1).transpose(1, 2)
        trend = F.adaptive_avg_pool1d(trend.transpose(1, 2), 24).flatten(1)
        season = F.adaptive_avg_pool1d(
            (x - F.avg_pool1d(F.pad(x.transpose(1, 2), (8, 0), mode="replicate"),
                               9, stride=1).transpose(1, 2)).transpose(1, 2), 24).flatten(1)
        z = self.trend(trend) + self.season(season)
        return self.norm(z + self.residual(z))


def make_encoder(kind: str, width: int, features=FEATURES, steps=HISTORY,
                 context=CONTEXT) -> nn.Module:
    if kind in ("gru", "stacked_gru", "lstm", "attention_gru"):
        return Recurrent(features, width, kind)
    if kind in ("tcn", "depthwise_tcn", "wavenet"):
        return Convolutional(features, width, kind)
    if kind == "conv_gru":
        return ConvGRU(features, width)
    if kind in ("transformer", "patch_transformer", "itransformer"):
        return Attention(features, width, kind, steps)
    if kind == "tsmixer":
        return TSMixer(features, width, steps)
    if kind == "multiscale_mixer":
        return MultiScaleMixer(features, width, steps)
    if kind == "tide":
        return TiDE(features, width, steps)
    if kind == "fourier_mixer":
        return FourierMixer(features, width, steps)
    if kind == "diagonal_ssm":
        return DiagonalSSM(features, width, steps)
    if kind == "cfc":
        return ContinuousGate(features, width)
    if kind == "kan_mixer":
        return KANMixer(features, width, steps)
    if kind == "regime_moe":
        return RegimeMoE(features, width, context)
    if kind == "dlinear_residual":
        return DLinearResidual(features, width, steps)
    raise ValueError(f"unknown architecture {kind}")


class USMarketModel(nn.Module):
    def __init__(self, kind: str, width: int, features=FEATURES,
                 steps=HISTORY, context=CONTEXT):
        super().__init__()
        self.kind, self.width = kind, width
        self.encoder = make_encoder(kind, width, features, steps, context)
        self.context = nn.Sequential(nn.LayerNorm(context),
                                     nn.Linear(context, width), nn.GELU())
        self.head = nn.Sequential(nn.LayerNorm(width * 2),
                                  nn.Linear(width * 2, width), nn.GELU())
        self.binary = nn.Linear(width, 2)
        self.next_features = nn.Linear(width, features)

    def forward(self, history: torch.Tensor, context: torch.Tensor):
        if history.ndim != 3 or context.ndim != 2 or history.shape[0] != context.shape[0]:
            raise ValueError("expected past [B,T,F] and known context [B,C]")
        z = (self.encoder(history, context) if self.kind == "regime_moe"
             else self.encoder(history))
        z = self.head(torch.cat([z, self.context(context)], -1))
        return {"binary_logits": self.binary(z),
                "next_features": self.next_features(z)}


def parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


@dataclass(frozen=True)
class Architecture:
    name: str
    width: int
    parameters: int
    target: int
    deviation_pct: float


def match_budget(kind: str, target=TARGET_PARAMS, features=FEATURES,
                 steps=HISTORY, context=CONTEXT) -> tuple[USMarketModel, Architecture]:
    """Search a single meaningful model-width axis; never pad with unused weights."""
    if kind not in KINDS:
        raise ValueError(f"unknown architecture {kind}")
    # All models use widths divisible by 4 for safe 4-head attention.
    lo, hi = 4, 64
    best: tuple[int, int] | None = None
    while lo <= hi:
        middle = (lo + hi) // 2
        width = middle * 4
        size = parameters(USMarketModel(kind, width, features, steps, context))
        if best is None or abs(size - target) < abs(best[1] - target):
            best = width, size
        if size < target:
            lo = middle + 1
        else:
            hi = middle - 1
    assert best is not None
    # Assess the nearest adjacent discrete width to avoid binary-search edge cases.
    for width in (max(16, best[0] - 4), min(256, best[0] + 4)):
        size = parameters(USMarketModel(kind, width, features, steps, context))
        if abs(size - target) < abs(best[1] - target):
            best = width, size
    width, size = best
    model = USMarketModel(kind, width, features, steps, context)
    return model, Architecture(kind, width, size, target,
                                round(100 * (size / target - 1), 3))


def audit(target=TARGET_PARAMS):
    return [match_budget(kind, target)[1].__dict__ for kind in KINDS]


def main():
    parser = argparse.ArgumentParser(description="Parameter-matched 20-model architecture audit.")
    parser.add_argument("--target", type=int, default=TARGET_PARAMS)
    parser.add_argument("--output", type=str)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.target < 5000:
        parser.error("target must be >= 5000")
    torch.set_num_threads(min(2, torch.get_num_threads()))
    rows = audit(args.target)
    if args.smoke:
        for row in rows:
            torch.manual_seed(42)
            m = USMarketModel(row["name"], row["width"])
            x = torch.randn(2, HISTORY, FEATURES)
            x[:, :, -1] = 1  # positive sample-gap channel for CfC-like model
            context = torch.randn(2, CONTEXT)
            out = m(x, context)
            loss = out["binary_logits"].square().mean() + out["next_features"].square().mean()
            loss.backward()
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite forward/backward for {row['name']}")
            row["smoke_loss"] = round(loss.item(), 5)
    print(json.dumps(rows, indent=2))
    if args.output:
        from pathlib import Path
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()

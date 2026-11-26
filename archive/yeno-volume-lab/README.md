# YeNo Profit Lab

Profit-first research on Polymarket US BTC 15-minute and 1-hour binary markets.
No wallet access, no live orders, no API credentials.

The old Builderr volume-challenge work (international 5-minute L2, AProbe and
entrant replays) was removed from the working tree on 2026-11-13. It remains
recoverable from git tag `volume-era-final` (commit `02f304c`), and the
uncommitted worktree state is in
`/root/backups/yeno-volume-era-workingtree-20261113.patch`. Its 9 GB of data
under `data/raw/` is kept: it is the only large executable L2 corpus on disk,
but it is a **different venue/domain** and is not Polymarket US history.

## Goal

Maximise **held-out net dollars** after spread, fees, minimum size, fill
probability and slippage — not classification accuracy, not trade count, not
eligible volume. No-trade is a valid outcome.

## Where things live

| Path | Contents |
|---|---|
| `market_us/` | all active code: collector, exogenous features, models, training |
| `market_us/README.md` | data provenance, model ladder, settlement rules |
| `market_us/ARCHITECTURES.md` | 20-architecture screening suite and selection protocol |
| `market_us/results/` | training runs, checkpoints, fold comparisons |
| `data/research/polymarket_us/market.sqlite3` | US markets, settlements, display history, live top-5 books |
| `data/research/polymarket_us/spot_archive/` | 2 years of Binance 1m OHLCV (context only, not BRTI) |
| `data/research/polymarket_us/exogenous/` | macro / cross-asset feature feeds |

## What the data supports today

- **52 days** of settled US markets (2026-09-22 → 2026-11-12): 4,921 fifteen-minute
  and 1,242 one-hour markets; 6,107 / 6,163 settled.
- **Display-price history** for all of it: ~24 samples per market. Not
  executable quotes.
- **Real top-5 order books**: only from 2026-11-05, 30-second cadence, ~8 days.
  This is the only data that can support an honest profit backtest.

## Current model status

`market_us/results/us-20-250k-all-days/` (44 days, 117,713 samples, 250k params).
Twenty architectures were screened with two chronological folds. Result: models
are a residual on market-implied probability and **none showed a reliable edge**.
Many "wins" are float ties from the zero-initialised residual head, not learning.

Training is cheap: the whole 20-model sweep took ~23 min on this VPS's CPU.
**A GPU rental is not the bottleneck; executable book history is.**

## Commands

```sh
cd /root/Proj/YeNoVolumeLab
python3 -m pytest -q market_us/tests
python3 market_us/exogenous.py status
python3 market_us/collector.py status

# 20-architecture screen over every usable day
python3 market_us/train250.py --output market_us/results/us-20-250k-all-days-v2
```

Live services (root, pre-existing): `yeno-us-live.service`,
`yeno-us-backfill.timer`, `yeno-spot-archive.timer`.

## Rules

- Point-in-time timestamps only. Fit scalers/encoders on train days only.
- Split whole chronological days; purge at boundaries; keep a sealed tail.
- Report net dollars, drawdown and no-trade rate. Never report a model's
  probability accuracy as if it were profit.
- Display prices are not fills. International L2 is not US executable history.

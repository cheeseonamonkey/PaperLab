# YeNo / Polymarket US: Profit-first research

This directory is isolated from the previous Builderr volume challenge and its international Polymarket data. The existing 9 GB L2 history is NOT executable Polymarket US history. No wallet access, trades, or API credentials.

## Recommended model ladder

1. **Always benchmark:** no-trade, quoted-market-implied probability, parametric normalized-window-delta/volatility model, regularized logistic regression, and boosted decision trees (HistGradientBoosting or LightGBM).
2. **Candidate neural:** shared multi-resolution encoder with two GRU layers, 64–96 hidden units, 15-minute and hourly probability heads and a 16–32-unit gated slow-regime branch. Initial target: roughly 75,000–250,000 trainable parameters, adjusted for actual features. Include separate calibrated uncertainty estimates and a no-trade policy.
3. **Ablations:** 1D-CNN + GRU (DeepLOB-inspired), compact TCN, attention only if genuinely beneficial; sizes 32/64/128/256 and 1–3 layers. Only evaluate models beyond ~1M parameters after collecting sufficient distinct US markets and out-of-sample days.
4. **Targets:** properly calibrated probabilities of each US BRTI-based binary event resolving Up, plus optional future BTC return distributions. Train with log loss or Brier, then select execution policy by *realistic held-out net profit* (after spread, fees, min-order constraints, slippage, and unsuccessful fills).
5. **Data horizon:** recent one-minute crypto context and actual US contract BBO/order-book history; 15-minute/hour/day derived features; daily and slower macro regime features. Point-in-time timestamps mandatory.
6. **Trade tests:** evaluate entry times from market open through final seconds, including simple T-15s/T-10s/T-5s rules. A fixed $0.85 purchase cutoff is a heuristic, not a proven edge. US settlement uses the 60 BRTI readings *before both window boundaries*, so the simple terminal snapshot is not authoritative.
7. **Backtest integrity:** entire unseen calendar days or weeks, walk-forward tests, no overlap leaks, no tuning on sealed holdouts, regime shifts, independent US-vs-international venue semantics. Optimize dollars rather than number of trades.

Relevant published approaches: DeepLOB https://arxiv.org/abs/1808.03668 ; Bayesian DeepLOB (uncertainty-aware trading) https://arxiv.org/abs/1811.10041 . They motivate architectures but are not evidence a profitable live YeNo bot exists.

Official US market data: https://docs.polymarket.us/data-guide/overview . US market example confirming BRTI 60-sample rule: https://polymarket.us/event/btc-updown-15m-2026-09-28-1615z .

## Read-only external-feature data

Run:

    python3 market_us/exogenous.py collect --crypto-days 3
    python3 market_us/exogenous.py status
    python3 market_us/exogenous.py build --anchors /path/to/us_market_decisions.parquet --output /path/to/us_aux_features.parquet
    python3 -m pytest -q market_us/tests

Data written in data/research/polymarket_us/exogenous/ (Parquet per feed and checksum manifest).

- Coinbase Exchange: minute BTC/ETH/SOL/XRP candles, complete bars known conservatively at +63 seconds, 300-candle API chunks.
- Yahoo chart (unofficial, research use): daily SPY, QQQ, GLD, USO, UUP. Day close available only next midnight UTC; do not treat timestamp as the close-publication time.
- Cboe: official daily VIX history, delayed until next day UTC.
- FRED: daily DGS2, DGS10, DFF, DFEDTARU, DTWEXBGS, DCOILWTICO; conservative daily observation delays.
- Economic releases: CPIAUCSL, PAYEMS, UNRATE, GDPC1, ICSA are **collected but excluded by default**: FRED's latest historical values may contain later revisions. Historical ALFRED vintages and actual release times/consensus surprises are required for robust backtests. Published release calendars are legitimate future-known features, but realized release values are not known ahead of time.

The feature builder backward-asof joins known_at <= decision_at, enforces maximum staleness, emits missing flags, and extracts crypto returns/volatility/volume, ETF changes, yield curve slope and crypto-relative momentum. This is a feature layer, NOT executable US-market research yet. It never substitutes Coinbase spot quotes for the official BRTI settlement process.

The six-hour-plus training suggestion should not be used before the US order-book and settlement labels are verified. Kaggle GPU experiments are capped at 3 hours per automated cycle with no overlap or paid capacity; do not launch a large model simply to burn GPU hours.

## Data acquisition / coverage (2026-11-06)

- Polymarket US BTC 15m/1h contract history: 2026-09-22 onward. Older tested slugs returned 404. Historical display prices are **not** historical executable order books.
- Official Polymarket US BTC reference: 2026-09-01 onward, as far as the tested API provides data. SQLite: `data/research/polymarket_us/market.sqlite3`.
- Separate two-year spot context: Binance Vision BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT 1m OHLCV, 2024-11-06 to 2026-11-05. 1,051,200 observations per asset, 4,204,800 total; no minute gaps in the audited window. **Not** BRTI settlement or US contract prices.
- Source/provenance: `market_us/archive_spot.py` downloads and checksum-verifies 116 Binance source ZIP archives, saves raw ZIP and Zstd Parquet with JSON metadata in `data/research/polymarket_us/spot_archive/`. Resumable; skips already-complete files.
- Daily VPS jobs: `yeno-us-live.service` (30-second live snapshots, auto-restart); `yeno-us-backfill.timer` (daily US history/settlements); `yeno-spot-archive.timer` (daily spot-data extension). All are root-owned systemd units.

```sh
systemctl status yeno-us-live.service yeno-us-backfill.timer yeno-spot-archive.timer
journalctl -u yeno-spot-archive.service -n 30 --no-pager
python3 market_us/collector.py status
```

Historical US backfill intentionally starts 2026-09-22 rather than asking for tens of thousands of nonexistent older contract slugs. Preserve venue separation in all evaluation/training; neither international Polymarket books nor Binance spot prices substitute for US executable book history.

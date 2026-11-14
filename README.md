# YeNo Paper Lab — Polymarket US

**12 simultaneous paper strategies, $100 independently simulated cash each**, using **Polymarket US** BTC 15-minute Up/Down (BRTI) markets. No accounts, wallet, exchange keys, real order placement or leverage.

- [Current results](REPORT.md) · [Persistent state](data/state.json) · [Raw, compressed observations](data/observations/) · [Workflows](../../actions)
- **Hourly Actions** runs approximately 50 minutes, polling US public order books at a **15-second target cadence** (when network calls fit). Runs can start late or be dropped by GitHub; **not an always-on service**.
- Simulates both marketable buys and **resting limit buys**, with cash reservations, expiry/cancellation and delayed observed crossing. Settles exclusively using the **official US 0/1 settlement endpoint**.
- Competing independent models all see a **single shared, timestamped data feed**. Inputs include official BRTI minute candles, current Polymarket US bid/ask/top-5 depth, US price-to-beat and display history, time to expiry, book imbalance, and additional BTC/ETH/SOL/XRP spot context. Coinbase context does not determine official settlement.

<!-- YENO_STATUS_START -->
## Current research status

Venue: **Polymarket US**, BTC 15m BRTI Up/Down. All orders **simulated**.
Accounts: **12 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-14T07:39:31+00:00**.

Research sample: **1 markets tracked / 0 officially settled / 0 settled strategy positions**.

Polls: **1 attempts / 1 recorded / 0 skipped**. Last error: None.

| Strategy | Paper cash | Realized P&L | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|
| book_imbalance | $100.00 | $+0.00 | 0 | 0 | 0 |
| brti_distance | $100.00 | $+0.00 | 0 | 0 | 0 |
| brti_distance_limit | $100.00 | $+0.00 | 0 | 0 | 0 |
| btc_momentum | $100.00 | $+0.00 | 0 | 0 | 0 |
| btc_reversion | $100.00 | $+0.00 | 0 | 0 | 0 |
| conv_gru | $100.00 | $+0.00 | 0 | 0 | 0 |
| cross_asset_momentum | $100.00 | $+0.00 | 0 | 0 | 0 |
| depthwise_tcn | $100.00 | $+0.00 | 0 | 0 | 0 |
| lstm | $100.00 | $+0.00 | 0 | 0 | 0 |
| market_implied | $100.00 | $+0.00 | 0 | 0 | 0 |
| skip_gru_2 | $100.00 | $+0.00 | 0 | 0 | 0 |
| stacked_rnn | $100.00 | $+0.00 | 0 | 0 | 0 |

Full caveats and the audit trail are in [REPORT.md](REPORT.md).
<!-- YENO_STATUS_END -->

## Strategies

| Account | Signal | Paper execution |
|---|---|---|
| stacked_rnn | Frozen 250K fitted recurrent model | Limit |
| skip_gru_2 | Frozen 250K fitted skip-GRU | Limit |
| depthwise_tcn | Frozen 250K fitted causal CNN | Marketable |
| lstm | Frozen 250K fitted LSTM | Limit |
| conv_gru | Frozen 250K fitted conv-GRU | Marketable |
| market_implied | Explicit never-trade benchmark | Hold |
| brti_distance | BRTI distance vs strike and volatility | Marketable |
| brti_distance_limit | Same estimated probability | Limit |
| btc_momentum | BTC 5-minute signal vs implied odds | Marketable |
| btc_reversion | Counter-trend vs implied odds | Limit |
| cross_asset_momentum | BTC/ETH/SOL/XRP momentum | Limit |
| book_imbalance | US YES depth imbalance vs implied odds | Limit |

Each account starts at **$100**, caps a proposed entry around **$5**, enforces a modeled **5-share minimum**, and caps open cost basis at **$15**. Pending orders reserve paper cash and cannot spend another strategy's money. Each account can initiate at most one position/order per 15-minute market.

**Marketable buy assumption:** US displayed ask plus $0.005/share slippage, 2% all-in notional fee buffer, and top-of-book capacity.

**Resting buy assumption:** post at the displayed bid, reserve its cost, and credit a hypothetical fill *only* if a **later US snapshot** has best ask at or below the posted limit and offers adequate displayed size. Fill is marked at the conservative original limit price, with the same 2% fee buffer; **no maker rebate is assumed**. This crossing is a proxy, **not evidence of queue priority or a real fill**. Otherwise orders remain pending and expire, returning reserved cash.

Fees are illustrative **stress assumptions**, not a verified US fee schedule. Results are speculative paper P&L, not live-executable returns.

## Model provenance and limitations

The 20-architecture, approximately 250K-parameter Polymarket US experiment in [YeNoVolumeLab](https://github.com/cheeseonamonkey/YeNoVolumeLab) finished on November 6, 2026. Five checkpoint families had nontrivial trained residuals and improved market-relative validation loss on both older-day chronological folds:

**Stacked RNN · Skip-GRU-2 · Depthwise TCN · LSTM · Conv-GRU.**

Its **40-architecture, 200K** screening attempt finished **1/40**, so it cannot provide a credible 40-way winner list.

The saved original 250K weights, metadata, training scalers, feature audit and fold comparisons are committed here under [models](models/). Model implementations are retained in [legacy_us](legacy_us/) for exact tensor layout and checkpoint compatibility. Training source revision and SHA-256 provenance are in [models/provenance.json](models/provenance.json).

### Critical live inference caveat

The frozen neural checkpoints expect **120 × 24** one-minute, point-in-time historical input features and **64 context** channels. The live US adapter reproduces the reference/price layout, *but currently mean-imputes the 52 slow macro and cross-asset ETF context fields* rather than reproducing their original vintage-aware as-of feeds. New Coinbase crypto context is **collected separately**, not silently substituted into those trained channels.

**Consequently the neural predictions are out-of-distribution research signals.** They can make hypothetical paper decisions, but are neither calibrated nor comparable to the original held-out results without a feature-parity study. Models abstain when there is insufficient authentic US BRTI/display history. No fitted model has an established net-profit advantage.

Training was on historical US **display** prices, not actual historical executable depth; price-history data must not be reported as fills. Official US settlement uses BRTI samples near the event's boundaries, *not* the Coinbase last price.

## Persistence and cost

- [data/state.json](data/state.json): independent cash, open orders, filled trades, official settled outcomes, and audit timestamps.
- [data/observations](data/observations/): **compressed daily JSONL**, one shared US book/feature snapshot per successful polling decision. Git commit history remains auditable.
- [models/checkpoints](models/checkpoints/): five fitted PyTorch checkpoints (approximately 2.5 MB combined), frozen metadata and scalers. Never rewritten by the paper runner.
- [REPORT.md](REPORT.md): auto-generated account comparison; the **Current research status** block above updates from the same saved state after paper runs.
- [research/proposals](research/proposals/): **review-only** Pi experiment suggestions, never deployed.

The hourly process persists files locally on every successful tick; Actions commits state and new observations at job completion. A cancelled runner can lose its **uncommitted** session. Keeping all 15-second snapshots in Git indefinitely will enlarge repo history; storage can be moved to archive releases if growth becomes an issue.

## GitHub Actions

The hourly job needs **no secret**. It installs CPU-only PyTorch and calls `python yeno.py run --duration 3000` (50 minutes, roughly four updates per minute). GitHub Actions is not a 24/7 low-latency execution engine; network and runner timings will vary. A one-off `workflow_dispatch` run can request **60–3300 seconds** for verification.

A separate **optional daily** Pi/OpenRouter research workflow needs only the Actions secret `OPENROUTER_API_KEY`:

1. Get an OpenRouter key with zero/low allowed spend.
2. Add [OPENROUTER_API_KEY](https://github.com/cheeseonamonkey/YeNoPaperLab/settings/secrets/actions) under repository Actions secrets.
3. After 40 officially settled US markets, Pi can read **aggregate paper performance** and submit one bounded experiment hypothesis daily. It cannot modify any strategy, model or paper account. OpenRouter's free router may enforce availability or request limits; there is no paid-model fallback configured.

## Local

Requires Python 3.12+; CPU models need PyTorch.

```sh
python -m pip install 'torch==2.14.1' --index-url https://download.pytorch.org/whl/cpu
python -m unittest discover -s tests -v
python yeno.py check
python yeno.py run                 # Single US public-data observation
python yeno.py run --duration 180 # 3-minute paper loop
python yeno.py report
python research.py ready          # Needs 40 settled official US markets
```

Read-only public API endpoints: `gateway.polymarket.us/v1/market/slug/...`, `/v1/markets/{slug}/book`, `/v1/markets/{slug}/settlement`, `/v1/price-history` and `/v1/asset-prices/history`. No Polymarket international Gamma/CLOB host is used.

**Paper research only; no proven statistical or trading edge.**

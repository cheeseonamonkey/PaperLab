# Paper Lab — Polymarket US

**12 simultaneous paper strategies, $100 independently simulated cash each**, using **Polymarket US** BTC 15-minute and 1-hour Up/Down (BRTI) markets. No accounts, wallet, exchange keys, real order placement or leverage.

- [Current results](REPORT.md) · [Persistent state](data/state.json) · [Raw, compressed observations](data/observations/) · [Workflows](../../actions)
- **Hourly Actions** runs approximately one hour, polling US public order books at a **30-second target cadence** (when network calls fit). Runs can start late or be dropped by GitHub; **not an always-on service**.
- Simulates **resting limit buys**, with cash reservations, expiration and delayed observed crossing. Settles exclusively using the **official US 0/1 settlement endpoint**.
- Competing independent models all see a **single shared, timestamped data feed**. Inputs include official BRTI minute candles, current Polymarket US bid/ask/top-5 depth, US price-to-beat and display history, time to expiry, book imbalance, and additional BTC/ETH/SOL/XRP spot context. Coinbase context does not determine official settlement.

<!-- YENO_STATUS_START -->
## Current research status

Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.
Accounts: **12 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-14T14:37:59+00:00**.

Research sample: **3 markets tracked / 1 officially settled / 0 settled strategy positions**.

Polls: **31 attempts / 30 recorded / 1 skipped**. Last error: None.

| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| book_imbalance | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| brti_distance | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| brti_distance_limit | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| btc_momentum | $100.00 | $+0.00 | — | — (n=0) | — | 0 | 0 | 0 |
| btc_reversion | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| conv_gru | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| cross_asset_momentum | $100.00 | $+0.00 | — | — (n=0) | — | 0 | 0 | 1 |
| depthwise_tcn | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| lstm | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| market_implied | $100.00 | $+0.00 | — | — (n=0) | — | 0 | 0 | 0 |
| skip_gru_2 | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |
| stacked_rnn | $95.00 | $+0.00 | — | — (n=0) | — | 0 | 1 | 0 |

Market-midpoint benchmark: awaiting first officially settled market.

Win rate uses settled simulated fills. Forecast Brier averages snapshots within each market, then averages markets; n is the number of settled markets. Positive ΔBrier means better than the paired market-midpoint forecast; lower Brier is better.

Full caveats and the audit trail are in [REPORT.md](REPORT.md).
<!-- YENO_STATUS_END -->

## Strategies

| Account | Signal | Paper execution |
|---|---|---|
| stacked_rnn | Inactive legacy 250K recurrent model | Limit |
| skip_gru_2 | Inactive legacy 250K skip-GRU | Limit |
| depthwise_tcn | Inactive legacy 250K causal CNN | Limit |
| lstm | Inactive legacy 250K LSTM | Limit |
| conv_gru | Inactive legacy 250K conv-GRU | Limit |
| market_implied | Explicit never-trade benchmark | Hold |
| brti_distance | BRTI distance vs strike and volatility | Limit |
| brti_distance_limit | Same estimated probability | Limit |
| btc_momentum | BTC 5-minute signal vs implied odds | Limit |
| btc_reversion | Counter-trend vs implied odds | Limit |
| cross_asset_momentum | BTC/ETH/SOL/XRP momentum | Limit |
| book_imbalance | US YES depth imbalance vs implied odds | Limit |

Each account starts at **$100**. Each limit order can reserve up to **$15** of available paper cash, including the simulated fee buffer; share quantities may be fractional. Each strategy gets an opportunity to place an order for each market every **five minutes**. Pending orders reserve cash, and existing orders are monitored at every observation.

**Resting buy assumption:** post at the displayed bid, reserve its cost, and credit a hypothetical fill *only* if a **later US snapshot** has best ask at or below the posted limit and offers adequate displayed size. Fill is marked at the conservative original limit price, with the same 2% fee buffer; **no maker rebate is assumed**. This crossing is a proxy, **not evidence of queue priority or a real fill**. Otherwise orders remain pending and expire, returning reserved cash.

Fees are illustrative **stress assumptions**, not a verified US fee schedule. Results are speculative paper P&L, not live-executable returns.

## Training and evaluation

The research candidate trains only on settled **live observations** collected by this repo. BTC, ETH, SOL, and XRP context is included where available. Validation uses a chronological split and compares forecast error against the market-implied price. The candidate is research only and is not automatically placed into the paper accounts.

The backward historical archive is stored separately and is **not** read by the trainer. Historical display prices do not represent executable order books. No historical bootstrap is enabled.

Five legacy checkpoint accounts are inactive. Their earlier files remain in Git history for provenance.

## Persistence and cost

- [data/state.json](data/state.json): independent cash, open orders, filled trades, official settled outcomes, and audit timestamps.
- [data/observations](data/observations/): **compressed daily JSONL**, one shared US book/feature snapshot per successful polling decision. Git commit history remains auditable.
- [models/checkpoints](models/checkpoints/): inactive legacy checkpoints, retained for provenance.
- [data/backfill](data/backfill/): resumable historical 15-minute and 1-hour market display history, official settlements, and Coinbase BTC/ETH/SOL/XRP minute candles. The target is three prior market hours per hourly workflow run; historical display prices are not historical order books.
- [data/training](data/training/): candidate research model and run status, trained on settled live observations with chronological validation. The candidate is not automatically promoted to a paper strategy.
- [REPORT.md](REPORT.md): auto-generated account comparison; the **Current research status** block above updates from the same saved state after paper runs.
- [research/proposals](research/proposals/): **review-only** Pi experiment suggestions, never deployed.

The hourly process persists files locally on every successful tick; Actions commits state and new observations at job completion. A cancelled runner can lose its **uncommitted** session. Keeping all 30-second snapshots in Git indefinitely will enlarge repo history; storage can be moved to archive releases if growth becomes an issue.

## GitHub Actions

The hourly job needs **no secret**. It installs CPU-only PyTorch and calls `python yeno.py run --duration 3600` (one hour, targeting two observations per minute per horizon). GitHub Actions is not a 24/7 low-latency execution engine; network and runner timings will vary. A one-off `workflow_dispatch` run can request **60–3600 seconds** for verification.

Each cycle also stores up to three earlier hours of market history and exogenous candles. This archive is not used for training. The research model trains on all usable settled live observations and uses the market midpoint, horizon, and completed prior-minute crypto returns.

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

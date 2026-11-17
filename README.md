# Paper Lab — Polymarket US

**13 simultaneous paper strategies, $100 independently simulated cash each**, using **Polymarket US** BTC 15-minute and 1-hour Up/Down (BRTI) markets. No accounts, wallet, exchange keys, real order placement or leverage.

- [Current results](REPORT.md) · [Persistent state](data/state.json) · [Raw, compressed observations](data/observations/) · [Workflows](../../actions) · [Documentation index](docs/README.md) · [Strategy pages](docs/bots/README.md)
- **Hourly Actions** runs approximately one hour, polling US public order books at a **15-second target cadence** (when network calls fit). Runs can start late or be dropped by GitHub; **not an always-on service**.
- Simulates **resting limit buys and simulated urgent sells**, with cash reservations, expiration and a later-book-crossing fill proxy. Queue priority and execution latency are not modeled. Settles using the **official US 0/1 settlement endpoint**.
- Competing independent models all see a **single shared, timestamped data feed**. Inputs include official BRTI minute candles, current Polymarket US bid/ask/top-5 depth, US price-to-beat and display history, time to expiry, book imbalance, and additional BTC/ETH/SOL/XRP spot context. Coinbase context does not determine official settlement.

<!-- PAPER_STATUS_START -->
## Current research status

Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.
Accounts: **12 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-14T15:56:23+00:00**.

Research sample: **5 markets tracked / 3 officially settled / 9 settled strategy positions**.

Polls: **51 attempts / 39 recorded / 12 skipped**. Last error: None.

| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [book_imbalance](docs/bots/book_imbalance.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.092 (n=2) | -0.000 | 1 | 0 | 2 |
| [brti_distance](docs/bots/brti_distance.md) | $77.27 | $-5.00 | 0/1 (0.0%) | 0.093 (n=2) | -0.001 | 1 | 2 | 1 |
| [brti_distance_limit](docs/bots/brti_distance_limit.md) | $77.27 | $-5.00 | 0/1 (0.0%) | 0.093 (n=2) | -0.001 | 1 | 2 | 1 |
| [btc_momentum](docs/bots/btc_momentum.md) | $92.31 | $+0.00 | — | 0.083 (n=2) | +0.009 | 0 | 1 | 0 |
| [btc_reversion](docs/bots/btc_reversion.md) | $86.80 | $-5.00 | 0/1 (0.0%) | 0.103 (n=2) | -0.011 | 1 | 1 | 0 |
| [conv_gru](docs/bots/conv_gru.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.216 (n=1) | -0.032 | 1 | 0 | 0 |
| [cross_asset_momentum](docs/bots/cross_asset_momentum.md) | $93.37 | $+0.00 | — | 0.079 (n=2) | +0.013 | 0 | 1 | 0 |
| [depthwise_tcn](docs/bots/depthwise_tcn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.244 (n=1) | -0.059 | 1 | 0 | 0 |
| [lstm](docs/bots/lstm.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.284 (n=1) | -0.099 | 1 | 0 | 0 |
| [market_implied](docs/bots/market_implied.md) | $100.00 | $+0.00 | — | 0.092 (n=2) | +0.000 | 0 | 0 | 0 |
| [skip_gru_2](docs/bots/skip_gru_2.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.256 (n=1) | -0.071 | 1 | 0 | 0 |
| [stacked_rnn](docs/bots/stacked_rnn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.260 (n=1) | -0.076 | 1 | 0 | 0 |

Market-midpoint benchmark: Brier 0.092 / log loss 0.300 across 2 settled markets.

Win rate uses settled simulated fills. Forecast Brier averages snapshots within each market, then averages markets; n is the number of settled markets. Positive ΔBrier means better than the paired market-midpoint forecast; lower Brier is better.

Full caveats and the audit trail are in [REPORT.md](REPORT.md).
<!-- PAPER_STATUS_END -->

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
| research_linear | Causal market-relative logistic candidate | Limit |

Five legacy neural accounts currently abstain; `market_implied` is a hold-only benchmark. The distance pair shares one signal; momentum and reversion are sign-reversed variants. Thirteen accounts are not thirteen independent active hypotheses. See [execution limits](docs/EXECUTION.md) and [research plan](docs/RESEARCH.md).

Each account starts at **$100**. Order size uses one-quarter Kelly, capped at **10% of current account equity per order** and **30% committed exposure** across open positions and pending entries. Fractional simulated shares are allowed; maker fills assume zero exchange fee and no rebate. Each strategy gets an opportunity to place an order for each market every **one minute**. Pending orders reserve cash, and existing orders are monitored at every observation.

**Resting buy assumption:** post at the displayed bid, reserve its cost, and credit a hypothetical fill *only* if a **later US snapshot** has best ask at or below the posted limit and offers adequate displayed size. Fills use the original limit price, zero maker exchange fee, and **no maker rebate**. Sell limits require a later observed bid crossing the offer with sufficient displayed size. This crossing is a proxy, **not evidence of queue priority or a real fill**. Otherwise orders remain pending and expire, returning reserved cash.

The maker fee is zero with no rebate assumed; the separately implemented taker formula follows the published straight-contract coefficient. An order-book crossing cannot establish actual queue priority. Results are speculative paper P&L, not live-executable returns.

## Training and evaluation

The research candidate trains on a fixed two-day historical bootstrap plus settled **live observations** collected by this repo. BTC, ETH, SOL, XRP, and timestamped SP500 context are included where available. Validation uses a chronological split and compares forecast error against the market-implied price. It runs only in its isolated `research_linear` paper account and does not change legacy strategies.

The bootstrap is fetched once and placed in the normal observation directory, with separate settlement labels. The backward historical archive is stored separately and is **not** read by the trainer. Historical display prices do not represent executable order books.

Five legacy checkpoint accounts are inactive. Their earlier files remain in Git history for provenance.

## Persistence and cost

- [data/state.json](data/state.json): independent cash, open orders, filled trades, official settled outcomes, and audit timestamps.
- [data/observations](data/observations/): **compressed daily JSONL**, one shared US book/feature snapshot per successful polling decision. Git commit history remains auditable.
- [models/checkpoints](models/checkpoints/): inactive legacy checkpoints, retained for provenance.
- [data/backfill](data/backfill/): resumable historical 15-minute and 1-hour market display history, official settlements, and Coinbase BTC/ETH/SOL/XRP minute candles. The target is three prior market hours per hourly workflow run; historical display prices are not historical order books.
- [data/training](data/training/): candidate model, chronological validation, and research run history.
- [data/ledgers](data/ledgers/): per-bot orders and trades in CSV.
- [docs](docs/): research notes and generated per-bot pages. The candidate is not automatically promoted to a paper strategy.
- [REPORT.md](REPORT.md): auto-generated account comparison; the **Current research status** block above updates from the same saved state after paper runs.
- [research/proposals](research/proposals/): **review-only** Pi experiment suggestions, never deployed.

The hourly process persists files locally on every successful tick; Actions commits state and new observations at job completion. A cancelled runner can lose its **uncommitted** session. Keeping all 15-second snapshots in Git indefinitely will enlarge repo history; storage can be moved to archive releases if growth becomes an issue.

## GitHub Actions

The hourly job needs **no secret**. It installs CPU-only PyTorch and calls `python paper.py run --duration 3600` (one hour, targeting four observations per minute per horizon). GitHub Actions is not a 24/7 low-latency execution engine; network and runner timings will vary. A one-off `workflow_dispatch` run can request **60–3600 seconds** for verification.

Each cycle experiments with simple regularization and exogenous-return transforms, records their results without automatically promoting a candidate, and stores up to three earlier hours of market history and exogenous candles. This archive is not used for training. The research model trains on the fixed bootstrap and all usable settled live observations and uses the market midpoint, horizon, and completed prior-minute crypto returns.

A separate **optional daily** Pi/OpenRouter research workflow needs only the Actions secret `OPENROUTER_API_KEY`:

1. Get an OpenRouter key with zero/low allowed spend.
2. Add [OPENROUTER_API_KEY](https://github.com/cheeseonamonkey/YeNoPaperLab/settings/secrets/actions) under repository Actions secrets.
3. After 40 officially settled US markets, Pi can read **aggregate paper performance** and submit one bounded experiment hypothesis daily. It cannot modify any strategy, model or paper account. OpenRouter's free router may enforce availability or request limits; there is no paid-model fallback configured.

## Local

Requires Python 3.12+; CPU models need PyTorch.

```sh
python -m pip install 'torch==2.14.1' --index-url https://download.pytorch.org/whl/cpu
python -m unittest discover -s tests -v
python paper.py check
python paper.py run                 # Single US public-data observation
python paper.py run --duration 180 # 3-minute paper loop
python paper.py report
python research.py ready          # Needs 40 settled official US markets
```

Read-only public API endpoints: `gateway.polymarket.us/v1/market/slug/...`, `/v1/markets/{slug}/book`, `/v1/markets/{slug}/settlement`, `/v1/price-history` and `/v1/asset-prices/history`. No Polymarket international Gamma/CLOB host is used.

**Paper research only; no proven statistical or trading edge.**

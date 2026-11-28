# Paper Lab — Polymarket US

**13 simultaneous paper strategies, $100 independently simulated cash each**, using **Polymarket US** BTC 15-minute and 1-hour Up/Down (BRTI) markets. No accounts, wallet, exchange keys, real order placement or leverage.

- [Current results](REPORT.md) · [Persistent state](data/state.json) · [Raw, compressed observations](data/observations/) · [Workflows](../../actions) · [Documentation index](docs/README.md) · [Strategy pages](docs/bots/README.md)
- **Archive complete:** the full Polymarket US BTC archive (September 22 onward) is downloaded (`data/backfill/state.json`: `done`). The hourly Actions workflow now runs the paper replay and research loop below; archive backfill remains available by manual dispatch only.
- Historical batches simulate **delayed price-based entries and exits**, including modeled taker fees and slippage. These are paper proxies, not executable quotes. Settles using the **official US 0/1 settlement endpoint**.
- Strategies share historical US price displays, the market's price-to-beat, timestamp-available BRTI candles, and BTC/ETH/SOL/XRP context. Historical book depth is unavailable; book-dependent strategies abstain. Coinbase context never substitutes for official settlement.

<!-- PAPER_STATUS_START -->
## Current research status

Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.
Accounts: **13 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-18T09:20:06+00:00**.

Research sample: **34 markets tracked / 31 officially settled / 238 settled strategy positions**.

Polls: **1989 attempts / 845 recorded / 1144 skipped**. Last error: ValueError: US book timestamp stale/in future.

| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [book_imbalance](docs/bots/book_imbalance.md) | $62.30 | $-18.66 | 14/46 (30.4%) | 0.113 (n=30) | +0.001 | 46 | 11 | 3 |
| [brti_distance](docs/bots/brti_distance.md) | $37.80 | $-48.96 | 15/53 (28.3%) | 0.113 (n=30) | +0.001 | 53 | 3 | 0 |
| [brti_distance_limit](docs/bots/brti_distance_limit.md) | $37.80 | $-48.96 | 15/53 (28.3%) | 0.113 (n=30) | +0.001 | 53 | 3 | 0 |
| [btc_momentum](docs/bots/btc_momentum.md) | $83.83 | $-3.71 | 5/11 (45.5%) | 0.111 (n=30) | +0.003 | 11 | 6 | 0 |
| [btc_reversion](docs/bots/btc_reversion.md) | $97.49 | $+6.02 | 12/19 (63.2%) | 0.114 (n=30) | +0.000 | 19 | 4 | 1 |
| [conv_gru](docs/bots/conv_gru.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.216 (n=1) | -0.032 | 1 | 0 | 0 |
| [cross_asset_momentum](docs/bots/cross_asset_momentum.md) | $79.56 | $-3.44 | 5/11 (45.5%) | 0.111 (n=30) | +0.003 | 11 | 8 | 0 |
| [depthwise_tcn](docs/bots/depthwise_tcn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.244 (n=1) | -0.059 | 1 | 0 | 0 |
| [lstm](docs/bots/lstm.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.284 (n=1) | -0.099 | 1 | 0 | 0 |
| [market_implied](docs/bots/market_implied.md) | $100.00 | $+0.00 | — | 0.114 (n=30) | +0.000 | 0 | 0 | 0 |
| [research_linear](docs/bots/research_linear.md) | $67.04 | $-7.27 | 18/40 (45.0%) | 0.115 (n=24) | +0.002 | 40 | 14 | 1 |
| [skip_gru_2](docs/bots/skip_gru_2.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.256 (n=1) | -0.071 | 1 | 0 | 0 |
| [stacked_rnn](docs/bots/stacked_rnn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.260 (n=1) | -0.076 | 1 | 0 | 0 |

Market-midpoint benchmark: Brier 0.114 / log loss 0.363 across 30 settled markets.

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

Each account starts at **$100**. Order size uses one-quarter Kelly, capped at **10% of current account equity per order** and **30% committed exposure** across open positions and pending entries. Fractional simulated shares are allowed. Each strategy can act once per market per **minute** of historical observations; simultaneous positions share the account's exposure budget. Entry intents reserve cash until a later observed price permits a fee-adjusted paper fill or the order is cancelled.

**Historical execution:** an entry is only eligible on the next observation, using the later displayed price plus modeled slippage and taker fee. It cancels if the reserved budget is insufficient. Exits use the observed price minus slippage and taker fee. There are no historical depth or queue-priority guarantees.

Legacy live-book trades retain their original zero-maker-fee crossing assumptions and historical accounting. Results from either mode are speculative paper P&L, not live-executable returns.

## Training and evaluation

The research candidate trains on a fixed two-day historical bootstrap plus settled **historical-hour and earlier live observations** collected by this repo. BTC, ETH, SOL, XRP, and timestamped SP500 context are included where available. Validation uses a chronological split and compares forecast error against the market-implied price. It runs only in its isolated `research_linear` paper account and does not change legacy strategies.

The bootstrap is fetched once and placed in the normal observation directory, with separate settlement labels. The backward historical archive is stored separately and **is** read by the trainer as its own labeled source (owner-approved 2026-11-28): embedded settlements label strided display-price rows; inputs the archive never stored stay missing-valued. Historical display prices do not represent executable order books.

Five legacy checkpoint accounts are inactive. Their earlier files remain in Git history for provenance.

## Persistence and cost

- [data/state.json](data/state.json): independent cash, open orders, filled trades, official settled outcomes, and audit timestamps.
- [data/observations](data/observations/): **compressed daily JSONL**, one timestamped source observation shared across strategies. Git commit history remains auditable.
- [models/checkpoints](models/checkpoints/): inactive legacy checkpoints, retained for provenance.
- [data/backfill](data/backfill/): resumable historical 15-minute and 1-hour market display history, official settlements, and Coinbase BTC/ETH/SOL/XRP minute candles. The scheduled workflow is currently building the full available US BTC archive; a prior-hour replay remains manually available. Historical display prices are not order books.
- [data/training](data/training/): candidate model, chronological validation, and research run history.
- [data/ledgers](data/ledgers/): per-bot orders and trades in CSV.
- [docs](docs/): research notes and generated per-bot pages. The candidate is not automatically promoted to a paper strategy.
- [REPORT.md](REPORT.md): auto-generated account comparison; the **Current research status** block above updates from the same saved state after paper runs.
- [research/proposals](research/proposals/): **review-only** Pi experiment suggestions, never deployed.

Each short-lived hourly run commits its batch and state once. Failed publications retain short-lived artifacts; uncommitted results are not canonical.

## GitHub Actions

The existing `paper.yml` schedule runs the long-running research loop every hour: collect the previous closed hour, replay every paper account in parallel shards, merge, then train and evaluate the research candidate zoo. No new workflows or real-time polling. Manual dispatch with `archive_only=true` runs the (completed) archive backfill instead.

Research trains on the fixed bootstrap, timestamp-valid settled observations, and the backfill archive (labeled source, 45-day rolling window). Candidates — a systematic sweep over feature architectures × regularization × fit length, with a longer weekly deep pass on Sundays — are evaluated chronologically on an identical split. Forks that age past 21 days with ≥20 settled trades and realized P&L ≤ −$15 are retired to hold-only: history preserved, roster slot freed. The baseline is never automatically promoted, but a non-baseline candidate that clears the predeclared fork policy in `train_research.py` — beat the market Brier by ≥0.003, beat the linear baseline, ≥5 validation markets, 3 consecutive winning runs — spawns a **frozen fork**: its own isolated $100 paper account (see `strategies/roster.json`), identical risk controls, parent and validation recorded in `data/training/forks/`. Caps: at most 40 fork accounts and 50 accounts total; fork history is never deleted.

A separate **optional daily** Pi/OpenRouter research workflow needs only the Actions secret `OPENROUTER_API_KEY`:

1. Get an OpenRouter key with zero/low allowed spend.
2. Add [OPENROUTER_API_KEY](https://github.com/cheeseonamonkey/PaperLab/settings/secrets/actions) under repository Actions secrets.
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

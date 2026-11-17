# Paper Lab — Polymarket US

Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.
Accounts: **13 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-17T08:45:29+00:00**.

Research sample: **13 markets tracked / 11 officially settled / 31 settled strategy positions**.

Polls: **543 attempts / 243 recorded / 300 skipped**. Last error: ValueError: US book timestamp stale/in future.

| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [book_imbalance](docs/bots/book_imbalance.md) | $88.14 | $-7.12 | 0/4 (0.0%) | 0.094 (n=10) | -0.001 | 4 | 3 | 0 |
| [brti_distance](docs/bots/brti_distance.md) | $68.95 | $-1.50 | 3/9 (33.3%) | 0.053 (n=10) | +0.040 | 9 | 3 | 0 |
| [brti_distance_limit](docs/bots/brti_distance_limit.md) | $68.95 | $-1.50 | 3/9 (33.3%) | 0.053 (n=10) | +0.040 | 9 | 3 | 0 |
| [btc_momentum](docs/bots/btc_momentum.md) | $103.79 | $+3.79 | 1/1 (100.0%) | 0.089 (n=10) | +0.004 | 1 | 0 | 0 |
| [btc_reversion](docs/bots/btc_reversion.md) | $86.80 | $-13.20 | 0/2 (0.0%) | 0.098 (n=10) | -0.005 | 2 | 0 | 0 |
| [conv_gru](docs/bots/conv_gru.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.216 (n=1) | -0.032 | 1 | 0 | 0 |
| [cross_asset_momentum](docs/bots/cross_asset_momentum.md) | $103.26 | $+3.26 | 1/1 (100.0%) | 0.089 (n=10) | +0.003 | 1 | 0 | 0 |
| [depthwise_tcn](docs/bots/depthwise_tcn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.244 (n=1) | -0.059 | 1 | 0 | 0 |
| [lstm](docs/bots/lstm.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.284 (n=1) | -0.099 | 1 | 0 | 0 |
| [market_implied](docs/bots/market_implied.md) | $100.00 | $+0.00 | — | 0.093 (n=10) | +0.000 | 0 | 0 | 0 |
| [research_linear](docs/bots/research_linear.md) | $100.00 | $+0.00 | — | 0.079 (n=4) | +0.000 | 0 | 0 | 0 |
| [skip_gru_2](docs/bots/skip_gru_2.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.256 (n=1) | -0.071 | 1 | 0 | 0 |
| [stacked_rnn](docs/bots/stacked_rnn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.260 (n=1) | -0.076 | 1 | 0 | 0 |

Market-midpoint benchmark: Brier 0.093 / log loss 0.322 across 10 settled markets.

Win rate is settled simulated fills only. Forecasts estimate Up probability; Brier and log loss use the official outcome.
Forecast losses average snapshots within each market, then average markets. Positive ΔBrier means improvement over the paired market midpoint; lower Brier/log loss is better.
Realized profit is **not** total equity: active positions are not marked to market.
US YES book is the market source; NO quotes are complement-derived.
Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.
Resting maker fills assume zero exchange fee and no rebate; marketable test fills use the published straight-contract taker formula and $0.005/share slippage. Historical orders retain their original fee assumptions.
Five legacy checkpoint accounts abstain in this fresh-start run; the repository-trained research candidate is evaluated separately.
The remaining seven strategies are explicit deterministic baselines, including a no-trade account.
No authentication, private APIs, real orders, funds or wallets.

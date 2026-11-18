# Paper Lab — Polymarket US

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

Win rate is settled simulated fills only. Forecasts estimate Up probability; Brier and log loss use the official outcome.
Forecast losses average snapshots within each market, then average markets. Positive ΔBrier means improvement over the paired market midpoint; lower Brier/log loss is better.
Realized profit is **not** total equity: active positions are not marked to market.
US YES book is the market source; NO quotes are complement-derived.
Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.
Resting maker fills assume zero exchange fee and no rebate; marketable test fills use the published straight-contract taker formula and $0.005/share slippage. Historical orders retain their original fee assumptions.
Five legacy checkpoint accounts abstain in this fresh-start run; the repository-trained research candidate is evaluated separately.
The remaining seven strategies are explicit deterministic baselines, including a no-trade account.
No authentication, private APIs, real orders, funds or wallets.

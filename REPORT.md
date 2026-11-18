# Paper Lab — Polymarket US

Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.
Accounts: **13 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-18T01:46:19+00:00**.

Research sample: **27 markets tracked / 24 officially settled / 168 settled strategy positions**.

Polls: **1507 attempts / 640 recorded / 867 skipped**. Last error: ValueError: US book timestamp stale/in future.

| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [book_imbalance](docs/bots/book_imbalance.md) | $68.58 | $-30.08 | 6/33 (18.2%) | 0.101 (n=23) | -0.003 | 33 | 1 | 1 |
| [brti_distance](docs/bots/brti_distance.md) | $58.81 | $-26.48 | 12/36 (33.3%) | 0.087 (n=23) | +0.011 | 36 | 2 | 1 |
| [brti_distance_limit](docs/bots/brti_distance_limit.md) | $58.81 | $-26.48 | 12/36 (33.3%) | 0.087 (n=23) | +0.011 | 36 | 2 | 1 |
| [btc_momentum](docs/bots/btc_momentum.md) | $98.09 | $-1.91 | 5/10 (50.0%) | 0.096 (n=23) | +0.001 | 10 | 0 | 0 |
| [btc_reversion](docs/bots/btc_reversion.md) | $90.86 | $-9.14 | 6/12 (50.0%) | 0.100 (n=23) | -0.002 | 12 | 0 | 0 |
| [conv_gru](docs/bots/conv_gru.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.216 (n=1) | -0.032 | 1 | 0 | 0 |
| [cross_asset_momentum](docs/bots/cross_asset_momentum.md) | $96.75 | $-3.25 | 4/8 (50.0%) | 0.097 (n=23) | +0.001 | 8 | 0 | 0 |
| [depthwise_tcn](docs/bots/depthwise_tcn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.244 (n=1) | -0.059 | 1 | 0 | 0 |
| [lstm](docs/bots/lstm.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.284 (n=1) | -0.099 | 1 | 0 | 0 |
| [market_implied](docs/bots/market_implied.md) | $100.00 | $+0.00 | — | 0.098 (n=23) | +0.000 | 0 | 0 | 0 |
| [research_linear](docs/bots/research_linear.md) | $76.03 | $-23.97 | 9/28 (32.1%) | 0.099 (n=17) | -0.002 | 28 | 0 | 0 |
| [skip_gru_2](docs/bots/skip_gru_2.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.256 (n=1) | -0.071 | 1 | 0 | 0 |
| [stacked_rnn](docs/bots/stacked_rnn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.260 (n=1) | -0.076 | 1 | 0 | 0 |

Market-midpoint benchmark: Brier 0.098 / log loss 0.329 across 23 settled markets.

Win rate is settled simulated fills only. Forecasts estimate Up probability; Brier and log loss use the official outcome.
Forecast losses average snapshots within each market, then average markets. Positive ΔBrier means improvement over the paired market midpoint; lower Brier/log loss is better.
Realized profit is **not** total equity: active positions are not marked to market.
US YES book is the market source; NO quotes are complement-derived.
Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.
Resting maker fills assume zero exchange fee and no rebate; marketable test fills use the published straight-contract taker formula and $0.005/share slippage. Historical orders retain their original fee assumptions.
Five legacy checkpoint accounts abstain in this fresh-start run; the repository-trained research candidate is evaluated separately.
The remaining seven strategies are explicit deterministic baselines, including a no-trade account.
No authentication, private APIs, real orders, funds or wallets.

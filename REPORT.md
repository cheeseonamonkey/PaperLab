# Paper Lab — Polymarket US

Venue: **Polymarket US**, BTC 15m and 1h BRTI Up/Down. All orders **simulated**.
Accounts: **13 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-17T18:28:35+00:00**.

Research sample: **20 markets tracked / 18 officially settled / 130 settled strategy positions**.

Polls: **1025 attempts / 456 recorded / 569 skipped**. Last error: ValueError: US book timestamp stale/in future.

| Strategy | Paper cash | Realized P&L | Win rate | Brier (markets) | ΔBrier vs market | Settled | Open | Pending limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [book_imbalance](docs/bots/book_imbalance.md) | $81.49 | $-14.77 | 5/19 (26.3%) | 0.094 (n=17) | -0.002 | 19 | 2 | 0 |
| [brti_distance](docs/bots/brti_distance.md) | $66.61 | $-25.99 | 9/32 (28.1%) | 0.074 (n=17) | +0.019 | 32 | 1 | 1 |
| [brti_distance_limit](docs/bots/brti_distance_limit.md) | $66.61 | $-25.99 | 9/32 (28.1%) | 0.074 (n=17) | +0.019 | 32 | 1 | 1 |
| [btc_momentum](docs/bots/btc_momentum.md) | $100.34 | $+4.60 | 5/8 (62.5%) | 0.090 (n=17) | +0.003 | 8 | 1 | 1 |
| [btc_reversion](docs/bots/btc_reversion.md) | $79.64 | $-16.10 | 4/9 (44.4%) | 0.097 (n=17) | -0.004 | 9 | 2 | 1 |
| [conv_gru](docs/bots/conv_gru.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.216 (n=1) | -0.032 | 1 | 0 | 0 |
| [cross_asset_momentum](docs/bots/cross_asset_momentum.md) | $98.67 | $+2.39 | 4/6 (66.7%) | 0.090 (n=17) | +0.003 | 6 | 1 | 1 |
| [depthwise_tcn](docs/bots/depthwise_tcn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.244 (n=1) | -0.059 | 1 | 0 | 0 |
| [lstm](docs/bots/lstm.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.284 (n=1) | -0.099 | 1 | 0 | 0 |
| [market_implied](docs/bots/market_implied.md) | $100.00 | $+0.00 | — | 0.093 (n=17) | +0.000 | 0 | 0 | 0 |
| [research_linear](docs/bots/research_linear.md) | $76.03 | $+2.18 | 9/19 (47.4%) | 0.089 (n=11) | -0.002 | 19 | 9 | 1 |
| [skip_gru_2](docs/bots/skip_gru_2.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.256 (n=1) | -0.071 | 1 | 0 | 0 |
| [stacked_rnn](docs/bots/stacked_rnn.md) | $95.00 | $-5.00 | 0/1 (0.0%) | 0.260 (n=1) | -0.076 | 1 | 0 | 0 |

Market-midpoint benchmark: Brier 0.093 / log loss 0.318 across 17 settled markets.

Win rate is settled simulated fills only. Forecasts estimate Up probability; Brier and log loss use the official outcome.
Forecast losses average snapshots within each market, then average markets. Positive ΔBrier means improvement over the paired market midpoint; lower Brier/log loss is better.
Realized profit is **not** total equity: active positions are not marked to market.
US YES book is the market source; NO quotes are complement-derived.
Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.
Resting maker fills assume zero exchange fee and no rebate; marketable test fills use the published straight-contract taker formula and $0.005/share slippage. Historical orders retain their original fee assumptions.
Five legacy checkpoint accounts abstain in this fresh-start run; the repository-trained research candidate is evaluated separately.
The remaining seven strategies are explicit deterministic baselines, including a no-trade account.
No authentication, private APIs, real orders, funds or wallets.

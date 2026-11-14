# Paper Lab — Polymarket US

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

Win rate is settled simulated fills only. Forecasts estimate Up probability; Brier and log loss use the official outcome.
Forecast losses average snapshots within each market, then average markets. Positive ΔBrier means improvement over the paired market midpoint; lower Brier/log loss is better.
Realized profit is **not** total equity: active positions are not marked to market.
US YES book is the market source; NO quotes are complement-derived.
Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.
Entry cost uses an assumed 2% fee buffer; marketable buys additionally add $0.005/share slippage. No actual fee or rebate schedule is inferred.
Five legacy checkpoint accounts abstain in this fresh-start run; the repository-trained research candidate is evaluated separately.
The remaining seven strategies are explicit deterministic baselines, including a no-trade account.
No authentication, private APIs, real orders, funds or wallets.

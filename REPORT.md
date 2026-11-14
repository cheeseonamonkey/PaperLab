# YeNo Paper Lab — Polymarket US

Venue: **Polymarket US**, BTC 15m BRTI Up/Down. All orders **simulated**.
Accounts: **12 independent $100 bankrolls**, not a shared pool. Latest successful observation: **2026-11-14T07:39:31+00:00**.

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

Realized profit is **not** total equity: active positions are not marked to market.
US YES book is the market source; NO quotes are complement-derived.
Limit fills require a **later** observed ask crossing the resting bid and displayed size covering the order. This is an optimistic uncertainty bound, **not proof a resting order actually filled**.
Entry cost uses an assumed 2% fee buffer; marketable buys additionally add $0.005/share slippage. No actual fee or rebate schedule is inferred.
Five frozen 250K checkpoints use trained BRTI/display histories; 52 slow macro context fields are mean-imputed (not the original live feature distribution). Results are exploratory and uncalibrated.
The remaining seven strategies are explicit deterministic baselines, including a no-trade account.
No authentication, private APIs, real orders, funds or wallets.

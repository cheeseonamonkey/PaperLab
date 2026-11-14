# Strategy pages

These pages are generated views of the paper state. For account balances, fills, and forecast scores, use the linked page or [REPORT.md](../../REPORT.md) as the current record; this index intentionally stores no metric snapshots.

## Active signal families

| Strategy | What it tests | Relationship |
|---|---|---|
| [book_imbalance](book_imbalance.md) | YES-side order-book depth imbalance | Independent feature family |
| [brti_distance](brti_distance.md) | BRTI distance from strike with volatility | Shares its probability signal with `brti_distance_limit` |
| [brti_distance_limit](brti_distance_limit.md) | Same BRTI distance probability | Execution variant of `brti_distance`; not an independent forecast |
| [btc_momentum](btc_momentum.md) | Short BTC momentum against implied odds | Sign-reversed counterpart to `btc_reversion` |
| [btc_reversion](btc_reversion.md) | Counter-trend BTC signal against implied odds | Sign-reversed counterpart to `btc_momentum` |
| [cross_asset_momentum](cross_asset_momentum.md) | BTC, ETH, SOL, and XRP momentum | Independent signal family |
| [research_linear](research_linear.md) | Causal logistic adjustment to market odds using completed returns | Shared research candidate; dedicated paper account |

## Benchmarks and inactive legacy models

| Strategy | Role |
|---|---|
| [market_implied](market_implied.md) | Hold-only market benchmark; never trades |
| [conv_gru](conv_gru.md) | Inactive legacy checkpoint; abstains |
| [depthwise_tcn](depthwise_tcn.md) | Inactive legacy checkpoint; abstains |
| [lstm](lstm.md) | Inactive legacy checkpoint; abstains |
| [skip_gru_2](skip_gru_2.md) | Inactive legacy checkpoint; abstains |
| [stacked_rnn](stacked_rnn.md) | Inactive legacy checkpoint; abstains |

## How to read these pages

- [Research plan](../RESEARCH.md) defines forecast evaluation and promotion criteria.
- [Execution policy](../EXECUTION.md) explains paper order states and the later-book-crossing fill proxy.
- [Operations](../OPERATIONS.md) covers collection, persistence, fees, and workflow behavior.
- [Daily audit](../AUDIT.md) is the review checklist.
- The [paper overview](../../README.md) links the complete account comparison and its caveats.

Each strategy retains an isolated simulated bankroll. Related variants are not independent evidence. All fills remain estimates from public-book snapshots; they do not establish queue priority or real execution.

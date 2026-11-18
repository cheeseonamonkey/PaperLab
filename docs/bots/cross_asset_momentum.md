# cross_asset_momentum

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $79.56 |
| Reserved | $0.00 |
| Realized P&L | $-3.44 |
| Settled wins / losses | 5 / 6 |
| Open positions | 8 |
| Pending orders | 0 |
| Orders filled / placed | 27 / 30 |
| Recorded exit fees | $0.6554 |
| Calibration markets | 28 |
| Calibration logit offset | -0.1333 |
| Brier (markets) | 0.1111 (30) |
| ΔBrier vs market | +0.0028 |

[Order ledger](../../data/ledgers/cross_asset_momentum-orders.csv) · [Trade ledger](../../data/ledgers/cross_asset_momentum-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 5
    "Losses" : 6
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 6 | $-0.96 |
| 1h | 5 | $-2.48 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

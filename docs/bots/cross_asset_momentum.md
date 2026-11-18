# cross_asset_momentum

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $96.75 |
| Reserved | $0.00 |
| Realized P&L | $-3.25 |
| Settled wins / losses | 4 / 4 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 14 / 17 |
| Recorded exit fees | $0.5370 |
| Calibration markets | 21 |
| Calibration logit offset | -0.0373 |
| Brier (markets) | 0.0967 (23) |
| ΔBrier vs market | +0.0012 |

[Order ledger](../../data/ledgers/cross_asset_momentum-orders.csv) · [Trade ledger](../../data/ledgers/cross_asset_momentum-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 4
    "Losses" : 4
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 3 | $-0.78 |
| 1h | 5 | $-2.48 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

# brti_distance

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $66.61 |
| Reserved | $5.52 |
| Realized P&L | $-25.99 |
| Settled wins / losses | 9 / 23 |
| Open positions | 1 |
| Pending orders | 1 |
| Orders filled / placed | 57 / 67 |
| Recorded exit fees | $5.6459 |
| Calibration markets | 15 |
| Calibration logit offset | -0.0060 |
| Brier (markets) | 0.0740 (17) |
| ΔBrier vs market | +0.0186 |

[Order ledger](../../data/ledgers/brti_distance-orders.csv) · [Trade ledger](../../data/ledgers/brti_distance-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 9
    "Losses" : 23
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 15 | $-26.17 |
| 1h | 17 | $+0.18 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

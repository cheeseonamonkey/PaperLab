# brti_distance

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $37.80 |
| Reserved | $0.00 |
| Realized P&L | $-48.96 |
| Settled wins / losses | 15 / 38 |
| Open positions | 3 |
| Pending orders | 0 |
| Orders filled / placed | 91 / 105 |
| Recorded exit fees | $6.5534 |
| Calibration markets | 28 |
| Calibration logit offset | -0.1191 |
| Brier (markets) | 0.1126 (30) |
| ΔBrier vs market | +0.0012 |

[Order ledger](../../data/ledgers/brti_distance-orders.csv) · [Trade ledger](../../data/ledgers/brti_distance-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 15
    "Losses" : 38
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 32 | $-47.11 |
| 1h | 21 | $-1.86 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

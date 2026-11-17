# brti_distance_limit

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $103.16 |
| Reserved | $20.63 |
| Realized P&L | $+3.16 |
| Settled wins / losses | 2 / 1 |
| Open positions | 0 |
| Pending orders | 2 |
| Orders filled / placed | 3 / 6 |
| Recorded exit fees | $0.0000 |
| Calibration markets | 2 |
| Calibration logit offset | -0.0105 |
| Brier (markets) | 0.0568 (4) |
| ΔBrier vs market | +0.0140 |

[Order ledger](../../data/ledgers/brti_distance_limit-orders.csv) · [Trade ledger](../../data/ledgers/brti_distance_limit-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 2
    "Losses" : 1
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 3 | $+3.16 |
| 1h | 0 | $+0.00 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

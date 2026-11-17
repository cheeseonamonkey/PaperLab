# book_imbalance

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $88.14 |
| Reserved | $0.00 |
| Realized P&L | $-7.12 |
| Settled wins / losses | 0 / 4 |
| Open positions | 3 |
| Pending orders | 0 |
| Orders filled / placed | 10 / 13 |
| Recorded exit fees | $0.2120 |
| Calibration markets | 8 |
| Calibration logit offset | +0.0118 |
| Brier (markets) | 0.0943 (10) |
| ΔBrier vs market | -0.0014 |

[Order ledger](../../data/ledgers/book_imbalance-orders.csv) · [Trade ledger](../../data/ledgers/book_imbalance-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 0
    "Losses" : 4
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 2 | $-2.04 |
| 1h | 2 | $-5.08 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

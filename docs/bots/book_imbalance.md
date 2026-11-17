# book_imbalance

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $81.49 |
| Reserved | $0.00 |
| Realized P&L | $-14.77 |
| Settled wins / losses | 5 / 14 |
| Open positions | 2 |
| Pending orders | 0 |
| Orders filled / placed | 35 / 40 |
| Recorded exit fees | $1.1617 |
| Calibration markets | 15 |
| Calibration logit offset | -0.0150 |
| Brier (markets) | 0.0943 (17) |
| ΔBrier vs market | -0.0016 |

[Order ledger](../../data/ledgers/book_imbalance-orders.csv) · [Trade ledger](../../data/ledgers/book_imbalance-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 5
    "Losses" : 14
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 8 | $-4.04 |
| 1h | 11 | $-10.73 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

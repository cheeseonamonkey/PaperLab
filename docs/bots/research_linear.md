# research_linear

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $76.03 |
| Reserved | $0.00 |
| Realized P&L | $-23.97 |
| Settled wins / losses | 9 / 19 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 29 / 31 |
| Recorded exit fees | $0.0138 |
| Calibration markets | 17 |
| Calibration logit offset | -0.0742 |
| Brier (markets) | 0.0985 (17) |
| ΔBrier vs market | -0.0021 |

[Order ledger](../../data/ledgers/research_linear-orders.csv) · [Trade ledger](../../data/ledgers/research_linear-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 9
    "Losses" : 19
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 10 | $-23.61 |
| 1h | 18 | $-0.35 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

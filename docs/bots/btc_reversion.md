# btc_reversion

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $90.86 |
| Reserved | $0.00 |
| Realized P&L | $-9.14 |
| Settled wins / losses | 6 / 6 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 19 / 21 |
| Recorded exit fees | $0.5704 |
| Calibration markets | 21 |
| Calibration logit offset | -0.0477 |
| Brier (markets) | 0.1001 (23) |
| ΔBrier vs market | -0.0021 |

[Order ledger](../../data/ledgers/btc_reversion-orders.csv) · [Trade ledger](../../data/ledgers/btc_reversion-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 6
    "Losses" : 6
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 3 | $-14.96 |
| 1h | 9 | $+5.82 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

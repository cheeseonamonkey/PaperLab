# btc_momentum

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $98.09 |
| Reserved | $0.00 |
| Realized P&L | $-1.91 |
| Settled wins / losses | 5 / 5 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 17 / 18 |
| Recorded exit fees | $0.7525 |
| Calibration markets | 21 |
| Calibration logit offset | -0.0376 |
| Brier (markets) | 0.0964 (23) |
| ΔBrier vs market | +0.0015 |

[Order ledger](../../data/ledgers/btc_momentum-orders.csv) · [Trade ledger](../../data/ledgers/btc_momentum-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 5
    "Losses" : 5
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 4 | $+2.43 |
| 1h | 6 | $-4.34 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

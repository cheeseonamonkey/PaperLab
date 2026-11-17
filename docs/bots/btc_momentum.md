# btc_momentum

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $103.79 |
| Reserved | $0.00 |
| Realized P&L | $+3.79 |
| Settled wins / losses | 1 / 0 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 1 / 1 |
| Recorded exit fees | $0.0000 |
| Calibration markets | 2 |
| Calibration logit offset | -0.0164 |
| Brier (markets) | 0.0627 (4) |
| ΔBrier vs market | +0.0081 |

[Order ledger](../../data/ledgers/btc_momentum-orders.csv) · [Trade ledger](../../data/ledgers/btc_momentum-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 1
    "Losses" : 0
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 1 | $+3.79 |
| 1h | 0 | $+0.00 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

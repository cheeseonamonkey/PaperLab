# btc_reversion

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $86.80 |
| Reserved | $0.00 |
| Realized P&L | $-13.20 |
| Settled wins / losses | 0 / 2 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 2 / 2 |
| Recorded exit fees | $0.0000 |
| Calibration markets | 2 |
| Calibration logit offset | -0.0205 |
| Brier (markets) | 0.0822 (4) |
| ΔBrier vs market | -0.0114 |

[Order ledger](../../data/ledgers/btc_reversion-orders.csv) · [Trade ledger](../../data/ledgers/btc_reversion-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 0
    "Losses" : 2
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 2 | $-13.20 |
| 1h | 0 | $+0.00 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

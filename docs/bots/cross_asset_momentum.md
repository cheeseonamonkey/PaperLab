# cross_asset_momentum

Paper account · simulated orders

| Metric | Value |
|---|---:|
| Cash | $103.26 |
| Reserved | $0.00 |
| Realized P&L | $+3.26 |
| Settled wins / losses | 1 / 0 |
| Open positions | 0 |
| Pending orders | 0 |
| Orders filled / placed | 1 / 2 |
| Recorded exit fees | $0.0000 |
| Calibration markets | 8 |
| Calibration logit offset | +0.0162 |
| Brier (markets) | 0.0895 (10) |
| ΔBrier vs market | +0.0035 |

[Order ledger](../../data/ledgers/cross_asset_momentum-orders.csv) · [Trade ledger](../../data/ledgers/cross_asset_momentum-trades.csv) · [Overview](../../REPORT.md)

```mermaid
pie title Settled simulated trades
    "Wins" : 1
    "Losses" : 0
```

## Results by market horizon

| Horizon | Closed trades | Realized P&L |
|---|---:|---:|
| 15m | 1 | $+3.26 |
| 1h | 0 | $+0.00 |

## Research

The shared research candidate is evaluated separately; it is not deployed to this account. [Latest experiments](../research/latest.md) · [Research plan](../RESEARCH.md)

Limit fills are estimates based on later observed book crossings; queue priority is unknown.

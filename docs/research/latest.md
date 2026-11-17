# Research experiments

Status: **trained**. Markets: 242. Rows: 5739.

Archive backfill is excluded. Bootstrap and live sources: {'bootstrap': 5700, 'live': 39}.

Candidates are evaluated chronologically and are not automatically promoted.

| Candidate | Brier | Market Brier | Validation markets |
|---|---:|---:|---:|
| linear | 0.1531 | 0.1541 | 74 |
| market_only | 0.1534 | 0.1541 | 74 |
| regularized | 0.1531 | 0.1541 | 74 |
| tanh_returns | 0.1532 | 0.1541 | 74 |

## Baseline by horizon and source

| Horizon / source | Markets | Brier | Market Brier | Log loss | Market log loss |
|---|---:|---:|---:|---:|---:|
| 15m:bootstrap | 56 | 0.1685 | 0.1692 | 0.4905 | 0.4919 |
| 15m:live | 3 | 0.0911 | 0.0944 | 0.3241 | 0.3322 |
| 1h:bootstrap | 14 | 0.1163 | 0.1182 | 0.3720 | 0.3760 |
| 1h:live | 2 | 0.0040 | 0.0046 | 0.0616 | 0.0661 |

Validation is repeatedly reused; small groups are descriptive and do not establish an edge.

# Research experiments

Status: **trained**. Markets: 261. Rows: 6220.

Archive backfill is excluded. Bootstrap and live sources: {'bootstrap': 5700, 'live': 520}.

Candidates are evaluated chronologically and are not automatically promoted.

| Candidate | Brier | Market Brier | Validation markets |
|---|---:|---:|---:|
| linear | 0.0716 | 0.0734 | 4 |
| market_only | 0.0717 | 0.0734 | 4 |
| regularized | 0.0716 | 0.0734 | 4 |
| tanh_returns | 0.0743 | 0.0734 | 4 |

## Baseline by horizon and source

| Horizon / source | Markets | Brier | Market Brier | Log loss | Market log loss |
|---|---:|---:|---:|---:|---:|
| 15m:live | 3 | 0.0945 | 0.0968 | 0.3271 | 0.3323 |
| 1h:live | 1 | 0.0029 | 0.0033 | 0.0506 | 0.0543 |

Validation is repeatedly reused; small groups are descriptive and do not establish an edge.

# Research experiments

Status: **trained**. Markets: 248. Rows: 5831.

Archive backfill is excluded. Bootstrap and live sources: {'bootstrap': 5700, 'live': 131}.

Candidates are evaluated chronologically and are not automatically promoted.

| Candidate | Brier | Market Brier | Validation markets |
|---|---:|---:|---:|
| linear | 0.1115 | 0.1077 | 6 |
| market_only | 0.1116 | 0.1077 | 6 |
| regularized | 0.1114 | 0.1077 | 6 |
| tanh_returns | 0.1110 | 0.1077 | 6 |

## Baseline by horizon and source

| Horizon / source | Markets | Brier | Market Brier | Log loss | Market log loss |
|---|---:|---:|---:|---:|---:|
| 15m:live | 4 | 0.1057 | 0.1059 | 0.3672 | 0.3677 |
| 1h:live | 2 | 0.1230 | 0.1112 | 0.3873 | 0.3619 |

Validation is repeatedly reused; small groups are descriptive and do not establish an edge.

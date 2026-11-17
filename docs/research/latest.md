# Research experiments

Status: **trained**. Markets: 255. Rows: 6082.

Archive backfill is excluded. Bootstrap and live sources: {'bootstrap': 5700, 'live': 382}.

Candidates are evaluated chronologically and are not automatically promoted.

| Candidate | Brier | Market Brier | Validation markets |
|---|---:|---:|---:|
| linear | 0.1011 | 0.0994 | 13 |
| market_only | 0.1010 | 0.0994 | 13 |
| regularized | 0.1010 | 0.0994 | 13 |
| tanh_returns | 0.1009 | 0.0994 | 13 |

## Baseline by horizon and source

| Horizon / source | Markets | Brier | Market Brier | Log loss | Market log loss |
|---|---:|---:|---:|---:|---:|
| 15m:live | 9 | 0.0889 | 0.0899 | 0.3132 | 0.3155 |
| 1h:live | 4 | 0.1286 | 0.1209 | 0.3996 | 0.3834 |

Validation is repeatedly reused; small groups are descriptive and do not establish an edge.

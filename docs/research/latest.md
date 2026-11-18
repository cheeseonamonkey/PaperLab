# Research experiments

Status: **trained**. Markets: 268. Rows: 6473.

Archive backfill is excluded. Bootstrap and live sources: {'bootstrap': 5700, 'live': 773}.

Candidates are evaluated chronologically and are not automatically promoted.

| Candidate | Brier | Market Brier | Validation markets |
|---|---:|---:|---:|
| linear | 0.1279 | 0.1324 | 11 |
| market_only | 0.1284 | 0.1324 | 11 |
| regularized | 0.1280 | 0.1324 | 11 |
| tanh_returns | 0.1346 | 0.1324 | 11 |

## Baseline by horizon and source

| Horizon / source | Markets | Brier | Market Brier | Log loss | Market log loss |
|---|---:|---:|---:|---:|---:|
| 15m:live | 8 | 0.1691 | 0.1746 | 0.4848 | 0.4972 |
| 1h:live | 3 | 0.0181 | 0.0201 | 0.1190 | 0.1268 |

Validation is repeatedly reused; small groups are descriptive and do not establish an edge.

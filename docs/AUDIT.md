# Daily research check-in

Review results by 15m and 1h separately.

- **Data:** latest observation and source age; missing/skipped polls; bootstrap coverage; archive remains excluded; Actions gaps or failed commits.
- **Forecast:** market-level Brier/log loss against the same-market midpoint; settled market counts and date range.
- **Execution:** orders placed, filled by proxy, expired, and open; fill assumptions; gross P&L, fees, net P&L, drawdown, exposure.
- **Strategy roster:** mark active, abstaining, benchmark, duplicate, or mirror. Do not count duplicate/mirror variants as independent evidence.
- **Research:** candidates tried, validation split, sample size, uncertainty, and whether a holdout has been exposed. No automatic promotion.
- **Next step:** one small, falsifiable experiment with an unchanged baseline.

Stop and investigate stale feeds, missing state, unexplained account changes, or a sudden rise in errors before interpreting performance. Actions are scheduled jobs, not a guaranteed continuous process; check gaps explicitly.

Use the [strategy index](bots/README.md) to identify mirrored or shared-signal variants before counting evidence. Check the [research plan](RESEARCH.md#strategy-descendants-and-forks) before considering any roster expansion.

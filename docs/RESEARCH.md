# Research plan

## Current loop

Each scheduled run evaluates small, deterministic feature and regularization variants against a market-implied baseline. It records chronological validation results; no candidate is automatically promoted. Inputs include completed-minute BTC, ETH, SOL, and XRP returns where available. The one-time two-day bootstrap shares the normal observation path; settled live observations are added over time. The separate historical archive is excluded from training.

The current research model is not connected to paper execution. The optional OpenRouter/Pi process can propose bounded experiments for review; it does not edit or deploy strategy code. Keep model use optional and cost-bounded. Free-model availability is not guaranteed.

## Safe progression

1. Improve data quality and record source timestamps, quotes, depth, and (if available) trade prints. Preserve immutable raw observations for replay.
2. Compare features and simple transforms on identical chronological splits. Keep 15m and 1h outcomes separate; report Brier/log loss versus the paired market forecast and net paper P&L after execution costs.
3. Add execution experiments only when the simulator models their costs and failure cases. A limit fill requires more than a touch: queue ahead and trade flow matter.
4. Later, allow parameter proposals in a constrained schema. Evaluate out of sample, record every candidate and parent, and require human review before changing the live paper roster. Generated code, if ever tested, belongs in a resource-limited isolated process; execution and risk rules remain fixed.
5. Reserve a final forward period that researchers cannot inspect or tune against. Repeatedly selecting the best of many candidates creates winner’s curse; a holdout used repeatedly stops being a holdout.

## Metrics and promotion

Show forecast quality separately from execution: market-level Brier and log loss; filled/unfilled/cancelled orders; fill proxy; gross and net P&L; fees and spread cost; drawdown; exposure; and results by horizon and market regime. Always show sample counts and uncertainty. Do not promote on a raw win rate or one lucky run. With small samples, report a confidence interval for mean net return per settled trade and wait for a predeclared minimum sample; choose that threshold before inspecting results.

## Formulas

Binary Brier score for forecast (p_i) and settlement (y_i\in\{0,1\}):

`Brier = (1/n) Σ (pᵢ − yᵢ)²`; lower is better. Compare on the same markets against market midpoint forecasts.

Top-`k` order-book imbalance:

`OBIₖ = (Σ bid size₁…ₖ − Σ ask size₁…ₖ) / (Σ bid size₁…ₖ + Σ ask size₁…ₖ)`.

It is a descriptive feature, not proof of direction or toxicity. VPIN-style volume buckets require reliable classified trade flow; current data does not support claiming VPIN.

Avellaneda–Stoikov reservation-price reference:

`r = s − q γ σ² (T − t)`

Here `γ` is risk aversion, `q` inventory, `σ²` price variance, and `T−t` time remaining. This is a market-making model reference, not a validated strategy for binary contracts or this simulator.

## Reading

- [Avellaneda & Stoikov, *High-frequency trading in a limit order book*](https://math.nyu.edu/~avellane/HighFrequencyTrading.pdf)
- [Polymarket US data guide](https://docs.polymarket.us/data-guide/overview)
- [US exchange fee notice (Oct. 23, 2026)](https://polymarketexchange.com/files/notices/Exchange%20Notice%20-%20Amendment%20to%20Taker%20and%20Maker%20Rebate%20Tiers%20%282026.10.23%29.pdf)

Fee schedules are venue- and date-specific. The current repo uses the documented standard maker fee assumption of zero without rebates; its straight-taker coefficient is documented in [Operations](OPERATIONS.md). Recheck the official schedule before interpreting simulated net returns.

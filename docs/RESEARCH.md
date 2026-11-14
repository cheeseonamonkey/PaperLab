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

## Strategy descendants and forks

Creating a strategy fork (a new child variant or paper account) is currently **disabled**. The paper roster is fixed; the workflow does not spawn, train, or promote account descendants automatically. Keep candidate ideas in the review-only proposal path and compare them offline first. If a future fork is approved, give it a documented parent hypothesis, a distinct name, an isolated bankroll, identical risk controls, and a predeclared evaluation split. Related variants must remain labeled as dependent evidence; changing a name does not create an independent experiment.

See the [strategy index](bots/README.md) for current signal relationships and the [execution policy](EXECUTION.md) for account-level constraints.

## Per-bot online calibration

Each active account tracks its own forecast error after official settlement. Each resolved market gets one update, regardless of snapshot count. An offset is accumulated with learning rate 0.05 and bounded to ±0.15 logit; it is only applied after 20 resolved markets. It learns from forecasts even when no order fills, so signal evaluation and trading execution stay separate. This is a small experimental calibration, not an optimized strategy or a guarantee of better forecasts.

The default minimum edge is 0.045 (formerly 0.05). `MIN_EDGE`, `STRATEGY_MIN_EDGE`, `CALIBRATION_WARMUP`, `CALIBRATION_RATE`, and `CALIBRATION_MAX_LOGIT` in paper.py are explicit manual knobs. Risk limits remain separate. No parameter is selected from a small profit sample and no automatic forks are created.

## Exo research

The existing automated proposal path uses Pi and OpenRouter; it is **not** the Exo harness. [Exo](https://github.com/exoharness/exo) is a separate agent framework with a protected event history and editable policies; its [research paper](https://arxiv.org/abs/2611.00463) describes results on other tasks, not trading performance. Its upstream setup requires Docker and a toolchain, and gives the agent substantial self-modification capability. It is not installed or enabled here.

A later integration should preserve the repo as the canonical record, restrict proposals to bounded experiment configurations, log outcomes and failures, and require chronological unseen evaluation before any strategy changes. Repeated experiments can overfit even when each has a holdout; see [Probability of Backtest Overfitting](https://escholarship.org/uc/item/4w1110bb). Online calibration research is relevant but does not validate our simple update: [Online Learning in Betting Markets](https://proceedings.mlr.press/v235/zhu24k.html). Continue comparing signal loss to the market separately from paper P&L.

# Execution policy

Paper simulation only. The runner has no authenticated order path.

| Action | Current simulation | Research direction |
|---|---|---|
| Entry | Resting limit buy; cash reserved; expires if unfilled | Post-only intent, short TTL, cancel on stale or adverse cross-asset move |
| Take profit | No new passive take-profit order; existing resting sells may fill | Add passive take-profit policy |
| Stop or urgent exit | Simulated IOC at observed best bid with taker fee; no fill if displayed top-level depth is insufficient | Add explicit floor, partial fills, and latency |
| Expiry | Official binary settlement | Compare hold-to-settlement with a defined exit cutoff |

A limit price caps the execution price only if an order fills. It does not guarantee a fill, maker status, queue priority, or protection from adverse selection. “Post-only” is an exchange instruction; this paper simulator cannot certify that status.

## Current fill proxy

A resting entry is credited only on a later observation when the displayed opposing best price crosses the limit and displayed size is sufficient. A sell uses a later bid crossing the offer. This is a book-crossing proxy, not queue simulation: trade prints, queue ahead, hidden liquidity, event ordering, and network latency are not modeled. It can miss fills and can also misstate their quality. Do not call it a validated backtest.

Urgent exits are simulated at the observed best bid, only when displayed top-level depth covers the entire position. They charge the modeled taker fee; otherwise the position remains open. This is an immediate, all-or-none approximation: it has no latency, partial fills, or deeper book sweep, and does not guarantee real execution.

## Risk and lifecycle

Entry size uses one-quarter Kelly on modeled binary-contract edge, capped at 10% of current account equity per order and 30% aggregate committed exposure. Equity is cash plus cost basis of open positions; pending entry reservations count toward exposure. This keeps limits proportional after simulated gains or losses. Cost basis is not a live mark, and this remains a paper experiment rather than a validated or live sizing rule.

Use explicit states: `FLAT → ENTERING → OPEN → EXITING → SETTLED`; unfilled entry expiry returns to `FLAT`. Before adding live or more detailed simulation, reject stale data, block new entries near expiry, cap exposure and order rate, and make cancel/fill races idempotent. A stale-data rule must use source event time where available; receive time alone hides feed age.

The roster and account boundaries are described in the [strategy index](bots/README.md). New child strategies are currently disabled; see [research progression](RESEARCH.md#strategy-descendants-and-forks).

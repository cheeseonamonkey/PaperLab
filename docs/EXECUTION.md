# Execution policy

Paper simulation only. The runner has no authenticated order path.

| Action | Current simulation | Research direction |
|---|---|---|
| Entry | Resting limit buy; cash reserved; expires if unfilled | Post-only intent, short TTL, cancel on stale or adverse cross-asset move |
| Take profit | Resting limit sell | Keep passive |
| Stop or urgent exit | No guaranteed exit; position may settle | Test marketable IOC limit with a hard price floor and taker fee |
| Expiry | Official binary settlement | Compare hold-to-settlement with a defined exit cutoff |

A limit price caps the execution price only if an order fills. It does not guarantee a fill, maker status, queue priority, or protection from adverse selection. “Post-only” is an exchange instruction; this paper simulator cannot certify that status.

## Current fill proxy

A resting entry is credited only on a later observation when the displayed opposing best price crosses the limit and displayed size is sufficient. A sell uses a later bid crossing the offer. This is a book-crossing proxy, not queue simulation: trade prints, queue ahead, hidden liquidity, event ordering, and network latency are not modeled. It can miss fills and can also misstate their quality. Do not call it a validated backtest.

Urgent exit execution is a separate experiment. If added, model a marketable IOC limit against visible depth, reject fills below its price floor, charge the applicable taker fee, and leave any unfilled remainder open. “Marketable limit” still cannot guarantee full execution in a thin book.

## Risk and lifecycle

Use explicit states: `FLAT → ENTERING → OPEN → EXITING → SETTLED`; unfilled entry expiry returns to `FLAT`. Before adding live or more detailed simulation, reject stale data, block new entries near expiry, cap exposure and order rate, and make cancel/fill races idempotent. A stale-data rule must use source event time where available; receive time alone hides feed age.

# Execution policy

Paper simulation only; no authenticated order path, wallet, or real funds.

## Current historical-hour replay

The hourly workflow fetches the previous completed UTC hour and processes available price observations chronologically. **Historical display prices are not executable bid/ask quotes or order-book depth.**

- **Entry:** compare modeled probability against the displayed price plus $0.005/share slippage and the modeled taker fee. Reserve cash; a paper buy can fill only on a later historical observation, at that later price. If the required cost exceeds the reservation, cancel it.
- **Exit:** sell eligible open positions at the later displayed price minus $0.005/share slippage and the modeled taker fee. Without a later observation, positions can remain open until official settlement.
- **Expiry and settlement:** unfilled entry reservations expire; binary contract payout is determined only by the Polymarket US settlement endpoint (0/1).
- **Unavailable inputs:** strategies requiring missing historical order-book depth abstain; no synthetic spread, liquidity, queue position, or maker rebate is fabricated.

These are hypothetical price-proxy fills, not a validated backtest. An indicative display price does not establish actual executable liquidity or latency. Previously recorded live-book crossing fills retain their original accounting and remain labeled as legacy assumptions.

## Risk and lifecycle

Every account starts with an independent $100 paper bankroll. One-quarter Kelly sizing is capped at **10% of current account equity per entry** and **30% aggregate committed exposure**, including pending entry reservations. Multiple simultaneous positions may coexist; repeated opportunities for the same market are limited to one decision per minute.

A paper entry passes `PENDING → OPEN → EXITED / SETTLED`, or `PENDING → CANCELLED / EXPIRED`. State and market outcomes must be idempotent across hourly workflow retries. Do not reset or reinterpret historical account balances when changing execution modes.

## Legacy live-book observations

Older trades used a later bid/ask crossing with displayed size as an optimistic hypothetical maker fill (zero assumed maker fee/rebate). Urgent exits used immediate displayed best-bid depth and modeled taker fees. A crossing does not prove queue priority or actual fill. The previous live collector is no longer the scheduled workflow.

The fee coefficient and source-specific details are documented in [Operations](OPERATIONS.md). No configuration here authorizes real orders.

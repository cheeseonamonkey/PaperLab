# YeNo Paper Lab

Public, auditable **paper-only** experiment trading [Polymarket](https://polymarket.com/) **Bitcoin 15-minute Up/Down** contracts. Starts with **$100 simulated cash**. GitHub Actions observes markets approximately every **8 hours** (00:11 / 08:11 / 16:11 UTC), settles previous trades from official results, and commits a transparent ledger.

**No brokerage credentials, order submission, wallet, signing, deposits, real funds, leverage, or production trading paths.** The only required GitHub secret is optional and is used solely for AI research.

**[Current paper results](REPORT.md)** · [Trade ledger](data/ledger.json) · [Scheduled runs](../../actions)

## How it works

1. Read current/next 15-minute BTC Up/Down market metadata from Polymarket's public Gamma API.
2. Read **both** outcome best asks and available top-level size from the public CLOB.
3. Fetch recent BTC-USD spot candles from Coinbase. The first baseline is a simplistic momentum heuristic, **not** a validated edge.
4. Pick a side using the committed [champion parameters](strategies/champion.json). Spend up to **$5** on apparent modeled edge or **$1** for explicit exploration. All spends include modeled fees. Never exceed simulated cash.
5. Check best-ask displayed liquidity before recording a hypothetical entry. Never claim a true live fill. Skip missing/inconsistent data.
6. On subsequent runs, settle only when Gamma reports the market **closed and resolved** with an exact binary outcome. An unresolved/disputed market stays pending.
7. Commit [historical observations and trades](data/ledger.json) back to the repository. Prevent duplicate market entries even on manual reruns.

**Execution assumptions:** observed best ask plus **$0.005/share** simulated slippage and **2%** of notional modeled entry fees. These are intentionally simple buffers, **not** Polymarket's actual dynamic fees or a guaranteed executable quote. Quotes are collected sequentially, not atomically. Reported equity excludes unrealized mark-to-market changes.

A scheduled run is a **single market observation**, not continuous monitoring of every 15-minute market; approximately three opportunities/day. GitHub may delay/drop scheduled runs.

## AI research (optional)

An independent Actions workflow runs ~32 minutes after each paper observation and can use **Pi + OpenRouter's** zero-priced **openrouter/free** router. It uses one GitHub Actions secret:

1. Generate an OpenRouter key, preferably with a restricted spending limit.
2. Open **Settings → Secrets and variables → Actions → New repository secret**.
3. Add exactly **OPENROUTER_API_KEY**. No need for any exchange key.

Research activates only after at least **40 official resolved observations**, including at least 12 chronological holdout observations. Until then, it silently collects trustworthy examples rather than fabricating a backtest.

Pi receives historical **training** observations and proposes **one bounded JSON parameter configuration** per run. It runs with read-only agent tools. The evaluation script tests against a later, withheld chronological segment using the **same strategy/execution math** as paper trading. Proposals are accepted only if they meet minimum held-out improvement, drawdown, and participation thresholds.

Accepted candidate configs are saved under [research/proposals](research/proposals/); they **do not self-deploy**. You review and explicitly change champion.json. Real-world predictive power is unproven; repeatedly tuning to a fixed holdout is still a multiple-testing risk.

**Why not Evo immediately?** Evo's full code-editing tree search requires a more mature benchmark and wider testing surface. Starting with bounded Pi parameter experiments avoids allowing free-router agents to edit execution or settlement logic. When observations accumulate, Evo can be added on a non-deploying research branch with an explicit benchmark and regression gates.

## Run locally

Requires **Python 3.12+**, no Python dependencies.

```bash
python -m unittest discover -s tests -v
python yeno.py run         # fetch public feeds, update ledger + report
python yeno.py report      # regenerate REPORT.md
python research.py ready   # 'collecting' until enough resolved observations
```

## Files

| File | Responsibility |
|---|---|
| yeno.py | Market observation, paper entry, official settlement, reporting |
| research.py | Chronological research split, bounded candidate validation |
| data/ledger.json | Persistent public observation/position history |
| strategies/champion.json | Only active paper strategy |
| research/proposals/ | Validated suggestions; **never automatically active** |
| .github/workflows/paper.yml | 8-hour public-data-only paper cycle |
| .github/workflows/research.yml | Optional 8-hour Pi research after sample threshold |
| .github/workflows/tests.yml | Unit tests on pushes and pull requests |

**Disclaimer:** Simulated research, not investment advice. No backtest proves future profitability. Never put real-money API keys or a signing wallet in this repo or its Actions secrets.

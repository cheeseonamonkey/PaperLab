# PaperLab paper-only guardrails

- Canonical source: https://github.com/cheeseonamonkey/PaperLab
- VENUE = Polymarket US (gateway.polymarket.us), BTC BRTI 15-minute and 1-hour contracts. Do not use international Gamma/CLOB API or treat those markets as equivalent.
- Paper only, $100 independent initial cash for each of 13 strategies. New strategy accounts must not inherit another strategy's history. Do not implement authentication, wallet signing, order submission, private endpoints, leverage, or live funds.
- Keep identical equity-based sizing controls across accounts: one-quarter Kelly sizing, at most 10% of account equity per order and 30% total committed exposure. This is a paper-simulation constraint, not a live trading recommendation.
- Five 250K PyTorch checkpoints and scalers originate from the preserved YeNoVolumeLab US 20-model screen; use their exact feature ordering, dimensionality, and causal timestamps. The 40-architecture run had only 1/40 checkpoints completed, not a winning 40-way study.
- Model context currently mean-imputes 52 macro features; expose this deviation and DO NOT claim equivalent trained feature distribution or proven edge.
- The existing hourly CI schedule temporarily downloads the historical US BTC archive in resumable batches. The previous-hour replay remains manual. No live polling loop, extra workflow/scheduler, or synthetic historical order books. Historical executions are delayed price-based paper proxies with taker fees/slippage, not confirmed fills. Legacy book-crossing trades retain their original assumptions.
- Settlement is ONLY from /v1/markets/{slug}/settlement returning 0 or 1; no third-party BTC price proxy.
- New strategies get isolated paper portfolios; no shared capital or state leaks. Keep identical risk controls.
- The Pi research workflow may write review-only hypotheses to research/proposals, never mutate execution, account balances, model checkpoints, or production strategy selection.
- Auto-research (owner-approved 2026-11-28, supersedes the fixed-roster rule): the scheduled hourly run is the research loop (collect → replay → train/evaluate). Non-baseline candidates in train_research.CANDIDATES that clear the predeclared fork policy (train_research.evaluate_fork: Brier margin, minimum validation markets, 3-run streak, caps of 40 forks / 50 total accounts) spawn frozen fork paper accounts via strategies/roster.json — isolated $100 bankrolls, identical risk controls, paper-only like every other account. The baseline is never auto-promoted and fork history is never deleted.
- State and market observations are versioned in the repo, with compressed per-day observations. Preserve and test backward compatibility before schema changes.
- Run python -m unittest discover -s tests -v and python -m py_compile on affected files.

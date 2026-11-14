# YeNo US paper-only guardrails

- Canonical source: https://github.com/cheeseonamonkey/YeNoPaperLab
- VENUE = Polymarket US (gateway.polymarket.us), BTC BRTI 15-minute contracts. Do not use international Gamma/CLOB API or treat those markets as equivalent.
- Paper only, $100 independent initial cash for each of 13 strategies. New strategy accounts must not inherit another strategy's history. Do not implement authentication, wallet signing, order submission, private endpoints, leverage, or live funds.
- Keep identical equity-based sizing controls across accounts: one-quarter Kelly sizing, at most 5% of account equity per order and 20% total committed exposure. This is a paper-simulation constraint, not a live trading recommendation.
- Five 250K PyTorch checkpoints and scalers originate from the preserved YeNoVolumeLab US 20-model screen; use their exact feature ordering, dimensionality, and causal timestamps. The 40-architecture run had only 1/40 checkpoints completed, not a winning 40-way study.
- Model context currently mean-imputes 52 macro features; expose this deviation and DO NOT claim equivalent trained feature distribution or proven edge.
- Limit orders are purely hypothetical cross-on-later-snapshot fills; never assume posted maker rebates or queue priority. A cross does not prove a real fill.
- Settlement is ONLY from /v1/markets/{slug}/settlement returning 0 or 1; no third-party BTC price proxy.
- New strategies get isolated paper portfolios; no shared capital or state leaks. Keep identical risk controls.
- The Pi research workflow may write review-only hypotheses to research/proposals, never mutate execution, account balances, model checkpoints, or production strategy selection.
- State and market observations are versioned in the repo, with compressed per-day observations. Preserve and test backward compatibility before schema changes.
- Run python -m unittest discover -s tests -v and python -m py_compile on affected files.

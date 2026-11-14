# Autonomous research guardrails

This is a PAPER-ONLY experiment. There are no real-money execution paths.

- Never implement signing, wallets, exchange order submission, private REST endpoints, leverage, or real-money integrations.
- Do not alter the ledger format, official-only settlement, trade-size limits, or execution-cost assumptions in autonomous research.
- Never infer market resolution from spot prices or backfill historical snapshots with prices unavailable at observation time.
- Only propose edits to strategies/champion.json for a human reviewer after independent validation. The automated Pi research workflow writes to research/proposals only.
- Preserve chronological train/holdout isolation; never train on the withheld period. Multiple repeated holdout queries can overfit.
- Do not enable paid-model fallback, run shell tools in an LLM agent, or expose the OpenRouter key in repository contents/logs.
- Before changing the engine, update tests and run python -m unittest discover -s tests -v.

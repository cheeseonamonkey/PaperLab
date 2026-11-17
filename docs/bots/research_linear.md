# research_linear

Dedicated paper account for the causal market-relative logistic candidate. It uses the current market midpoint plus completed BTC, ETH, SOL, XRP, and timestamped SP500 returns when available. The inference path abstains when the model is missing, trained after the market window began, uses incompatible feature dimensions, or receives an observation outside the active US market window.

The model is research-only and has no authenticated execution path. Orders use the same one-quarter Kelly sizing as other accounts: 10% of account equity maximum per order and 30% aggregate committed exposure maximum. The account starts with an independent $100 paper bankroll; prior v2 account histories are preserved when it is added.

# Reproducible external Polymarket research tools

All sources are separately cloned, unmodified and intentionally NOT committed inside this project. The project tracks the installer and exact upstream SHA pins. `scripts/setup-replay-engines.sh` recreates them.

| Local directory | Upstream URL | Pinned commit | Purpose |
| --- | --- | --- | --- |
| `pm-hftbacktest` | https://github.com/mileswangs/pm-hftbacktest | `7f08791d2efe830e10ec80a8dc91956e0b0f65fe` | Tick-level execution replay; `pm-hftbacktest==1.0.10` installed |
| `marketlens-python` | https://github.com/marketlenstrade/marketlens-python | `380de6e458117eb8bacb011ef4d5f23991833c16` | Separate Python L2 reconstruction and fill simulator; `marketlens==1.8.12` installed editable |
| `marketlens-data` | https://github.com/marketlenstrade/polymarket-historical-data | `6eb9b8efda545eddafb2a8f75acb4bcbca6db019` | Independently collected June 15 BTC 5m/15m/hourly histories, sparse checkout limited to BTC day |

Other research data: PMData BTC five-minute free August 8 Parquet files, sourced from https://huggingface.co/datasets/mileswangs/polymarket-btc-updown-5m-orderbook-tick-data (CC BY 4.0). `data/raw/polymarket/pmdata-2026-08-08/`. Includes all 288 markets' full-book snapshots, price_change messages, trades and Chainlink TWAP; full 14-day dataset remains available upstream but was NOT all downloaded. Source datasets have different sample dates and cannot be compared as if they describe the same session.

**Dependency safety:** third-party software is isolated inside `.venv-replay`, not installed system-wide. Run paper-only local simulations; never connect wallets or give secrets. These repositories are not audited by our project.

**Discarded candidate:** https://github.com/luuhongyii/polymarket-backtest at `16f3068` had a missing `polymarket_backtest.data` package; its public source could not import cleanly and was excluded, not patched or counted as a passing independent evaluator.

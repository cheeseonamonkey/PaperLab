# YeNo US — 20 architecture screening candidates

Prepared 2026-11-05. This suite is a **parameter-matched model factory**, not a claimed trading benchmark.

## Input contract

- 120 past observations at 30-second sampling = 1 hour of numeric history, 24 features per observation. Missingness and sample gap are inputs; last feature is nonnegative normalized sample gap for the CfC-inspired cell.
- 12 causally available public-market context features, such as contract time remaining, reference-price distance, market volume, volume delta, spread, liquidity/depth delta, 15m/1h identifier, and macro regime. Inputs must only use values known at the specific decision instant.
- Two supervised binary logits (15-minute and 1-hour Up), plus one auxiliary 24-dimensional next-state head used in self-supervised pretraining. No samples of future windows may enter either input.
- User inventory, own filled volume, available cash, open limit orders and realized P&L belong in a separate **execution policy**, NOT the market probability model. This prevents a policy feedback loop from pretending the user's own inventory predicts external settlement.

## Parameter-matched zoo

1. GRU
2. Two-layer GRU
3. LSTM
4. Attention-pooled GRU
5. Dilated causal TCN
6. Depthwise dilated TCN
7. Gated WaveNet-inspired CNN
8. Causal CNN→GRU
9. Tiny Transformer
10. Patch-token Transformer
11. iTransformer-inspired channel tokens
12. Time-series Mixer
13. Three-scale temporal mixer
14. TiDE-inspired dense encoder
15. Fourier-domain mixer (FITS-inspired; not FITS reproduction)
16. Diagonal state-space memory (not S4/Mamba)
17. Continuous-time gated RNN (CfC-inspired; not official CfC)
18. Fixed-basis RBF KAN-inspired nonlinear mixer (not spline KAN)
19. Regime-gated mixture of experts with public macro context
20. Trend/seasonal DLinear residual with nonlinear head

Built only from PyTorch; no custom CUDA kernels. Every model has the same outputs. Widths are automatically selected by a 120k parameter budget (no unused padding); initial count range measured between 113.5k and 126k. Equivalent parameter count does NOT imply equal FLOPs, wall time, training stability, effective receptive field, or sample efficiency.

## Architectural research

- DeepLOB CNN-LSTM order-book representation: https://arxiv.org/abs/1808.03668
- TSMixer (TMLR 2023): https://research.google/pubs/tsmixer-an-all-mlp-architecture-for-time-series-forecasting/
- TimeMixer (ICLR 2024): https://proceedings.iclr.cc/paper_files/paper/2024/hash/a7ac8a21e5a27e7ab31a5f42a0117bdb-Abstract-Conference.html
- FITS 10k-parameter spectral forecasting (ICLR 2024): https://proceedings.iclr.cc/paper_files/paper/2024/hash/701251e1db4a2e4dd2ef23f5265d5936-Abstract-Conference.html
- CfC continuous-time recurrence (Nature Machine Intelligence 2022): https://www.nature.com/articles/s42256-022-00556-7
- KANMixer 2026; placement/basis/speed robustness matters: https://pubmed.ncbi.nlm.nih.gov/42386843/

No paper demonstrates a profit edge for these architectures on Polymarket US BTC binaries. All are research hypotheses. A model that predicts order-book next-state well can still lose money.

## Selection protocol (profit-first)

1. Collect genuine US 15m + hourly settlement, market price history, and new executable order books. Maintain separate provenance; displayed historical prices do not reconstruct actual historical bid/ask fills. Legacy international Polymarket L2 may be used for numeric pretraining only if evaluated as a different domain.
2. Fit all scalers, rolling transforms, and self-supervised encoders on train periods only. Split **entire chronological days/weeks**, purge label overlap at split boundaries and lock a fully sealed final period.
3. Include independent non-neural baselines: no-trade, market-implied odds, standardized price-to-beat distance divided by remaining volatility, logistic/Ridge, and gradient-boosted trees. Start the 20-model sweep with equal short CPU budgets, 1 seed; retain diverse top 3–5 by causal validation loss, calibration, runtime and ability to beat persistence.
4. Continue selected candidates with 3–5 seeds and progressively longer lookbacks and unseen days. Compare SSL vs supervised-from-scratch, with and without slow macro, with 15m/1h shared heads vs separate models. Select **only on development data**, not sealed dates.
5. Run independently executable fee-aware strategies using actual US bid/ask/size and realistic maker/taker timing, fill likelihood, fee schedule, min size, cancellation risk, drawdown and $10 bankroll. Optimize held-out **net dollars**, not classification hit rate. No-trade is a legitimate result.
6. Freeze full method before opening sealed days. Avoid 20-way winner's curse and overfitting many overlapping samples from too few independent market days.

## Model-specific cautions

- With evenly spaced 30s data, CfC-style recurrent dynamics have little advantage unless actual event-time gaps are represented; time-to-close is an input even for other encoders.
- KAN should primarily compete in low-dimensional calibrated probability or edge heads; splines can be expensive and unstable under noisy series.
- Fourier mixing may learn intraday/time-of-day artifacts; require regime-shift tests.
- Mixture-of-experts can fragment small data into even smaller effective training groups.
- The terminal threshold probability, including the venue-specific BRTI 60-sample settlement averaging, is more directly relevant than raw next-price MSE. A principled probability baseline should estimate final-reference distribution conditional on time remaining.
- The 60-second action loop and event-driven order manager are **separate**; orders can fill or require cancellation between action opportunities.

## Commands

    cd /root/Proj/YeNoVolumeLab
    python3 market_us/models.py --smoke --output market_us/architectures-120k.json
    python3 -m pytest -q market_us/tests

No model training/selection is enabled until a full authentic US market dataset is ready.

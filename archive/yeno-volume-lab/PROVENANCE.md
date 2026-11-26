# YeNoVolumeLab salvage (provenance)

Salvaged from local `/root/Proj/YeNoVolumeLab` on 2026-11-26 before disk cleanup.
Source repo: https://github.com/cheeseonamonkey/YeNoVolumeLab (commit b6e3337 at salvage time).

Included: research code, architecture/docs, small manifests/splits/feature audits, fold comparison JSON, scalers, training logs/summaries.
Excluded intentionally: raw/normalized/research data dumps, sqlite DBs, model weights (`.pt`), parquet caches, venvs, external vendored clones, secrets, bulky operational logs.

PaperLab already carries selected 250K checkpoints under `models/checkpoints/` with provenance in `models/provenance.json`; this directory keeps the broader YeNo research context without duplicating large artifacts.

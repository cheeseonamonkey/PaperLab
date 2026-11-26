#!/usr/bin/env bash
# Resume the 52-day 20-architecture screen until it reports completion.
# train250.py caps each invocation at 89 minutes and skips finished models,
# so a bounded retry loop completes fold1, fold2 and the all-days refit.
set -u
cd "$(dirname "$0")/.."
OUT=market_us/results/us-20-250k-52d-v2
LOG=market_us/results/train-52d-v2.log
for _ in 1 2 3 4 5 6; do
  PYTHONPATH=. python3 market_us/train250.py --output "$OUT" >> "$LOG" 2>&1
  [ -f "$OUT/finished.json" ] && break
  sleep 5
done
echo "LOOP_DONE $(date -u +%FT%TZ)" >> "$LOG"

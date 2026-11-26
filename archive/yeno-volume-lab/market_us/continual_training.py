"""Continuous bounded YeNo experiments, not infinite epochs on one dataset.

Every timer invocation spends its available budget completing an existing run
or beginning a new predeclared seed/regularization/walk-forward comparison.
All completed models receive an all-dates research fit, with no deployment.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import logging
import os
import time
from pathlib import Path

from market_us.collector import DB
from market_us.exogenous import STORE
from market_us.train250 import ROOT, OUTPUT, run, snapshot_db, snapshot_auxiliary
from market_us.sweep40 import write_json

SERIES = ROOT / "experiments/results/us-250k-continual"
LOG = logging.getLogger("yeno.us.continual")

# Different, predeclared experiments rather than blindly increasing epochs.
REGULARIZATION = (
    (0.12, 0.00015, 0.025),
    (0.18, 0.00020, 0.035),
    (0.25, 0.00015, 0.045),
    (0.30, 0.00010, 0.050),
    (0.15, 0.00025, 0.030),
    (0.22, 0.00012, 0.040),
)


def config(number: int, minutes: int) -> argparse.Namespace:
    if number == 0:
        return argparse.Namespace(
            db=DB, output=OUTPUT, params=250000, batch_size=192, workers=2,
            threads_per_worker=2, max_epochs=3, dropout=0.18, lr=0.00025,
            weight_decay=0.02, residual_penalty=0.03, seed=42,
            fold_shift=0, max_minutes=minutes)
    dropout, lr, penalty = REGULARIZATION[(number - 1) % len(REGULARIZATION)]
    # Shifting validation blocks samples more of the observed calendar days.
    # After the cycle, the all-dates fit includes every usable settled day.
    return argparse.Namespace(
        db=DB, output=SERIES / f"run-{number:04d}", params=250000,
        batch_size=192, workers=2, threads_per_worker=2, max_epochs=3,
        dropout=dropout, lr=lr, weight_decay=0.025,
        residual_penalty=penalty, seed=42 + 101 * number,
        fold_shift=(number - 1) % 12, max_minutes=minutes)


def current_number() -> int:
    if not (OUTPUT / "finished.json").exists():
        return 0
    seen = sorted(int(p.name[4:]) for p in SERIES.glob("run-[0-9][0-9][0-9][0-9]")
                  if p.is_dir())
    if not seen:
        return 1
    for number in seen:
        if not (SERIES / f"run-{number:04d}" / "finished.json").exists():
            return number
    return max(seen) + 1


def freeze_daily_source(output: Path) -> None:
    # Reuse an immutable per-UTC-day snapshot, not a new DB copy every 2 hours.
    # Read-only SQLite uses the shared path through the symlink (no new writer).
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    frozen = SERIES / "snapshots" / day
    frozen.mkdir(parents=True, exist_ok=True)
    snapshot_db(DB, frozen / "frozen_us.sqlite3")
    snapshot_auxiliary(STORE, frozen / "frozen_exogenous")
    for name in ("frozen_us.sqlite3", "frozen_exogenous"):
        dest = output / name
        if not dest.exists() and not dest.is_symlink():
            dest.symlink_to(frozen / name, target_is_directory=name=="frozen_exogenous")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-minutes", type=int, default=87)
    args = parser.parse_args()
    if not 5 <= args.budget_minutes <= 89:
        parser.error("budget must be 5..89 minutes")
    SERIES.mkdir(parents=True, exist_ok=True)
    with (SERIES / "coordinator.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.warning("Training already active, skipping duplicate invocation")
            return
        deadline = time.monotonic() + args.budget_minutes * 60
        while deadline-time.monotonic() > 5*60:
            number = current_number()
            remaining = min(85, int((deadline-time.monotonic()-90)/60))
            if remaining < 4:
                return
            job = config(number, remaining)
            job.output.mkdir(parents=True, exist_ok=True)
            if number > 0:
                freeze_daily_source(job.output)
                manifest = job.output / "cycle.json"
                if not manifest.exists():
                    write_json(manifest,{
                        "cycle":number, "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
                        "method":"20 architectures, 2 walk-forward folds, then all-dates fit",
                        "frozen_source":str((job.output/"frozen_us.sqlite3").resolve()),
                        "args":{k:str(v) if isinstance(v,Path) else v
                                for k,v in vars(job).items()},
                        "warning":"Exploratory repeated testing on formerly exposed dates; no pristine holdout or trading-profit claim"})
            LOG.info("START cycle=%s minutes=%s output=%s",number,remaining,job.output)
            run(job)
            if not (job.output / "finished.json").exists():
                LOG.info("PAUSE cycle=%s, checkpoint resume next training window",number)
                return
            LOG.info("DONE cycle=%s; begin next experiment if time remains",number)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    main()

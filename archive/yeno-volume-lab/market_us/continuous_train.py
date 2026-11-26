"""VPS-side repeating YeNo trainer. One bounded experiment per two-hour cycle.

Resumes incomplete stages without duplicating completed checkpoints; after
completion starts a new predeclared seed/regularization/walk-forward variant.
This is experimentation, NOT autonomous trading.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from market_us.train250 import OUTPUT as INITIAL
from market_us.sweep40 import write_json

ROOT = INITIAL.parent / "us-250k-continuous"
LOG = logging.getLogger("yeno.training.loop")


def pick_run(root: Path):
    if not (INITIAL / "finished.json").exists():
        return INITIAL, 0
    rounds = sorted(root.glob("round-*"))
    for directory in rounds:
        if not (directory / "finished.json").exists():
            return directory, int(directory.name.split("-")[-1])
    index = (int(rounds[-1].name.split("-")[-1]) + 1) if rounds else 1
    return root / f"round-{index:04d}", index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-minutes", type=int, default=85)
    args = parser.parse_args()
    if not 1 <= args.max_minutes <= 87:
        parser.error("max-minutes must be 1..87")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ROOT.mkdir(parents=True, exist_ok=True)
    folder, index = pick_run(ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    seed = 42 if index == 0 else 42 + 173 * index
    dropout = (0.18, 0.12, 0.24, 0.16)[index % 4]
    lr = (0.00025, 0.00020, 0.00015, 0.00030)[index % 4]
    shift = 0 if index == 0 else 2 * ((index - 1) % 7)
    epochs = 3 if index % 2 == 0 else 4
    command = [
        sys.executable, "-u", "-m", "market_us.train250",
        "--output", str(folder), "--params", "250000",
        "--workers", "3", "--threads-per-worker", "2",
        "--max-minutes", str(args.max_minutes),
        "--seed", str(seed), "--dropout", str(dropout),
        "--lr", str(lr), "--max-epochs", str(epochs),
        "--fold-shift", str(shift),
    ]
    manifest = {
        "round": index,
        "output": str(folder),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "dropout": dropout,
        "learning_rate": lr,
        "fold_shift": shift,
        "max_epochs": epochs,
        "max_minutes": args.max_minutes,
        "experiment_policy": (
            "Train 20 models with market-balanced chronological validation, "
            "then refit on all usable days; vary regularization/seed/folds "
            "for robustness. No lookahead or trading assertions."
        ),
    }
    LOG.info("Selected round %d: %s", index, folder)
    write_json(ROOT / "latest.json", manifest)
    result = subprocess.run(command, check=False)
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["exit_code"] = result.returncode
    manifest["complete"] = (folder / "finished.json").exists()
    write_json(ROOT / "latest.json", manifest)
    if result.returncode:
        raise SystemExit(result.returncode)
    LOG.info("Round %d %s. Next scheduled cycle will %s.",
             index, "complete" if manifest["complete"] else "paused",
             "start another experiment" if manifest["complete"] else "resume")


if __name__ == "__main__":
    main()
